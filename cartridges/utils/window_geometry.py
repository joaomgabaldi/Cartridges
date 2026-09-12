# window_geometry.py
#
# Copyright 2026 kramo
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

import ctypes
import logging
from ctypes import wintypes
from typing import Any, NamedTuple, Optional

from gi.repository import GLib, Gtk

_MONITOR_DEFAULTTONULL = 0x00000000
# SWP_NOZORDER | SWP_NOACTIVATE: place it exactly, without raising or focusing
_PLACE = 0x0004 | 0x0010
_MONITORINFOF_PRIMARY = 0x00000001
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
        """False for the "nothing stored yet" value the schema starts at.

        Also false for the minimized-window parking spot, exactly
        (-32000,-32000): `read()` no longer produces it, but a store poisoned
        by a build that did must not keep reopening the window as a sliver.
        """
        if self.x == -32000 and self.y == -32000:
            return False
        return self.width > 0 and self.height > 0 and self.x != UNSET


class Monitor(NamedTuple):
    """An attached screen, in the same physical coordinates as :class:`Geometry`."""

    device: str  # "\\\\.\\DISPLAY2", the name the desktop numbers monitors by
    x: int  # the whole screen, taskbar included: a window sent here is
    y: int  # maximized over it, and the badge is centred on it
    width: int
    height: int
    primary: bool

    @property
    def number(self) -> str:
        """The "2" of ``\\\\.\\DISPLAY2`` — what Windows' own display settings
        calls this screen, so the preference reads like the list there."""
        return self.device.rsplit("DISPLAY", 1)[-1] or "?"


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
                )
            )
        return True

    try:
        _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(collect), 0)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not list the monitors: %s", error)
        return []

    # Sorted by name, not by the order the callback fired in: the enumeration
    # order is whatever the driver hands over, and a list that reshuffles
    # between runs would make "Monitor 2" mean a different screen each time.
    return sorted(found, key=lambda monitor: monitor.device)


def has_secondary_monitor() -> bool:
    """True when some attached monitor is not the primary one.

    What both session options that use other screens need: the game runs on the
    primary, so without a second monitor there is nowhere to park the window and
    nowhere to show the art. A failed enumeration answers False, which is the
    safe side — the caller switches its option off instead of touching a screen.
    """
    return any(not monitor.primary for monitor in monitors())


def identify_monitors(seconds: int = 3) -> None:
    """Pisca o número de cada monitor sobre ele, como as configurações do Windows.

    A pergunta "qual deles é o 2?" não tem resposta em texto: dois monitores
    iguais dão o mesmo rótulo, e a posição relativa só desempata enquanto eles
    estiverem em lados diferentes. O que responde é olhar para as telas — então
    o número vai para a tela, e não mais texto para a lista.

    Mora aqui, e não junto da tela de preferências, porque é a mesma pergunta
    que o resto do arquivo responde: onde ficam os monitores, e como se põe uma
    janela em cima de um deles.
    """
    for monitor in monitors():
        badge = Gtk.Window(decorated=False, resizable=False)
        label = Gtk.Label()
        label.set_markup(f'<span size="96pt" weight="bold">{monitor.number}</span>')
        badge.set_child(label)
        # Um quarto do lado menor da tela, para o número sair do mesmo tamanho
        # relativo em telas de tamanhos diferentes.
        side = max(200, min(monitor.width, monitor.height) // 4)
        badge.set_default_size(side, side)
        badge.connect("map", _center_badge, monitor, side)
        badge.present()
        GLib.timeout_add_seconds(seconds, _close_badge, badge)


def _center_badge(badge: Gtk.Window, monitor: Monitor, side: int) -> None:
    """No "map", e não no "realize": veja :func:`apply_placement`."""
    _place(
        badge,
        Geometry(
            monitor.x + (monitor.width - side) // 2,
            monitor.y + (monitor.height - side) // 2,
            side,
            side,
            False,
        ),
    )


def _close_badge(badge: Gtk.Window) -> bool:
    badge.close()
    return GLib.SOURCE_REMOVE


def read(window: Gtk.Window) -> Optional[Geometry]:
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
        window.is_maximized(),
    )


def apply_size(window: Gtk.Window, geometry: Geometry) -> None:
    """Ask for the stored size. Must run before the window is shown.

    Approximate on purpose: GTK sizes the content area while the stored figure
    covers the frame, so this lands within the frame's width of the right answer
    and :func:`apply_placement` corrects it exactly, before anything is visible.
    Doing it here as well keeps the window from being laid out at a default size
    it is never going to have.
    """
    if geometry.usable:
        window.set_default_size(geometry.width, geometry.height)


def apply_placement(window: Gtk.Window, geometry: Geometry) -> None:
    """Put the window back on its monitor. Call this from "map", not "realize".

    A realized window already has a Win32 handle, so placing it there looks like
    it should work and does nothing: GTK positions the window again on its way
    to the screen, discarding whatever it was moved to beforehand.

    Order matters: the window is moved first and maximized second, because
    maximizing fills whichever monitor the window currently sits on. The other
    way round always fills the primary one, which is the entire bug this exists
    to fix.
    """
    _place(window, geometry)
    if geometry.maximized:
        # Deliberately not conditional on `_place` succeeding: if the stored
        # position was refused the user still asked for a maximized window, and
        # should get one wherever Windows has decided to put it.
        window.maximize()


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


def move_to_monitor(window: Gtk.Window, device: str) -> bool:
    """Park ``window`` maximized on ``device``. Says whether it went.

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

    target = next((m for m in monitors() if m.device == device), None)
    if target is None:
        logging.info("Monitor %s is not attached; leaving the window alone", device)
        return False
    if target.primary:
        logging.info("Monitor %s is the primary one; leaving the window alone", device)
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
    logging.info("Window parked on %s for the session", device)
    return True


def restore_from_monitor(window: Gtk.Window) -> None:
    """Put the window back exactly where :func:`move_to_monitor` found it.

    A no-op when no move happened, so the end of every session can call it
    without asking.
    """
    global _before_session, _before_placement  # pylint: disable=global-statement

    placement = _before_placement
    _before_session, _before_placement = None, None

    if placement is None or (hwnd := _hwnd(window)) is None:
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


def _place(window: Gtk.Window, geometry: Geometry) -> bool:
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


def _hwnd(window: Gtk.Window) -> Optional[int]:
    """The window's Win32 handle, or None before it is realized.

    Everything here is best-effort: a failure costs the user a window that opens
    where it last did, which is what happens without this module at all, so it
    must never be allowed to take the application down with it.
    """
    try:
        import gi  # pylint: disable=import-outside-toplevel

        gi.require_version("GdkWin32", "4.0")
        from gi.repository import GdkWin32  # pylint: disable=import-outside-toplevel

        if (surface := window.get_surface()) is None:
            return None
        return GdkWin32.Win32Surface.get_handle(surface) or None
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not read the window handle: %s", error)
        return None
