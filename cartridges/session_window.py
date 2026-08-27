# session_window.py
#
# Copyright 2024 kramo
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

from time import monotonic
from typing import Any, Optional

from gi.repository import Adw, GLib, Gtk

from cartridges import shared
from cartridges.game import Game
from cartridges.utils import session_log


class SessionWindow(Adw.Window):
    """Small window shown while playing, used to clock a manual play session.

    We can't detect when the game itself exits (Steam/Epic/UWP just hand off to
    another process), so the user clicks "Já terminei de jogar." to end the
    session. Elapsed time is flushed into ``game.playtime`` every minute, so a
    crash, freeze or power loss only ever loses the last partial minute.
    """

    # Only one session is tracked at a time. This also keeps the window alive:
    # it is the app's only standalone top-level, so without a reference here it
    # could be garbage-collected out from under us.
    active: "Optional[SessionWindow]" = None

    def __init__(self, game: Game, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        SessionWindow.active = self
        self.game = game
        # Monotonic, not wall clock: this measures an interval, and `time()`
        # moves under NTP corrections, manual clock changes and resume-from-
        # sleep. A forward jump was credited to the game as playtime it never
        # had; a backward one was dropped by the `> 0` test in `flush`.
        self.session_start = monotonic()
        self.session_seconds = 0  # this session's running total, for the toast
        self.tick_id = 0

        # Unique title so the Win32 placement below can find our HWND
        self.set_title(_("Jogando {}").format(game.name))
        self.set_default_size(300, 150)
        self.set_resizable(False)

        button = Gtk.Button(label=_("Já terminei de jogar"))
        button.add_css_class("suggested-action")  # uses the Windows accent colour
        button.add_css_class("pill")
        button.set_halign(Gtk.Align.CENTER)
        button.set_valign(Gtk.Align.CENTER)
        button.set_vexpand(True)
        button.connect("clicked", lambda *_: self.close())

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(button)
        self.set_content(toolbar)

        self.connect("close-request", self.on_close)

        # Block the main window with a "session in progress" overlay so the user
        # can't start a second session from there while this one is running
        shared.win.show_session_blocker(game)

        # Save accumulated time every minute (crash/power-loss safety net)
        self.tick_id = GLib.timeout_add_seconds(60, self.tick)

        self.connect("map", lambda *_: GLib.idle_add(self.position_bottom_right))

    def flush(self) -> None:
        """Add elapsed time to the game's total and persist it."""
        now = monotonic()
        elapsed = int(now - self.session_start)
        if elapsed > 0:
            self.game.playtime += elapsed
            self.session_seconds += elapsed
            # Advance by the whole seconds actually banked, not to `now`: the
            # discarded remainder would otherwise be lost on every minute tick.
            self.session_start += elapsed  # makes flush idempotent if called again
            self.game.save()

    def tick(self) -> bool:
        self.flush()
        return GLib.SOURCE_CONTINUE

    def on_close(self, *_args: Any) -> bool:
        if self.tick_id:
            GLib.source_remove(self.tick_id)
            self.tick_id = 0

        if SessionWindow.active is self:
            SessionWindow.active = None

        shared.win.hide_session_blocker()

        self.flush()
        session_log.record(self.game.game_id, self.session_seconds)
        self.game.update()

        shared.win.session_toast(self.game, self.session_seconds)

        # Bring the main window back now that the session is over
        shared.win.present()
        return False

    def position_bottom_right(self) -> bool:
        """Place the window just above the clock (bottom-right work area).

        GTK4 has no cross-platform way to move a window, but this is a
        Windows-only fork, so use Win32 directly. Best-effort: any failure just
        leaves the window at its default position.
        """
        try:
            import ctypes  # pylint: disable=import-outside-toplevel
            from ctypes import wintypes  # pylint: disable=import-outside-toplevel

            user32 = ctypes.windll.user32  # type: ignore

            # Declare types so the 64-bit HWND isn't truncated to a 32-bit int
            user32.FindWindowW.restype = wintypes.HWND
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.GetWindowRect.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.RECT),
            ]
            user32.SetWindowPos.argtypes = [
                wintypes.HWND,
                wintypes.HWND,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]

            work = wintypes.RECT()
            user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(work), 0)  # WORKAREA

            hwnd = user32.FindWindowW(None, self.get_title())
            if not hwnd:
                return False

            rect = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top

            margin = 12
            x = work.right - width - margin
            y = work.bottom - height - margin

            # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE — no resize, keep z-order
            # (so it never steals focus or sits on top of the game)
            user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return False
