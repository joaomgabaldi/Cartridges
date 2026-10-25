"""O Ludusavi (`ludusavi.exe`, ao lado do Python do app) como processo.

Só fala com ele: monta a linha de comando, lê o JSON de `--api` e transforma
qualquer defeito em `LudusaviFalhou`. Não sabe de pasta de jogo, de backup nem de
configuração — isso é de quem chama.
"""

import json
import logging
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

Executor = Callable[..., "subprocess.CompletedProcess[str]"]

# Backup de save grande é lento, mas o Ludusavi também trava (atualização do
# manifesto sem rede): sem limite, a thread de backup ficaria presa para sempre.
LIMITE_DE_TEMPO = 10 * 60
# A restauração morta no meio deixaria o save do jogo pela metade: ela tem mais folga.
LIMITE_DA_RESTAURACAO = 60 * 60


class LudusaviFalhou(Exception):
    """O Ludusavi não rodou, saiu com erro ou devolveu algo que não se entende."""


@dataclass(frozen=True)
class Versao:
    """Uma cópia guardada de um jogo: ``id`` é o que `restore --backup` pede.

    ``comentario`` é a marca que o app grava com `marcar` ("" sem marca); ``arquivo``
    é o zip da versão, ou None quando o Ludusavi não informou a pasta do jogo.
    """

    id: str
    quando: datetime  # UTC
    comentario: str = ""
    arquivo: Path | None = None


@dataclass(frozen=True)
class Previa:
    """O que uma restauração tocaria: caminhos finais dos arquivos e chaves do registro.
    ``sobrescritos``: os arquivos que já existem (`change` diferente de "New"), que a
    restauração grava por cima."""

    arquivos: tuple[str, ...]
    chaves: tuple[str, ...]
    sobrescritos: tuple[str, ...] = ()


def executavel() -> Optional[Path]:
    exe = Path(sys.executable).parent / "ludusavi.exe"
    return exe if exe.is_file() else None


def rodar(  # pylint: disable=too-many-arguments
    argumentos: list[str],
    pasta_config: Path,
    executor: Executor = subprocess.run,
    *,
    codigos_ok: tuple[int, ...] = (0,),
    limite_de_tempo: float = LIMITE_DE_TEMPO,
    api: bool = True,
) -> dict:
    """Roda `ludusavi --config <pasta> --try-manifest-update <argumentos> --api`.

    ``codigos_ok`` existe porque o `find` sai com 1 quando não conhece o jogo e,
    mesmo assim, entrega um JSON válido: ali "não achado" não é defeito.
    ``api=False`` é para o que não aceita `--api` (o `backups edit`): sem a opção e
    sem JSON, só o código de saída conta, e o resultado é sempre ``{}``.
    """
    exe = executavel()
    if exe is None:
        raise LudusaviFalhou("ludusavi.exe não encontrado")
    # Lista, nunca texto: o nome do jogo (aspas, `&`, acento) vai como um item só.
    comando = [str(exe), "--config", str(pasta_config), "--try-manifest-update", *argumentos]
    if api:
        comando.append("--api")
    try:
        processo = executor(
            comando,
            capture_output=True,
            # Sem isto o Ludusavi herda a entrada do app e fica esperando nela para sempre.
            stdin=subprocess.DEVNULL,
            encoding="utf-8",
            creationflags=subprocess.CREATE_NO_WINDOW,
            timeout=limite_de_tempo,
        )
    except subprocess.TimeoutExpired as erro:
        raise LudusaviFalhou("o Ludusavi demorou demais e foi interrompido") from erro
    except OSError as erro:
        raise LudusaviFalhou(f"não foi possível iniciar o Ludusavi: {erro}") from erro
    if processo.stderr:
        logging.warning("Ludusavi: %s", processo.stderr.strip())
    if processo.returncode not in codigos_ok:
        raise LudusaviFalhou(f"o Ludusavi saiu com o código {processo.returncode}")
    if not api:
        return {}
    if not (processo.stdout or "").strip():
        raise LudusaviFalhou("o Ludusavi não devolveu nada")
    try:
        saida = json.loads(processo.stdout)
    except ValueError as erro:
        raise LudusaviFalhou("o Ludusavi devolveu algo que não é JSON") from erro
    if not isinstance(saida, dict):
        raise LudusaviFalhou("o Ludusavi devolveu um JSON inesperado")
    return saida


def _nome_achado(argumentos: list[str], pasta_config: Path, executor: Executor) -> Optional[str]:
    jogos = rodar(["find", *argumentos], pasta_config, executor, codigos_ok=(0, 1)).get("games")
    if not isinstance(jogos, dict) or not jogos:
        return None
    return max(jogos, key=lambda nome: (jogos[nome] or {}).get("score", 0))


def nome_por_appid(appid: str, pasta_config: Path, executor: Executor = subprocess.run) -> Optional[str]:
    """O nome do jogo no manifesto do Ludusavi para um appID da Steam, ou None."""
    return _nome_achado(["--steam-id", appid], pasta_config, executor)


def manifesto_baixado(pasta_config: Path) -> bool:
    return (pasta_config / "manifest.yaml").is_file()


def baixar_manifesto(pasta_config: Path, executor: Executor = subprocess.run) -> None:
    """Baixa o `manifest.yaml`. O `--try-manifest-update` dos outros comandos não basta: o
    `backups` não baixa, e o app só roda o `find` e o `backup` com o manifesto já baixado.
    `--force` porque o cache pode dizer que a última busca foi há menos de 24 h. O limite
    é curto porque, sem rede, o Ludusavi pode ficar parado com a trava dos saves presa."""
    rodar(["manifest", "update", "--force"], pasta_config, executor, api=False, limite_de_tempo=3 * 60)


def nomes_do_manifesto(pasta_config: Path) -> list[str]:
    """Os nomes dos jogos do `manifest.yaml`, sem repetição, em ordem alfabética (sem
    diferenciar maiúsculas). Levanta `OSError` se o arquivo não abre e `ValueError` se não
    tem nenhuma chave de topo. Lê linha a linha: não há PyYAML no ambiente."""
    nomes = set()
    descartadas = 0
    texto = (pasta_config / "manifest.yaml").read_text(encoding="utf-8")
    for linha in texto.splitlines():
        linha = linha.rstrip()
        if not linha.endswith(":") or linha[0] in " \t#-":
            continue
        chave = linha[:-1]
        if chave.startswith('"') and chave.endswith('"') and len(chave) > 1:
            try:
                chave = json.loads(chave)
            except ValueError:
                descartadas += 1
                continue
        elif chave.startswith("'") and chave.endswith("'") and len(chave) > 1:
            chave = chave[1:-1].replace("''", "'")
        if chave:
            nomes.add(chave)
    if descartadas:
        logging.info("Manifesto do Ludusavi: %d chaves com escape inválido descartadas", descartadas)
    if not nomes:
        raise ValueError("o manifesto do Ludusavi não tem nenhum jogo")
    return sorted(nomes, key=str.casefold)


def _verificar(saida: dict) -> None:
    if (saida.get("errors") or {}).get("someGamesFailed"):
        raise LudusaviFalhou("o Ludusavi não conseguiu copiar os arquivos do jogo")


def _do_jogo(saida: dict, nome: str) -> dict:
    jogos = saida.get("games")
    jogo = jogos.get(nome) if isinstance(jogos, dict) else None
    return jogo if isinstance(jogo, dict) else {}


def fazer_backup(
    nome: str,
    pasta_config: Path,
    executor: Executor = subprocess.run,
    limite: int | None = None,
) -> tuple[str, ...]:
    """Guarda uma versão nova; ``limite`` é quantas cópias completas o Ludusavi mantém.

    Devolve os arquivos que o backup conferiu, mudados ou não (sem mudança, o Ludusavi
    não cria versão, mas a última já os tem). Fica de fora o "Removed": arquivo da versão
    anterior que o backup de agora não achou."""
    argumentos = ["backup", nome, "--force"]
    if limite is not None:
        argumentos += ["--full-limit", str(limite)]
    saida = rodar(argumentos, pasta_config, executor)
    _verificar(saida)
    arquivos = _do_jogo(saida, nome).get("files") or {}
    return tuple(c for c, dados in arquivos.items() if (dados or {}).get("change") != "Removed")


def marcar(
    nome: str,
    versao: str,
    comentario: str,
    pasta_config: Path,
    executor: Executor = subprocess.run,
) -> None:
    """Grava ``comentario`` na versão ``versao`` do jogo ``nome``."""
    rodar(
        ["backups", "edit", nome, "--backup", versao, "--comment", comentario],
        pasta_config,
        executor,
        api=False,
    )


def _quando(texto: object) -> Optional[datetime]:
    """``2026-10-09T15:46:38.971055700Z`` em UTC; ilegível é None."""
    try:
        quando = datetime.fromisoformat(str(texto))
    except ValueError:
        return None
    return quando.astimezone(timezone.utc) if quando.tzinfo else quando.replace(tzinfo=timezone.utc)


def versoes(pasta_config: Path, executor: Executor = subprocess.run) -> dict[str, list[Versao]]:
    """Todas as versões de todos os jogos, por nome, da mais nova para a mais velha."""
    jogos = rodar(["backups"], pasta_config, executor).get("games")
    por_jogo: dict[str, list[Versao]] = {}
    for nome, dados in (jogos if isinstance(jogos, dict) else {}).items():
        dados = dados or {}
        pasta = dados.get("backupPath")
        lista = []
        for copia in dados.get("backups") or []:
            quando = _quando(copia.get("when"))
            if copia.get("name") and quando:
                arquivo = Path(pasta) / copia["name"] if pasta else None
                lista.append(Versao(copia["name"], quando, copia.get("comment") or "", arquivo))
        por_jogo[nome] = sorted(lista, key=lambda v: v.quando, reverse=True)
    return por_jogo


def restaurar(
    nome: str,
    pasta_config: Path,
    versao: Optional[str] = None,
    executor: Executor = subprocess.run,
) -> None:
    """Devolve os arquivos do jogo; sem ``versao``, a mais recente."""
    argumentos = ["restore", nome, "--force"]
    if versao:
        argumentos += ["--backup", versao]
    _verificar(rodar(argumentos, pasta_config, executor, limite_de_tempo=LIMITE_DA_RESTAURACAO))


def previa(
    nome: str,
    pasta_config: Path,
    versao: str | None = None,
    executor: Executor = subprocess.run,
) -> Previa:
    """O que `restaurar` tocaria, sem copiar nada; sem ``versao``, a mais recente."""
    argumentos = ["restore", nome, "--force", "--preview"]
    if versao:
        argumentos += ["--backup", versao]
    saida = rodar(argumentos, pasta_config, executor)
    _verificar(saida)
    jogo = _do_jogo(saida, nome)
    arquivos = jogo.get("files") or {}
    sobrescritos = (
        caminho for caminho, dados in arquivos.items() if (dados or {}).get("change") != "New"
    )
    return Previa(tuple(arquivos), tuple(jogo.get("registry") or {}), tuple(sobrescritos))
