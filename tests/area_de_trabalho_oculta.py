"""Põe a thread principal numa área de trabalho do Windows que nunca aparece.

As janelas que os testes abrem (cartões de conquista, janela principal) ficam
nessa área, longe da tela de quem usa o PC, e não roubam o foco. Tem de rodar
antes de qualquer import do GTK/Gdk: depois que a thread tem janelas, o Windows
recusa a troca. `CARTRIDGES_TESTES_NA_TELA=1` desliga.
"""

import ctypes
import os
import warnings
from ctypes import wintypes

GENERIC_ALL = 0x10000000
_ativa = False


def ativa() -> bool:
    """True se a suíte está na área oculta (onde não existe primeiro plano)."""
    return _ativa


def entrar() -> bool:
    """True se a thread passou para a área oculta; nunca derruba a suíte."""
    global _ativa  # pylint: disable=global-statement
    if os.environ.get("CARTRIDGES_TESTES_NA_TELA") == "1":
        return False
    try:
        u = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        u.CreateDesktopW.restype = wintypes.HANDLE
        u.CreateDesktopW.argtypes = [
            wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPVOID,
            wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        ]
        u.SetThreadDesktop.argtypes = [wintypes.HANDLE]
        u.CloseDesktop.argtypes = [wintypes.HANDLE]
        u.CloseDesktop.restype = wintypes.BOOL
        area = u.CreateDesktopW("cartridges-testes", None, None, 0, GENERIC_ALL, None)
        if not area:
            raise OSError(ctypes.get_last_error(), "CreateDesktopW falhou")
        if not u.SetThreadDesktop(area):
            erro = ctypes.get_last_error()
            u.CloseDesktop(area)
            raise OSError(erro, "SetThreadDesktop falhou")
        _ativa = True
        return True
    except Exception as erro:  # pylint: disable=broad-exception-caught
        warnings.warn(f"Testes seguem na tela: sem área de trabalho oculta ({erro})", stacklevel=2)
        return False
