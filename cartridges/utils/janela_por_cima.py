"""Uma janela por cima de tudo sem roubar o foco do jogo (o aviso de conquista: um jogo em tela cheia minimiza ao perder o foco).

Estilos do Win32 aplicados depois do `create()` da ``QWindow`` e antes de ela aparecer: ``WS_EX_NOACTIVATE`` (não ativa), ``WS_EX_TOPMOST``, ``WS_EX_TRANSPARENT`` + ``WS_EX_LAYERED`` + ``SetLayeredWindowAttributes`` (o clique passa; o TRANSPARENT sozinho é ignorado) e ``WS_EX_TOOLWINDOW`` (fora da barra e do Alt+Tab; no Qt, depois de a janela aparecer).

O cartão também tem um dono: uma janela oculta, criada uma vez, a que ele é amarrado antes do ``show()`` e de novo depois (o Qt refaz o dono ao mostrar). Janela com dono não ganha botão na barra; a principal não serve de dono (minimizada na sessão, o Windows esconde as janelas dela).

O NOACTIVATE não basta com o processo em primeiro plano: `mostrar_sem_tomar_o_foco` devolve o foco a quem o tinha. Não aparece sobre jogo em tela cheia exclusiva; a iluminação cobre esse caso.
"""

import ctypes
import logging
from ctypes import wintypes
from typing import Any, Optional

GWL_EXSTYLE = -20
GWLP_HWNDPARENT = -8  # a do dono (owner), não a de janela-filha
GW_OWNER = 4
WS_POPUP = 0x80000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000
WS_EX_NOACTIVATE = 0x08000000
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
LWA_ALPHA = 0x2
MONITOR_DEFAULTTOPRIMARY = 1
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

# Sem WS_EX_LAYERED e SetLayeredWindowAttributes(0, 255, LWA_ALPHA) o clique não passa. No Qt (D3D11) a janela
# transparente ou com WindowTransparentForInput já sai com essa chamada, sem efeito a mais; com USAR_CAMADAS = False
# o WS_EX_LAYERED continua (é do Qt).
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
    """user32 com os tipos declarados (HWND de 64 bits não pode virar int de 32).

    Cópia própria: ``ctypes.windll.user32`` é compartilhado, e os ``argtypes`` do ``GetMonitorInfoW`` daqui
    quebrariam ``window_geometry``, que declara outra estrutura para a mesma função.
    """
    global _user32  # pylint: disable=global-statement
    if _user32 is None:
        u = ctypes.WinDLL("user32")  # type: ignore[attr-defined]
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
        u.GetWindow.restype = wintypes.HWND
        u.GetWindow.argtypes = [wintypes.HWND, ctypes.c_uint]
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsIconic.argtypes = [wintypes.HWND]
        u.SetForegroundWindow.argtypes = [wintypes.HWND]
        u.CreateWindowExW.restype = wintypes.HWND
        u.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.MonitorFromWindow.restype = wintypes.HMONITOR
        u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        u.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFO)]
        _user32 = u
    return _user32


def handle(janela: Any) -> Optional[int]:
    """O HWND de uma ``QWindow`` (``winId()``), ou None se ela não existe no Windows."""
    try:
        return int(janela.winId()) or None
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


def _definir_estilos(hwnd: int) -> bool:
    """Aplica os estilos e confere. False (ou exceção) se algum não pegou.

    `SetWindowLongPtrW` devolve o valor antigo, não sucesso: só relendo se sabe.
    """
    u = _api()
    estilos = ESTILOS | (WS_EX_LAYERED if USAR_CAMADAS else 0)
    u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) | estilos)
    if USAR_CAMADAS and not u.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA):
        raise OSError("SetLayeredWindowAttributes falhou")
    # O Windows ignora WS_EX_TOPMOST em SetWindowLongPtr: só SetWindowPos o liga.
    if not u.SetWindowPos(
        hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
    ):
        raise OSError("SetWindowPos falhou")
    exigidos = WS_EX_NOACTIVATE | (WS_EX_LAYERED if USAR_CAMADAS else 0)
    return int(u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)) & exigidos == exigidos


_dono: Optional[int] = None


def _dono_oculto() -> Optional[int]:
    global _dono  # pylint: disable=global-statement
    u = _api()
    if _dono is None or not u.IsWindow(_dono):
        _dono = u.CreateWindowExW(0, "STATIC", "", WS_POPUP, 0, 0, 0, 0, None, None, None, None)
        if not _dono:
            _dono = None
            raise OSError("CreateWindowExW falhou")
    return _dono


def dono_oculto() -> Optional[int]:
    """O dono oculto compartilhado, para outras janelas que ficam fora da barra."""
    return _dono_oculto()


def _amarrar_ao_dono(hwnd: int) -> None:
    u = _api()
    dono = _dono_oculto()
    u.SetWindowLongPtrW(hwnd, GWLP_HWNDPARENT, dono)
    if u.GetWindow(hwnd, GW_OWNER) != dono:
        raise OSError("a janela não aceitou o dono")


def dono_de(janela: Any) -> int:
    """O HWND do dono da janela (0 se não tem dono ou ela não existe no Windows)."""
    hwnd = handle(janela)
    if not hwnd:
        return 0
    try:
        return int(_api().GetWindow(hwnd, GW_OWNER) or 0)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.debug("Não foi possível ler o dono da janela do aviso", exc_info=True)
        return 0


def preparar(janela: Any) -> bool:
    """Aplica os estilos e o dono (depois de `create()`, antes de mostrar). Se False, quem chama não deve mostrar a janela: ela tomaria o foco."""
    hwnd = handle(janela)
    if not hwnd:
        return False
    try:
        if not _definir_estilos(hwnd):
            logging.warning("A janela do aviso não aceitou os estilos")
            return False
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível preparar a janela do aviso", exc_info=True)
        return False
    try:
        _amarrar_ao_dono(hwnd)
    except Exception:  # pylint: disable=broad-exception-caught
        # Sem dono o WS_EX_NOACTIVATE ainda a mantém fora da barra de tarefas.
        logging.warning("Não foi possível dar um dono à janela do aviso", exc_info=True)
    return True


def mostrar_sem_tomar_o_foco(janela: Any) -> None:
    """Mostra a janela e, se ela tomou o foco (o Windows pode ativá-la com o processo em primeiro plano), o devolve. Falha do Win32 não levanta."""
    anterior = None
    try:
        anterior = _api().GetForegroundWindow()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível ler a janela em primeiro plano", exc_info=True)
    janela.show()
    # O Qt refaz o dono ao mostrar a janela: sem amarrar de novo, o cartão ficava sem dono.
    hwnd = handle(janela)
    if hwnd:
        try:
            _amarrar_ao_dono(hwnd)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Não foi possível dar um dono à janela do aviso", exc_info=True)
    if not anterior:
        return
    try:
        u = _api()
        atual = u.GetForegroundWindow()
        if atual and atual in (handle(janela), dono_de(janela)) and u.IsWindow(anterior):
            if not u.SetForegroundWindow(anterior):
                logging.warning("O Windows recusou devolver o foco após mostrar o aviso")
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível devolver o foco após mostrar o aviso", exc_info=True)


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
    """O monitor inteiro (não a área de trabalho) da janela em primeiro plano: o jogo em tela cheia cobre a barra de tarefas."""
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
        # Mostrar a janela pode desfazer o TOPMOST, e logo após o primeiro plano mudar o Windows aceita o HWND_TOPMOST
        # sem aplicá-lo (devolve sucesso): o cartão ficava atrás do jogo. Passar antes por HWND_NOTOPMOST faz valer.
        u.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
        u.SetWindowPos(
            hwnd, HWND_TOPMOST, x, y, 0, 0, SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
        return True
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível posicionar o aviso", exc_info=True)
        return False
