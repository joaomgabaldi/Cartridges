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

from cartridges.conquistas import formatos, keyvalues
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


_CHAVE_DA_CONTA_ATIVA = (
    winreg.HKEY_CURRENT_USER,
    r"Software\Valve\Steam\ActiveProcess",
    "ActiveUser",
)
# O steamid64 de uma conta é este valor mais o número da conta (a pasta de `userdata`).
_STEAMID64_BASE = 76561197960265728


def _inteiro_do_registro(raiz: int, caminho: str, nome: str) -> Optional[int]:
    """Um valor DWORD do registro. Nunca levanta; o que não é inteiro vale None."""
    try:
        with winreg.OpenKey(raiz, caminho) as chave:
            valor = winreg.QueryValueEx(chave, nome)[0]
    except OSError:
        return None
    return valor if isinstance(valor, int) and not isinstance(valor, bool) else None


def pasta_da_steam() -> Optional[Path]:
    for raiz, caminho, nome in _CHAVES_DA_STEAM:
        valor = _valor_do_registro(raiz, caminho, nome)
        # Só caminho absoluto: um valor relativo valeria a partir da pasta atual do app.
        if valor and (pasta := Path(valor.strip())).is_absolute() and pasta.is_dir():
            return pasta
    return None


def eh_caminho_de_rede(caminho: object) -> bool:
    """Se ``caminho`` começa como UNC (``\\\\servidor\\…``, ``//servidor/…``,
    ``\\\\?\\UNC\\…``, ``\\\\.\\…``). Só olha o texto: checar o arquivo já faria o
    Windows conectar na máquina e mandar as credenciais do usuário."""
    texto = str(caminho or "").lstrip()
    return len(texto) >= 2 and texto[0] in "\\/" and texto[1] in "\\/"


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


def _numero(texto: object) -> Optional[int]:
    """Um inteiro de até 20 dígitos ASCII; o resto (e arquivo de 1 MB de dígitos) é None."""
    if not isinstance(texto, str) or len(texto) > 20 or not appid_valido(texto):
        return None
    return int(texto)


def _conta_conectada() -> Optional[str]:
    """A conta com a Steam aberta agora (``ActiveUser``; 0 com a Steam fechada)."""
    ativa = _inteiro_do_registro(*_CHAVE_DA_CONTA_ATIVA)
    return str(ativa) if ativa is not None and ativa > 0 else None


def _conta_mais_recente(steam: Path) -> Optional[str]:
    """A última conta que entrou na Steam, pelo `config\\loginusers.vdf`: a marcada
    com ``MostRecent`` ou, sem marca, a de maior ``Timestamp``. Ilegível: None."""
    dados = keyvalues.ler_texto(steam / "config" / "loginusers.vdf")
    usuarios = dados.get("users") if dados else None
    if not isinstance(usuarios, dict):
        return None
    candidatos: list[tuple[bool, int, str]] = []
    for steamid64, campos in usuarios.items():
        numero = _numero(steamid64)
        if numero is None or not isinstance(campos, dict):
            continue
        conta = numero - _STEAMID64_BASE
        if conta <= 0:
            continue
        carimbo = _numero(campos.get("Timestamp")) or 0
        candidatos.append((campos.get("MostRecent") == "1", carimbo, str(conta)))
    # Marcada vence; entre as marcadas (ou entre todas, sem marca), a mais nova.
    return max(candidatos)[2] if candidatos else None


def _contas(steam: Path) -> list[Path]:
    """As contas da Steam deste PC cujos arquivos valem.

    Uma só, quando dá para saber qual é: a conectada agora ou, com a Steam
    fechada, a última que entrou. O histórico só soma, então misturar as contas
    de quem divide o PC misturaria as conquistas. Sem saber (ou se a conta achada
    não tem pasta em `userdata`), todas: as pastas com nome só de dígitos.
    """
    todas = [conta for conta in _subpastas(steam / "userdata") if appid_valido(conta.name)]
    achada = _conta_conectada() or _conta_mais_recente(steam)
    if achada is None:
        return todas
    return [conta for conta in todas if conta.name == achada] or todas


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
