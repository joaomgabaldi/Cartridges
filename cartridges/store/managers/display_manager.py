# display_manager.py
#
# Copyright 2023 Geoffrey Coulaud
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

import threading
from typing import Any, Callable

from gi.repository import GLib

from cartridges import shared
from cartridges.game import Game
from cartridges.game_cover import GameCover
from cartridges.store.managers.manager import Manager
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager


def is_main_thread() -> bool:
    """True on the thread running the GTK main loop.

    That is the interpreter's main thread: the application is constructed and
    ``run()`` there, and every worker is a `Gio.Task` pool thread or an explicit
    ``threading.Thread``. Asked at call time rather than captured at import, so
    it cannot be thrown off by which thread happened to import this module.
    """
    return threading.current_thread() is threading.main_thread()


class DisplayManager(Manager):
    """Manager in charge of adding a game to the UI"""

    run_after = (SteamAPIManager, SgdbManager)
    signals = {"update-ready"}

    def process_game(
        self, game: Game, additional_data: dict, callback: Callable[[Manager], Any]
    ) -> None:
        """Run the display update on the main thread, wherever we were called.

        This is the only manager whose ``main`` is pure GTK: it appends the game
        to a FlowBox, swaps menu models, invalidates the sort. A blocking
        manager runs inline on its caller's thread, and during an import that
        caller is a ``Gio.Task`` worker — so every one of those calls was being
        made off the main thread. GTK4 has no thread-safety story at all (there
        is no GDK lock to take any more), so this was not "usually fine": it was
        undefined behaviour that happened to survive most of the time.

        Marshalling instead of locking is the only correct option, since the
        toolkit itself must be entered from the one thread. The manager callback
        fires from inside the idle too, so the pipeline still only advances once
        the display work has actually happened — nothing downstream can observe
        a half-added game.
        """
        if is_main_thread():
            super().process_game(game, additional_data, callback)
            return

        GLib.idle_add(self._run_on_main, game, additional_data, callback)

    def _run_on_main(
        self, game: Game, additional_data: dict, callback: Callable[[Manager], Any]
    ) -> bool:
        super().process_game(game, additional_data, callback)
        return False  # one-shot

    def main(self, game: Game, _additional_data: dict) -> None:
        game.menu_button.set_menu_model(
            game.hidden_game_options if game.hidden else game.game_options
        )

        game.title.set_label(game.name)

        # Gold glow around the cover when a patch is waiting for this game,
        # mirroring the details-page update notice so the library hints at it
        # without the user having to open the game. Runs on every update-ready,
        # so dismissing the patch clears the glow on the next redraw.
        if game.has_update:
            game.cover_button.add_css_class("update-available")
        else:
            game.cover_button.remove_css_class("update-available")

        # Connect only once: main() runs on every game update, and reconnecting
        # here would pile up duplicate handlers on the same popover
        if not getattr(game, "popover_connected", False):
            game.popover_connected = True
            game.menu_button.get_popover().connect(
                "notify::visible", game.toggle_play, None
            )
            game.menu_button.get_popover().connect(
                "notify::visible", shared.win.set_active_game, game
            )

        if game.game_id in shared.win.game_covers:
            game.game_cover = shared.win.game_covers[game.game_id]
            game.game_cover.add_picture(game.cover)
        else:
            game.game_cover = GameCover({game.cover}, game.get_cover_path())
            shared.win.game_covers[game.game_id] = game.game_cover

        if (
            shared.win.navigation_view.get_visible_page() == shared.win.details_page
            and shared.win.active_game == game
        ):
            shared.win.show_details_page(game)

        # Which grid the game belongs in now (None = it shouldn't be shown)
        target = None
        if not game.removed and not game.blacklisted:
            target = shared.win.hidden_library if game.hidden else shared.win.library

        # The FlowBox the game currently lives in, if any
        flowbox_child = game.get_parent()
        current = flowbox_child.get_parent() if flowbox_child else None

        # Re-parenting the widget makes the ScrolledWindow lose the user's
        # scroll position (the grid jumps back to the top). On a plain edit the
        # game stays in the same grid, so only move it when it actually has to
        # move — being hidden/unhidden, removed, or added for the first time.
        if current is not target:
            if current is not None:
                current.remove(game)
                if game.get_parent():
                    game.get_parent().set_child()

            if target is not None:
                target.append(game)
                game.get_parent().set_focusable(False)

        # Coalescido: isto roda uma vez por jogo, e cada set_library_child
        # varre a store inteira — no import em massa dava O(n²). O idle roda
        # uma vez depois do lote, exatamente como o filter_func já faz.
        shared.win.schedule_library_child()

        # Keep the grid ordered when a single game is added or edited. During
        # bulk operations the sort is re-applied once at the end instead.
        if shared.win.get_application().state == shared.AppState.DEFAULT:
            shared.win.library.invalidate_sort()
            shared.win.hidden_library.invalidate_sort()
