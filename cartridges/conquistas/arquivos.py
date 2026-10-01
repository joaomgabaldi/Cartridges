"""Onde cada emulador de Steam (e a Steam) grava as conquistas de um jogo.

A tabela de caminhos é a de `find-achievement-files.ts` do Hydra Launcher
(hydralauncher/hydra, licença MIT). Os caminhos do AppData e dos Documentos
sobrevivem à desinstalação do jogo; os da pasta do jogo, não — e é por isso que
o app guarda o que leu (`historico`).

FLT, SmartSteamEmu e RLE ficam de fora: o Hydra não tem leitor para eles.
"""

import os
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gi.repository import GLib

from cartridges.conquistas import formatos
from cartridges.importer.shortcuts_source import steam_appid_from_url
from cartridges.utils.game_folder import game_folder


@dataclass(frozen=True)
class ArquivoDeConquista:
    caminho: Path
    formato: str


@dataclass(frozen=True)
class Pastas:
    appdata: Path
    localappdata: Path
    documentos: Path
    documentos_publicos: Path
    programdata: Path


# Nomes de pasta que guardam o executável sem ser a raiz do jogo
# (`NESTED_EXECUTABLE_DIRS` do Hydra). Só se sobe por elas: um executável em
# `C:\Jogos\X\x.exe` nunca leva a busca a `C:\Jogos`, onde moram os outros.
_PASTAS_DE_BINARIOS = frozenset(
    {"bin", "bin32", "bin64", "binaries", "win32", "win64", "x64", "x86", "game", "runtime"}
)
_SUBIDAS = 3


def pastas_do_sistema() -> Pastas:
    perfil = Path(os.environ.get("USERPROFILE", str(Path.home())))
    documentos = GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
    return Pastas(
        appdata=Path(os.environ.get("APPDATA", str(perfil / "AppData" / "Roaming"))),
        localappdata=Path(os.environ.get("LOCALAPPDATA", str(perfil / "AppData" / "Local"))),
        documentos=Path(documentos) if documentos else perfil / "Documents",
        documentos_publicos=Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Documents",
        programdata=Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")),
    )


def pasta_da_steam() -> Optional[Path]:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as chave:
            valor = winreg.QueryValueEx(chave, "SteamPath")[0]
    except OSError:
        return None
    pasta = Path(str(valor))
    return pasta if pasta.is_dir() else None


def eh_jogo_da_steam(executavel: str) -> bool:
    return steam_appid_from_url(executavel or "") is not None


def _subpastas(pasta: Path) -> list[Path]:
    try:
        return sorted(p for p in pasta.iterdir() if p.is_dir())
    except OSError:
        return []


def bases_do_jogo(executavel: str) -> list[Path]:
    """A pasta do executável e as pastas-pai que ainda são do jogo."""
    pasta = game_folder(executavel or "")
    if not pasta:
        return []
    atual = Path(pasta)
    bases = [atual]
    for _subida in range(_SUBIDAS):
        if atual.name.casefold() not in _PASTAS_DE_BINARIOS or atual.parent == atual:
            break
        atual = atual.parent
        bases.append(atual)
    return bases


def _fixos(p: Pastas, appid: str) -> list[ArquivoDeConquista]:
    def a(caminho: Path, formato: str) -> ArquivoDeConquista:
        return ArquivoDeConquista(caminho, formato)

    return [
        a(p.appdata / "Goldberg SteamEmu Saves" / appid / "achievements.json", formatos.GOLDBERG),
        a(p.appdata / "GSE Saves" / appid / "achievements.json", formatos.GOLDBERG),
        a(p.documentos_publicos / "Steam" / "CODEX" / appid / "achievements.ini", formatos.PADRAO),
        a(p.appdata / "Steam" / "CODEX" / appid / "achievements.ini", formatos.PADRAO),
        a(p.documentos_publicos / "Steam" / "RUNE" / appid / "achievements.ini", formatos.PADRAO),
        a(p.documentos_publicos / "OnlineFix" / appid / "Stats" / "Achievements.ini", formatos.ONLINEFIX),
        a(p.documentos_publicos / "OnlineFix" / appid / "Achievements.ini", formatos.ONLINEFIX),
        a(p.appdata / "EMPRESS" / "remote" / appid / "achievements.json", formatos.GOLDBERG),
        a(
            p.documentos_publicos / "EMPRESS" / appid / "remote" / appid / "achievements.json",
            formatos.GOLDBERG,
        ),
        a(p.programdata / "RLD!" / appid / "achievements.ini", formatos.RLD),
        a(p.programdata / "Steam" / "Player" / appid / "stats" / "achievements.ini", formatos.RLD),
        a(p.programdata / "Steam" / "RLD!" / appid / "stats" / "achievements.ini", formatos.RLD),
        a(p.programdata / "Steam" / "dodi" / appid / "stats" / "achievements.ini", formatos.RLD),
        a(p.documentos / "SKIDROW" / appid / "SteamEmu" / "UserStats" / "achiev.ini", formatos.SKIDROW),
        a(p.documentos / "Player" / appid / "SteamEmu" / "UserStats" / "achiev.ini", formatos.SKIDROW),
        a(p.localappdata / "SKIDROW" / appid / "SteamEmu" / "UserStats" / "achiev.ini", formatos.SKIDROW),
        a(p.appdata / "CreamAPI" / appid / "stats" / "CreamAPI.Achievements.cfg", formatos.CREAMAPI),
        a(p.appdata / ".1911" / appid / "achievement", formatos.RAZOR1911),
    ]


def _aninhados(p: Pastas, appid: str) -> list[ArquivoDeConquista]:
    """Goldberg e GSE com um nível a mais (`scan-nested-achievement-files.ts`)."""
    achados = []
    for raiz in (p.appdata / "Goldberg SteamEmu Saves" / appid, p.appdata / "GSE Saves" / appid):
        for sub in _subpastas(raiz):
            achados.append(ArquivoDeConquista(sub / "achievements.json", formatos.GOLDBERG))
    return achados


def _na_pasta_do_jogo(bases: list[Path], appid: str) -> list[ArquivoDeConquista]:
    achados = []
    for base in bases:
        achados.append(ArquivoDeConquista(base / "SteamData" / "user_stats.ini", formatos.USERSTATS))
        for settings in (base / "steam_settings", base / "coldclient" / "steam_settings"):
            achados.append(ArquivoDeConquista(settings / appid / "achievements.json", formatos.GOLDBERG))
        for perfil in _subpastas(base / "3DMGAME"):
            achados.append(ArquivoDeConquista(perfil / "stats" / "achievements.ini", formatos.TRES_DM))
        for perfil in _subpastas(base / "Profile"):
            achados.append(ArquivoDeConquista(perfil / "Stats" / "Achievements.Bin", formatos.ALI213))
    return achados


def _na_steam(appid: str) -> list[ArquivoDeConquista]:
    pasta = pasta_da_steam()
    if pasta is None:
        return []
    return [
        ArquivoDeConquista(conta / "config" / "librarycache" / f"{appid}.json", formatos.STEAM)
        for conta in _subpastas(pasta / "userdata")
    ]


def arquivos_do_jogo(appid: str, executavel: str) -> list[ArquivoDeConquista]:
    """Os arquivos de conquista que existem hoje para ``appid``, sem repetição."""
    pastas = pastas_do_sistema()
    candidatos = [
        *_fixos(pastas, appid),
        *_aninhados(pastas, appid),
        *_na_pasta_do_jogo(bases_do_jogo(executavel), appid),
    ]
    if eh_jogo_da_steam(executavel):
        candidatos.extend(_na_steam(appid))

    vistos: set[str] = set()
    existentes = []
    for candidato in candidatos:
        chave = str(candidato.caminho).casefold()
        if chave in vistos or not candidato.caminho.is_file():
            continue
        vistos.add(chave)
        existentes.append(candidato)
    return existentes
