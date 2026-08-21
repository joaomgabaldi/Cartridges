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
"""

import ctypes
import logging
from ctypes import wintypes
from typing import NamedTuple, Optional

from gi.repository import Gtk

_MONITOR_DEFAULTTONULL = 0x00000000
# SWP_NOZORDER | SWP_NOACTIVATE: place it exactly, without raising or focusing
_PLACE = 0x0004 | 0x0010

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


def read(window: Gtk.Window) -> Optional[Geometry]:
    """The window's frame rectangle, or None if it can no longer be asked.

    For a maximized window this is the monitor's work area, which is not a size
    worth restoring but is exactly the position needed to reopen on the same
    screen, so callers keep the position and drop the size in that case.
    """
    if (hwnd := _hwnd(window)) is None:
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
