# window_geometry.py
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

"""Remember the main window's size, position and state across runs.

Two things here are not what a GTK application would normally do, and both have
the same cause: GTK4 has no window-position API at all. The toolkit's model
comes from Wayland, where a client may neither know nor choose where it sits.
That is fine there and useless on Windows, where an app that cannot remember its
monitor reopens on the primary one every time, however many screens are
attached. So the position is read and applied through Win32, the same way the
session window is placed.

Size is measured and restored as a Win32 frame rectangle rather than through
GTK's default size, because on Windows those two disagree: give a window a
default width of 724 and, once it has been maximized and restored, GTK reports
that width back as 696. The frame's 28 pixels are counted on the way in but not
on the way out. Persisting that through a two-way GSettings binding, as an
application normally would, made the remembered size ratchet down by 28x29 on
every run, which is how this window reached 724x428 from a 1170x795 default. A
frame rectangle means the same thing in both directions, so it survives the
round trip.

The size is also only ever saved while the window is not maximized, so that a
maximized window remembers the size to go back to rather than the screen it
happened to fill.

The same Win32 handle also answers a second question, which is why the monitor
list lives here: parking the window on another screen while a game runs (see
:func:`move_to_monitor`) is the startup restore done twice — out to the chosen
monitor, then back to exactly where it was. GDK's own monitor list cannot be
used for it: on Windows ``get_connector()`` and ``get_description()`` are both
``None``, and GDK's ordering is not the desktop's, so there would be nothing to
label a monitor with and nothing stable to store.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import weakref
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any, NamedTuple, Optional

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtGui import QWindow

from cartridges import shared

_MONITOR_DEFAULTTONULL = 0x00000000
# SWP_NOZORDER | SWP_NOACTIVATE: place it exactly, without raising or focusing
_PLACE = 0x0004 | 0x0010
# O retângulo que o GTK da `main` gravava inclui a sombra da janela (a diferença de 28x29 que `main.py` cita): o Qt não a
# tem. Esquerda/topo e largura/altura a descontar na primeira abertura depois da `main` (DA-72). O reparte entre os
# lados é aproximado (14 e 14; o 1 a mais de altura fica embaixo): a sombra do GTK4 é um pouco maior embaixo.
_SOMBRA_DO_GTK = (14, 14, 28, 29)
# A folga entre o botão das tarefas e a janela solta que se abre acima dele.
_FOLGA_BOTAO = 12
_MONITORINFOF_PRIMARY = 0x00000001
_SW_HIDE = 0
_SW_SHOWNORMAL = 1
_SW_SHOWMAXIMIZED = 3

# Declared rather than left to ctypes' defaults, which pass and return C ints:
# a handle is a 64-bit pointer here, and a truncated HMONITOR would read as "no
# monitor" and quietly throw away every stored position.
_user32 = ctypes.windll.user32  # type: ignore
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
_user32.MonitorFromRect.restype = wintypes.HANDLE
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.IsZoomed.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


_user32.GetWindowPlacement.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(_WINDOWPLACEMENT),
]
_user32.GetWindowPlacement.restype = wintypes.BOOL
_user32.SetWindowPlacement.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(_WINDOWPLACEMENT),
]
_user32.SetWindowPlacement.restype = wintypes.BOOL

_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    wintypes.LPARAM,
)
_user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    _MONITORENUMPROC,
    wintypes.LPARAM,
]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFOEXW)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


_user32.EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(_DISPLAY_DEVICEW),
    wintypes.DWORD,
]
_user32.EnumDisplayDevicesW.restype = wintypes.BOOL
_EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001
_DISPLAY_DEVICE_ACTIVE = 0x00000001

# What the schema holds until a window has been closed once. Not 0, which is a
# perfectly real coordinate, and not -1, which a second monitor placed above the
# primary genuinely produces: this desktop's portrait screen starts at y=-476.
UNSET = -(2**31)


class Geometry(NamedTuple):
    """The window's frame rectangle, and whether it was showing maximized."""

    x: int
    y: int
    width: int
    height: int
    maximized: bool

    @property
    def usable(self) -> bool:
        """False for the "nothing stored yet" value the schema starts at."""
        return self.width > 0 and self.height > 0 and self.x != UNSET


def stored(schema: Any) -> Geometry:
    """A geometria que ``save_window_geometry`` gravou no GSettings do estado.

    Lida de novo a cada "map", e não uma vez na abertura: a janela principal
    pode ser escondida e reaparecer (veja `on_win_close_request`), e o "map"
    seguinte tem de devolvê-la a onde o usuário a deixou, não a onde ela abriu.
    """
    return Geometry(
        schema.get_int("x"),
        schema.get_int("y"),
        schema.get_int("width"),
        schema.get_int("height"),
        schema.get_boolean("is-maximized"),
    )


class Monitor(NamedTuple):
    """An attached screen, in the same physical coordinates as :class:`Geometry`."""

    device: str  # "\\\\.\\DISPLAY2", the name the desktop numbers monitors by
    x: int  # the whole screen, taskbar included: a window sent here is
    y: int  # maximized over it, and the badge is centred on it
    width: int
    height: int
    primary: bool
    ordinal: int = 0  # 1-based place in :func:`monitors`; 0 when built by hand
    # O caminho do monitor (``\\\\?\\DISPLAY#DEL4123#5&...#{e6f07b5f-...}``): o
    # modelo e a saída de vídeo em que ele está ligado. Vazio quando o Windows
    # não o informa, e então vale o ``device``.
    path: str = ""

    @property
    def key(self) -> str:
        """O que a preferência ``session-monitor`` guarda para esta tela.

        Não o ``device``: o Windows troca os nomes ``DISPLAYn`` entre as telas
        quando elas dormem e acordam, são religadas em outra ordem ou o driver
        reinicia, e a tela escolhida passava a ser a outra. O caminho é do
        monitor e da porta em que ele está, e só muda se o cabo mudar de porta.
        """
        return self.path or self.device

    def is_stored(self, stored: str) -> bool:
        """Se ``stored`` (o valor da preferência) aponta para esta tela.

        Aceita também o ``device``, que é o que as versões anteriores gravavam:
        a escolha antiga continua valendo até a tela de preferências gravar o
        caminho no lugar dele.
        """
        return bool(stored) and stored in (self.path, self.device)

    @property
    def number(self) -> str:
        """What the preference list and the identify badge call this screen.

        The place in the list, and not the "22" of ``\\\\.\\DISPLAY22``: the
        desktop keeps counting up as screens and drivers come and go, so after
        a while the device names read 22, 23, 24 while Windows' own display
        settings still say 1, 2, 3.
        """
        if self.ordinal:
            return str(self.ordinal)
        return self.device.rsplit("DISPLAY", 1)[-1] or "?"


def _device_order(monitor: Monitor) -> tuple[int, str]:
    """DISPLAY2 before DISPLAY10, which plain string order gets backwards."""
    digits = monitor.device.rsplit("DISPLAY", 1)[-1]
    return (int(digits) if digits.isdigit() else 0, monitor.device)


def _place_order(monitor: Monitor) -> tuple[bool, int, int, tuple[int, str]]:
    """O principal primeiro; os outros da esquerda para a direita, depois de
    cima para baixo. O nome só desempata telas na mesma posição."""
    return (not monitor.primary, monitor.x, monitor.y, _device_order(monitor))


def numbered(found: list[Monitor]) -> list[Monitor]:
    """The monitors in place order, each told its place (1, 2, 3...).

    Pela posição na área de trabalho, e não pela ordem dos nomes ``DISPLAYn``:
    o Windows troca esses nomes entre as telas (veja :attr:`Monitor.key`), e a
    tela da esquerda virava o "Monitor 3" de uma sessão para a outra. A
    posição só muda quando o usuário rearranja as telas.
    """
    return [
        monitor._replace(ordinal=place)
        for place, monitor in enumerate(sorted(found, key=_place_order), 1)
    ]


def _monitor_path(device: str) -> str:
    """O caminho do monitor ligado em ``device``, ou "" se o Windows não diz."""
    for index in range(4):  # mais de uma só em telas espelhadas
        info = _DISPLAY_DEVICEW()
        info.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
        if not _user32.EnumDisplayDevicesW(
            device, index, ctypes.byref(info), _EDD_GET_DEVICE_INTERFACE_NAME
        ):
            break
        if info.StateFlags & _DISPLAY_DEVICE_ACTIVE and info.DeviceID:
            return info.DeviceID
    return ""


def monitors() -> list[Monitor]:
    """Every attached monitor, in desktop order.

    Empty if the enumeration fails, which callers must treat as "don't move the
    window" rather than as an error worth showing anyone.
    """
    found: list[Monitor] = []

    def collect(handle: int, _hdc: int, _rect: Any, _param: int) -> bool:
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if _user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            area = info.rcMonitor
            found.append(
                Monitor(
                    info.szDevice,
                    area.left,
                    area.top,
                    area.right - area.left,
                    area.bottom - area.top,
                    bool(info.dwFlags & _MONITORINFOF_PRIMARY),
                    path=_monitor_path(info.szDevice),
                )
            )
        return True

    try:
        _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(collect), 0)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not list the monitors: %s", error)
        return []

    # Sorted by place, not by the order the callback fired in: the enumeration
    # order is whatever the driver hands over, and a list that reshuffles
    # between runs would make "Monitor 2" mean a different screen each time.
    return numbered(found)


def has_secondary_monitor() -> bool:
    """True when some attached monitor is not the primary one.

    What both session options that use other screens need: the game runs on the
    primary, so without a second monitor there is nowhere to park the window and
    nowhere to show the art. A failed enumeration answers False, which is the
    safe side — the caller switches its option off instead of touching a screen.
    """
    return any(not monitor.primary for monitor in monitors())


def monitores_da_sessao() -> list[Monitor]:
    """Os monitores que a sessão pode usar: todos menos o principal.

    O principal fica fora: é onde o jogo roda, e a janela maximizada ali
    ficaria na frente dele.
    """
    return [monitor for monitor in monitors() if not monitor.primary]


def escolha_de_monitor(monitores: list[Monitor], gravado: str) -> tuple[list[str], int]:
    """Os rótulos da lista de monitores e a posição do que está gravado.

    O que fica guardado é o caminho do monitor (:attr:`Monitor.key`), e não a
    posição na lista nem o nome ``DISPLAYn``, que o Windows troca entre as
    telas: desligar um monitor, ou o Windows renomear as telas, não faz a
    escolha passar a apontar para outro. Uma escolha antiga, gravada pelo
    nome, também é reconhecida (:meth:`Monitor.is_stored`). Se o monitor
    gravado estiver desligado (ou for o principal, guardado de antes de ele sair
    da lista), a posição é a do primeiro: quem chama grava essa escolha, que é a
    única forma de a lista mostrar o que vai acontecer de verdade.

    Só o número no rótulo, porque só o número tem resposta: resolução e posição
    empatam entre telas iguais, e é o botão "Identificar monitores" que diz qual
    é qual — na própria tela, que é onde se olha.
    """
    rotulos = [_("Monitor {}").format(m.number) for m in monitores]
    escolhido = next((i for i, m in enumerate(monitores) if m.is_stored(gravado)), 0)
    return rotulos, escolhido


# As placas na tela, seguradas aqui até fecharem: quem as pediu (as Preferências) pode já ter fechado.
_placas: list[Any] = []
_PLACA = Path(__file__).resolve().parent.parent / "qml" / "PlacaDoMonitor.qml"


def _criar_placa(monitor: Monitor, lado: int) -> Any:
    """A placa do ``monitor``: uma ``QQuickView`` sem moldura com o número, no centro da tela (D68)."""
    from PySide6.QtCore import QUrl, Qt  # noqa: PLC0415
    from PySide6.QtQuick import QQuickView  # noqa: PLC0415

    placa = QQuickView()
    # Janela comum sem moldura, como o `Gtk.Window(decorated=False)` da `main`: recebe foco e aparece na barra de tarefas.
    placa.setFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
    placa.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    placa.setInitialProperties({"numero": monitor.number})
    placa.setSource(QUrl.fromLocalFile(str(_PLACA)))
    if placa.rootObject() is None:
        erros = "; ".join(erro.toString() for erro in placa.errors())
        placa.deleteLater()
        raise RuntimeError(f"a placa do monitor não carregou: {erros}")
    placa.resize(lado, lado)
    placa.show()
    # Depois do `show`: antes dele a janela ainda não tem lugar na área de trabalho.
    _place(
        placa,
        Geometry(
            monitor.x + (monitor.width - lado) // 2,
            monitor.y + (monitor.height - lado) // 2,
            lado,
            lado,
            False,
        ),
    )
    return placa


def _fechar_placa(ref: Any) -> None:
    placa = ref()
    if placa is None:
        return
    if placa in _placas:
        _placas.remove(placa)
    try:
        placa.close()
        placa.deleteLater()
    except RuntimeError:  # o objeto Qt já foi apagado
        pass


def identificar_monitores(segundos: int = 3, criar: Optional[Callable[[Monitor, int], Any]] = None) -> None:
    """Pisca o número de cada monitor sobre ele, como as configurações do Windows.

    A pergunta "qual deles é o 2?" não tem resposta em texto: dois monitores
    iguais dão o mesmo rótulo, e a posição relativa só desempata enquanto eles
    estiverem em lados diferentes. O que responde é olhar para as telas — então
    o número vai para a tela, e não mais texto para a lista.

    Mora aqui, e não junto da tela de preferências, porque é a mesma pergunta
    que o resto do arquivo responde: onde ficam os monitores, e como se põe uma
    janela em cima de um deles. Só na thread principal.
    """
    criar = criar or _criar_placa
    for monitor in monitors():
        # Um quarto do lado menor da tela, para o número sair do mesmo tamanho
        # relativo em telas de tamanhos diferentes.
        lado = max(200, min(monitor.width, monitor.height) // 4)
        placa = criar(monitor, lado)
        if placa is None:
            continue
        _placas.append(placa)
        QTimer.singleShot(segundos * 1000, functools.partial(_fechar_placa, weakref.ref(placa)))


def read(window: Any) -> Optional[Geometry]:
    """The window's frame rectangle, or None if it can no longer be asked.

    For a maximized window this is the monitor's work area, which is not a size
    worth restoring but is exactly the position needed to reopen on the same
    screen, so callers keep the position and drop the size in that case.
    """
    if (hwnd := _hwnd(window)) is None:
        return None

    # A minimized window's rect is the icon parking spot — (-32000,-32000),
    # ~160x28 — not a geometry. And minimized is this app's normal state while a
    # game runs (it minimizes itself on launch), so closing from the taskbar or
    # quitting mid-session would persist the sliver and reopen tiny. Treat it
    # like an unaskable window: the previously stored geometry stays.
    if _user32.IsIconic(hwnd):
        return None

    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None

    return Geometry(
        rect.left,
        rect.top,
        rect.right - rect.left,
        rect.bottom - rect.top,
        bool(_user32.IsZoomed(hwnd)),
    )


def gravar(schema: Any, janela: Any, tela_cheia: bool) -> bool:
    """Grava onde a janela está, se ainda dá para perguntar; diz se gravou (as regras do `save_window_geometry` da `main`).

    Em tela cheia (Big Picture) o retângulo é o da tela, não o da janela: vale a geometria gravada antes. Fechar o app
    no meio de uma sessão: a janela está estacionada no monitor do jogo, e o que tem de ser lembrado é de onde ela saiu
    (D52). Minimizada, `read` não responde, e fica a gravada antes.
    """
    if tela_cheia:
        return False
    geometry = session_geometry() or read(janela)
    if geometry is None:
        return False
    schema.set_int("x", geometry.x)
    schema.set_int("y", geometry.y)
    schema.set_boolean("is-maximized", geometry.maximized)
    # A maximized window's rectangle is its monitor, not a size to reopen at,
    # so the last real size is left in place for it to be restored to.
    if not geometry.maximized:
        schema.set_int("width", geometry.width)
        schema.set_int("height", geometry.height)
    return True


def restaurar(janela: Any, geometria: Geometry) -> None:
    """Põe a janela de volta no lugar e no tamanho gravados. Sem nada gravado (`usable` falso), não mexe nela.

    Order matters: the window is moved first and maximized second, because maximizing fills whichever monitor the
    window currently sits on. The other way round always fills the primary one.
    """
    if not geometria.usable:
        # Primeira abertura: o 1170x795 lógico já vem do `Principal.qml` (DA-71, feito em F); o `SetWindowPos` trabalha em
        # pixels físicos e o encolheria fora de 100% de escala.
        return
    if not _place(janela, geometria) and (atual := read(janela)) is not None:
        # A posição gravada não existe mais (um monitor desligado): a janela fica onde o Windows a pôs, no tamanho
        # gravado, como a `main` (o `apply_size` vinha antes do lugar).
        _place(janela, geometria._replace(x=atual.x, y=atual.y))
    if geometria.maximized:
        # Deliberately not conditional on `_place` succeeding: if the stored
        # position was refused the user still asked for a maximized window, and
        # should get one wherever Windows has decided to put it.
        janela.showMaximized()


def sem_a_sombra_do_gtk(geometria: Geometry) -> Geometry:
    """A geometria gravada pela `main` convertida para o Qt: tira a sombra do GTK do retângulo. Maximizada não muda
    (o retângulo é o do monitor)."""
    if not geometria.usable or geometria.maximized:
        return geometria
    esquerda, topo, largura, altura = _SOMBRA_DO_GTK
    return geometria._replace(
        x=geometria.x + esquerda,
        y=geometria.y + topo,
        width=max(1, geometria.width - largura),
        height=max(1, geometria.height - altura),
    )


# Existe depois que o Qt gravou a geometria pela primeira vez: dali em diante o retângulo gravado já é o dele.
_MARCA_DO_QT = "geometria-qt"


class GeometriaDaJanela(QObject):
    """A geometria da principal no contexto do QML (`geometria`, D87): restaurada no `onCompleted` do `Principal.qml`,
    gravada no `closing` (`PainelDasTarefas.principalFechando`) e no primeiro passo do `_fechar`.

    A janela fica numa referência comum, como no `PainelDasTarefas`: ela não segura o objeto C++ (o dono é o motor),
    e uma janela já destruída responde com `RuntimeError`. Uma fraca morreria com o invólucro Python, que o PySide
    solta a qualquer momento.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._janela: Any = None

    @Slot(QObject)
    def restaurar(self, janela: Any) -> None:
        self._janela = janela
        try:
            geometria = stored(shared.state_schema)
            if not (shared.app_dir / _MARCA_DO_QT).exists():
                geometria = sem_a_sombra_do_gtk(geometria)
            restaurar(janela, geometria)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Could not restore the window geometry", exc_info=True)

    @Slot()
    def gravar(self) -> None:
        """Nunca levanta: roda no fechamento."""
        janela = self._janela
        try:
            # Já fechada pelo `quit()`: o `close()` do Qt destrói a janela nativa e o `winId()` criaria outra, num
            # lugar qualquer. O `closing` dela já gravou.
            if janela is None or not janela.isVisible():
                return
            if gravar(shared.state_schema, janela, janela.visibility() == QWindow.Visibility.FullScreen):
                (shared.app_dir / _MARCA_DO_QT).parent.mkdir(parents=True, exist_ok=True)
                (shared.app_dir / _MARCA_DO_QT).touch()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Could not save the window geometry", exc_info=True)


# Where the window was before a play session sent it to another monitor, and
# the flag that says a session is holding it there. Module state rather than a
# window attribute because the same three callers — the launch, the end of the
# session and the app quitting — all have to agree on one answer, and only one
# session can run at a time anyway.
_before_session: Optional[Geometry] = None
_before_placement: "Optional[_WINDOWPLACEMENT]" = None

def session_geometry() -> Optional[Geometry]:
    """Where the window would be if no game were running, or None if none is.

    What has to be persisted when the app is closed mid-session: the window is
    parked on the game's monitor, and saving *that* would make the parking spot
    the place the app reopens at forever after.
    """
    return _before_session


def move_to_monitor(window: Any, stored: str) -> bool:
    """Park ``window`` maximized on the monitor ``stored`` names. Says whether it went.

    ``stored`` is the ``session-monitor`` preference: a :attr:`Monitor.key`,
    or the device name older versions saved (:meth:`Monitor.is_stored`).

    False for every reason there is not to move — no such monitor attached, the
    monitor is the primary one (where the game runs, which the window would then
    cover), no handle to move, nothing readable to come back to — and the caller
    then does what it did before this feature existed (minimize, in the launch
    path). Losing the window off-screen is a much worse failure than not moving
    it, so anything unclear counts as a reason not to.

    Done with ``WINDOWPLACEMENT`` rather than with ``SetWindowPos``, because
    here there is a state to come back to. A placement carries both halves of
    what a window is — where it sits when it is not maximized, and whether it is
    showing maximized right now — so reading one before and writing it back
    after restores a maximized window *and* the size it un-maximizes to, which
    moving a maximized window by hand loses: its restore rectangle would become
    the game's monitor.

    Both writes are synchronous, which is the second reason not to use
    :meth:`Gtk.Window.maximize` here: the un-maximize has to have finished
    before the window is moved, and GTK's may not land until the next frame — by
    which time the move it was supposed to precede has already happened.
    """
    global _before_session, _before_placement  # pylint: disable=global-statement

    target = next((m for m in monitors() if m.is_stored(stored)), None)
    if target is None:
        logging.info("Monitor %s is not attached; leaving the window alone", stored)
        return False
    if target.primary:
        logging.info("Monitor %s is the primary one; leaving the window alone", stored)
        return False

    if (hwnd := _hwnd(window)) is None or (current := read(window)) is None:
        return False
    if (placement := _get_placement(hwnd)) is None:
        return False

    # Two writes, in the order the startup restore uses and for the same
    # reason: put the window on the monitor first, maximize it second. Asking
    # for both at once does nothing to a window that is already maximized —
    # Windows takes the placement's rectangle as where to *restore* it to and
    # keeps maximizing it over the monitor it is already on, which is how a
    # maximized library window stayed put while reporting that it had moved.
    if not _set_placement(hwnd, placement, _SW_SHOWNORMAL, target):
        return False
    # Best effort: a window that arrived on the right monitor but did not
    # maximize is still the right window in the right place, and still one the
    # end of the session puts back.
    _set_placement(hwnd, placement, _SW_SHOWMAXIMIZED, target)

    _before_session, _before_placement = current, placement
    logging.info("Window parked on %s (%s) for the session", target.device, target.number)
    return True


def restore_from_monitor(window: Any) -> None:
    """Put the window back exactly where :func:`move_to_monitor` found it.

    A no-op when no move happened, so the end of every session can call it
    without asking. A window GTK has hidden (`on_win_close_request` does that
    mid-session) gets the placement written as ``SW_HIDE`` instead: showing it
    here, behind GTK's back, leaves it without keyboard focus after the
    `present()` that follows. Hidden is enough to bring back what matters — the
    rectangle it un-maximizes to and whether it was maximized — which would
    otherwise stay the game monitor's, and the next "map" moves the window
    still maximized without touching that rectangle.
    """
    global _before_session, _before_placement  # pylint: disable=global-statement

    placement = _before_placement
    _before_session, _before_placement = None, None

    if placement is None or (hwnd := _hwnd(window)) is None:
        return

    if not _user32.IsWindowVisible(hwnd):
        _set_placement(hwnd, placement, _SW_HIDE)
        return

    # The mirror of the two steps in `move_to_monitor`, for the same reason: a
    # window that was maximized before the game has to be un-maximized onto its
    # own monitor first, or asking for "maximized, over there" leaves it
    # maximized right here.
    if placement.showCmd == _SW_SHOWMAXIMIZED:
        _set_placement(hwnd, placement, _SW_SHOWNORMAL)
    _user32.SetWindowPlacement(hwnd, ctypes.byref(placement))


def _set_placement(
    hwnd: int,
    placement: "_WINDOWPLACEMENT",
    show: int,
    target: Optional[Monitor] = None,
) -> bool:
    """Show ``hwnd`` as ``show``, keeping the rest of ``placement`` as it is.

    With a ``target``, the placement's rectangle is replaced by that monitor's,
    which is the only way ``WINDOWPLACEMENT`` has of saying *where*: Windows
    maximizes a window over whichever screen its rectangle lands on. Nobody
    sees the rectangle itself — the window covers it — so the whole screen
    serves. Without one, the window keeps the rectangle it is carrying, which
    is what putting it back means.
    """
    wanted = _WINDOWPLACEMENT.from_buffer_copy(placement)
    wanted.showCmd = show
    if target is not None:
        wanted.rcNormalPosition.left = target.x
        wanted.rcNormalPosition.top = target.y
        wanted.rcNormalPosition.right = target.x + target.width
        wanted.rcNormalPosition.bottom = target.y + target.height
    return bool(_user32.SetWindowPlacement(hwnd, ctypes.byref(wanted)))


def _get_placement(hwnd: int) -> "Optional[_WINDOWPLACEMENT]":
    placement = _WINDOWPLACEMENT()
    placement.length = ctypes.sizeof(_WINDOWPLACEMENT)
    if not _user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
        return None
    return placement


def posicao_acima_do_botao(botao: tuple[int, int, int, int], altura_da_janela: int) -> tuple[int, int]:
    """O canto (x, y) da moldura de uma janela solta para que ela fique logo acima do botão das tarefas.

    `botao` é (x, y, largura, altura) em coordenadas lógicas da tela (as do Qt: a escala não entra na conta);
    `altura_da_janela` é a da moldura inteira. A janela fica alinhada à esquerda do botão, com a folga de 12 px.
    """
    return botao[0], botao[1] - _FOLGA_BOTAO - altura_da_janela


def _place(window: Any, geometry: Geometry) -> bool:
    """Move and size the window's frame to ``geometry``.

    A stored position is not trusted blindly. Monitors get unplugged and
    desktops get rearranged, so a remembered position can name a place that no
    longer exists; restoring onto it would leave the window somewhere the user
    can neither see nor drag back.
    """
    if not geometry.usable or (hwnd := _hwnd(window)) is None:
        return False

    rect = wintypes.RECT()
    rect.left = geometry.x
    rect.top = geometry.y
    rect.right = geometry.x + geometry.width
    rect.bottom = geometry.y + geometry.height
    if not _user32.MonitorFromRect(ctypes.byref(rect), _MONITOR_DEFAULTTONULL):
        logging.info(
            "Stored window position %d,%d %dx%d is on no attached monitor; ignoring it",
            geometry.x,
            geometry.y,
            geometry.width,
            geometry.height,
        )
        return False

    return bool(
        _user32.SetWindowPos(
            hwnd, 0, geometry.x, geometry.y, geometry.width, geometry.height, _PLACE
        )
    )


def _hwnd(window: Any) -> Optional[int]:
    """The window's Win32 handle, or None before it is realized.

    Uma `QWindow` (a janela principal do Qt) dá o ``winId()``, que no Windows já é o HWND.

    Everything here is best-effort: a failure costs the user a window that opens
    where it last did, which is what happens without this module at all, so it
    must never be allowed to take the application down with it.
    """
    if window is None or not isinstance(window, QWindow):
        return None
    try:
        return int(window.winId()) or None
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not read the window handle: %s", error)
        return None
