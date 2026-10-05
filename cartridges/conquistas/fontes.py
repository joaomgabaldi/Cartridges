"""De onde vêm as conquistas de cada jogo — ou de lugar nenhum, e o cartão some.

Três respostas: a conta de uma loja (Xbox ou Epic; ver `contas.py`; jogo do
Xbox/Game Pass com a conta Microsoft conectada, ou jogo da Epic com a conta Epic
conectada), a Steam ou um emulador (appID e onde ler o progresso: atalho
`steam://`, arquivo de emulador, ou sinal de emulador na pasta do jogo), ou
nenhuma. Jogo do Xbox ou da Epic sem conta não cai para a Steam: o catálogo da
Steam ficaria parado em "0 de N", que é justamente o que esta regra acaba.

`do_jogo` olha o disco e roda em thread (varredura, vigia). A página do jogo
não pode tocar no disco do jogo (um HD dormindo travaria a tela), então a
varredura grava a fonte no histórico (`historico.registrar(..., fonte=)`) e o
cartão usa `gravada`.
"""

import json
import logging
import os
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from cartridges.conquistas import arquivos, contas, historico
from cartridges.conquistas.epic import api as epic_api, conta as epic_conta
from cartridges.conquistas.xbox import api, conta
from cartridges.utils.run_executable import aumid_from_command

XBOX = "xbox"
STEAM = "steam"
EPIC = "epic"
_NAMESPACE = re.compile(r"[A-Za-z0-9_-]{1,64}")
# `com.epicgames.launcher://apps/<ns>%3A<item>%3A<AppName>?action=launch` (Playnite
# `EpicLauncher.cs`) ou, nos atalhos antigos, `.../apps/<AppName>?...`.
_URL_DA_EPIC = re.compile(r"com\.epicgames\.launcher://apps/([^?\"\s]+)", re.IGNORECASE)
_TAMANHO_DO_MANIFEST = 1024 * 1024
_MANIFESTS = 500
SINAIS_DE_EMULADOR = frozenset(
    {
        "steam_settings",
        "steam_emu.ini",
        "ali213.ini",
        "onlinefix.ini",
        "onlinefix64.dll",
        "cream_api.ini",
        "codex.ini",
        "3dmgame.ini",
    }
)


@dataclass(frozen=True)
class Fonte:
    tipo: str
    # titleId (xbox), namespace (epic) ou appID (steam); "" numa fonte de loja ainda
    # sem id (nunca gravada).
    id: str

    @property
    def texto(self) -> str:
        return f"{self.tipo}:{self.id}"

    @staticmethod
    def de_texto(texto: Optional[str]) -> Optional["Fonte"]:
        if not isinstance(texto, str) or texto.count(":") != 1:
            return None
        tipo, id_ = texto.split(":")
        if tipo == EPIC:
            valido = _NAMESPACE.fullmatch(id_) is not None
        else:
            valido = tipo in (XBOX, STEAM) and arquivos.appid_valido(id_)
        return Fonte(tipo, id_) if valido else None


def pfn(game: Any) -> Optional[str]:
    aumid = aumid_from_command(getattr(game, "executable", "") or "")
    return (aumid.split("!", 1)[0] or None) if aumid else None


def bases(game: Any) -> list[Path]:
    return arquivos.bases_do_jogo(getattr(game, "executable", "") or "")


def _tem_config(pastas: list[Path]) -> bool:
    return any((base / "MicrosoftGame.config").is_file() for base in pastas)


def eh_do_xbox(game: Any) -> bool:
    try:
        return pfn(game) is not None or _tem_config(bases(game))
    except OSError:
        return False


def _tem_sinal(pastas: list[Path]) -> bool:
    for base in pastas:
        try:
            if any(item.name.casefold() in SINAIS_DE_EMULADOR for item in base.iterdir()):
                return True
        except OSError:
            continue
    return False


def _da_steam(game: Any) -> Optional[Fonte]:
    appid = getattr(game, "steam_appid", None)
    if not arquivos.appid_valido(appid):
        return None
    executavel = getattr(game, "executable", "") or ""
    if (
        arquivos.eh_jogo_da_steam(executavel)
        or arquivos.arquivos_do_jogo(str(appid), executavel)
        or _tem_sinal(arquivos.bases_do_jogo(executavel))
    ):
        return Fonte(STEAM, str(appid))
    return None


def _da_url(executavel: str) -> Optional[tuple[str, str]]:
    achado = _URL_DA_EPIC.search(executavel or "")
    if achado is None:
        return None
    partes = urllib.parse.unquote(achado.group(1)).split(":")
    if len(partes) == 3:
        namespace, _item, app = partes
        return (namespace if _NAMESPACE.fullmatch(namespace) else ""), app
    if len(partes) == 1 and partes[0]:
        return "", partes[0]
    return None


def url_da_epic(game: Any) -> bool:
    """Se o executável é o atalho do launcher da Epic. Só o texto, nunca o disco."""
    return _da_url(getattr(game, "executable", "") or "") is not None


def _manifests() -> list[dict]:
    """Os manifests do Epic Games Launcher instalado (`<guid>.item`, JSON), já filtrados."""
    pasta = arquivos.pastas_do_sistema().programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    try:
        itens = sorted(item for item in pasta.iterdir() if item.suffix.casefold() == ".item")[:_MANIFESTS]
    except OSError:
        return []
    lidos = []
    for item in itens:
        try:
            if item.stat().st_size > _TAMANHO_DO_MANIFEST:
                continue
            dados = json.loads(item.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, RecursionError):
            continue
        namespace = dados.get("CatalogNamespace") if isinstance(dados, dict) else None
        if isinstance(namespace, str) and _NAMESPACE.fullmatch(namespace):
            lidos.append(dados)
    return lidos


def _dos_manifests(app: str) -> Optional[str]:
    """O namespace do ``AppName`` nos manifests do launcher."""
    procurado = app.casefold()
    for dados in _manifests():
        if isinstance(dados.get("AppName"), str) and dados["AppName"].casefold() == procurado:
            return dados["CatalogNamespace"]
    return None


def _da_pasta(pastas: list[Path]) -> Optional[tuple[str, str]]:
    """O jogo cuja pasta de instalação (``InstallLocation`` do manifest) contém o exe.

    Atalho `.lnk` direto para o exe: a pasta do jogo não guarda o namespace (o
    ``.egstore`` só tem o manifesto binário, conferido no host), o manifest do launcher guarda.
    """
    if not pastas:
        return None
    for dados in _manifests():
        local = dados.get("InstallLocation")
        if not isinstance(local, str) or not local.strip():
            continue
        try:
            raiz = Path(os.path.normcase(os.path.abspath(local)))
        except (OSError, ValueError):
            continue
        for base in pastas:
            pasta = Path(os.path.normcase(os.path.abspath(base)))
            # Pasta inteira: `FallGuys2` não está dentro de `FallGuys`.
            if pasta == raiz or raiz in pasta.parents:
                app = dados.get("AppName")
                return dados["CatalogNamespace"], app if isinstance(app, str) else ""
    return None


def da_epic(game: Any) -> Optional[tuple[str, str]]:
    """``(namespace, AppName)`` do jogo da Epic; namespace ``""`` = pendente (a
    segunda passada resolve pela biblioteca). ``None``: não é jogo da Epic.
    Olha o disco: só em thread."""
    da_url = _da_url(getattr(game, "executable", "") or "")
    if da_url is not None:
        namespace, app = da_url
        if namespace or not app:
            return namespace, app
        return (_dos_manifests(app) or epic_api.namespace_local_do_app(app) or ""), app
    return _da_pasta(bases(game))


def eh_da_epic(game: Any) -> bool:
    try:
        return da_epic(game) is not None
    except OSError:
        return False


def do_jogo(game: Any) -> Optional[Fonte]:
    """A fonte do jogo, olhando o disco. Roda em thread e nunca levanta."""
    try:
        if eh_do_xbox(game):
            if not conta.conectada():
                return None
            titulo = api.titulo_local(pfn(game), bases(game))
            if titulo is None:
                return Fonte(XBOX, "")
            if titulo:
                return Fonte(XBOX, titulo)
            # "" é pacote sabidamente sem Xbox Live: vale a regra da Steam.
        epic = da_epic(game)
        if epic is not None:
            # Jogo da Epic sem conta não cai para a Steam (cartão oculto).
            return Fonte(EPIC, epic[0]) if epic_conta.conectada() else None
        return _da_steam(game)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning(
            "Falha ao decidir a fonte das conquistas de %s", getattr(game, "name", "?"), exc_info=True
        )
        return None


def gravada(game: Any) -> Optional[Fonte]:
    """A fonte guardada no histórico. Só lê o arquivo do histórico, nunca o disco do jogo."""
    return Fonte.de_texto(historico.fonte(game.game_id))


def ativa(fonte: Optional[Fonte]) -> bool:
    """Steam e emulador sempre; loja com conta, só com a conta conectada."""
    if fonte is None:
        return False
    loja = contas.da_fonte(fonte)
    return loja is None or loja.conectada()


def chave_do_catalogo(fonte: Fonte) -> str:
    loja = contas.da_fonte(fonte)
    return loja.chave_do_catalogo(fonte.id) if loja is not None else fonte.id
