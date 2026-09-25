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

"""Check whether a game is currently running, by executable name, folder or package.

Used to track a game's playtime by following its own process. Three ways to ask:

* :func:`is_process_running` matches an executable name, for games that are a
  plain ``.exe`` we launched ourselves.
* :func:`is_process_running_under` matches an install folder, at any depth. This
  is the broadest of the three and needs no configuring, because
  :func:`install_dir_from_command` derives the folder from the game's own launch
  command. It exists because a game is rarely one executable: the thing we launch
  regularly hands off to a differently named one beside it (Diablo IV's
  ``Diablo IV Launcher.exe`` to ``Diablo IV.exe``, Epic's ``PlayGTAV.exe`` to the
  real game), and the running executable can change mid-session when the player
  switches mode. The folder is the part that stays put.
* :func:`is_package_running` matches an MSIX/UWP *package family name*, for
  Microsoft Store and Game Pass games. These are launched through
  ``shell:AppsFolder\\<AUMID>``, which hands the request to the shell and leaves
  us no process to follow, and their manifests are no help either: every GDK
  title declares the same ``GameLaunchHelper.exe``, so a name match would
  confuse two Game Pass games with each other. The package family name is the
  game's identity, is stable, and is carried by the process itself, so it works
  no matter where the game is installed. Every process of the game reports it —
  the launcher, the game, the crash handler, and the separate executable a game
  swaps itself for when the player switches mode — so the game stays visible for
  as long as any part of it is alive, and no longer.

Uses the Win32 Toolhelp snapshot API directly through ``ctypes`` so there's no
console-window flash and no third-party dependency.
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
# Enough to query identity and image path, and — unlike PROCESS_QUERY_INFORMATION
# — granted for another process at a higher integrity level, so a game launched
# elevated ("run as admin") stays visible to us.
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


# Prototypes declared once at import: the poll runs every couple of seconds
# while a game is tracked, so per-call ctypes setup was pure repeated overhead.
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
# The two the package check leans on. Undeclared they happen to work, because
# ctypes' default is a C `int` and every handle Windows hands out fits in 32
# bits — but that is luck, not a contract (the same reason `session_window.py`
# declares `FindWindowW` so the 64-bit HWND isn't truncated), and it is exactly
# the kind of thing that stays silent until it doesn't.
#
# The length arguments are not interchangeable and ctypes, unlike Windows, says
# so out loud: `GetPackageFamilyName` takes a `UINT32 *` while
# `QueryFullProcessImageNameW` takes a `DWORD *`, and `POINTER(DWORD)` rejects a
# `byref(c_uint32)` outright. So these declarations have to agree with what
# `_query_string` and `_process_image_path` actually pass — which is why the
# buffer size in the latter is a `wintypes.DWORD`.
#
# Guarded, unlike the block above: these two are looked up by name at import,
# and this module is imported from `game.py`, so a kernel32 without them would
# stop the whole app from starting rather than costing the feature that needs
# them. `_process_package_family` already treats an unanswerable question as
# "not this game", which is the right way to degrade.
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

# "We could not ask", as opposed to None's "we asked and it has no package".
# A sentinel rather than an exception because it is an ordinary outcome of
# walking every process on the machine — most of them are not ours to open.
_UNREADABLE = "\x00unreadable"

def _win32_path(path: str) -> str:
    """``path`` with backslash separators, whatever ``os.sep`` says.

    Every path comparison in this module has a Win32 value on one side —
    `QueryFullProcessImageNameW` reports backslashes, and so does `%SystemRoot%`
    — and a Python-normalised value on the other. Those two only agree if
    `os.sep` is a backslash, and on the interpreter this app actually ships with
    it is not: the MSYS2 ucrt64 build reports `os.name == "nt"` and uses
    `ntpath`, but with `sep` and `altsep` the other way round, so `normpath`,
    `realpath` and `join` all hand back forward slashes.

    The effect was silent and total: `is_process_running_under` compared
    `d:/xboxgames/halo/` against `D:\\XboxGames\\Halo\\Content\\halo.exe` and
    never matched, so folder-based playtime tracking — the one route that needs
    no configuring and the only one that follows a game swapping executables
    mid-session — did nothing at all. Normalising explicitly, rather than
    trusting `os.sep`, is what makes the comparison independent of which build
    is running it.
    """
    return path.replace("/", "\\")


# Windows' own directory, used to tell a game's process from the system hosts
# that share its package identity (see `_process_package_family`). Read from the
# environment rather than hardcoded: this machine has games spread over C: and
# D:, and nothing about a path may be assumed.
_system_root = _win32_path(
    os.path.join(os.environ.get("SystemRoot", "C:\\Windows"), "")
).casefold()


def is_process_running(exe_name: str) -> bool:
    """Return True if a process with the given executable name is running.

    ``exe_name`` may be a bare name ("game.exe") or a full path; only the file
    name is compared. The ".exe" suffix is optional.
    """
    if not exe_name:
        return False

    name = os.path.basename(exe_name.strip().strip('"'))
    if not name:
        return False

    return _is_running_windows(name)


def _matches(candidate: str, targets: set[str]) -> bool:
    return candidate.casefold() in targets


def _name_variants(name: str) -> set[str]:
    """Names to accept, so "game" also matches "game.exe" and vice versa."""
    lowered = name.casefold()
    variants = {lowered}
    if lowered.endswith(".exe"):
        variants.add(lowered[: -len(".exe")])
    else:
        variants.add(lowered + ".exe")
    return variants


def _is_running_windows(name: str) -> bool:
    """True if any running process is called ``name``."""
    targets = _name_variants(name)
    return _any_process(lambda _pid, exe_file: _matches(exe_file, targets))


# The idle and system pseudo-processes. They have no image path to compare and
# `OpenProcess` refuses them whatever we ask for, so they cost a failed syscall
# per poll for an answer that cannot change. Matched by pid rather than by name
# because their `szExeFile` is not something to rely on ("System Idle Process",
# "[System Process]" or a translated variant, depending on the build).
_PSEUDO_PIDS = frozenset({0, 4})

# Windows' own processes, matched against the `szExeFile` the snapshot already
# hands us for nothing. Every name here ships in %SystemRoot% and nowhere else,
# so `_process_package_family` would throw it away on the image-path check
# anyway — skipping it up front only declines to pay an `OpenProcess` to learn
# what is already known. That equivalence is the whole soundness argument for
# this set, and it is why no name may be added to it that a game could
# plausibly be called: the name is looked at *before* the package identity, so
# a game listed here would become invisible for as long as it ran. Note this
# cannot be turned around into a positive filter — every GDK title declares the
# same `GameLaunchHelper.exe`, which is the reason the feature matches on
# package family in the first place.
#
# The saving is not marginal: `svchost.exe` alone is routinely a third of the
# process list, and the shell hosts (`RuntimeBroker.exe` — the very process the
# image-path check exists for — `dllhost.exe`, `conhost.exe`) are much of what
# is left.
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

# What the last poll worked out: pid -> (executable name, package family or
# None). Rebuilt from the snapshot on every call rather than pruned, which is
# what keeps a process that has since exited from lingering in it — see
# `is_package_running`.
_package_family_cache: dict[int, tuple[str, Optional[str]]] = {}


def is_package_running(package_family: str) -> bool:
    """Return True if a process of the given MSIX/UWP package is running.

    ``package_family`` is a package family name such as
    ``BethesdaSoftworks.ProjectGold_3275kfvn8vcwc`` — the part of an AUMID
    before the ``!``.

    Asking this of one process is expensive — an `OpenProcess`, one or two
    `GetPackageFamilyName` calls, a `QueryFullProcessImageNameW` and a
    `CloseHandle` — and the poll runs on the GTK main thread with the Toolhelp
    snapshot held open. The worst case is also the common one: while the game is
    not running (the whole startup grace, and the whole grace window after it
    exits) nothing matches, so every one of the machine's 300-odd processes is
    interrogated every two seconds, with an EDR or Defender sitting in front of
    `OpenProcess`. That reached hundreds of milliseconds a poll and the user saw
    it as the window stuttering. Hence the pre-filter above and the cache here.

    The cache is keyed on the pid *and* the executable name from the snapshot,
    because Windows hands a pid out again as soon as it is free and the name is
    the only other identifying thing the snapshot gives us for free. Only one
    answer is ever taken from it, though: "this process carries no package
    identity". Every process that did carry one is asked again, ours or not,
    and that is deliberate —

    * a match is what keeps a session counting, so it is re-established for real
      every poll (one `OpenProcess`, for the one process that matters) and means
      exactly what it meant before this cache existed;
    * a *different* package is where a recycled pid could lie to us, and the
      name would not catch it: every GDK title runs a `GameLaunchHelper.exe`, so
      a pid freed by one title's helper and handed to another's inside one poll
      matches on name while being a different game entirely. The kernel can tell
      them apart, so the kernel is asked. There are only ever a handful of
      packaged processes outside %SystemRoot% to pay for.

    That leaves a remembered "no package". For it to be wrong the same pid would
    have to come back under the same executable name carrying an identity it did
    not have before, i.e. one binary being packaged and unpackaged at once.

    A refused `OpenProcess` is deliberately *not* remembered, and is the reason
    `_process_package_family` reports it as its own answer rather than as "no
    package". It is a property of the call, not of the process: a handle can be
    refused because the process is exiting between the snapshot and the open, or
    because an anti-cheat driver stripped the right after the process started.
    Caching that would turn one unlucky call into a permanent verdict — and
    since a packaged game that is never seen now ends its session outright, the
    cost of being wrong is the whole session.
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
    # Whatever this walk did not reach is dropped, and that is the eviction: a
    # dict built out of the snapshot we have just read cannot hold a pid that is
    # no longer on the machine. A walk cut short by a match leaves the tail
    # uncached, which costs nothing — the tail is never reached while the game
    # is running.
    _package_family_cache = current
    return running


def is_process_running_under(directory: str) -> bool:
    """Return True if a running process' executable lives inside ``directory``.

    Matches at any depth, which is what makes this useful: the executable that
    is alive changes during a session (Call of Duty swaps its multiplayer binary
    for ``sp23\\sp23-cod.exe`` when the player starts the campaign, Battlefield 6
    keeps one ``bf6.exe`` in the root and another under ``SP\\``), but all of
    them live under the game's folder.
    """
    if not (prefix := _as_path_prefix(directory)):
        return False

    def matches(pid: int, exe_file: str) -> bool:
        # O mesmo pré-filtro de `is_package_running`, pelas mesmas razões: o
        # nome vem de graça no snapshot, e sem ele cada poll pagava um
        # `OpenProcess` por processo da máquina — svchost e os hosts do shell
        # inclusive — na main thread, pelo grace inteiro e pela sessão toda.
        # É válido aqui porque `_is_watchable_dir` garante que o prefixo
        # vigiado nunca está sob %SystemRoot%, e todo nome do conjunto só
        # existe lá: nenhum deles pode ser o jogo.
        if pid in _PSEUDO_PIDS or exe_file.casefold() in _SYSTEM_PROCESS_NAMES:
            return False
        path = _process_path(pid)
        return path is not None and path.casefold().startswith(prefix)

    return _any_process(matches)


# Absolute path to an .exe, quoted the way the importer writes launch commands.
# Both separators accepted, and not out of tolerance for sloppy input: the
# interpreter this ships with hands back forward slashes from every `os.path`
# call, so a command built from a Python-side path — one the user pasted, or one
# a future `set_executable` builds with `Path` instead of `Gio.File.get_path()`
# — would silently fail to parse and leave the folder watch with nothing.
_QUOTED_EXE = re.compile(r'"([A-Za-z]:[\\/][^"]*\.exe)"', re.IGNORECASE)
# The same unquoted, accepted only when it contains no spaces — a bare path with
# spaces cannot be told apart from its trailing arguments.
_BARE_EXE = re.compile(r"(?<!\S)([A-Za-z]:[\\/]\S*\.exe)(?!\S)", re.IGNORECASE)
# Folders that hold many unrelated games rather than one. Watching any of these
# would count every other game's processes as this game's playtime, so a command
# that resolves to one is treated as giving us no folder at all.
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
    """The folder to watch for a game's processes, taken from its launch command.

    Returns "" when the command holds no executable path we are sure of (a
    launcher URI, a Store game, an unquoted path with spaces) or when the folder
    it points at is too broad to identify one game. Being sure matters more than
    being clever here: watching the wrong folder credits someone else's process
    as playtime, which is worse than not watching at all.
    """
    if not executable:
        return ""

    candidates = _QUOTED_EXE.findall(executable) or _BARE_EXE.findall(executable)
    if not candidates:
        return ""

    # Last match, like the launch command itself: the game's executable comes
    # after any working-directory or launcher argument in front of it.
    directory = _game_root(os.path.dirname(candidates[-1]))
    return directory if _is_watchable_dir(directory) else ""


# How far up to look for the game's root before giving up. Deeper than any real
# layout needs; it only stops a malformed path from walking forever.
_MAX_ROOT_WALK = 8


def _game_root(directory: str) -> str:
    """The game's own folder, climbing out of any launcher or engine subfolder.

    A launch command points at whatever executable starts the game, which is
    frequently not at the game's root. Poppy Playtime launches
    ``PlaytimeLauncher\\PlaytimeLauncher.exe`` while every chapter it goes on to
    start is a *sibling* folder; Battlefield 6 launches ``SP\\bf6.exe`` and keeps
    its multiplayer binary one level up; Unreal titles launch out of
    ``Binaries\\Win64``. Watching only the folder the command names would miss
    the game itself and bank a session lasting as long as the launcher did.

    The climb stops at the folder whose parent is a well-known container of many
    games, which is what marks a root. Returns "" when no container is reached:
    that layout is not one we recognise, and the alternative to admitting so
    would be watching a folder that holds somebody else's games too.
    """
    if not directory:
        return ""

    current = os.path.normpath(directory)
    below = ""  # the folder one level under `current` on the way up
    for _ in range(_MAX_ROOT_WALK):
        parent = os.path.dirname(current)
        if parent == current:
            return ""  # hit the drive root without ever finding a container
        container = os.path.basename(parent).casefold()
        if container in _CONTAINER_DIRS:
            # Program Files holds publishers as often as games: `Epic Games`,
            # `EA Games` and `Rockstar Games` each hold several games — and
            # Rockstar's launcher, which lingers in the tray after the game.
            # There the root is the second level, not the first.
            # ponytail: a game living directly in Program Files with its exe
            # two levels down gets its subfolder watched, not its root.
            if container in _PROGRAM_FILES_DIRS and below:
                current = below
            # Backslashes on the way out, so what this hands to
            # `install_dir_from_command` — and from there to
            # `ProcessSession.install_dir`, which is persisted and compared —
            # is in the same shape as `_as_path_prefix` and `_system_root`.
            return _win32_path(current)
        below, current = current, parent
    return ""


def _is_watchable_dir(directory: str) -> bool:
    """Is ``directory`` specific enough to stand for exactly one game?"""
    if not directory:
        return False

    # Re-normalised here, so `_game_root` having already done it is not enough:
    # `normpath` is exactly the call that reintroduces forward slashes on the
    # build this ships with, which would leave the `_system_root` test below
    # comparing two different separator conventions and never firing.
    resolved = _win32_path(os.path.normpath(directory))
    _drive, tail = os.path.splitdrive(resolved)
    if not tail.strip("\\/"):
        return False  # a drive root matches every process on the disk
    if os.path.basename(resolved).casefold() in _CONTAINER_DIRS:
        return False
    # No game lives in Windows' own folder, and the shell hosts that do would
    # then be counted as playtime forever.
    return not resolved.casefold().startswith(_system_root)


def _as_path_prefix(directory: str) -> str:
    """``directory`` as a casefolded prefix ending in exactly one separator.

    Symlinks and junctions are resolved first: ``QueryFullProcessImageNameW``
    reports the path a process was really loaded from, so a folder reached
    through a junction would otherwise never compare equal to it. Game Pass
    installs proved that is not hypothetical — theirs are reached through two
    chained junctions.
    """
    if not (cleaned := directory.strip().strip('"')):
        return ""

    try:
        resolved = os.path.realpath(cleaned)
    except (OSError, ValueError):
        return ""

    # The trailing separator is what stops ".../Battlefield 1" from matching
    # ".../Battlefield 11/game.exe": the comparison has to land on a path
    # boundary rather than in the middle of a folder name.
    return _win32_path(os.path.join(resolved, "")).casefold()


def _process_path(pid: int) -> Optional[str]:
    """Full path of a process' executable, or None if it can't be read."""
    handle = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        return _process_image_path(handle)
    finally:
        _kernel32.CloseHandle(handle)


def _process_package_family(pid: int) -> Optional[str]:
    """The package family name a process belongs to, casefolded.

    None for an unpackaged process, or one that only hosts the package on
    Windows' behalf. That last case is the reason for the image path check:
    ``RuntimeBroker.exe`` reports the family name of whatever app it is
    brokering for, and it both outlives and predates the app itself, so counting
    it would inflate playtime with time the game was not running.

    ``_UNREADABLE`` — distinct from None — when the process could not be opened
    at all. Same practical outcome for a single poll (it is not this game), but
    the caller must not cache it: see `is_package_running`.
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
    """Call a Win32 "ask for the length, then ask again" string getter."""
    length = ctypes.c_uint32(0)
    if function(handle, ctypes.byref(length), None) != _ERROR_INSUFFICIENT_BUFFER:
        return None
    buffer = ctypes.create_unicode_buffer(length.value)
    if function(handle, ctypes.byref(length), buffer) != 0:
        return None
    return buffer.value


def _process_image_path(handle: int) -> Optional[str]:
    """Full path of a process' executable, or None if it can't be read."""
    size = wintypes.DWORD(_MAX_PATH * 4)
    buffer = ctypes.create_unicode_buffer(size.value)
    if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
        return buffer.value
    return None


def _any_process(predicate: Callable[[int, str], bool]) -> bool:
    """True if ``predicate(pid, exe name)`` holds for any running process.

    Enumerates via the Toolhelp snapshot API, stopping at the first match. The
    predicate is called with the snapshot open, so it must not block.
    """
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


