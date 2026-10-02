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


# Onde a Steam diz que está instalada: a chave do usuário e, na falta dela (uma
# instalação para todos os usuários), a da máquina. Nunca um caminho fixo: cada
# um instala a Steam onde quiser. `appcache` e `userdata` ficam sempre ali,
# nunca nas bibliotecas de jogos de outros discos.
_CHAVES_DA_STEAM = (
    (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
)


def _valor_do_registro(raiz: int, caminho: str, nome: str) -> Optional[str]:
    try:
        with winreg.OpenKey(raiz, caminho) as chave:
            valor = winreg.QueryValueEx(chave, nome)[0]
    except OSError:
        return None
    return valor if isinstance(valor, str) and valor.strip() else None


def pasta_da_steam() -> Optional[Path]:
    for raiz, caminho, nome in _CHAVES_DA_STEAM:
        valor = _valor_do_registro(raiz, caminho, nome)
        if valor and (pasta := Path(valor.strip())).is_dir():
            return pasta
    return None


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


def _contas(steam: Path) -> list[Path]:
    """As contas da Steam neste PC: as pastas de `userdata` com nome só de dígitos."""
    return [conta for conta in _subpastas(steam / "userdata") if appid_valido(conta.name)]


def _estado_na_steam(steam: Path, conta: Path, appid: str) -> ArquivoDeConquista:
    return ArquivoDeConquista(
        steam / "appcache" / "stats" / f"UserGameStats_{conta.name}_{appid}.bin",
        formatos.STEAM_STATS,
    )


def _na_steam(appid: str) -> list[ArquivoDeConquista]:
    """O estado que a própria Steam guarda e o cache da biblioteca, por conta."""
    steam = pasta_da_steam()
    if steam is None:
        return []
    achados = []
    for conta in _contas(steam):
        achados.append(_estado_na_steam(steam, conta, appid))
        achados.append(
            ArquivoDeConquista(conta / "config" / "librarycache" / f"{appid}.json", formatos.STEAM)
        )
    return achados


def appid_valido(appid: object) -> bool:
    """Só dígitos ASCII. O appID vira pedaço de caminho (as pastas dos emuladores,
    o arquivo do cache) e entra em URL; `..` ou uma barra escapariam da pasta."""
    texto = str(appid)
    return texto.isascii() and texto.isdigit()


def arquivos_do_jogo(appid: str, executavel: str) -> list[ArquivoDeConquista]:
    """Os arquivos de conquista que existem hoje para ``appid``, sem repetição."""
    if not appid_valido(appid):
        return []
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


def da_steam_esperados(appid: str, executavel: str) -> list[ArquivoDeConquista]:
    """O estado da Steam de cada conta, exista ou não ainda.

    A Steam cria esse arquivo ao abrir o jogo, já com as conquistas antigas: o
    vigia precisa conhecê-lo antes, para lê-lo em silêncio quando aparecer.
    """
    if not appid_valido(appid) or not eh_jogo_da_steam(executavel):
        return []
    steam = pasta_da_steam()
    if steam is None:
        return []
    return [_estado_na_steam(steam, conta, appid) for conta in _contas(steam)]
