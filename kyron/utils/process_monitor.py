# process_monitor.py
#
# Copyright 2024 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Check whether a game is running, by executable name, folder or package, to track its playtime.

* :func:`is_process_running`: an executable name.
* :func:`is_process_running_under`: an install folder, at any depth. Needs no configuring and survives hand-offs between executables (``Diablo IV Launcher.exe`` to ``Diablo IV.exe``).
* :func:`is_package_running`: an MSIX/UWP *package family name* (Microsoft Store, Game Pass). They launch through ``shell:AppsFolder\\<AUMID>`` (no process to follow) and every GDK title declares the same ``GameLaunchHelper.exe``, so a name match would confuse two games.

Uses the Toolhelp snapshot API through ``ctypes``: no console-window flash, no dependency.
"""

import ctypes
import logging
import os
import re
from ctypes import wintypes
from typing import Callable, Optional

_TH32CS_SNAPPROCESS = 0x00000002
_MAX_PATH = 260
_INVALID_HANDLE = ctypes.c_void_p(-1).value
# Basta para consultar identidade e caminho e, ao contrário de PROCESS_QUERY_INFORMATION, é concedido para processo de
# integridade maior: um jogo elevado ("executar como administrador") segue visível.
_PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
_ERROR_INSUFFICIENT_BUFFER = 122


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_wchar * _MAX_PATH),
    ]


# Protótipos declarados uma vez: a consulta roda a cada poucos segundos.
_kernel32 = ctypes.windll.kernel32  # type: ignore
_kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_kernel32.Process32FirstW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(PROCESSENTRY32W),
]
_kernel32.Process32NextW.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(PROCESSENTRY32W),
]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
# As duas da checagem de pacote. `GetPackageFamilyName` usa `UINT32 *` e `QueryFullProcessImageNameW` `DWORD *`, e `POINTER(DWORD)` rejeita `byref(c_uint32)`: por isso o buffer de `_process_image_path` é `wintypes.DWORD`.
# Com guarda, ao contrário do bloco acima: um kernel32 sem elas impediria o app de abrir em vez de custar só o recurso.
try:
    _kernel32.GetPackageFamilyName.restype = wintypes.LONG
    _kernel32.GetPackageFamilyName.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_uint32),
        wintypes.LPWSTR,
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
except AttributeError:  # pragma: no cover - Windows 7 and earlier
    logging.warning("This Windows has no package API; Store games can't be followed")

# "Não deu para perguntar", ao contrário do None ("perguntei e não tem pacote"): sentinela e não exceção, pois é resultado comum ao percorrer todos os processos.
_UNREADABLE = "\x00unreadable"

def _win32_path(path: str) -> str:
    """``path`` with backslash separators, whatever ``os.sep`` says.

    Os valores do Win32 (`QueryFullProcessImageNameW`, `%SystemRoot%`) usam barra invertida e os normalizados pelo
    Python só concordam se `os.sep` também for. Na versão anterior (GTK, MSYS2 ucrt64) não era: `normpath`, `realpath`
    e `join` devolviam barra normal e o rastreio por pasta nunca casava. Normalizar explicitamente independe do build.
    """
    return path.replace("/", "\\")


# Pasta do Windows, para distinguir o processo do jogo dos hosts do sistema que dividem a identidade do pacote (`_process_package_family`). Lida do ambiente, não fixa.
_system_root = _win32_path(
    os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "")
).casefold()


def is_process_running(exe_name: str) -> bool:
    """True se há um processo com esse executável; ``exe_name`` pode ser nome ou caminho (só o nome é comparado) e o ".exe" é opcional."""
    if not exe_name:
        return False

    name = os.path.basename(exe_name.strip().strip('"'))
    if not name:
        return False

    return _is_running_windows(name)


def _matches(candidate: str, targets: set[str]) -> bool:
    return candidate.casefold() in targets


def _name_variants(name: str) -> set[str]:
    lowered = name.casefold()
    variants = {lowered}
    if lowered.endswith(".exe"):
        variants.add(lowered[: -len(".exe")])
    else:
        variants.add(lowered + ".exe")
    return variants


def _is_running_windows(name: str) -> bool:
    targets = _name_variants(name)
    return _any_process(lambda _pid, exe_file: _matches(exe_file, targets))


# Pseudoprocessos idle e system: sem caminho de imagem, e o `OpenProcess` os recusa. Por pid e não por nome (o `szExeFile` varia com o build/idioma).
_PSEUDO_PIDS = frozenset({0, 4})

# Processos do próprio Windows, pelo `szExeFile` do snapshot: todos moram só em %SystemRoot%, e `_process_package_family` os descartaria pelo caminho de qualquer forma; pular antes poupa um `OpenProcess`. Nenhum nome que um jogo possa ter entra aqui (o nome é olhado *antes* da identidade). Não vira filtro positivo: todo título GDK declara o mesmo `GameLaunchHelper.exe`.
_SYSTEM_PROCESS_NAMES = frozenset(
    {
        "system",
        "registry",
        "memory compression",
        "memcompression",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "lsaiso.exe",
        "svchost.exe",
        "fontdrvhost.exe",
        "dwm.exe",
        "audiodg.exe",
        "spoolsv.exe",
        "taskhostw.exe",
        "sihost.exe",
        "ctfmon.exe",
        "explorer.exe",
        "conhost.exe",
        "dllhost.exe",
        "runtimebroker.exe",
        "wmiprvse.exe",
        "searchindexer.exe",
        "searchhost.exe",
        "startmenuexperiencehost.exe",
        "shellexperiencehost.exe",
        "applicationframehost.exe",
        "textinputhost.exe",
        "backgroundtaskhost.exe",
        "wudfhost.exe",
        "werfault.exe",
        "smartscreen.exe",
    }
)

# O que a última consulta apurou: pid -> (nome do executável, família do pacote ou None). Refeito do snapshot a cada chamada, não podado: um processo encerrado não permanece.
_package_family_cache: dict[int, tuple[str, Optional[str]]] = {}


def is_package_running(package_family: str) -> bool:
    """True se há um processo do pacote MSIX/UWP; ``package_family`` é a parte do AUMID antes do ``!``.

    Perguntar por processo é caro (`OpenProcess` e mais três chamadas) e, com o jogo parado, os ~300 processos eram interrogados a cada 2 s, com o Defender na frente: a janela engasgava. Daí o pré-filtro e este cache.
    A chave é pid *e* nome do executável (o Windows reaproveita pids). Só "não tem pacote" é lembrado; quem tem pacote é perguntado de novo (um pid reciclado entre dois `GameLaunchHelper.exe` casaria pelo nome com outro jogo).
    Um `OpenProcess` recusado não é lembrado (é propriedade da chamada, não do processo): cachear viraria veredicto permanente, e um jogo empacotado nunca visto encerra a sessão.
    """
    global _package_family_cache  # pylint: disable=global-statement

    if not (family := package_family.strip().casefold()):
        return False

    previous = _package_family_cache
    current: dict[int, tuple[str, Optional[str]]] = {}

    def matches(pid: int, exe_file: str) -> bool:
        name = exe_file.casefold()
        if pid in _PSEUDO_PIDS or name in _SYSTEM_PROCESS_NAMES:
            return False
        cached = previous.get(pid)
        if cached is not None and cached[0] == name and cached[1] is None:
            current[pid] = cached
            return False
        found = _process_package_family(pid)
        if found is not _UNREADABLE:
            current[pid] = (name, found)
        return found == family

    running = _any_process(matches)
    # O que a varredura não alcançou é descartado, e essa é a evicção; a cauda não cacheada após um acerto não custa nada.
    _package_family_cache = current
    return running


def is_process_running_under(directory: str) -> bool:
    """True se o executável de algum processo em execução está dentro de ``directory``, em qualquer profundidade.

    O executável vivo muda na sessão (Call of Duty troca o binário por ``sp23\\sp23-cod.exe`` na campanha; Battlefield 6
    tem um ``bf6.exe`` na raiz e outro em ``SP\\``), mas todos ficam sob a pasta do jogo.
    """
    if not (prefix := _as_path_prefix(directory)):
        return False

    def matches(pid: int, exe_file: str) -> bool:
        # O pré-filtro de `is_package_running`: sem ele cada poll pagava um `OpenProcess` por processo da máquina. Vale aqui porque
        # `_is_watchable_dir` garante que o prefixo vigiado nunca está sob %SystemRoot%, onde todo nome do conjunto mora.
        if pid in _PSEUDO_PIDS or exe_file.casefold() in _SYSTEM_PROCESS_NAMES:
            return False
        path = _process_path(pid)
        return path is not None and path.casefold().startswith(prefix)

    return _any_process(matches)


# Caminho absoluto de um .exe entre aspas, como o importador escreve. As duas barras são aceitas: um comando montado de um caminho Python pode vir com barra normal.
_QUOTED_EXE = re.compile(r'"([A-Za-z]:[\\/][^"]*\.exe)"', re.IGNORECASE)
# O mesmo sem aspas, só sem espaços: com espaços não se distingue dos argumentos.
_BARE_EXE = re.compile(r"(?<!\S)([A-Za-z]:[\\/]\S*\.exe)(?!\S)", re.IGNORECASE)
# Pastas que guardam muitos jogos: vigiá-las contaria os processos dos outros como tempo deste, então valem como "sem pasta".
_CONTAINER_DIRS = frozenset(
    {
        "program files",
        "program files (x86)",
        "games",
        "steamlibrary",
        "steamapps",
        "common",
        "xboxgames",
        "windowsapps",
    }
)
_PROGRAM_FILES_DIRS = frozenset({"program files", "program files (x86)"})


def install_dir_from_command(executable: str) -> str:
    """A pasta a vigiar para os processos do jogo, tirada do comando de abertura.

    "" se o comando não tem um caminho de executável seguro (URI de launcher, jogo da Store, caminho solto com
    espaços) ou se a pasta é ampla demais: vigiar a pasta errada credita processo alheio como tempo de jogo.
    """
    if not executable:
        return ""

    candidates = _QUOTED_EXE.findall(executable) or _BARE_EXE.findall(executable)
    if not candidates:
        return ""

    # O último, como o próprio comando: o executável do jogo vem depois de diretório de trabalho ou launcher.
    caminho = candidates[-1]
    # Caminho UNC nunca entra: faria o Windows conectar à máquina e enviar as credenciais do usuário, numa varredura que ninguém pediu.
    if caminho[:1] in ("\\", "/") and caminho[1:2] in ("\\", "/"):
        return ""
    directory = _game_root(os.path.dirname(caminho))
    return directory if _is_watchable_dir(directory) else ""


# Quantos níveis subir atrás da raiz do jogo; só impede um caminho malformado de andar para sempre.
_MAX_ROOT_WALK = 8


def _game_root(directory: str) -> str:
    """A pasta do próprio jogo, subindo para fora de subpastas de launcher ou engine.

    O comando aponta para quem inicia o jogo, muitas vezes fora da raiz (Poppy Playtime: ``PlaytimeLauncher\\PlaytimeLauncher.exe`` com os capítulos em pastas irmãs; Battlefield 6: ``SP\\bf6.exe``; Unreal: ``Binaries\\Win64``). Sobe até a primeira pasta com desinstalador, ou até a que tem um contêiner conhecido de jogos como pai; "" se nenhuma for alcançada (adivinhar mediria o jogo errado ou vigiaria jogos alheios).
    """
    if not directory:
        return ""

    current = os.path.normpath(directory)
    below = ""  # the folder one level under `current` on the way up
    for _ in range(_MAX_ROOT_WALK):
        parent = os.path.dirname(current)
        if parent == current:
            return ""  # hit the drive root without ever finding a root marker
        if _has_uninstaller(current):
            return _win32_path(current)
        container = os.path.basename(parent).casefold()
        if container in _CONTAINER_DIRS:
            # Program Files guarda editoras tanto quanto jogos (`Epic Games`, `EA Games`, `Rockstar Games`, cujo launcher
            # fica na bandeja depois do jogo): lá a raiz é o segundo nível.
            # shortcut: um jogo direto em Program Files, com o exe dois níveis abaixo e sem desinstalador, vigia a subpasta e não a raiz.
            if container in _PROGRAM_FILES_DIRS and below:
                current = below
            # Barras invertidas na saída: o valor vai a `ProcessSession.install_dir` (persistido e comparado) no formato de `_as_path_prefix` e `_system_root`.
            return _win32_path(current)
        below, current = current, parent
    return ""


def _has_uninstaller(directory: str) -> bool:
    """``directory`` foi instalada como um programa só, e não guarda vários?

    ``unins000.exe`` é do Inno Setup (repacks, instaladores offline da GOG), ``uninstall.exe`` do NSIS e ``__Installer``
    é o que o app da EA deixa na raiz do jogo. Uma pasta de editora guarda os instaladores dos jogos, não o próprio.
    """
    try:
        with os.scandir(directory) as entries:
            return any(
                entry.name.casefold() == "__installer"
                or (
                    entry.name.casefold().startswith("unins")
                    and entry.name.casefold().endswith(".exe")
                )
                for entry in entries
            )
    except OSError:
        return False


def _is_watchable_dir(directory: str) -> bool:
    if not directory:
        return False

    # Renormalizado aqui: o `normpath` reintroduz barras normais no build da versão anterior, e o teste de `_system_root` compararia convenções diferentes.
    resolved = _win32_path(os.path.normpath(directory))
    _drive, tail = os.path.splitdrive(resolved)
    if not tail.strip("\\/"):
        return False  # a drive root matches every process on the disk
    if os.path.basename(resolved).casefold() in _CONTAINER_DIRS:
        return False
    # Nenhum jogo mora na pasta do Windows, e os hosts do shell que moram contariam como tempo de jogo para sempre.
    return not resolved.casefold().startswith(_system_root)


def _as_path_prefix(directory: str) -> str:
    """``directory`` como prefixo casefold terminando em exatamente um separador.

    Links e junções são resolvidos antes: ``QueryFullProcessImageNameW`` dá o caminho real, e uma pasta alcançada por
    junção nunca casaria (as do Game Pass passam por duas junções encadeadas).
    """
    if not (cleaned := directory.strip().strip('"')):
        return ""

    try:
        resolved = os.path.realpath(cleaned)
    except (OSError, ValueError):
        return ""

    # O separador final impede ".../Battlefield 1" de casar com ".../Battlefield 11/game.exe".
    return _win32_path(os.path.join(resolved, "")).casefold()


def _process_path(pid: int) -> Optional[str]:
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return _process_image_path(handle)
    finally:
        _kernel32.CloseHandle(handle)


def _process_package_family(pid: int) -> Optional[str]:
    """A família de pacote de um processo, casefold.

    None para processo sem pacote ou que só hospeda o pacote pelo Windows (a razão da checagem do caminho:
    ``RuntimeBroker.exe`` reporta a família do app que intermedia e vive além dele, inflando o tempo de jogo).
    ``_UNREADABLE`` (distinto de None) se o processo nem abriu: não deve ser cacheado (ver `is_package_running`).
    """
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return _UNREADABLE

    try:
        family = _query_string(_kernel32.GetPackageFamilyName, handle)
        if family is None:
            return None  # unpackaged: APPMODEL_ERROR_NO_PACKAGE
        path = _process_image_path(handle)
        if path and path.casefold().startswith(_system_root):
            return None
        return family.casefold()
    finally:
        _kernel32.CloseHandle(handle)


def _query_string(function: Callable, handle: int) -> Optional[str]:
    length = ctypes.c_uint32(0)
    if function(handle, ctypes.byref(length), None) != _ERROR_INSUFFICIENT_BUFFER:
        return None
    buffer = ctypes.create_unicode_buffer(length.value)
    if function(handle, ctypes.byref(length), buffer) != 0:
        return None
    return buffer.value


def _process_image_path(handle: int) -> Optional[str]:
    size = wintypes.DWORD(_MAX_PATH * 4)
    buffer = ctypes.create_unicode_buffer(size.value)
    if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return buffer.value
    return None


def _any_process(predicate: Callable[[int, str], bool]) -> bool:
    """True se ``predicate(pid, exe name)`` vale para algum processo, parando no primeiro acerto (snapshot Toolhelp aberto: não pode bloquear)."""
    try:
        snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == _INVALID_HANDLE:
            return False

        try:
            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            if not _kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
                return False
            while True:
                if predicate(entry.th32ProcessID, entry.szExeFile):
                    return True
                if not _kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                    break
        finally:
            _kernel32.CloseHandle(snapshot)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not enumerate running processes: %s", error)
    return False


