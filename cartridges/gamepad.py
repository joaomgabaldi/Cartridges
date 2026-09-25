# gamepad.py
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

"""Xbox controller navigation, built on XInput.

The library grid is a :class:`Gtk.FlowBox` whose children are real buttons, so
the app is already fully keyboard-navigable. This module does not reimplement
any of that: it reads the pad and translates it into the widget calls GTK
already exposes (``child_focus`` to move, ``activate`` to press), which is why
it stays this small.

Only XInput devices are supported, i.e. Xbox controllers and the third-party
pads that present themselves as one. PlayStation and Switch controllers need a
translation layer (Steam Input, DS4Windows) to show up here, and that is a
deliberate scope choice rather than an oversight.

**The controller is only ever read while the main window has focus.** This is
not a filter over incoming events — the poll timer is destroyed outright when
focus is lost and recreated when it comes back. Without that, launching a game
(which minimises the window) would leave the pad steering the library in the
background, and a stray press could start a second launch. The same reasoning
rules out any "press B to end the session" shortcut: that would require reading
the pad precisely when another game owns it.

For the same reason, while a game's session is being tracked the integration is
suspended outright — polling stops and the XInput DLL is released — and brought
back only once the session ends. See :meth:`GamepadManager.suspend`.
"""

import ctypes
import logging
from ctypes import wintypes
from typing import Any, Optional

from gi.repository import Adw, GLib, Gtk

from cartridges import shared

# How often the pad is read while the window has focus. 30 Hz is well past the
# rate a person can navigate a grid at, and halves the wakeups of a 60 Hz loop.
POLL_INTERVAL_MS = 33
# XInput is slow to answer for an empty slot (a documented quirk, roughly a
# millisecond per unused slot), so unplugged slots are only scanned occasionally
# instead of on every tick.
SCAN_INTERVAL_US = 2_000_000

# Key-repeat feel for a held direction: a pause before it starts running, then
# a steady rate. Tuned by hand — expect to adjust these two with a pad in hand.
REPEAT_DELAY_US = 400_000
REPEAT_INTERVAL_US = 120_000

# Stick thresholds. The release value sits below the press value on purpose:
# with a single threshold, a stick resting near the edge flickers across it and
# the selection stutters. Requiring a return past the lower value to re-arm is
# what makes a held direction read as one continuous push.
THUMB_PRESS = 16_000
THUMB_RELEASE = 10_000

# A dormant pad also wakes on the stick alone, but only on a near-full push:
# half of the 0–32767 range on either axis. Connect-time drift sits far below
# this, so it still cannot wake anything, while someone who navigates by stick
# and never touches a button is not made to reach for one first. Set this high
# on purpose — the stick is pushed all the way or not at all, so there is no
# gentle nudge here to miss.
THUMB_WAKE = 16_384

# Length of a scroll between rows, matching the feel of the viewport's own
# scroll-to-focus that this module takes over from
SCROLL_DURATION_MS = 200

# Rumble presets, as (left motor, right motor, milliseconds). The two motors
# are not interchangeable: the left one is the heavy low-frequency weight and
# reads as a thud, the right one is light and high-frequency and reads as a
# click. Hence the tick on the right and the wall on the left.
RUMBLE_MOVE = (0.0, 0.14, 12)  # per card crossed, deliberately barely there
# Nowhere further to go. Leans on the heavy motor with a little of the light
# one for definition, so it lands as a firm stop rather than a vague hum — it
# is now the only feedback for hitting the end, the system beep having been
# silenced for pad navigation.
RUMBLE_EDGE = (0.6, 0.2, 70)
# Both motors, near full, and long enough to read as a send-off rather than a
# tick. This one is allowed to be the loudest thing the pad does: it fires once,
# it confirms an action that takes over the whole screen, and it is the last
# thing the app says before the window minimises and gets out of the way.
RUMBLE_LAUNCH = (0.85, 0.85, 400)

# XInput button masks
XINPUT_DPAD_UP = 0x0001
XINPUT_DPAD_DOWN = 0x0002
XINPUT_DPAD_LEFT = 0x0004
XINPUT_DPAD_RIGHT = 0x0008
XINPUT_START = 0x0010
XINPUT_BACK = 0x0020
XINPUT_LEFT_SHOULDER = 0x0100
XINPUT_RIGHT_SHOULDER = 0x0200
XINPUT_A = 0x1000
XINPUT_B = 0x2000
XINPUT_X = 0x4000
XINPUT_Y = 0x8000

ERROR_SUCCESS = 0

MAX_SLOTS = 4


class XInputGamepad(ctypes.Structure):
    """``XINPUT_GAMEPAD``"""

    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XInputState(ctypes.Structure):
    """``XINPUT_STATE``"""

    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XInputGamepad)]


class XInputVibration(ctypes.Structure):
    """``XINPUT_VIBRATION``"""

    _fields_ = [
        ("wLeftMotorSpeed", wintypes.WORD),
        ("wRightMotorSpeed", wintypes.WORD),
    ]


def _load_xinput() -> Any:
    """Return the newest XInput DLL present, or None on failure.

    1.4 ships with Windows 8 and later; the older names are only reached on
    systems where it is missing. Any failure disables the feature silently —
    a missing DLL must never stop the app from starting.
    """
    for name in ("xinput1_4.dll", "xinput1_3.dll", "xinput9_1_0.dll"):
        try:
            library = ctypes.WinDLL(name)  # type: ignore[attr-defined]
            # Looking the exports up has to happen inside the try as well. A
            # DLL can load perfectly and still not export what we need — the
            # xinput stubs and wrapper DLLs people drop next to games (and
            # Wine/Proton's own builds) are the common case, and a missing
            # XInputSetState raises AttributeError here rather than at load.
            # Outside the try that escaped through GamepadManager.__init__ into
            # do_activate, where PyGObject swallows it at the vfunc boundary:
            # the process survived, but everything scheduled after the gamepad
            # manager — the update and news checkers included — never ran, for
            # a feature that is meant to fail silently.
            library.XInputGetState.argtypes = [
                wintypes.DWORD,
                ctypes.POINTER(XInputState),
            ]
            library.XInputGetState.restype = wintypes.DWORD
            library.XInputSetState.argtypes = [
                wintypes.DWORD,
                ctypes.POINTER(XInputVibration),
            ]
            library.XInputSetState.restype = wintypes.DWORD
        except (OSError, AttributeError):
            # OSError: DLL absent. AttributeError: not Windows at all, where
            # ctypes has no WinDLL — the feature simply does not exist there —
            # or a DLL that loads without the entry points we need. Either way,
            # move on to the next candidate name.
            continue
        logging.debug("Gamepad support using %s", name)
        return library

    logging.debug("No XInput DLL found; gamepad support unavailable")
    return None


class GamepadManager:
    """Polls an Xbox controller and drives the window's focus with it.

    Attach one to the main window with :meth:`attach`. It manages its own
    lifetime from there: the timer only exists while the window has focus and
    the setting is on.
    """

    # The manager in charge, so code outside this module (Game.launch) can ask
    # for a rumble without having to be handed a reference. Mirrors how
    # SessionWindow and ProcessSession expose their current instance.
    active: "Optional[GamepadManager]" = None

    def __init__(self) -> None:
        self.xinput = _load_xinput()
        self.window: Optional[Gtk.Window] = None

        self._poll_id = 0
        self._slot: Optional[int] = None  # connected controller, if any
        self._last_scan = 0

        # While a game's session is being tracked the pad belongs entirely to
        # the game, so the whole integration is torn down: polling stops and the
        # XInput DLL is handed back (``self.xinput`` dropped to None). This flag
        # keeps ``_sync`` from resurrecting the poll timer on a focus or setting
        # change in the meantime. Cleared when the session ends and the DLL is
        # reloaded. See :meth:`suspend` / :meth:`resume`.
        self._suspended = False
        self._release_id = 0  # pending deferred DLL release, if any

        # Previous button bitmask, for edge detection. ``_resync`` makes the
        # next read adopt whatever it finds as the new baseline without acting
        # on it: a button held down while focus was elsewhere (say, A pressed
        # inside a game) would otherwise surface as a fresh press the moment
        # the window came back, and launch something.
        self._buttons = 0
        self._resync = True

        # The analog stick does nothing until the pad has been woken. A
        # controller can report a slightly off-centre stick the instant it
        # connects, and that drift would otherwise read as a held direction and
        # start driving the selection — buzzing on every wall it hits — with
        # nobody touching it. Re-armed alongside ``_resync`` (on connect and on
        # focus return), so a fresh pad or a returning window both start
        # dormant. Any button or d-pad press wakes it, as does a near-full stick
        # push (see THUMB_WAKE); only sub-threshold drift is ignored.
        self._engaged = False

        self._direction: Optional[Gtk.DirectionType] = None
        self._direction_since = 0
        self._repeats = 0

        # A direction found already held by a resync is the baseline, not a
        # press: latched here so the repeat clock ignores it until it is let go
        # of. Buttons get this for free through edge detection, directions do
        # not — see the resync branch in :meth:`_poll`.
        self._direction_latched = False

        # Handler id for the settings signal, kept so it can be disconnected.
        # ``shared.schema`` outlives every window, so a connection left behind
        # keeps this manager (and through ``self.window`` the whole widget
        # tree) alive after shutdown, and hands a torn-down manager a _sync()
        # the next time the setting is toggled.
        self._schema_handler_id = 0

        # The in-flight scroll. Held so it is not collected mid-animation, and
        # so the next move can cut it short instead of queueing behind it.
        self._scroll: Optional[Adw.TimedAnimation] = None

        # Bumped per rumble so a finished one's stop timer cannot silence the
        # rumble that replaced it
        self._rumble_generation = 0

    # Lifetime ---------------------------------------------------------------

    def attach(self, window: Gtk.Window) -> None:
        """Start managing the poll timer for ``window``."""
        if self.xinput is None:
            return

        GamepadManager.active = self
        self.window = window
        window.connect("notify::is-active", lambda *_: self._sync())
        self._schema_handler_id = shared.schema.connect(
            "changed::gamepad", lambda *_: self._sync()
        )
        self._sync()

    def _sync(self) -> None:
        """Create or destroy the poll timer to match the current state."""
        wanted = (
            self.window is not None
            and self.window.is_active()
            and shared.schema.get_boolean("gamepad")
            # A tracked session owns the pad; stay down until it releases us. The
            # DLL check also guards the window between release and reload, where
            # a running poll would call into a library that is no longer there.
            and not self._suspended
            and self.xinput is not None
        )

        if wanted and not self._poll_id:
            # Anything held while we were not looking is part of the baseline,
            # not a press we owe the user a reaction to
            self._resync = True
            # ...and the stick sleeps again until the window is deliberately
            # driven with a button, so a drifting pad cannot steer the grid the
            # moment focus returns.
            self._engaged = False
            self._poll_id = GLib.timeout_add(POLL_INTERVAL_MS, self._poll)
        elif not wanted and self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = 0
            self._direction = None
            # Deliberately not stopping the motors here. Every rumble we start
            # carries its own stop timer, and that timer keeps running after
            # the window loses focus — which is exactly what the launch pulse
            # depends on, since launching minimises the window a few
            # milliseconds after the buzz begins. Cutting rumble off on focus
            # loss would silence the one buzz that matters most.

    def detach(self) -> None:
        """Stop polling for good."""
        # The window's own "notify::is-active" dies with the window, but the
        # settings object is a process-lifetime global: what it holds, it holds
        # forever. Dropping this is what actually lets the manager go.
        if self._schema_handler_id:
            shared.schema.disconnect(self._schema_handler_id)
            self._schema_handler_id = 0
        if self._release_id:
            GLib.source_remove(self._release_id)
            self._release_id = 0
        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = 0
        self.rumble()
        self.window = None
        if GamepadManager.active is self:
            GamepadManager.active = None

    def suspend(self) -> None:
        """Hand the pad entirely to a game whose session is being tracked.

        Called when the "session in progress" blocker goes up. Polling stops at
        once, so the app makes no XInput calls while a game owns the device, and
        the DLL itself is released a beat later — long enough for the launch
        buzz that fires just before this to finish and zero its own motors.
        Releasing before that could strand the motors running, since the buzz's
        stop timer would find no library to talk to. :meth:`resume` reverses it.
        """
        if self._suspended:
            return
        self._suspended = True

        if self._poll_id:
            GLib.source_remove(self._poll_id)
            self._poll_id = 0
        self._direction = None

        # Let any in-flight rumble (the launch send-off) run its course, then
        # drop the DLL. RUMBLE_LAUNCH is the longest buzz, so its duration plus
        # a small margin is enough to know the motors are back to rest.
        if self._release_id:
            GLib.source_remove(self._release_id)
        self._release_id = GLib.timeout_add(RUMBLE_LAUNCH[2] + 60, self._release)

    def _release(self) -> bool:
        """Silence the motors and unload the XInput DLL, if still suspended."""
        self._release_id = 0
        if not self._suspended:
            # Resumed inside the grace window; keep the loaded DLL as-is.
            return GLib.SOURCE_REMOVE
        self.rumble()  # final guarantee the motors are at rest before we let go
        self._slot = None  # forget the slot; resume rescans from scratch
        self.xinput = None  # ctypes frees the library once nothing references it
        logging.debug("Gamepad DLL released for the duration of the session")
        return GLib.SOURCE_REMOVE

    def resume(self) -> None:
        """Bring the integration back after a tracked session ends."""
        if not self._suspended:
            return
        self._suspended = False

        if self._release_id:
            GLib.source_remove(self._release_id)
            self._release_id = 0

        if self.xinput is None:
            self.xinput = _load_xinput()

        # Whatever the pad did while a game held it is not ours to react to
        self._resync = True
        self._engaged = False
        self._sync()

    # Reading ----------------------------------------------------------------

    def _read(self) -> Optional[XInputGamepad]:
        """Return the connected pad's state, or None if there isn't one."""
        state = XInputState()

        if self._slot is not None:
            result = self.xinput.XInputGetState(self._slot, ctypes.byref(state))
            if result == ERROR_SUCCESS:
                return state.Gamepad
            # Unplugged mid-session: fall through and rescan on the usual delay
            self._slot = None

        now = GLib.get_monotonic_time()
        if now - self._last_scan < SCAN_INTERVAL_US:
            return None
        self._last_scan = now

        for slot in range(MAX_SLOTS):
            if self.xinput.XInputGetState(slot, ctypes.byref(state)) == ERROR_SUCCESS:
                self._slot = slot
                # A pad that just appeared may already have buttons held, and
                # its stick may already be reporting drift — stay dormant until
                # a button wakes it.
                self._resync = True
                self._engaged = False
                logging.debug("Gamepad connected in slot %s", slot)
                return state.Gamepad

        return None

    def _poll(self) -> bool:
        pad = self._read()
        if pad is None:
            self._direction = None
            return GLib.SOURCE_CONTINUE

        # A play session in progress blocks the UI behind an overlay. That
        # overlay stops clicks, but not focus traversal, so the guard has to be
        # here too: restoring the window mid-session (the process tracker does
        # not open one of its own) would otherwise leave the grid navigable
        # underneath it. State is still read, so the baseline stays current and
        # the session ending does not release a burst of stale presses.
        if self._blocked():
            self._buttons = pad.wButtons
            self._direction = None
            return GLib.SOURCE_CONTINUE

        if self._resync:
            self._resync = False
            self._buttons = pad.wButtons
            self._direction = self._read_direction(pad)
            # Adopting the direction as the baseline is not enough on its own:
            # unlike the buttons, a held direction needs no fresh edge to act —
            # the repeat branch only asks that one is held and old enough. So
            # holding the d-pad inside a fullscreen game and alt-tabbing back
            # had the grid start scrolling by itself 400ms later, at ~8Hz, with
            # nobody touching anything. Latch it instead: whatever is already
            # held at this instant counts as consumed and stays inert until it
            # is released or swapped for another direction.
            self._direction_latched = self._direction is not None
            self._direction_since = GLib.get_monotonic_time()
            self._repeats = 0
            self._show_selection()
            return GLib.SOURCE_CONTINUE

        self._handle_direction(pad)
        self._handle_buttons(pad)
        return GLib.SOURCE_CONTINUE

    def _show_selection(self) -> None:
        """Light up the selection as soon as a controller is there to use it.

        GTK holds the focus ring back until it decides the user is navigating
        by keyboard, so on startup the first game is focused but draws no
        border — the selection existed and was invisible until the first press
        moved it. A pad being present is enough intent to show it.

        Focus is only pulled to a game when it is not already on one, and never
        out of an open search box: the pad appearing should not interrupt
        someone in the middle of typing.
        """
        window = self.window
        if window is None:
            return

        window.set_focus_visible(True)

        # A menu or dialog is already holding the focus for a reason
        if self._focus_scope() is not window:
            return

        library = self._visible_library()
        if library is None:
            return

        # A página de zerados não tem busca: só a da biblioteca prende o foco.
        if library is shared.win.library and shared.win.search_bar.get_search_mode():
            return

        if self._focused_flowbox_child(library) is None:
            self._focus_first()

    @staticmethod
    def _blocked() -> bool:
        """True while a play session owns the app."""
        # avoid import cycles
        from cartridges.process_session import ProcessSession
        from cartridges.session_window import SessionWindow

        return SessionWindow.active is not None or ProcessSession.active is not None

    # Direction --------------------------------------------------------------

    def _read_direction(self, pad: XInputGamepad) -> Optional[Gtk.DirectionType]:
        """Collapse the d-pad and left stick into one direction, or None.

        The d-pad wins when both are pushed, and the stick resolves to whichever
        axis is dominant so a diagonal picks a lane instead of firing twice.
        """
        buttons = pad.wButtons
        if buttons & XINPUT_DPAD_UP:
            return Gtk.DirectionType.UP
        if buttons & XINPUT_DPAD_DOWN:
            return Gtk.DirectionType.DOWN
        if buttons & XINPUT_DPAD_LEFT:
            return Gtk.DirectionType.LEFT
        if buttons & XINPUT_DPAD_RIGHT:
            return Gtk.DirectionType.RIGHT

        # The stick is muted until the pad is engaged. Connect-time drift lands
        # here, not on the d-pad above, so gating only this half kills the
        # spurious selection-drift and its wall-banging rumble while leaving the
        # d-pad free to be the very press that wakes the pad. A deliberate,
        # near-full push wakes it too — drift never reaches THUMB_WAKE — so a
        # stick-only user is not stuck reaching for a button first.
        if not self._engaged:
            if abs(pad.sThumbLX) >= THUMB_WAKE or abs(pad.sThumbLY) >= THUMB_WAKE:
                self._engaged = True
            else:
                return None

        # Lower bar to keep an already-held direction than to start one
        threshold = THUMB_RELEASE if self._direction is not None else THUMB_PRESS
        x, y = pad.sThumbLX, pad.sThumbLY

        if abs(x) > abs(y):
            if x > threshold:
                return Gtk.DirectionType.RIGHT
            if x < -threshold:
                return Gtk.DirectionType.LEFT
        else:
            if y > threshold:
                return Gtk.DirectionType.UP
            if y < -threshold:
                return Gtk.DirectionType.DOWN

        return None

    def _handle_direction(self, pad: XInputGamepad) -> None:
        direction = self._read_direction(pad)
        now = GLib.get_monotonic_time()

        if direction != self._direction:
            self._direction = direction
            self._direction_since = now
            self._repeats = 0
            # The direction changed, so whatever was held across the resync is
            # over: either it was released (direction is None now) or it was
            # traded for a different one. Both are real input, and a direction
            # pressed after the resync moves at once, as it always did.
            self._direction_latched = False
            if direction is not None:
                self._move(direction)
            return

        if direction is None:
            return

        # Still the very direction that was already held when the window got
        # focus back. It has never been released, so there is no press here to
        # repeat — only a hand that never moved.
        if self._direction_latched:
            return

        # First repeat waits out the delay, the rest come at a steady interval
        due = REPEAT_DELAY_US + REPEAT_INTERVAL_US * self._repeats
        if now - self._direction_since >= due:
            self._repeats += 1
            self._move(direction)

    def _move(self, direction: Gtk.DirectionType) -> None:
        window = self.window
        if window is None:
            return

        # GTK only paints focus rings once it believes the user is navigating by
        # keyboard. Without this the selection moves invisibly.
        window.set_focus_visible(True)

        if window.get_focus() is None:
            self._focus_first()
            return

        scope = self._focus_scope()
        self._focus_and_scroll(lambda: scope.child_focus(direction))

    def _focus_scope(self) -> Gtk.Widget:
        """The widget the focus should be allowed to move within.

        Normally the window, but an open menu or dialog becomes its own scope.
        Both live inside the window's widget tree rather than in a separate
        toplevel, so asking the *window* to move focus would happily walk into
        the library sitting behind them — the selection would crawl around
        under the dialog while the user watched nothing happen.
        """
        window = self.window
        if window is None:
            return window  # type: ignore[return-value]

        widget = window.get_focus()
        while widget is not None:
            if isinstance(widget, (Gtk.Popover, Adw.Dialog)):
                return widget
            widget = widget.get_parent()

        return window

    def _focus_and_scroll(self, move_focus: Any) -> None:
        """Move the focus, then scroll to it ourselves.

        The viewport's own scroll-to-focus is switched off for the duration of
        the move. It only ever scrolls far enough to bring the focused card
        into view, which stops short of the grid's 15px top margin and left a
        sliver of the second row showing above the first. Correcting that
        afterwards meant overwriting the adjustment mid-animation, which is
        what killed the smooth scroll — so instead this takes the whole job,
        margin included, and animates it in one motion.

        Only this module's moves are affected: the flag goes straight back on,
        and it is read when the focus changes, so mouse and keyboard users keep
        the stock behaviour.
        """
        viewport = self._visible_viewport()

        # Failing to move focus makes GTK ring the error bell, which GDK turns
        # into MessageBeep on Windows — the Asterisk sound, once per nudge
        # against the end of the list. The rumble says the same thing without
        # the noise, so the bell is muted for the duration of our move only.
        # Keyboard and mouse users still get it: the setting is read at the
        # moment focus fails, and it is back on by then.
        settings = Gtk.Settings.get_default()
        bell = settings.get_property("gtk-error-bell") if settings else None

        if viewport is not None:
            viewport.set_scroll_to_focus(False)
        if settings is not None:
            settings.set_property("gtk-error-bell", False)

        moved = move_focus()

        if settings is not None:
            settings.set_property("gtk-error-bell", bell)
        if viewport is not None:
            viewport.set_scroll_to_focus(True)

        # child_focus answers False when nothing in that direction could take
        # the focus, which is the only honest signal that we are against a wall
        self._rumble(RUMBLE_MOVE if moved else RUMBLE_EDGE)

        self._sync_active_game()
        self._scroll_to_focus()

    @staticmethod
    def _visible_viewport() -> Optional[Gtk.Viewport]:
        """The viewport wrapping the grid currently on screen."""
        library = GamepadManager._visible_library()
        if library is None:
            return None
        parent = library.get_parent()
        return parent if isinstance(parent, Gtk.Viewport) else None

    def _scroll_to_focus(self) -> None:
        """Animate the grid to wherever the focused card needs it."""
        library = self._visible_library()
        viewport = self._visible_viewport()
        if library is None or viewport is None:
            return

        window = shared.win
        scrolled = (
            window.zerados_scrolledwindow
            if library is window.zerados_library
            else window.scrolledwindow
        )

        child = self._focused_flowbox_child(library)
        if child is None:
            return

        # Two frames of reference: position within the grid decides whether
        # this is an edge row, position within the viewport says how far off
        # screen the card currently is.
        in_grid, grid = child.compute_bounds(library)
        in_view, view = child.compute_bounds(viewport)
        if not in_grid or not in_view:
            return

        adjustment = scrolled.get_vadjustment()
        value = adjustment.get_value()
        page = adjustment.get_page_size()
        lower = adjustment.get_lower()
        upper = adjustment.get_upper()

        if grid.origin.y <= 1:
            # First row: all the way up, so the grid's own margin comes back
            target = lower
        elif grid.origin.y + grid.size.height >= library.get_height() - 1:
            target = upper - page
        elif view.origin.y < 0:
            target = value + view.origin.y
        elif view.origin.y + view.size.height > page:
            target = value + view.origin.y + view.size.height - page
        else:
            return  # already fully visible

        target = min(max(target, lower), max(lower, upper - page))
        if abs(target - value) < 1:
            return

        if self._scroll is not None:
            # Held direction: start from wherever the last one got to rather
            # than letting two animations drive the same value
            self._scroll.pause()

        self._scroll = Adw.TimedAnimation.new(
            scrolled,
            value,
            target,
            SCROLL_DURATION_MS,
            Adw.PropertyAnimationTarget.new(adjustment, "value"),
        )
        self._scroll.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        self._scroll.play()

    @staticmethod
    def _focused_flowbox_child(library: Gtk.FlowBox) -> Optional[Gtk.FlowBoxChild]:
        """The grid cell the focus currently sits inside, if any."""
        widget = shared.win.get_focus()
        while widget is not None and widget is not library:
            if isinstance(widget, Gtk.FlowBoxChild):
                return widget
            widget = widget.get_parent()
        return None

    @staticmethod
    def _first_shown_child(library: Gtk.FlowBox) -> Optional[Gtk.FlowBoxChild]:
        """The first cell of ``library`` that its filter actually shows.

        ``get_child_at_index`` answers by raw index and knows nothing about the
        ``filter_func`` the window installs on both grids, so while a search is
        running index 0 is almost always a card the filter has hidden. Focusing
        a hidden child does nothing — ``child_focus`` returns False — and the
        press reads as the app ignoring the pad. Re-testing each candidate is
        the same thing ``CartridgesWindow.show_details_page_search`` does to
        find what the Enter key should open.
        """
        index = 0
        while child := library.get_child_at_index(index):
            if shared.win.filter_func(child):
                return child
            index += 1
        return None

    def _focus_first(self) -> None:
        """Put focus on the first game when nothing is focused yet."""
        window = self.window
        if window is None:
            return

        library = self._visible_library()
        if library is not None and (child := self._first_shown_child(library)):
            self._focus_and_scroll(
                lambda: child.child_focus(Gtk.DirectionType.TAB_FORWARD)
            )
            return

        window.child_focus(Gtk.DirectionType.TAB_FORWARD)

    @staticmethod
    def _visible_library() -> Optional[Gtk.FlowBox]:
        """The grid on the page currently being shown, if it is a library."""
        window = shared.win
        page = window.navigation_view.get_visible_page()
        if page == window.library_page:
            return window.library
        if page == window.zerados_library_page:
            return window.zerados_library
        return None

    # Buttons ----------------------------------------------------------------

    def _handle_buttons(self, pad: XInputGamepad) -> None:
        buttons = pad.wButtons
        pressed = buttons & ~self._buttons  # rising edges only
        self._buttons = buttons

        if not pressed:
            return

        # Any deliberate press — a face button, a shoulder, or the d-pad —
        # wakes the stick for the rest of this focus session. This runs after
        # _handle_direction in the same poll, so a d-pad press still moves on
        # the tick that engages, and a face button acts on its first press
        # rather than being swallowed as a mere unlock.
        self._engaged = True

        if pressed & XINPUT_A:
            self._activate()
        elif pressed & XINPUT_B:
            self._back()
        elif pressed & XINPUT_START:
            self._open_primary_menu()
        elif pressed & XINPUT_Y:
            self._open_game_menu()
        elif pressed & XINPUT_BACK:
            shared.win.on_toggle_search_action()

    def _activate(self) -> None:
        """Press whatever is focused, exactly as a click or Enter would.

        Going through the focused widget rather than calling ``launch()``
        directly is what keeps the pad honest: on a cover this runs the same
        handler a mouse click does, so the "cover starts the game" preference
        keeps working without this module knowing the setting exists.
        """
        window = self.window
        if window is None:
            return

        window.set_focus_visible(True)

        focus = window.get_focus()
        if focus is None:
            self._focus_first()
            return

        self._sync_active_game()

        # Buttons are emitted directly rather than going through
        # Gtk.Widget.activate(), which GTK deprecated in 4.10. Everything the
        # grid and the details page put in the focus chain is a button; the
        # fallback covers rows and entries in the dialogs.
        if isinstance(focus, Gtk.Button):
            focus.emit("clicked")
        else:
            focus.activate()

    def _open_primary_menu(self) -> None:
        """Open the header menu, from which Preferences and the rest hang.

        Reusing the window's own action means the pad opens exactly what F10
        does, and once the popover is up ``_focus_scope`` keeps the d-pad
        inside it.
        """
        window = shared.win
        window.set_focus_visible(True)
        window.on_open_menu_action()

    def _open_game_menu(self) -> None:
        """Open the focused game's own ⋯ menu.

        That button normally only exists while the pointer is over the card —
        it lives in a revealer driven by hover — so it has to be revealed
        before it can be popped up, and hidden again afterwards or the card
        would keep wearing its buttons once the menu closed.
        """
        library = self._visible_library()
        if library is None:
            return

        child = self._focused_flowbox_child(library)
        if child is None:
            return

        game = child.get_child()
        if game is None or game.zerado:
            return

        game.play_revealer.set_reveal_child(True)
        game.menu_revealer.set_reveal_child(True)

        def hide_when_closed(button: Gtk.MenuButton, *_args: Any) -> None:
            if button.get_active():
                return
            game.play_revealer.set_reveal_child(False)
            game.menu_revealer.set_reveal_child(False)
            button.disconnect_by_func(hide_when_closed)

        game.menu_button.connect("notify::active", hide_when_closed)
        game.menu_button.popup()

    def _back(self) -> None:
        """Close whatever is on top: menu, dialog, search, then the page."""
        scope = self._focus_scope()

        if isinstance(scope, Gtk.Popover):
            scope.popdown()
            return

        if isinstance(scope, Adw.Dialog):
            scope.close()
            return

        window = shared.win
        page = window.navigation_view.get_visible_page()

        search_bar = None
        if page == window.library_page:
            search_bar = window.search_bar

        if search_bar is not None and search_bar.get_search_mode():
            search_bar.set_search_mode(False)
            return

        if page != window.library_page:
            window.navigation_view.pop()

    def _sync_active_game(self) -> None:
        """Point ``active_game`` at whatever the focus is sitting on.

        The menu actions all operate on ``shared.win.active_game``, which was
        only ever set by a click or by opening the details page. Moving focus
        with a pad has to keep it in step, or those actions would act on the
        last game the mouse touched.
        """
        # avoid import cycles
        from cartridges.game import Game

        window = self.window
        if window is None:
            return

        widget = window.get_focus()
        while widget is not None:
            if isinstance(widget, Game):
                shared.win.active_game = widget
                return
            widget = widget.get_parent()

    # Vibration --------------------------------------------------------------

    def _rumble(self, preset: tuple) -> None:
        """Play one of the presets, if the user wants rumble at all."""
        if not shared.schema.get_boolean("gamepad-rumble"):
            return
        self.rumble(*preset)

    @classmethod
    def rumble_launch(cls) -> None:
        """Buzz for a starting game. Safe to call with no pad and no manager."""
        if cls.active is not None:
            cls.active._rumble(RUMBLE_LAUNCH)  # pylint: disable=protected-access

    def rumble(self, left: float = 0.0, right: float = 0.0, duration_ms: int = 0) -> None:
        """Run the pad's motors, both taken as 0.0–1.0.

        ``duration_ms`` schedules the stop; pass 0 (the default) to stop the
        motors immediately, which is what makes a bare ``rumble()`` the "shut
        up" call used when focus is lost.
        """
        if self.xinput is None or self._slot is None:
            return

        vibration = XInputVibration(
            wLeftMotorSpeed=int(max(0.0, min(1.0, left)) * 65535),
            wRightMotorSpeed=int(max(0.0, min(1.0, right)) * 65535),
        )
        self.xinput.XInputSetState(self._slot, ctypes.byref(vibration))

        self._rumble_generation += 1

        if duration_ms > 0:
            generation = self._rumble_generation

            def stop() -> bool:
                # A newer rumble has taken over; its own timer owns the stop.
                # Without this, the 12ms tick of one card could silence the
                # 180ms launch pulse that started right after it.
                if generation == self._rumble_generation:
                    self.rumble()
                return GLib.SOURCE_REMOVE

            GLib.timeout_add(duration_ms, stop)
