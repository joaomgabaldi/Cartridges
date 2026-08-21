# run_executable.py
#
# Copyright 2023 kramo
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

import logging
import re
import subprocess
import threading

from cartridges import shared


def run_executable(executable, run_as_admin: bool = False) -> None:
    if run_as_admin:
        _run_elevated(executable)
        return

    logging.info("Launching `%s`", str(executable))
    # CREATE_NO_WINDOW hides the intermediate cmd.exe console that shell=True
    # spawns; the game itself opens its own window normally (via `start`).
    # CREATE_NEW_PROCESS_GROUP detaches the game from our Ctrl+C/console group.
    # pylint: disable=consider-using-with
    subprocess.Popen(
        executable,
        cwd=shared.home,
        shell=True,
        creationflags=(
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW  # type: ignore
        ),
    )


def _run_elevated(executable: str) -> None:
    """Launch elevated on Windows (shows a UAC prompt).

    The whole app can't run as admin (GTK/Adwaita misbehave elevated), so only
    the game that needs it is elevated. The UAC prompt blocks until answered,
    so the work runs on a daemon thread to keep the UI responsive.

    UWP / Game Pass games: invoke ``runas`` on the ``shell:AppsFolder`` item —
    the same thing as right-clicking the Start menu entry — which keeps the
    package identity (elevating the package's bare .exe launches nothing, and
    the .lnk exposes no ``runas`` verb). Classic games run through an elevated
    ``cmd /c``, whose spawned children inherit the elevated token.
    """
    threading.Thread(
        target=_elevate_worker, args=(executable,), daemon=True
    ).start()


def _elevate_worker(executable: str) -> None:
    if aumid := aumid_from_command(executable):
        # Invoke "runas" on the app's AppsFolder item — exactly what right-
        # clicking the Start menu entry and choosing "Run as administrator"
        # does. This keeps the package identity that a bare .exe loses (running
        # GameLaunchHelper.exe directly elevates but never launches the game).
        _shell_execute_runas(f"shell:AppsFolder\\{aumid}", None, None, 1)
        return

    _shell_execute_runas("cmd.exe", "/c " + executable, str(shared.home), 0)


# The characters an AUMID is made of, deliberately the same class the importer
# validates against when it writes the command (`importer/shortcuts_source.py`),
# so the two ends agree on what an AUMID is. Anything else — a closing quote, a
# space, an argument after it — ends the AUMID rather than being part of it.
_AUMID_CHARS = re.compile(r"[\w.!+\-]+")


def aumid_from_command(executable: str) -> str:
    """Extract the AUMID from a ``...shell:AppsFolder\\<AUMID>`` launch command.

    Returns "" for anything else, which doubles as the test for "is this a
    Microsoft Store / Game Pass game?" — used both to elevate it correctly and
    to pick how its playtime is tracked.

    The rest of the line is not the AUMID: a command may quote it and may carry
    arguments after it. A ``.url`` shortcut imports as
    ``start "" "shell:AppsFolder\\PFN!App"``, and taking everything after the
    marker gave back ``PFN!App"``, trailing quote and all. That stayed invisible
    on the tracking side, where ``ProcessSession`` splits on the ``!`` and throws
    the tail away, but the raw value is what ``_elevate_worker`` hands to
    ``ShellExecuteEx``: the quote made the elevated launch fail with nothing but
    a warning in the log, by which point the main window had already been
    minimised for a game that was never going to start.

    Not narrowed further to the ``PFN!AppId`` shape on purpose. The importer's
    ``_real_aumid`` falls back to a grouping id, which has no ``!``, when it
    cannot resolve one to a real AUMID; rejecting those here would only move
    them to the manual session window, where a game the shell cannot launch at
    all would sit collecting playtime.
    """
    marker = "shell:AppsFolder\\"
    index = executable.find(marker)
    if index == -1:
        return ""

    match = _AUMID_CHARS.match(executable, index + len(marker))
    return match.group() if match else ""


def _shell_execute_runas(file_, params, directory, show) -> None:
    """Invoke the ``runas`` verb via ShellExecuteEx (blocks on the UAC prompt)."""
    import ctypes  # pylint: disable=import-outside-toplevel
    from ctypes import wintypes  # pylint: disable=import-outside-toplevel

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("fMask", ctypes.c_ulong),
            ("hwnd", wintypes.HWND),
            ("lpVerb", wintypes.LPCWSTR),
            ("lpFile", wintypes.LPCWSTR),
            ("lpParameters", wintypes.LPCWSTR),
            ("lpDirectory", wintypes.LPCWSTR),
            ("nShow", ctypes.c_int),
            ("hInstApp", wintypes.HINSTANCE),
            ("lpIDList", ctypes.c_void_p),
            ("lpClass", wintypes.LPCWSTR),
            ("hkeyClass", wintypes.HKEY),
            ("dwHotKey", wintypes.DWORD),
            ("hIconOrMonitor", wintypes.HANDLE),
            ("hProcess", wintypes.HANDLE),
        ]

    see_mask_invokeidlist = 0x0000000C  # resolve the link's verbs via IContextMenu
    see_mask_noasync = 0x00000100  # finish before returning
    coinit_apartmentthreaded = 0x2

    ole32 = ctypes.windll.ole32  # type: ignore
    # IContextMenu (INVOKEIDLIST) needs COM; init it on this thread
    hresult = ole32.CoInitializeEx(None, coinit_apartmentthreaded)
    try:
        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = see_mask_invokeidlist | see_mask_noasync
        info.lpVerb = "runas"
        info.lpFile = file_
        info.lpParameters = params
        info.lpDirectory = directory
        info.nShow = show

        logging.info("Launching elevated `%s`", file_)
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):  # type: ignore
            # Non-zero failure code, e.g. the user cancelled the UAC prompt
            logging.warning("Elevated launch failed or was cancelled for `%s`", file_)
    finally:
        if hresult in (0, 1):  # S_OK / S_FALSE: we own the COM init
            ole32.CoUninitialize()
