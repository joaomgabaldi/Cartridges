# backup.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup: um retrato completo do app num .zip.

Leva a pasta do app inteira (jogos, capas, logos, papéis de parede, cores das
fitas, lista de fitas, conta da Tuya e histórico de sessões), os backups dos
saves (a pasta configurada, onde quer que esteja, entra como `saves/`) e as
configurações do registro. Fica fora só o que não pode ser restaurado com
sentido: os logs, a pasta de configuração do Ludusavi, o caminho de volta de uma
sessão em andamento, a pasta dos saves escolhida e o estado da janela. Os saves
não têm limite de tamanho: um jogo pode guardar gigabytes.

Restaurar substitui tudo, com o app fechado: `agendar` copia o .zip para a
pasta do app e Preferências reinicia o app; `aplicar_pendente`, na abertura,
antes de qualquer leitura, troca a pasta e as configurações e cria as
pendências da restauração (`utils/restauracao.py`). Se o backup traz saves, eles
voltam para a pasta padrão, dentro da mesma troca, e a escolha de outra pasta
é desfeita; se não traz (todo o da versão 5), os saves de agora e a escolha
ficam como estão. A pasta de fora nunca é tocada. Se algo falhar, tudo volta
como estava.
"""

import json
import logging
import shutil
import stat
import zipfile
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from time import sleep, time
from typing import Any, Callable, Iterable, Literal, Optional

from gi.repository import Gio, GLib

from cartridges import shared
from cartridges.saves import backup_de_saves
from cartridges.saves import pasta as pasta_dos_saves
from cartridges.utils import game_logo, restauracao, save_cover, session_wallpaper

VERSAO = 6
# Versões de backup que `validar` ainda aceita: a 5 só não tinha os saves.
_VERSOES_ACEITAS = (5, VERSAO)

_CONFIGURACOES = "configuracoes.json"
_CHAVE_DA_PASTA_DOS_SAVES = "pasta-dos-saves"
_AGENDADO = "restaurar.zip"
# Arquivos soltos na raiz da pasta do app que vão no backup.
_SOLTOS = ("fitas.json", "sessions.jsonl", "tuya_conta.json")
# O que fica na pasta do app durante a troca: os logs são desta máquina e desta
# execução, e o .zip agendado é a própria fonte da troca. A pasta `contas` também
# é desta máquina e deste usuário do Windows (o DPAPI não abre em outro PC), e
# `ludusavi` guarda a configuração do Ludusavi desta máquina.
_FICAM = frozenset({"logs", "contas", "ludusavi", _AGENDADO})
# Marca, dentro de `.anterior`, que todos os dados de antes já saíram da pasta
# do app: a partir dali, o que estiver nela veio do backup.
_COMPLETO = ".completo"
# Quanto da restauração se lê de uma vez: o progresso anda a cada pedaço.
_PEDACO = 1024 * 1024
_TENTATIVAS_DE_APAGAR = 5
# Quanto de um save é lido por vez ao copiá-lo para o backup.
_BLOCO = 1024 * 1024
# Marca, dentro de `.anterior`, que os saves da pasta padrão não saíram da
# pasta do app nesta troca (o backup não tinha saves): a limpeza de `_devolver`
# não pode apagá-los.
_SAVES_FICAM = ".saves-ficam"
# Marca, dentro de `.anterior`, que a troca deu certo: o que sobrar da pasta
# (um arquivo que o antivírus segurou) é descarte, nunca dado a devolver.
_CONCLUIDO = ".concluido"

# O caminho de volta de uma sessão em andamento nesta máquina: as telas e as
# fitas como estavam antes do jogo. Restaurado depois, "desfaria" uma troca
# que nunca aconteceu.
_CHAVES_DE_SESSAO = frozenset({"session-wallpaper-saved", "fita-estado-anterior"})

# Escolhas desta máquina, que um backup não leva nem traz: a pasta dos saves
# fica onde está (a restauração só a zera, em `aplicar_pendente`, quando o
# backup traz saves, que então ficam na pasta padrão).
_CHAVES_DESTA_MAQUINA = frozenset({_CHAVE_DA_PASTA_DOS_SAVES})

# Do schema de estado, só a ordenação é escolha de alguém. Tamanho e posição da
# janela, o balde do limitador da Steam e a última novidade vista são da máquina.
_CHAVES_DE_ESTADO = ("sort-mode",)

# O que o backup leva de cada pasta de jogo dos saves, além dos .zip: o mapa do
# Ludusavi.
_MAPA_DOS_SAVES = pasta_dos_saves.MAPA


def _extensoes() -> dict[str, tuple[str, ...]]:
    """Pasta do app -> extensões que o backup leva dela. Reaproveita as listas
    de cada módulo: uma extensão nova aceita por eles entra aqui sozinha."""
    return {
        "games": (".json",),
        "covers": (*save_cover.ANIMATED_SUFFIXES, ".tiff"),
        "logos": (".json", *game_logo.IMAGE_SUFFIXES),
        "wallpapers": (".json", *session_wallpaper.IMAGE_SUFFIXES),
        "fitas": (".json",),
        "conquistas": (".json",),
        # Aninhada, de um cache: dá menos trabalho levar as cópias prontas do
        # que regerá-las, uma a uma, na primeira abertura depois de restaurar.
        "cache/capas_animadas": (".webp",),
    }


class BackupInvalido(ValueError):
    """O arquivo não é um backup válido do Cartridges (ou está corrompido)."""


class SavesInacessiveis(Exception):
    """`exportar` não conseguiu ler a pasta dos saves (um OneDrive sem conexão,
    por exemplo): o erro não é do destino."""


# A pasta dos saves escolhida que a última `aplicar_pendente` desfez (o backup
# trouxe saves, que voltaram para a pasta padrão), para a janela avisar depois
# de aberta. Fora o caso, ``None``.
pasta_dos_saves_desfeita: str | None = None  # pylint: disable=invalid-name


# region Configurações


def _filtrar_chaves(chaves: Iterable[str]) -> list[str]:
    """``chaves`` sem as de sessão em andamento e as desta máquina. Separada de `_chaves_do_app`
    para poder ser testada sem um `Gio.Settings` de verdade."""
    return [
        chave
        for chave in chaves
        if chave not in _CHAVES_DE_SESSAO and chave not in _CHAVES_DESTA_MAQUINA
    ]


def _chaves_do_app() -> list[str]:
    return _filtrar_chaves(shared.schema.props.settings_schema.list_keys())


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


# endregion

# region Exportar


def _entradas() -> list[tuple[Path, str]]:
    """(arquivo no disco, nome no zip) de tudo o que o backup leva."""
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
    """A pasta dos saves no zip: a mesma da pasta padrão, onde a restauração os
    põe (um item da pasta do app, trocado junto com os outros)."""
    return pasta_dos_saves.padrao().name


def _e_arquivo(caminho: Path) -> bool:
    """Se ``caminho`` é um arquivo comum. Só "não existe" (ou o que vem antes não é
    pasta) é "não"; qualquer outro erro de leitura sobe como `OSError`. `Path.is_file`
    engole todos, e um save de fora, sem aviso, seria um backup incompleto."""
    try:
        return stat.S_ISREG(caminho.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return False


def _mapa_de_jogo(mapa: Path) -> bool:
    """Se ``mapa`` (o `mapping.yaml` de uma subpasta de `pasta`) existe, como `_e_arquivo`.
    Subpasta que é junção ou atalho não é jogo do Ludusavi, que não grava assim, e nem é
    consultada: as junções antigas de Documentos ("Minhas Músicas"…) negam acesso, e a
    raiz escolhida pode ser essa pasta."""
    jogo = mapa.parent
    return not (jogo.is_symlink() or jogo.is_junction()) and _e_arquivo(mapa)


def _entradas_dos_saves(pasta: Path) -> list[tuple[Path, str]]:
    """Os saves de ``pasta`` (a configurada: a padrão ou a escolhida, que existe),
    sempre como ``saves/<jogo>/<arquivo>``. Só as pastas de jogo do Ludusavi: a
    escolhida pode ser a raiz do OneDrive, e o resto dela não é do app. Não ser um
    save é não existir o `mapping.yaml` ou o arquivo; qualquer outro erro de leitura
    levanta `OSError`, e a exportação falha em vez de deixar um save de fora."""
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
    # As imagens e os backups dos saves (.zip) já vêm comprimidos: passar
    # deflate neles custa segundos e não ganha nada. Só o texto é comprimido.
    return (
        zipfile.ZIP_DEFLATED
        if caminho.suffix in (".json", ".jsonl", ".yaml")
        else zipfile.ZIP_STORED
    )


def _incluir(arquivo: zipfile.ZipFile, caminho: Path, nome: str) -> None:
    try:
        arquivo.write(caminho, nome, compress_type=_compressao(caminho))
    except FileNotFoundError:
        # Apagado entre a listagem e a leitura (uma capa trocada agora): o
        # backup sai sem ele, em vez de não sair.
        logging.debug("%s sumiu durante o backup", caminho)


def _incluir_save(arquivo: zipfile.ZipFile, caminho: Path, nome: str) -> None:
    """Como `_incluir`, para um arquivo da pasta dos saves, que pode estar num
    OneDrive sem conexão: só o erro de LER vira `SavesInacessiveis`, inclusive o
    arquivo que sumiu (com a trava dos saves, nada some de forma legítima: é a pasta
    que ficou fora de alcance). O de gravar no destino (disco cheio, rede caindo)
    segue como veio e mantém a mensagem do destino; por isso a leitura e a
    gravação não são feitas por `ZipFile.write`, que não deixa separá-las."""
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


def exportar(
    destino: Path, configuracoes: dict[str, Any]
) -> Literal["ausente", "vazia"] | None:
    """Grava o backup em ``destino``. Pode rodar fora da thread principal;
    ``configuracoes`` vem de `ler_configuracoes`, lida na principal.

    Devolve ``"ausente"`` se a pasta dos saves escolhida não existe ou não pode ser
    alcançada, e ``"vazia"`` se existe mas não tem nenhuma cópia de save: nos dois o
    .zip é gerado sem saves e quem chamou precisa avisar. Em todo o resto, ``None``;
    a pasta padrão ausente ou vazia não conta (ainda não houve backup de save)."""
    manifesto = {
        "version": VERSAO,
        "app_version": shared.VERSION,
        "created": int(time()),
        **configuracoes,
    }
    # Temporário + troca: exportar por cima de um backup antigo e cair no meio
    # deixaria o antigo perdido e o novo ilegível.
    temporario = destino.with_name(destino.name + ".tmp")
    aviso: Literal["ausente", "vazia"] | None = None
    try:
        # strict_timestamps=False: um arquivo com data anterior a 1980 (que o
        # formato zip não representa) entra com 1980, em vez de abortar tudo.
        with zipfile.ZipFile(temporario, "w", strict_timestamps=False) as arquivo:
            arquivo.writestr(
                _CONFIGURACOES,
                json.dumps(manifesto, indent=2, ensure_ascii=False),
                compress_type=zipfile.ZIP_DEFLATED,
            )
            for caminho, nome in _entradas():
                _incluir(arquivo, caminho, nome)
            # Com a trava do Ludusavi: um backup de save em andamento não pode
            # entrar aqui pela metade.
            with backup_de_saves.trava_dos_saves():
                # A pasta é lida uma vez, antes da listagem: o aviso e o que entra no
                # .zip partem da mesma leitura, mesmo que ela apareça ou suma depois.
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
                        # A pasta pode ter sumido entre a leitura e a listagem: fora de
                        # alcance não é "sem saves".
                        aviso = "vazia" if pasta.is_dir() else "ausente"
                for caminho, nome in entradas:
                    _incluir_save(arquivo, caminho, nome)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)
    return aviso


# endregion

# region Validar


def _nome_valido(nome: str, extensoes_por_pasta: dict[str, tuple[str, ...]]) -> bool:
    """Só o que `exportar` grava: o manifesto, um arquivo solto conhecido,
    ``<pasta conhecida>/<arquivo com extensão conhecida>`` ou
    ``saves/<jogo>/<mapping.yaml ou .zip>``. Nada absoluto, nada com ``..``,
    nada em subpasta que `_extensoes` não liste."""
    if nome in (_CONFIGURACOES, *_SOLTOS):
        return True
    if "\\" in nome or ":" in nome:
        return False
    partes = PurePosixPath(nome).parts
    if len(partes) < 2:
        return False
    if partes[0] == _nome_dos_saves():
        # Exatamente saves/<jogo>/<arquivo>; um nível só, como `exportar` grava.
        return (
            len(partes) == 3
            and partes[1] not in (".", "..")
            and _arquivo_de_save_valido(partes[2])
        )
    # A pasta pode ser aninhada ("cache/capas_animadas"): vale o que
    # `_extensoes` lista, inteiro.
    pasta, arquivo = "/".join(partes[:-1]), partes[-1]
    extensoes = extensoes_por_pasta.get(pasta)
    if extensoes is None or arquivo.startswith("."):
        return False
    return PurePosixPath(arquivo).suffix.lower() in extensoes


def _conferir(arquivo: zipfile.ZipFile) -> dict[str, Any]:
    """Os nomes e o manifesto de um backup aberto, sem ler o resto.
    ``BackupInvalido`` se não for um."""
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
    """O manifesto de um backup. ``BackupInvalido`` se não for um."""
    try:
        with zipfile.ZipFile(caminho) as arquivo:
            manifesto = _conferir(arquivo)
            # Sem limite de tamanho: os saves de um jogo chegam a gigabytes. O
            # nome e o CRC já pegam o zip que não é nosso.
            # O CRC de cada entrada: um byte trocado numa capa passaria daqui e
            # só estouraria no meio da troca.
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
    """Grava as entradas (menos o manifesto) em ``destino``, aos pedaços.

    O ``zipfile`` confere o CRC de cada entrada no fim da leitura: um byte
    trocado levanta aqui, antes de qualquer dado do app sair do lugar.
    ``progresso`` recebe a fração dos bytes já gravados.
    """
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
    """Copia ``origem`` para a pasta do app. A troca acontece na próxima
    abertura (`aplicar_pendente`); quem chama reinicia o app."""
    destino = shared.app_dir / _AGENDADO
    temporario = destino.with_name(destino.name + ".tmp")
    try:
        shutil.copyfile(origem, temporario)
        temporario.replace(destino)
    finally:
        temporario.unlink(missing_ok=True)


def ha_pendente() -> bool:
    """Há um backup agendado para a próxima abertura."""
    return (shared.app_dir / _AGENDADO).is_file()


def cancelar_agendado() -> None:
    """Desfaz `agendar`: nada é aplicado na próxima abertura."""
    (shared.app_dir / _AGENDADO).unlink(missing_ok=True)


def _irma(sufixo: str) -> Path:
    return shared.app_dir.with_name(shared.app_dir.name + sufixo)


def _apagar_pasta(pasta: Path) -> None:
    """`shutil.rmtree` que insiste um pouco. No Windows, o antivírus e o indexador
    seguram por alguns milissegundos o que acabou de ser movido ou gravado, e a
    pasta recusa a remoção ("não está vazia") logo depois de esvaziada."""
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


def _devolver(anterior: Path) -> None:
    """Põe de volta na pasta do app os dados que a troca tirou dela.

    Antes da marca `_COMPLETO`, nada do backup entrou ainda: só se movem de
    volta os que já tinham saído. Depois dela, tudo o que está na pasta do app
    (fora `_FICAM`) veio do backup e sai primeiro.
    """
    if not anterior.is_dir():
        return
    if (anterior / _CONCLUIDO).exists():
        # Sobra de uma troca que deu certo: devolver apagaria a biblioteca
        # restaurada e tudo o que veio depois dela.
        shutil.rmtree(anterior, ignore_errors=True)
        return
    ficam = _FICAM
    if (anterior / _SAVES_FICAM).exists():
        ficam = ficam | {_nome_dos_saves()}
    if (anterior / _COMPLETO).exists():
        for item in list(shared.app_dir.iterdir()):
            if item.name in ficam:
                continue
            if item.is_dir():
                shutil.rmtree(item)
            else:
                item.unlink()
        # Feita a limpeza, a marca não vale mais: uma queda (ou um arquivo
        # preso ao apagar `.anterior`) dali em diante faria a próxima abertura
        # apagar de novo, junto, o que já voltou.
        (anterior / _COMPLETO).unlink()
    for item in list(anterior.iterdir()):
        if item.name == _SAVES_FICAM:
            continue  # sai com a pasta
        try:
            item.replace(shared.app_dir / item.name)
        except FileNotFoundError:
            # Sumiu entre a listagem e a troca (um temporário que o antivírus
            # criou ali e já apagou): não há o que devolver.
            logging.warning("%s sumiu durante a recuperação do backup", item)
    try:
        _apagar_pasta(anterior)
    except OSError:
        # Os dados já voltaram; o que sobrou é descarte, e a abertura seguinte
        # tenta de novo.
        logging.warning("Não foi possível apagar %s", anterior, exc_info=True)


def aplicar_pendente(progresso: Optional[Callable[[float], None]] = None) -> Optional[bool]:
    """Na abertura, antes de carregar a biblioteca: aplica o backup agendado.

    ``None``: nada agendado. ``True``: restaurado. ``False``: falhou, e os
    dados e as configurações de antes voltaram ao lugar. ``progresso`` recebe a
    fração extraída do backup (de 0 a 1), da thread que chama.
    """
    global pasta_dos_saves_desfeita  # pylint: disable=global-statement
    pasta_dos_saves_desfeita = None
    anterior, extraido, lixo = _irma(".anterior"), _irma(".restaurando"), _irma(".lixo")
    shutil.rmtree(lixo, ignore_errors=True)
    # Uma troca que caiu no meio (app morto, PC desligado) deixa `.anterior`:
    # os dados de antes voltam antes de qualquer outra coisa.
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
        shutil.rmtree(extraido, ignore_errors=True)
        # Uma leitura só: os nomes e o manifesto antes, e o CRC de cada entrada
        # na própria extração — com vários GB de saves, ler duas vezes era
        # dobrar a espera.
        with zipfile.ZipFile(agendado) as arquivo:
            manifesto = _conferir(arquivo)
            extraido.mkdir()
            _extrair(arquivo, extraido, progresso or (lambda _fracao: None))

        # Sem `saves/` no backup (todo o da versão 5), os saves de agora ficam
        # onde estão, e a pasta escolhida continua valendo.
        traz_saves = (extraido / _nome_dos_saves()).is_dir()
        ficam = _FICAM if traz_saves else _FICAM | {_nome_dos_saves()}
        anterior.mkdir()
        if not traz_saves:
            (anterior / _SAVES_FICAM).touch()
        for item in list(shared.app_dir.iterdir()):
            if item.name not in ficam:
                item.replace(anterior / item.name)
        (anterior / _COMPLETO).touch()
        for item in list(extraido.iterdir()):
            item.replace(shared.app_dir / item.name)

        restauracao.gravar(
            restauracao.ids_que_dependem_de_atalho(shared.games_dir), int(time())
        )
        aplicar_configuracoes(manifesto)
        if traz_saves:
            # Os saves do backup entraram na pasta padrão, na troca acima.
            escolhida = shared.schema.get_string(_CHAVE_DA_PASTA_DOS_SAVES)
            shared.schema.reset(_CHAVE_DA_PASTA_DOS_SAVES)
            Gio.Settings.sync()
            # Só depois de zerada: uma falha antes daqui devolve tudo, a escolha
            # inclusive, e não há o que avisar.
            pasta_dos_saves_desfeita = escolhida or None
    except Exception:  # pylint: disable=broad-exception-caught
        logging.exception("Não foi possível restaurar o backup")
        # Em passos separados: se os dados não voltam, as configurações de antes
        # ainda precisam voltar.
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
        # Marcada e renomeada antes de apagar: uma queda no meio do rmtree, ou
        # um arquivo preso que impeça a renomeação, deixaria um `.anterior`
        # que a próxima abertura tomaria por uma troca interrompida. Com a
        # marca, ela só descarta; o que sobrar em `.lixo` sai na abertura
        # seguinte.
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
