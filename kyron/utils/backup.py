# backup.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup: um retrato completo do app num .zip.

Leva a pasta do app, os backups dos saves (a pasta configurada entra como `saves/`, sem limite de tamanho) e as configurações do registro; fica fora o que não se restaura com sentido (logs, configuração do Ludusavi, o caminho de volta de uma sessão, a pasta dos saves escolhida, o estado da janela).

Restaurar substitui tudo, com o app fechado: `agendar` copia o .zip e reinicia; `aplicar_pendente`, na abertura e antes de qualquer leitura, troca a pasta e as configurações e cria as pendências (`utils/restauracao.py`). Backup com saves os põe na pasta padrão e desfaz a escolha de outra pasta; o da versão 5 não os tem e nada muda. A pasta de fora nunca é tocada. Se algo falhar, tudo volta como estava.
"""

import json
import logging
import shutil
import stat
import zipfile
from contextlib import ExitStack, contextmanager
from pathlib import Path, PurePosixPath
from time import sleep, time
from typing import Any, Callable, Iterable, Literal, Optional

from kyron import shared
from kyron.conquistas import arquivos
from kyron.saves import backup_de_saves
from kyron.saves import pasta as pasta_dos_saves
from kyron.utils import game_logo, restauracao, save_cover, session_wallpaper
from kyron.utils.gravar_atomico import gravar_atomico

VERSAO = 6
# A versão 5 só não tinha os saves.
_VERSOES_ACEITAS = (5, VERSAO)

_CONFIGURACOES = "configuracoes.json"
_CHAVE_DA_PASTA_DOS_SAVES = "pasta-dos-saves"
_AGENDADO = "restaurar.zip"
_SOLTOS = ("fitas.json", "sessions.jsonl", "tuya_conta.json")
# O que fica na pasta do app durante a troca: logs e `ludusavi` são desta máquina, `contas` também (o DPAPI não abre em outro PC), e o .zip agendado é a fonte da troca.
_FICAM = frozenset({"logs", "contas", "ludusavi", _AGENDADO})
# Marca, em `.anterior`, de que os dados de antes já saíram da pasta do app: dali em diante, o que estiver nela veio do backup.
_COMPLETO = ".completo"
_PEDACO = 1024 * 1024
_TENTATIVAS_DE_APAGAR = 5
_ESPERA_DA_TRAVA_S = 5
_BLOCO = 1024 * 1024
# Marca, em `.anterior`, de que os saves da pasta padrão não saíram nesta troca (o backup não tinha): `_devolver` não pode apagá-los.
_SAVES_FICAM = ".saves-ficam"
# Marca, em `.anterior`, de que a troca deu certo: o que sobrar (um arquivo preso pelo antivírus) é descarte, nunca dado a devolver.
_CONCLUIDO = ".concluido"

# O caminho de volta de uma sessão em andamento (telas e fitas como antes do jogo): restaurado depois, desfaria uma troca que nunca aconteceu.
_CHAVES_DE_SESSAO = frozenset({"session-wallpaper-saved", "fita-estado-anterior"})

# Escolhas desta máquina, que um backup não leva nem traz: a pasta dos saves (só `aplicar_pendente` a zera, quando o backup traz saves)
# e a marca do assistente de primeira abertura (um backup antigo, sem ela, a zeraria e o assistente reapareceria).
_CHAVES_DESTA_MAQUINA = frozenset({_CHAVE_DA_PASTA_DOS_SAVES, "assistente-concluido"})

# Do schema de estado, só a ordenação é escolha de alguém; janela, balde do limitador da Steam e última novidade vista são da máquina.
_CHAVES_DE_ESTADO = ("sort-mode",)

_MAPA_DOS_SAVES = pasta_dos_saves.MAPA


def _extensoes() -> dict[str, tuple[str, ...]]:
    """Pasta do app -> extensões que o backup leva dela, reaproveitando as listas de cada módulo (uma extensão nova entra sozinha)."""
    return {
        "games": (".json",),
        "covers": (*save_cover.ANIMATED_SUFFIXES, ".tiff"),
        "logos": (".json", *game_logo.IMAGE_SUFFIXES),
        "wallpapers": (".json", *session_wallpaper.IMAGE_SUFFIXES),
        "fitas": (".json",),
        "conquistas": (".json",),
        # Aninhada, de um cache: levar as cópias prontas dá menos trabalho que regerá-las na primeira abertura.
        "cache/capas_animadas": (".webp",),
    }


class BackupInvalido(ValueError):
    """O arquivo não é um backup válido do Kyron (ou está corrompido)."""


class SavesInacessiveis(Exception):
    """`exportar` não conseguiu ler a pasta dos saves (um OneDrive sem conexão,
    por exemplo): o erro não é do destino."""


# A pasta dos saves escolhida que a última `aplicar_pendente` desfez, para a janela avisar depois de aberta.
pasta_dos_saves_desfeita: str | None = None  # pylint: disable=invalid-name


# region Configurações


def _filtrar_chaves(chaves: Iterable[str]) -> list[str]:
    """``chaves`` sem as de sessão em andamento e as desta máquina (separada de `_chaves_do_app` para ser testável)."""
    return [
        chave
        for chave in chaves
        if chave not in _CHAVES_DE_SESSAO and chave not in _CHAVES_DESTA_MAQUINA
    ]


def _chaves_do_app() -> list[str]:
    return _filtrar_chaves(shared.schema.list_keys())


def ler_configuracoes() -> dict[str, Any]:
    """As configurações como vão no backup (thread principal). Genérico de propósito: uma chave nova no schema entra sozinha."""
    return {
        "settings": {
            chave: shared.schema.get_value(chave) for chave in _chaves_do_app()
        },
        "state": {
            chave: shared.state_schema.get_value(chave)
            for chave in _CHAVES_DE_ESTADO
        },
    }


def _aplicar(settings: Any, valores: Any, chaves: Iterable[str]) -> None:
    valores = valores if isinstance(valores, dict) else {}
    for chave in chaves:
        valido = False
        if chave == "shortcuts-location" and arquivos.eh_caminho_de_rede(valores.get(chave)):
            # Uma pasta de rede de um backup alheio faria a importação conectar naquela máquina e trazer atalhos de lá.
            logging.warning("Configuração %s ignorada no backup: pasta de rede", chave)
        elif chave in valores:
            valido = settings.aceita(chave, valores[chave])
            if not valido:
                logging.warning("Configuração %s ignorada no backup: valor inválido", chave)
        if not valido:
            # Idêntico ao backup: o que ele não tem, ou tem num valor não aceito, fica no padrão.
            settings.reset(chave)
        else:
            settings[chave] = valores[chave]


def aplicar_configuracoes(configuracoes: dict[str, Any]) -> None:
    _aplicar(shared.schema, configuracoes.get("settings"), _chaves_do_app())
    _aplicar(shared.state_schema, configuracoes.get("state"), _CHAVES_DE_ESTADO)


# endregion

# region Exportar


def _entradas() -> list[tuple[Path, str]]:
    entradas = [
        (shared.app_dir / nome, nome)
        for nome in _SOLTOS
        if (shared.app_dir / nome).is_file()
    ]
    for pasta, extensoes in _extensoes().items():
        diretorio = shared.app_dir / pasta
        if not diretorio.is_dir():
            continue
        for caminho in sorted(diretorio.iterdir()):
            if caminho.is_file() and caminho.suffix.lower() in extensoes:
                entradas.append((caminho, f"{pasta}/{caminho.name}"))
    return entradas


def _nome_dos_saves() -> str:
    """A pasta dos saves no zip: a mesma da pasta padrão, onde a restauração os põe (trocada junto com os outros itens)."""
    return pasta_dos_saves.padrao().name


def _e_arquivo(caminho: Path) -> bool:
    """Se ``caminho`` é um arquivo comum. Só "não existe" é "não"; outro erro de leitura sobe como `OSError` (o `Path.is_file` engole todos, e um save de fora seria um backup incompleto sem aviso)."""
    try:
        return stat.S_ISREG(caminho.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


def _mapa_de_jogo(mapa: Path) -> bool:
    """Se ``mapa`` (o `mapping.yaml` de uma subpasta) existe, como `_e_arquivo`. Subpasta que é junção ou atalho não é jogo do Ludusavi e nem é consultada: as junções antigas de Documentos ("Minhas Músicas"…) negam acesso, e a raiz escolhida pode ser essa pasta."""
    jogo = mapa.parent
    return not (jogo.is_symlink() or jogo.is_junction()) and _e_arquivo(mapa)


def _entradas_dos_saves(pasta: Path) -> list[tuple[Path, str]]:
    """Os saves de ``pasta`` (a configurada, que existe), como ``saves/<jogo>/<arquivo>``. Só as pastas de jogo do Ludusavi: a escolhida pode ser a raiz do OneDrive.
    Não ser save é não existir o `mapping.yaml` ou o arquivo; outro erro de leitura levanta `OSError`, e a exportação falha em vez de deixar um save de fora."""
    entradas = []
    for jogo in pasta_dos_saves.saves_em(pasta, _mapa_de_jogo):
        for caminho in sorted(jogo.iterdir()):
            if _arquivo_de_save_valido(caminho.name) and _e_arquivo(caminho):
                entradas.append((caminho, f"{_nome_dos_saves()}/{jogo.name}/{caminho.name}"))
    return entradas


def _arquivo_de_save_valido(nome: str) -> bool:
    return nome == _MAPA_DOS_SAVES or (
        not nome.startswith(".") and PurePosixPath(nome).suffix.lower() == ".zip"
    )


def _compressao(caminho: Path) -> int:
    # Imagens e .zip de saves já vêm comprimidos: deflate neles custa segundos e não ganha nada. Só o texto é comprimido.
    return (
        zipfile.ZIP_DEFLATED
        if caminho.suffix in (".json", ".jsonl", ".yaml")
        else zipfile.ZIP_STORED
    )


def _incluir(arquivo: zipfile.ZipFile, caminho: Path, nome: str, progresso: Callable[[], None]) -> None:
    try:
        arquivo.write(caminho, nome, compress_type=_compressao(caminho))
        progresso()
    except FileNotFoundError:
        # Apagado entre a listagem e a leitura: o backup sai sem ele, em vez de não sair.
        logging.debug("%s sumiu durante o backup", caminho)


def _incluir_save(arquivo: zipfile.ZipFile, caminho: Path, nome: str, progresso: Callable[[], None]) -> None:
    """Como `_incluir`, para um save, que pode estar num OneDrive sem conexão: só o erro de LER vira `SavesInacessiveis`, inclusive o arquivo que sumiu
    (com a trava, nada some de forma legítima). O de gravar no destino segue como veio; por isso leitura e gravação não usam `ZipFile.write`, que não as separa."""
    with ExitStack() as pilha:
        try:
            info = zipfile.ZipInfo.from_file(caminho, nome, strict_timestamps=False)
            origem = pilha.enter_context(open(caminho, "rb"))
        except OSError as erro:
            raise SavesInacessiveis(str(erro)) from erro
        info.compress_type = _compressao(caminho)
        destino = pilha.enter_context(arquivo.open(info, "w"))
        while True:
            try:
                bloco = origem.read(_BLOCO)
            except OSError as erro:
                raise SavesInacessiveis(str(erro)) from erro
            if not bloco:
                break
            destino.write(bloco)
            progresso()  # por bloco: um save de gigabytes não pode parecer parado


@contextmanager
def _trava_dos_saves(progresso: Callable[[], None]):
    """A trava do Ludusavi, esperada com um aviso de progresso a cada tique (ele a segura por minutos)."""
    trava = backup_de_saves.trava_dos_saves()
    while not trava.acquire(timeout=_ESPERA_DA_TRAVA_S):
        progresso()
    try:
        yield
    finally:
        trava.release()


def exportar(
    destino: Path,
    configuracoes: dict[str, Any],
    progresso: Callable[[], None] | None = None,
) -> Literal["ausente", "vazia"] | None:
    """Grava o backup em ``destino`` (pode rodar fora da principal; ``configuracoes`` vem de `ler_configuracoes`, lida na principal).

    ``"ausente"`` se a pasta dos saves escolhida não existe ou não é alcançável; ``"vazia"`` se não tem cópia de save (nos dois o .zip sai sem saves e quem chamou avisa); senão ``None``. ``progresso()`` é chamado a cada arquivo gravado e a cada bloco de save lido.
    """
    progresso = progresso or (lambda: None)
    manifesto = {
        "version": VERSAO,
        "app_version": shared.VERSION,
        "created": int(time()),
        **configuracoes,
    }
    # Temporário + troca: exportar por cima de um backup antigo e cair no meio perderia o antigo e deixaria o novo ilegível.
    temporario = destino.with_name(destino.name + ".tmp")
    aviso: Literal["ausente", "vazia"] | None = None
    try:
        # strict_timestamps=False: data anterior a 1980 (que o zip não representa) entra como 1980, em vez de abortar.
        with zipfile.ZipFile(temporario, "w", strict_timestamps=False) as arquivo:
            arquivo.writestr(
                _CONFIGURACOES,
                json.dumps(manifesto, indent=2, ensure_ascii=False),
                compress_type=zipfile.ZIP_DEFLATED,
            )
            for caminho, nome in _entradas():
                _incluir(arquivo, caminho, nome, progresso)
            # Com a trava do Ludusavi: um backup de save em andamento não pode entrar pela metade.
            with _trava_dos_saves(progresso):
                # Lida uma vez, antes da listagem: o aviso e o que entra no .zip partem da mesma leitura.
                pasta = pasta_dos_saves.atual()
                existe = pasta.is_dir()
                try:
                    entradas = _entradas_dos_saves(pasta) if existe else []
                except OSError as erro:
                    raise SavesInacessiveis(str(erro)) from erro
                if pasta != pasta_dos_saves.padrao():
                    if not existe:
                        aviso = "ausente"
                    elif not entradas:
                        # Pode ter sumido entre a leitura e a listagem: fora de alcance não é "sem saves".
                        aviso = "vazia" if pasta.is_dir() else "ausente"
                for caminho, nome in entradas:
                    _incluir_save(arquivo, caminho, nome, progresso)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)
    return aviso


# endregion

# region Validar


def _nome_valido(nome: str, extensoes_por_pasta: dict[str, tuple[str, ...]]) -> bool:
    """Só o que `exportar` grava: o manifesto, um arquivo solto conhecido, ``<pasta conhecida>/<arquivo com extensão conhecida>``
    ou ``saves/<jogo>/<mapping.yaml ou .zip>``. Nada absoluto, nada com ``..``, nada em subpasta fora de `_extensoes`."""
    if nome in (_CONFIGURACOES, *_SOLTOS):
        return True
    if "\\" in nome or ":" in nome:
        return False
    partes = PurePosixPath(nome).parts
    if len(partes) < 2:
        return False
    if partes[0] == _nome_dos_saves():
        return (
            len(partes) == 3
            and partes[1] not in (".", "..")
            and _arquivo_de_save_valido(partes[2])
        )
    # A pasta pode ser aninhada ("cache/capas_animadas"): vale o que `_extensoes` lista, inteiro.
    pasta, arquivo = "/".join(partes[:-1]), partes[-1]
    extensoes = extensoes_por_pasta.get(pasta)
    if extensoes is None or arquivo.startswith("."):
        return False
    return PurePosixPath(arquivo).suffix.lower() in extensoes


def _conferir(arquivo: zipfile.ZipFile) -> dict[str, Any]:
    """Os nomes e o manifesto de um backup aberto, sem ler o resto. ``BackupInvalido`` se não for um."""
    try:
        extensoes = _extensoes()
        for info in arquivo.infolist():
            if not _nome_valido(info.filename, extensoes):
                raise BackupInvalido(f"entrada inesperada no backup: {info.filename}")
        manifesto = json.loads(arquivo.read(_CONFIGURACOES).decode("utf-8"))
    except BackupInvalido:
        raise
    except Exception as erro:  # pylint: disable=broad-exception-caught
        raise BackupInvalido(str(erro)) from erro

    if not isinstance(manifesto, dict) or manifesto.get("version") not in _VERSOES_ACEITAS:
        raise BackupInvalido("o arquivo não é um backup desta versão")
    if not isinstance(manifesto.get("settings"), dict):
        raise BackupInvalido("backup sem o bloco de configurações")
    return manifesto


def validar(caminho: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            manifesto = _conferir(arquivo)
            # Sem limite de tamanho (saves de gigabytes); o nome e o CRC pegam o zip que não é nosso. O CRC de cada
            # entrada: um byte trocado numa capa passaria daqui e só estouraria no meio da troca.
            if (corrompida := arquivo.testzip()) is not None:
                raise BackupInvalido(f"entrada corrompida no backup: {corrompida}")
    except BackupInvalido:
        raise
    except Exception as erro:  # pylint: disable=broad-exception-caught
        raise BackupInvalido(str(erro)) from erro
    return manifesto


def _extrair(
    arquivo: zipfile.ZipFile, destino: Path, progresso: Callable[[float], None]
) -> None:
    """Grava as entradas (menos o manifesto) em ``destino``, aos pedaços. O CRC é conferido no fim da leitura de cada entrada: um byte trocado levanta aqui, antes de qualquer dado do app sair do lugar. ``progresso`` recebe a fração gravada."""
    raiz = destino.resolve()
    entradas = [
        info
        for info in arquivo.infolist()
        if info.filename != _CONFIGURACOES and not info.is_dir()
    ]
    total = sum(info.file_size for info in entradas)
    gravados = 0
    for info in entradas:
        alvo = (destino / info.filename).resolve()
        if not alvo.is_relative_to(raiz):
            raise BackupInvalido(f"entrada fora da pasta do backup: {info.filename}")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        with arquivo.open(info) as origem, open(alvo, "wb") as saida:
            while pedaco := origem.read(_PEDACO):
                saida.write(pedaco)
                gravados += len(pedaco)
                progresso(gravados / total)
    progresso(1.0)


# endregion

# region Restaurar


def agendar(origem: Path) -> None:
    """Copia ``origem`` para a pasta do app; a troca acontece na próxima abertura (`aplicar_pendente`)."""
    destino = shared.app_dir / _AGENDADO
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        shutil.copyfile(origem, temporario)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


def ha_pendente() -> bool:
    return (shared.app_dir / _AGENDADO).is_file()


def cancelar_agendado() -> None:
    (shared.app_dir / _AGENDADO).unlink(missing_ok=True)


def _irma(sufixo: str) -> Path:
    return shared.app_dir.with_name(shared.app_dir.name + sufixo)


def _apagar_pasta(pasta: Path) -> None:
    """`shutil.rmtree` que insiste um pouco: no Windows, o antivírus e o indexador seguram por milissegundos o que acabou de ser movido ou gravado, e a pasta recusa a remoção ("não está vazia")."""
    for tentativa in range(_TENTATIVAS_DE_APAGAR):
        try:
            shutil.rmtree(pasta)
            return
        except FileNotFoundError:
            return
        except OSError:
            if tentativa == _TENTATIVAS_DE_APAGAR - 1:
                raise
            sleep(0.2)


def _sumiu(item: Path, erro: FileNotFoundError) -> None:
    """Para o `FileNotFoundError` de quem percorre uma pasta: se ``item`` sumiu entre a listagem e a operação (um temporário do antivírus, como
    ``RESTAURAR.ZIP.tmp``), não há o que fazer. Se ainda existe, o erro é outro (caminho longo demais também dá `FileNotFoundError`) e sobe: seguir apagaria dados que não saíram do lugar."""
    try:
        item.lstat()
    except FileNotFoundError:
        logging.warning("%s sumiu durante a restauração do backup", item)
        return
    raise erro


def _devolver(anterior: Path) -> None:
    """Põe de volta na pasta do app os dados que a troca tirou. Antes da marca `_COMPLETO` nada do backup entrou: só voltam os que saíram.
    Depois dela, tudo na pasta do app (fora `_FICAM`) veio do backup e sai primeiro."""
    if not anterior.is_dir():
        return
    if (anterior / _CONCLUIDO).exists():
        # Sobra de uma troca que deu certo: devolver apagaria a biblioteca restaurada e o que veio depois.
        shutil.rmtree(anterior, ignore_errors=True)
        return
    ficam = _FICAM
    if (anterior / _SAVES_FICAM).exists():
        ficam = ficam | {_nome_dos_saves()}
    if (anterior / _COMPLETO).exists():
        for item in list(shared.app_dir.iterdir()):
            if item.name in ficam:
                continue
            try:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()
            except FileNotFoundError as erro:
                _sumiu(item, erro)
        # Feita a limpeza, a marca não vale mais: uma queda dali em diante faria a próxima abertura apagar o que já voltou.
        (anterior / _COMPLETO).unlink()
    for item in list(anterior.iterdir()):
        if item.name == _SAVES_FICAM:
            continue  # sai com a pasta
        try:
            item.replace(shared.app_dir / item.name)
        except FileNotFoundError as erro:
            _sumiu(item, erro)
    try:
        _apagar_pasta(anterior)
    except OSError:
        # Os dados já voltaram; o que sobrou é descarte, e a abertura seguinte tenta de novo.
        logging.warning("Não foi possível apagar %s", anterior, exc_info=True)


def _marcar_comandos_a_conferir() -> None:
    """Marca cada jogo restaurado para o primeiro lançamento mostrar o comando: o backup pode vir de outra pessoa, o comando roda num shell, e o zip conferido só garante os nomes das entradas. Arquivo ilegível fica como está."""
    for arquivo in shared.games_dir.glob("*.json"):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(dados, dict) and dados.get("executable"):
            dados["comando_a_conferir"] = True
            dados["inis"] = None  # caminhos de outro PC ou de outra instalação: procurados de novo
            gravar_atomico(arquivo, json.dumps(dados, indent=4, sort_keys=True))


def aplicar_pendente(progresso: Optional[Callable[[float], None]] = None) -> Optional[bool]:
    """Na abertura, antes de carregar a biblioteca: aplica o backup agendado.

    ``None``: nada agendado. ``True``: restaurado. ``False``: falhou, e dados e configurações de antes voltaram.
    ``progresso`` recebe a fração extraída (0 a 1), da thread que chama.
    """
    global pasta_dos_saves_desfeita  # pylint: disable=global-statement
    pasta_dos_saves_desfeita = None
    anterior, extraido, lixo = _irma(".anterior"), _irma(".restaurando"), _irma(".lixo")
    shutil.rmtree(lixo, ignore_errors=True)
    # Uma troca que caiu no meio deixa `.anterior`: os dados de antes voltam antes de qualquer outra coisa.
    try:
        _devolver(anterior)
    except OSError:
        logging.exception("Não foi possível recuperar a troca interrompida do backup")
        return False

    agendado = shared.app_dir / _AGENDADO
    if not agendado.is_file():
        return None

    configuracoes_antes = ler_configuracoes()
    try:
        # A sobra de uma queda, misturada à extração nova, traria de volta arquivos que o backup não tem.
        _apagar_pasta(extraido)
        # Uma leitura só (nomes e manifesto antes, CRC na própria extração): com vários GB de saves, ler duas vezes dobraria a espera.
        with zipfile.ZipFile(agendado) as arquivo:
            manifesto = _conferir(arquivo)
            extraido.mkdir()
            _extrair(arquivo, extraido, progresso or (lambda _fracao: None))

        # Sem `saves/` (todo o da versão 5), os saves de agora ficam onde estão e a pasta escolhida continua valendo.
        traz_saves = (extraido / _nome_dos_saves()).is_dir()
        ficam = _FICAM if traz_saves else _FICAM | {_nome_dos_saves()}
        anterior.mkdir()
        if not traz_saves:
            (anterior / _SAVES_FICAM).touch()
        for item in list(shared.app_dir.iterdir()):
            if item.name not in ficam:
                try:
                    item.replace(anterior / item.name)
                except FileNotFoundError as erro:
                    _sumiu(item, erro)
        (anterior / _COMPLETO).touch()
        for item in list(extraido.iterdir()):
            try:
                item.replace(shared.app_dir / item.name)
            except FileNotFoundError as erro:
                _sumiu(item, erro)

        _marcar_comandos_a_conferir()
        restauracao.gravar(
            restauracao.ids_que_dependem_de_atalho(shared.games_dir), int(time())
        )
        aplicar_configuracoes(manifesto)
        if traz_saves:
            escolhida = shared.schema.get_string(_CHAVE_DA_PASTA_DOS_SAVES)
            shared.schema.reset(_CHAVE_DA_PASTA_DOS_SAVES)
            # Só depois de zerada: uma falha antes devolve tudo, a escolha inclusive, e não há o que avisar.
            pasta_dos_saves_desfeita = escolhida or None
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("Não foi possível restaurar o backup")
        # Em passos separados: se os dados não voltam, as configurações ainda precisam voltar.
        try:
            _devolver(anterior)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Não foi possível devolver os dados de antes da restauração")
        try:
            aplicar_configuracoes(configuracoes_antes)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Não foi possível desfazer as configurações da restauração")
        resultado = False
    else:
        # Marcada e renomeada antes de apagar: uma queda no meio do rmtree deixaria um `.anterior` que a próxima abertura tomaria por troca
        # interrompida. Com a marca, ela só descarta; o que sobrar em `.lixo` sai na abertura seguinte.
        try:
            (anterior / _CONCLUIDO).touch()
            anterior.replace(lixo)
        except OSError:
            logging.exception("Não foi possível descartar os dados de antes da restauração")
        shutil.rmtree(lixo, ignore_errors=True)
        resultado = True
    finally:
        shutil.rmtree(extraido, ignore_errors=True)
        agendado.unlink(missing_ok=True)
    return resultado


# endregion
