# single_instance.py
#
# Copyright 2026 joaomgabaldi
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

"""Impede que uma segunda cópia do app rode junto da primeira.

Duas cópias gravando os mesmos arquivos de jogo fariam uma sobrescrever o tempo de jogo da outra. Um mutex
nomeado não depende de nada rodando, e o Windows o destrói quando o processo termina (inclusive se morto),
então uma queda não deixa uma trava que bloqueie a próxima abertura.
"""

import hashlib
import logging
import os
import sys
import threading
from typing import Any, Callable, Optional

from cartridges import shared

# Namespace local da sessão, a granularidade dos dados protegidos (no perfil do usuário). `Global\` falhava nos dois sentidos: trancava um segundo usuário do Windows ou, sem acesso, o `CreateMutexW` dava ERROR_ACCESS_DENIED e a guarda abria em silêncio. O nome nunca pode mudar: é a identidade da trava.
# Só o canal final sem `CARTRIDGES_DADOS` usa os nomes de sempre; o `-dev` e os testes têm os seus, por pasta de dados, senão o app de desenvolvimento acordaria o instalado em vez de abrir.
_NOME_DO_CANAL_FINAL = "Local\\io.github.joaomgabaldi.Cartridges"


def nomes() -> tuple[str, str]:
    """O nome do mutex e o do evento da segunda abertura, para a pasta de dados deste processo."""
    if shared.canal() == "final" and not os.environ.get("CARTRIDGES_DADOS"):
        base = _NOME_DO_CANAL_FINAL
    else:
        resumo = hashlib.sha1(str(shared.app_dir).casefold().encode("utf-8")).hexdigest()[:8]
        base = f"Local\\{shared.APP_DIR_NAME}.{resumo}"
    return f"{base}.SingleInstance", f"{base}.Present"


_ERROR_ALREADY_EXISTS = 183

# Vive com o processo: se o handle fosse coletado, o mutex seria liberado e a guarda deixaria de valer.
_handle: Optional[Any] = None


def acquire() -> bool:
    """Toma a trava de instância única; False se outra cópia já a tem.

    True também se a trava nem puder ser criada: uma guarda que não se constrói não é motivo para recusar a abertura.
    """
    global _handle  # pylint: disable=global-statement

    if sys.platform != "win32":
        return True

    try:
        import ctypes  # pylint: disable=import-outside-toplevel

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_wchar_p,
        )
        kernel32.CreateMutexW.restype = ctypes.c_void_p

        handle = kernel32.CreateMutexW(None, False, nomes()[0])
        last_error = ctypes.get_last_error()
    except (OSError, AttributeError, ValueError) as error:
        logging.warning("Could not create the single-instance lock: %s", error)
        return True

    if not handle:
        logging.warning(
            "Could not create the single-instance lock (error %s)", last_error
        )
        return True

    if last_error == _ERROR_ALREADY_EXISTS:
        # Outra cópia é dona do mutex: este handle não possui nada, fechá-lo não solta a trava.
        kernel32.CloseHandle(ctypes.c_void_p(handle))
        return False

    _handle = handle
    return True


def release() -> None:
    """Solta o lock antes de um reinício pedido pelo app (restauração de backup): sem isso, o processo novo se acharia a segunda cópia e fecharia."""
    global _handle  # pylint: disable=global-statement

    if _handle is None or sys.platform != "win32":
        return
    try:
        import ctypes  # pylint: disable=import-outside-toplevel

        ctypes.WinDLL("kernel32").CloseHandle(ctypes.c_void_p(_handle))
    except (OSError, AttributeError) as error:
        logging.warning("Could not release the single-instance lock: %s", error)
    _handle = None


# Título da janela principal (Principal.qml), sem tradução: dá para casar daqui, antes de o gettext existir.
_MAIN_WINDOW_TITLE = "Kyron"


# Evento nomeado que a segunda cópia acende para a primeira: a janela principal pode estar escondida pelo Qt,
# e uma janela escondida por ele não volta por Win32. Só a primeira cópia sabe se mostrar. Mesmo escopo do mutex.

_EVENT_MODIFY_STATE = 0x0002
_INFINITE = 0xFFFFFFFF


def watch_second_launch(callback: Callable[[], None]) -> None:
    """Chama ``callback`` (numa thread de fundo) sempre que uma segunda cópia tentar abrir.

    Best-effort: sem o evento, só se perde o retorno da janela escondida.
    """
    if sys.platform != "win32":
        return

    try:
        import ctypes  # pylint: disable=import-outside-toplevel

        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.CreateEventW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_wchar_p,
        )
        kernel32.CreateEventW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32

        # Reinício automático (auto-reset): cada acendida acorda uma vez.
        if not (handle := kernel32.CreateEventW(None, False, False, nomes()[1])):
            return
    except (OSError, AttributeError, ValueError) as error:
        logging.warning("Could not create the second-launch event: %s", error)
        return

    def wait() -> None:
        while kernel32.WaitForSingleObject(handle, _INFINITE) == 0:  # WAIT_OBJECT_0
            callback()

    threading.Thread(target=wait, daemon=True).start()


def _wake_running_instance() -> None:
    """Acende o evento que a primeira cópia vigia (veja `watch_second_launch`)."""
    import ctypes  # pylint: disable=import-outside-toplevel

    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.OpenEventW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.SetEvent.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    if not (handle := kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, nomes()[1])):
        return
    # Este processo carrega o direito de foreground do clique do usuário: cede-o à primeira cópia, que mostra a janela.
    ctypes.WinDLL("user32").AllowSetForegroundWindow(ctypes.c_uint32(0xFFFFFFFF))
    kernel32.SetEvent(handle)
    kernel32.CloseHandle(handle)


def present_running_instance() -> None:
    """Traz para a frente a janela da instância que já roda (achada via Win32), senão o segundo clique no atalho parece não fazer nada.

    Best-effort: qualquer falha custa só o realce, nunca impede o processo de sair limpo.
    """
    if sys.platform != "win32":
        return

    # `try` próprio: se acordar a primeira cópia falhar, o realce abaixo ainda é tentado.
    try:
        _wake_running_instance()
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not wake the running Cartridges instance: %s", error)

    try:
        import ctypes  # pylint: disable=import-outside-toplevel
        from ctypes import wintypes  # pylint: disable=import-outside-toplevel

        user32 = ctypes.WinDLL("user32")
        user32.GetWindowTextW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        )
        user32.GetClassNameW.argtypes = (
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
        )
        user32.IsIconic.argtypes = (ctypes.c_void_p,)
        user32.IsWindowVisible.argtypes = (ctypes.c_void_p,)
        user32.ShowWindow.argtypes = (ctypes.c_void_p, ctypes.c_int)
        user32.SetForegroundWindow.argtypes = (ctypes.c_void_p,)

        found: list[int] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, ctypes.c_void_p, wintypes.LPARAM)
        def on_window(hwnd: int, _lparam: int) -> bool:
            title = ctypes.create_unicode_buffer(64)
            class_name = ctypes.create_unicode_buffer(64)
            user32.GetWindowTextW(hwnd, title, 64)
            user32.GetClassNameW(hwnd, class_name, 64)
            # Título + classe "Qt*" (ex.: Qt6120QWindowIcon) evita realçar uma pasta do Explorer com o mesmo nome e a versão anterior (GTK).
            if title.value == _MAIN_WINDOW_TITLE and class_name.value.lower().startswith(
                "qt"
            ):
                found.append(hwnd)
                return False  # para a enumeração: achou
            return True

        user32.EnumWindows(on_window, 0)
        if not found:
            return

        hwnd = ctypes.c_void_p(found[0])
        # Principal escondida: quem a mostra é a primeira cópia; dar foreground à HWND escondida a faria reaparecer sem o Qt saber.
        if not user32.IsWindowVisible(hwnd):
            return
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not present the running Cartridges window: %s", error)
