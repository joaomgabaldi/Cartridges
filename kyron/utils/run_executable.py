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

from kyron import shared


def run_executable(executable, run_as_admin: bool = False) -> None:
    if run_as_admin:
        _run_elevated(executable)
        return

    logging.info("Launching `%s`", str(executable))
    # CREATE_NO_WINDOW esconde o console do cmd.exe do shell=True; CREATE_NEW_PROCESS_GROUP solta o jogo do Ctrl+C do app.
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
    """Abre o jogo elevado (pede o UAC), numa thread daemon porque o prompt bloqueia até ser respondido.

    UWP / Game Pass: ``runas`` no item ``shell:AppsFolder``, que mantém a identidade do pacote (elevar o .exe
    solto não abre nada). Jogos comuns passam por um ``cmd /c`` elevado, cujos filhos herdam o token.
    """
    threading.Thread(
        target=_elevate_worker, args=(executable,), daemon=True
    ).start()


def _elevate_worker(executable: str) -> None:
    if aumid := aumid_from_command(executable):
        _shell_execute_runas(f"shell:AppsFolder\\{aumid}", None, None, 1)
        return

    # As aspas externas são as do `shell=True` normal: sem elas, um comando com dois pares de aspas cai na regra do cmd
    # que tira a primeira e a última e se parte ao meio.
    _shell_execute_runas("cmd.exe", f'/c "{executable}"', str(shared.home), 0)


# Mesma classe de caracteres que o importador valida (`importer/shortcuts_source.py`); aspas, espaço ou argumento encerram o AUMID.
_AUMID_CHARS = re.compile(r"[\w.!+\-]+")

# Sem diferenciar maiúsculas, como o shell. Regex e não casefold: o casefold pode mudar o tamanho do texto e as posições.
_MARKER_RE = re.compile(re.escape("shell:AppsFolder\\"), re.IGNORECASE)


def aumid_from_command(executable: str) -> str:
    """O AUMID de um comando ``...shell:AppsFolder\\<AUMID>``; "" para qualquer outro (o teste de "jogo da Microsoft Store").

    Só o AUMID, sem as aspas e argumentos que o comando pode ter (um ``.url`` importa como
    ``start "" "shell:AppsFolder\\PFN!App"``): com a aspa, a elevação via ``ShellExecuteEx`` falhava.
    Não exige a forma ``PFN!AppId`` de propósito: o importador cai num id de agrupamento sem ``!`` quando não resolve.
    """
    found = _MARKER_RE.search(executable)
    if found is None:
        return ""

    match = _AUMID_CHARS.match(executable, found.end())
    return match.group() if match else ""


def _shell_execute_runas(file_, params, directory, show) -> None:
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

    see_mask_invokeidlist = 0x0000000C  # resolve os verbos do link via IContextMenu
    see_mask_noasync = 0x00000100  # termina antes de retornar
    coinit_apartmentthreaded = 0x2

    ole32 = ctypes.windll.ole32  # type: ignore
    # INVOKEIDLIST (IContextMenu) precisa de COM nesta thread
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
            # Falha ou UAC cancelado
            logging.warning("Elevated launch failed or was cancelled for `%s`", file_)
    finally:
        if hresult in (0, 1):  # S_OK / S_FALSE: o COM é nosso
            ole32.CoUninitialize()
