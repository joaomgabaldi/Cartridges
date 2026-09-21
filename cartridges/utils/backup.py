# backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup completo: a biblioteca inteira e as configurações num .zip.

Leva tudo o que o app guarda de você — o registro de cada jogo, a capa, o logo,
o papel de parede e a cor das fitas de cada um, as fitas configuradas, o
histórico de sessões e as configurações — para que uma instalação nova fique
idêntica à antiga. Fica fora só o que vale nesta máquina e em mais nenhuma: a
conta da Tuya (um blob DPAPI não decifra em outra conta do Windows), os logs e
o caminho de volta de uma sessão em andamento.

Restaurar substitui, não mescla, e não acontece com o app aberto: a varredura
do HowLongToBeat e a do tamanho no disco gravariam os jogos antigos por cima
dos restaurados. `agendar` deixa o zip na pasta do app e o app fecha; na
abertura seguinte, `aplicar_pendente` faz a troca antes de qualquer coisa ler
os dados.
"""

import json
import logging
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from time import time
from typing import Any, Iterable, Optional

from gi.repository import Gio, GLib

from cartridges import shared
from cartridges.utils import session_log

VERSAO = 3

_MANIFESTO = "backup.json"

# O caminho de volta de uma sessão em andamento nesta máquina: as telas e as
# fitas como estavam antes do jogo. Restaurado noutra máquina, ou depois de a
# sessão acabar, "desfaria" uma troca que nunca aconteceu.
_CHAVES_DE_SESSAO = frozenset({"session-wallpaper-saved", "fita-estado-anterior"})

# Do schema de estado, só a ordenação é escolha de alguém. Tamanho e posição da
# janela, o balde do limitador da Steam e a última novidade vista são da máquina.
_CHAVES_DE_ESTADO = ("sort-mode",)


def _pastas() -> dict[str, Path]:
    # Resolvido a cada chamada: os testes repontam `shared`.
    return {
        "games": shared.games_dir,
        "covers": shared.covers_dir,
        "logos": shared.logos_dir,
        "wallpapers": shared.wallpapers_dir,
        "fitas": shared.fitas_dir,
    }


def _arquivos() -> dict[str, Path]:
    return {
        "fitas.json": shared.fitas_arquivo,
        "sessions.jsonl": session_log._path(),  # pylint: disable=protected-access
    }


def _pendente() -> Path:
    return shared.app_dir / "restaurar.zip"


def _chaves_do_app() -> list[str]:
    return [
        chave
        for chave in shared.schema.props.settings_schema.list_keys()
        if chave not in _CHAVES_DE_SESSAO
    ]


def ler_configuracoes() -> dict[str, Any]:
    """As configurações como vão no backup. Chamar na thread principal.

    Genérico de propósito: uma chave nova no schema entra no backup sozinha, em
    vez de depender de alguém lembrar de acrescentá-la a uma lista.
    """
    return {
        "settings": {
            chave: shared.schema.get_value(chave).unpack() for chave in _chaves_do_app()
        },
        "state": {
            chave: shared.state_schema.get_value(chave).unpack()
            for chave in _CHAVES_DE_ESTADO
        },
    }


def _variante(chave: Gio.SettingsSchemaKey, valor: Any) -> Optional[GLib.Variant]:
    """``valor`` como o schema o guarda, ou ``None`` se o schema não o aceita."""
    tipo = chave.get_value_type().dup_string()
    # GLib.Variant("b", ...) aceita qualquer coisa e a torna verdadeira; um
    # "sim" digitado à mão ligaria a opção em vez de ser descartado.
    if tipo == "b" and not isinstance(valor, bool):
        return None
    try:
        variante = GLib.Variant(tipo, valor)
    except (TypeError, ValueError, OverflowError):
        return None
    # Fora das opções do schema (um `sort-mode` que não existe): o GSettings
    # recusaria com um aviso crítico e deixaria o valor de antes no lugar.
    return variante if chave.range_check(variante) else None


def _aplicar(settings: Any, valores: Any, chaves: Iterable[str]) -> None:
    valores = valores if isinstance(valores, dict) else {}
    schema = settings.props.settings_schema
    for chave in chaves:
        variante = None
        if chave in valores:
            variante = _variante(schema.get_key(chave), valores[chave])
            if variante is None:
                logging.warning("Configuração %s ignorada no backup: valor inválido", chave)
        if variante is None:
            # Idêntico ao backup: o que ele não tem, ou tem num valor que esta
            # versão não aceita, fica no padrão.
            settings.reset(chave)
        else:
            settings.set_value(chave, variante)


def aplicar_configuracoes(configuracoes: dict[str, Any]) -> None:
    """Deixa as configurações como estão em ``configuracoes``."""
    _aplicar(shared.schema, configuracoes.get("settings"), _chaves_do_app())
    _aplicar(shared.state_schema, configuracoes.get("state"), _CHAVES_DE_ESTADO)
    Gio.Settings.sync()


def _incluir(arquivo: zipfile.ZipFile, caminho: Path, nome: str) -> None:
    # As imagens já vêm comprimidas: passar deflate nelas custa segundos e não
    # ganha nada. Só o texto (registros, sidecars, histórico) é comprimido.
    compressao = (
        zipfile.ZIP_DEFLATED if caminho.suffix in (".json", ".jsonl") else zipfile.ZIP_STORED
    )
    try:
        arquivo.write(caminho, nome, compress_type=compressao)
    except FileNotFoundError:
        # Apagado entre a listagem e a leitura (uma capa trocada agora): o
        # backup sai sem ele, em vez de não sair.
        logging.debug("%s sumiu durante o backup", caminho)


def exportar(destino: Path, configuracoes: dict[str, Any]) -> None:
    """Grava o backup em ``destino``. Pode rodar fora da thread principal."""
    manifesto = {
        "version": VERSAO,
        "app_version": shared.VERSION,
        "created": int(time()),
        **configuracoes,
    }
    # Temporário + troca: exportar por cima de um backup antigo e cair no meio
    # deixaria o antigo perdido e o novo ilegível.
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        # strict_timestamps=False: um arquivo com data anterior a 1980 (que o
        # formato zip não representa) entra com 1980, em vez de abortar tudo.
        with zipfile.ZipFile(temporario, "w", strict_timestamps=False) as arquivo:
            arquivo.writestr(
                _MANIFESTO,
                json.dumps(manifesto, indent=2, ensure_ascii=False),
                compress_type=zipfile.ZIP_DEFLATED,
            )
            for nome, pasta in _pastas().items():
                if not pasta.is_dir():
                    continue
                for caminho in sorted(pasta.iterdir()):
                    if caminho.is_file() and caminho.suffix != ".tmp":
                        _incluir(arquivo, caminho, f"{nome}/{caminho.name}")
            for nome, caminho in _arquivos().items():
                if caminho.is_file():
                    _incluir(arquivo, caminho, nome)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


def _nome_valido(nome: str) -> bool:
    """Só o que `exportar` grava: o manifesto, os dois arquivos, ou um arquivo
    direto de uma das pastas. Nada absoluto, nada com `..`, nada mais fundo."""
    if nome == _MANIFESTO or nome in _arquivos():
        return True
    if "\\" in nome or ":" in nome:
        return False
    partes = PurePosixPath(nome).parts
    return len(partes) == 2 and partes[0] in _pastas() and partes[1] not in (".", "..")


def validar(caminho: Path) -> dict[str, Any]:
    """O manifesto de um backup completo. ``ValueError`` se não for um."""
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            for nome in arquivo.namelist():
                if not _nome_valido(nome):
                    raise ValueError(f"entrada inesperada no backup: {nome}")
            # O CRC de cada entrada, e não só o do manifesto: um byte trocado
            # numa capa passaria daqui e só estouraria no meio da extração.
            if (corrompida := arquivo.testzip()) is not None:
                raise ValueError(f"entrada corrompida no backup: {corrompida}")
            manifesto = json.loads(arquivo.read(_MANIFESTO).decode("utf-8"))
    except ValueError:
        raise
    except Exception as erro:  # pylint: disable=broad-exception-caught
        # O arquivo veio de fora e pode falhar de muitos jeitos: truncado,
        # criptografado, com uma compressão que o Python não conhece. Para quem
        # chama, todos querem dizer a mesma coisa.
        raise ValueError(str(erro)) from erro
    if not isinstance(manifesto, dict) or manifesto.get("version") != VERSAO:
        raise ValueError("o arquivo não é um backup completo desta versão")
    return manifesto


def agendar(caminho: Path) -> None:
    """Deixa ``caminho`` para ser aplicado na próxima abertura do app."""
    destino = _pendente()
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        shared.app_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(caminho, temporario)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


def aplicar_pendente() -> Optional[bool]:
    """Aplica o backup que `agendar` deixou, se houver.

    Chamar na abertura, antes de qualquer coisa ler os dados do app. ``None``:
    nada agendado. ``True``: restaurado. ``False``: não deu (detalhes no log).
    """
    pendente = _pendente()
    if not pendente.is_file():
        return None

    extraido = shared.app_dir / "restaurar.tmp"
    antigo = shared.app_dir / "restaurar.old"
    # Sobras de uma abertura que caiu depois da troca: o que está no lugar já
    # é o backup, e o zip ainda aqui vai refazer tudo do zero.
    shutil.rmtree(extraido, ignore_errors=True)
    shutil.rmtree(antigo, ignore_errors=True)
    try:
        manifesto = validar(pendente)
        with zipfile.ZipFile(pendente) as arquivo:
            arquivo.extractall(extraido)
    except Exception as erro:  # pylint: disable=broad-exception-caught
        # Nada foi tocado ainda: a biblioteca atual fica, e o zip ruim sai
        # para não ser tentado de novo a cada abertura.
        logging.error("Backup agendado inválido: %s", erro)
        _limpar(extraido, pendente)
        return False

    try:
        _trocar(extraido, antigo)
    except OSError:
        logging.exception("Não foi possível trocar a biblioteca pela do backup")
        if antigo.is_dir() and not any(antigo.iterdir()):
            # Tudo voltou ao lugar: a biblioteca atual fica, como se o backup
            # nunca tivesse sido agendado.
            _limpar(extraido, antigo, pendente)
        # ponytail: se nem desfazer deu, o zip fica e a próxima abertura
        # termina a restauração; nesta, o app abre com o que estiver no lugar.
        return False

    # As configurações antes de o zip sair: aplicá-las de novo não muda nada,
    # e assim uma queda em qualquer ponto até aqui refaz tudo do zero.
    aplicar_configuracoes(manifesto)
    _limpar(extraido, antigo, pendente)
    logging.info("Backup restaurado")
    return True


def _trocar(extraido: Path, antigo: Path) -> None:
    """Põe o extraído no lugar do atual, que vai para ``antigo``.

    Só com `os.replace`, que no mesmo disco move ou falha inteiro — ao
    contrário de `rmtree`, que com um arquivo em uso apaga metade da pasta e
    para. Nada é apagado aqui; uma falha no meio desfaz o que já foi movido e
    levanta o erro.
    """
    itens = [*_pastas().items(), *_arquivos().items()]
    antigo.mkdir(exist_ok=True)
    feitos: list[tuple[Path, Path]] = []
    try:
        for nome, destino in itens:
            if destino.exists():
                destino.replace(antigo / nome)
                feitos.append((antigo / nome, destino))
        for nome, destino in itens:
            origem = extraido / nome
            if origem.exists():
                origem.replace(destino)
                feitos.append((destino, origem))
    except OSError:
        for de, para in reversed(feitos):
            de.replace(para)
        raise


def _limpar(*caminhos: Path) -> None:
    for caminho in caminhos:
        if caminho.is_dir():
            shutil.rmtree(caminho, ignore_errors=True)
            continue
        try:
            caminho.unlink(missing_ok=True)
        except OSError:
            logging.exception("Não foi possível apagar %s", caminho)
