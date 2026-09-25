# dialog_backdrop.py
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

"""Keep the dimmed area around a dialog from dragging the window.

libadwaita builds that area out of a `GtkWindowHandle` — the first child of the
private `AdwFloatingSheet` — so pressing it and moving the mouse moves the whole
window, the same as dragging a title bar. With a 480px dialog open in a window
filling the screen, that handle is nearly everything the user can see, so the
window follows almost any drag. Nothing else on Windows behaves that way: a
window is moved by its title bar and by nothing else.

The handle is private and is rebuilt whenever the dialog switches between
floating and bottom sheet, so its drag gesture cannot simply be removed once and
forgotten. Instead the dialog itself — which outlives every sheet it is shown in
— takes a click gesture in the capture phase, ahead of the handle's own gesture
in the bubble phase, and claims the press before a drag can start.

Only that one widget is claimed. Presses inside the dialog, its header bar
included, are left alone, so dragging the dialog's title bar still moves the
window as it should. So is the bottom sheet used in a narrow window, which dims
with a plain gizmo rather than a window handle and closes when tapped.
"""

from gi.repository import Adw, Gtk

_BLOCKED = "_cartridges_backdrop_drag_blocked"


def block_window_drag(dialog: Adw.Dialog) -> None:
    """Stop presses on the backdrop around `dialog` from moving the window."""
    # A dialog becomes the visible one again every time a dialog stacked on top
    # of it closes, and one gesture is enough.
    if getattr(dialog, _BLOCKED, False):
        return
    setattr(dialog, _BLOCKED, True)

    # Only the primary button, which is the one the handle drags with. What the
    # secondary button does there — the window's system menu — is libadwaita's
    # to decide and is not what makes the window wander.
    gesture = Gtk.GestureClick(propagation_phase=Gtk.PropagationPhase.CAPTURE)
    gesture.connect("pressed", _claim_backdrop_press)
    dialog.add_controller(gesture)


def _claim_backdrop_press(
    gesture: Gtk.GestureClick, _n_press: int, x: float, y: float
) -> None:
    """Claim the press when it landed on the backdrop, and only then.

    The backdrop is the one window handle in a dialog with nothing inside it:
    the handles wrapping a header bar all hold the bar's own box.
    """
    target = gesture.get_widget().pick(x, y, Gtk.PickFlags.DEFAULT)

    if isinstance(target, Gtk.WindowHandle) and target.get_child() is None:
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
