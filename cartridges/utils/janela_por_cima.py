"""Uma janela que fica por cima de tudo sem roubar o foco do jogo.

Um jogo em tela cheia minimiza quando perde o foco, então o aviso de conquista
não pode ser uma janela comum. Os estilos estendidos do Win32 fazem o
trabalho, aplicados depois do `realize()` (quando a janela já existe no
Windows) e antes de ela aparecer:

- ``WS_EX_NOACTIVATE``: mostrar ou clicar não a torna a janela ativa;
- ``WS_EX_TOOLWINDOW``: fora da barra de tarefas e do Alt+Tab;
- ``WS_EX_TOPMOST``: por cima das janelas comuns;
- ``WS_EX_TRANSPARENT``: o clique passa para o que está embaixo.

Não aparece sobre jogo em tela cheia exclusiva (o mesmo limite do Hydra); a
iluminação cobre esse caso. O mesmo jeito de falar com o Win32 que
`session_window.position_bottom_right` já usa.
"""

import ctypes
import logging
from ctypes import wintypes
from typing import Any, Optional

import gi

gi.require_version("GdkWin32", "4.0")
from gi.repository import GdkWin32  # noqa: E402

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
LWA_ALPHA = 0x2
MONITOR_DEFAULTTOPRIMARY = 1
HWND_TOPMOST = -1

# Decididos na prova técnica (Tarefa 1 do plano da fase 2): sem WS_EX_LAYERED e
# SetLayeredWindowAttributes(0, 255, LWA_ALPHA) o clique não passa (o
# WS_EX_TRANSPARENT sozinho é ignorado). Com GDK_DEBUG=dcomp e fundo transparente
# no CSS, o canto arredondado mostra o que está atrás, também com as camadas.
# Mostrar com set_visible(True) simples depois dos estilos e então SetWindowPos
# (HWND_TOPMOST, SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW) mantém o foco;
# ShowWindow(SW_SHOWNOACTIVATE) antes de o GTK mostrar derruba o processo.
USAR_CAMADAS = True
FUNDO_TRANSPARENTE = True

ESTILOS = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT

CANTOS = ("superior-esquerdo", "superior-direito", "inferior-esquerdo", "inferior-direito")


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


_user32: Optional[Any] = None


def _api() -> Any:
    """user32 com os tipos declarados (HWND de 64 bits não pode virar int de 32)."""
    global _user32  # pylint: disable=global-statement
    if _user32 is None:
        u = ctypes.windll.user32  # type: ignore[attr-defined]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, wintypes.COLORREF, ctypes.c_ubyte, wintypes.DWORD,
        ]
        u.SetWindowPos.argtypes = [
            wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.MonitorFromWindow.restype = wintypes.HMONITOR
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
        _user32 = u
    return _user32


def handle(janela: Any) -> Optional[int]:
    """O HWND da janela, ou None se ela ainda não existe no Windows."""
    try:
        superficie = janela.get_surface()
        if superficie is None:
            return None
        return int(GdkWin32.Win32Surface.get_handle(superficie))
    except Exception:  # pylint: disable=broad-exception-caught
        logging.debug("Janela do aviso sem handle", exc_info=True)
        return None


def estilos_de(janela: Any) -> int:
    """Os estilos estendidos atuais da janela (0 se ela não existe no Windows)."""
    hwnd = handle(janela)
    if not hwnd:
        return 0
    try:
        return int(_api().GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível ler os estilos da janela do aviso", exc_info=True)
        return 0


def _definir_estilos(hwnd: int) -> None:
    u = _api()
    estilos = ESTILOS | (WS_EX_LAYERED if USAR_CAMADAS else 0)
    u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) | estilos)
    if USAR_CAMADAS:
        u.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
    # O Windows ignora WS_EX_TOPMOST em SetWindowLongPtr: só SetWindowPos o liga.
    u.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    )


def preparar(janela: Any) -> bool:
    """Aplica os estilos. Chamar depois de `realize()`, antes de mostrar."""
    hwnd = handle(janela)
    if not hwnd:
        return False
    try:
        _definir_estilos(hwnd)
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível preparar a janela do aviso", exc_info=True)
        return False


def posicao(
    canto: str, monitor: tuple[int, int, int, int], tamanho: tuple[int, int], margem: int
) -> tuple[int, int]:
    """Canto superior esquerdo da janela para ficar no canto pedido do monitor."""
    esquerda, topo, direita, base = monitor
    largura, altura = tamanho
    if canto not in CANTOS:
        canto = "inferior-direito"
    x = esquerda + margem if canto.endswith("esquerdo") else direita - largura - margem
    y = topo + margem if canto.startswith("superior") else base - altura - margem
    return x, y


def _monitor_em_uso() -> tuple[int, int, int, int]:
    """O monitor inteiro (não a área de trabalho) da janela em primeiro plano:
    o jogo em tela cheia cobre a barra de tarefas, e o aviso vai no canto dele."""
    u = _api()
    monitor = u.MonitorFromWindow(u.GetForegroundWindow(), MONITOR_DEFAULTTOPRIMARY)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(_MONITORINFO)
    if not u.GetMonitorInfoW(monitor, ctypes.byref(info)):
        raise OSError("GetMonitorInfoW falhou")
    r = info.rcMonitor
    return r.left, r.top, r.right, r.bottom


def por_no_canto(janela: Any, canto: str, margem: int = 24) -> bool:
    """Leva a janela (já visível) ao canto pedido, por cima de tudo, sem ativar."""
    hwnd = handle(janela)
    if not hwnd:
        return False
    try:
        u = _api()
        retangulo = wintypes.RECT()
        u.GetWindowRect(hwnd, ctypes.byref(retangulo))
        tamanho = (retangulo.right - retangulo.left, retangulo.bottom - retangulo.top)
        x, y = posicao(canto, _monitor_em_uso(), tamanho, margem)
        u.SetWindowPos(
            hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível posicionar o aviso", exc_info=True)
        return False
