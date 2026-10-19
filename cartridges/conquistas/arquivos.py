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
from typing import Iterable, Optional, TypeVar

from gi.repository import GLib

from cartridges import shared
from cartridges.conquistas import formatos
from cartridges.importer.shortcuts_source import steam_appid_from_url
from cartridges.utils.game_folder import game_folder


T = TypeVar("T")


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


def _do_registro(raiz: int, caminho: str, nome: str) -> object:
    """O valor cru do registro, ou None se a chave ou o valor não existem. Nunca levanta."""
    try:
        with winreg.OpenKey(raiz, caminho) as chave:
            return winreg.QueryValueEx(chave, nome)[0]
    except OSError:
        return None


def _valor_do_registro(raiz: int, caminho: str, nome: str) -> Optional[str]:
    valor = _do_registro(raiz, caminho, nome)
    return valor if isinstance(valor, str) and valor.strip() else None


_CHAVE_DA_CONTA_ATIVA = (
    winreg.HKEY_CURRENT_USER,
    r"Software\Valve\Steam\ActiveProcess",
    "ActiveUser",
)
# A última conta que o `ActiveUser` trouxe, para quando a Steam estiver fechada.
_CONTA_GUARDADA = "conquistas-ultima-conta-steam"


def _inteiro_do_registro(raiz: int, caminho: str, nome: str) -> Optional[int]:
    """Um valor DWORD do registro. Nunca levanta; o que não é inteiro vale None."""
    valor = _do_registro(raiz, caminho, nome)
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


def raiz_de_instalacao(texto: object) -> Optional[Path]:
    """A pasta de instalação que um launcher guarda, normalizada para comparar.

    Só pasta absoluta e que não é a raiz do disco (que pegaria todo jogo instalado
    nele). Só olha o texto, nunca o disco.
    """
    if not isinstance(texto, str) or not texto.strip() or not os.path.isabs(texto):
        return None
    try:
        pasta = Path(os.path.normcase(os.path.abspath(texto)))
    except (OSError, ValueError):
        return None
    return None if pasta.parent == pasta else pasta


def da_instalacao_mais_funda(pastas: list[Path], raizes: Iterable[tuple[Path, T]]) -> Optional[T]:
    """O valor da pasta de instalação mais funda que contém uma das ``pastas`` do jogo.

    ``raizes`` vem de `raiz_de_instalacao`. Pasta inteira: `FallGuys2` não está
    dentro de `FallGuys`. No empate vale a primeira.
    """
    normalizadas = []
    for base in pastas:
        try:
            normalizadas.append(Path(os.path.normcase(os.path.abspath(base))))
        except (OSError, ValueError):
            continue
    if not normalizadas:
        return None
    melhor: Optional[tuple[int, T]] = None
    for raiz, valor in raizes:
        profundidade = len(raiz.parts)
        if (melhor is None or profundidade > melhor[0]) and any(
            pasta == raiz or raiz in pasta.parents for pasta in normalizadas
        ):
            melhor = (profundidade, valor)
    return melhor[1] if melhor is not None else None


def bases_da_pasta(pasta: Path) -> list[Path]:
    """`pasta` e as pastas-pai que ainda são do jogo: sobe enquanto o nome for o de uma
    pasta de binários, até `_SUBIDAS` vezes. A última é a raiz do jogo."""
    bases = [pasta]
    for _subida in range(_SUBIDAS):
        if pasta.name.casefold() not in _PASTAS_DE_BINARIOS or pasta.parent == pasta:
            break
        pasta = pasta.parent
        bases.append(pasta)
    return bases


def bases_do_jogo(executavel: str) -> list[Path]:
    """A pasta do executável e as pastas-pai que ainda são do jogo."""
    pasta = game_folder(executavel or "")
    return bases_da_pasta(Path(pasta)) if pasta else []


# Os caminhos fixos de cada emulador, na ordem de preferência (entre dois caminhos
# iguais, vale o primeiro): a pasta do sistema (atributo de `Pastas`), o caminho a
# partir dela com ``{appid}`` no lugar do appID, e o formato do arquivo.
_FIXOS: tuple[tuple[str, str, str], ...] = (
    ("appdata", "Goldberg SteamEmu Saves/{appid}/achievements.json", formatos.GOLDBERG),
    ("appdata", "GSE Saves/{appid}/achievements.json", formatos.GOLDBERG),
    ("documentos_publicos", "Steam/CODEX/{appid}/achievements.ini", formatos.PADRAO),
    ("appdata", "Steam/CODEX/{appid}/achievements.ini", formatos.PADRAO),
    ("documentos_publicos", "Steam/RUNE/{appid}/achievements.ini", formatos.PADRAO),
    ("documentos_publicos", "OnlineFix/{appid}/Stats/Achievements.ini", formatos.ONLINEFIX),
    ("documentos_publicos", "OnlineFix/{appid}/Achievements.ini", formatos.ONLINEFIX),
    ("appdata", "EMPRESS/remote/{appid}/achievements.json", formatos.GOLDBERG),
    ("documentos_publicos", "EMPRESS/{appid}/remote/{appid}/achievements.json", formatos.GOLDBERG),
    ("programdata", "RLD!/{appid}/achievements.ini", formatos.RLD),
    ("programdata", "Steam/Player/{appid}/stats/achievements.ini", formatos.RLD),
    ("programdata", "Steam/RLD!/{appid}/stats/achievements.ini", formatos.RLD),
    ("programdata", "Steam/dodi/{appid}/stats/achievements.ini", formatos.RLD),
    ("documentos", "SKIDROW/{appid}/SteamEmu/UserStats/achiev.ini", formatos.SKIDROW),
    ("documentos", "Player/{appid}/SteamEmu/UserStats/achiev.ini", formatos.SKIDROW),
    ("localappdata", "SKIDROW/{appid}/SteamEmu/UserStats/achiev.ini", formatos.SKIDROW),
    ("appdata", "CreamAPI/{appid}/stats/CreamAPI.Achievements.cfg", formatos.CREAMAPI),
    ("appdata", ".1911/{appid}/achievement", formatos.RAZOR1911),
)
# Goldberg e GSE guardam também um nível abaixo do appID (`scan-nested-achievement-files.ts`).
_RAIZES_ANINHADAS = ("Goldberg SteamEmu Saves", "GSE Saves")


def _fixos(p: Pastas, appid: str) -> list[ArquivoDeConquista]:
    return [
        ArquivoDeConquista(getattr(p, pasta).joinpath(*modelo.format(appid=appid).split("/")), formato)
        for pasta, modelo, formato in _FIXOS
    ]


def _aninhados(p: Pastas, appid: str) -> list[ArquivoDeConquista]:
    """Goldberg e GSE com um nível a mais."""
    return [
        ArquivoDeConquista(sub / "achievements.json", formatos.GOLDBERG)
        for raiz in _RAIZES_ANINHADAS
        for sub in _subpastas(p.appdata / raiz / appid)
    ]


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


def _conta_conectada() -> Optional[str]:
    """A conta com a Steam aberta agora (``ActiveUser``; 0 com a Steam fechada)."""
    ativa = _inteiro_do_registro(*_CHAVE_DA_CONTA_ATIVA)
    return str(ativa) if ativa is not None and ativa > 0 else None


_conta_enfileirada: Optional[str] = None


def _guardar_conta(conta: str) -> bool:
    shared.state_schema.set_string(_CONTA_GUARDADA, conta)
    return False  # o GLib repetiria o callback que devolvesse um valor verdadeiro


def _conta_do_usuario() -> Optional[str]:
    """A conectada agora ou, com a Steam fechada, a última que o app viu conectada.

    Nunca pelo `config\\loginusers.vdf`, que diria a última que entrou: ler esse
    arquivo é o que ladrão de conta Steam faz, e o Kaspersky derrubava o app por
    isso (PDM:Trojan.Win32.Generic, 19/10/2026). Quem chama roda numa thread: a
    gravação vai para a thread principal, e só quando a conta muda.
    """
    global _conta_enfileirada  # pylint: disable=global-statement
    guardada = shared.state_schema.get_string(_CONTA_GUARDADA) or None
    conectada = _conta_conectada()
    if conectada is None:
        return guardada
    # Uma gravação só, e não uma por jogo da varredura antes de a principal rodar.
    if conectada not in (guardada, _conta_enfileirada):
        _conta_enfileirada = conectada
        GLib.idle_add(_guardar_conta, conectada)
    return conectada


def _contas(steam: Path) -> list[Path]:
    """As contas da Steam deste PC cujos arquivos valem.

    Uma só, quando dá para saber qual é: a conectada agora ou, com a Steam
    fechada, a última que o app viu conectada. O histórico só soma, então
    misturar as contas de quem divide o PC misturaria as conquistas. Sem saber
    (a Steam nunca esteve aberta com o app aberto, ou a conta achada não tem
    pasta em `userdata`), todas: as pastas com nome só de dígitos.
    """
    todas = [conta for conta in _subpastas(steam / "userdata") if appid_valido(conta.name)]
    achada = _conta_do_usuario()
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
