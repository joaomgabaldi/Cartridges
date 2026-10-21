"""Uma cortina preta sobre o monitor do app, para o fade do Big Picture.

Janela Win32 própria (classe registrada uma vez), em camadas, por cima de tudo,
que deixa o clique passar e não rouba o foco. O dono é o mesmo dono oculto dos
cartões de `janela_por_cima`, o que a mantém fora da barra de tarefas. Qualquer
falha ao criá-la levanta `OSError`: quem chama faz a troca sem fade.
"""

import ctypes
from ctypes import wintypes
from types import SimpleNamespace
from typing import Any, Optional

from cartridges.utils import janela_por_cima

MONITOR_DEFAULTTONEAREST = 2
BLACK_BRUSH = 4
SW_SHOWNOACTIVATE = 4
CLASSE = "CartridgesCortinaBP"
ESTILOS = (
    janela_por_cima.WS_EX_LAYERED
    | janela_por_cima.WS_EX_TOPMOST
    | janela_por_cima.WS_EX_TRANSPARENT
    | janela_por_cima.WS_EX_TOOLWINDOW
    | janela_por_cima.WS_EX_NOACTIVATE
)

_WNDPROC = ctypes.WINFUNCTYPE(
    ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
)


class _WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.UINT),
        ("style", wintypes.UINT),
        ("lpfnWndProc", _WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
        ("hIconSm", wintypes.HICON),
    ]


_api_real: Optional[Any] = None
_proc: Optional[Any] = None  # mantém o callback vivo enquanto a classe existir
_classe_registrada = False


def _api() -> Any:
    """As funções do Win32 usadas aqui (user32, gdi32 e kernel32) num objeto só."""
    global _api_real  # pylint: disable=global-statement
    if _api_real is None:
        u = janela_por_cima._api()  # pylint: disable=protected-access
        u.DefWindowProcW.restype = ctypes.c_ssize_t
        u.DefWindowProcW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
        ]
        u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        u.DestroyWindow.argtypes = [wintypes.HWND]
        u.RegisterClassExW.argtypes = [ctypes.POINTER(_WNDCLASSEXW)]
        g = ctypes.WinDLL("gdi32")  # type: ignore[attr-defined]
        g.GetStockObject.restype = wintypes.HBRUSH
        k = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
        k.GetModuleHandleW.restype = wintypes.HINSTANCE
        _api_real = SimpleNamespace(
            **{
                nome: getattr(u, nome)
                for nome in (
                    "DefWindowProcW", "RegisterClassExW", "CreateWindowExW",
                    "MonitorFromWindow", "GetMonitorInfoW", "ShowWindow",
                    "SetWindowPos", "SetLayeredWindowAttributes", "DestroyWindow",
                )
            },
            GetStockObject=g.GetStockObject,
            GetModuleHandleW=k.GetModuleHandleW,
        )
    return _api_real


def _registrar_classe(u: Any) -> Any:
    """Registra a classe uma vez e devolve o HINSTANCE."""
    global _proc, _classe_registrada  # pylint: disable=global-statement
    instancia = u.GetModuleHandleW(None)
    if not _classe_registrada:
        _proc = _WNDPROC(lambda h, m, w, l: u.DefWindowProcW(h, m, w, l))
        classe = _WNDCLASSEXW()
        classe.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        classe.lpfnWndProc = _proc
        classe.hInstance = instancia
        classe.hbrBackground = u.GetStockObject(BLACK_BRUSH)
        classe.lpszClassName = CLASSE
        if not u.RegisterClassExW(ctypes.byref(classe)):
            raise OSError("RegisterClassExW falhou")
        _classe_registrada = True
    return instancia


class CortinaMonitor:
    """Janela preta que cobre o monitor da janela `hwnd_app`; `alfa` 0 a 1."""

    def __init__(self, hwnd_app: int) -> None:
        self.hwnd: Optional[int] = None
        u = _api()
        instancia = _registrar_classe(u)
        monitor = u.MonitorFromWindow(hwnd_app, MONITOR_DEFAULTTONEAREST)
        info = janela_por_cima._MONITORINFO()  # pylint: disable=protected-access
        info.cbSize = ctypes.sizeof(info)
        if not u.GetMonitorInfoW(monitor, ctypes.byref(info)):
            raise OSError("GetMonitorInfoW falhou")
        r = info.rcMonitor
        hwnd = u.CreateWindowExW(
            ESTILOS, CLASSE, "", janela_por_cima.WS_POPUP,
            r.left, r.top, r.right - r.left, r.bottom - r.top,
            janela_por_cima.dono_oculto(), None, instancia, None,
        )
        if not hwnd:
            raise OSError("CreateWindowExW falhou")
        self.hwnd = hwnd
        try:
            self.alfa(0.0)
            u.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
            if not u.SetWindowPos(
                hwnd, janela_por_cima.HWND_TOPMOST, 0, 0, 0, 0,
                janela_por_cima.SWP_NOSIZE | janela_por_cima.SWP_NOMOVE
                | janela_por_cima.SWP_NOACTIVATE,
            ):
                raise OSError("SetWindowPos falhou")
        except BaseException:
            self.fechar()
            raise

    def alfa(self, valor: float) -> None:
        if self.hwnd is None:
            return
        byte = round(max(0.0, min(1.0, valor)) * 255)
        if not _api().SetLayeredWindowAttributes(
            self.hwnd, 0, byte, janela_por_cima.LWA_ALPHA
        ):
            raise OSError("SetLayeredWindowAttributes falhou")

    def fechar(self) -> None:
        if self.hwnd is not None:
            hwnd, self.hwnd = self.hwnd, None
            _api().DestroyWindow(hwnd)
