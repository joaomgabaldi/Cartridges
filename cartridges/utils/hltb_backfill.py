# hltb_backfill.py
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

"""Fill in HowLongToBeat times for games that are already in the library.

The import pipeline looks the times up for every game it adds, but it only ever
runs for *new* games: a game already in the store is dropped as a duplicate, and
the startup load from disk runs no online manager at all. So a library imported
before this feature existed — or one where a lookup failed on a bad network day
— would keep its empty rows forever, and the only cure was opening each game and
pressing the fetch button. That does not scale past a handful of games, which is
what this sweep is for.

It runs once per app launch, on a single worker thread, and is deliberately
unhurried: pacing comes from the same :class:`HLTBRateLimiter` the importer
uses, so a sweep of a large library trickles out in the background instead of
hammering a site that publishes no API. Nothing here is on the critical path —
every result is applied to its game as it lands, so quitting halfway keeps
whatever was already found.
"""

import logging
import threading
from typing import Optional

from gi.repository import GLib

from cartridges import shared
from cartridges.game import Game
from cartridges.store.managers.hltb_manager import shared_helper
from cartridges.utils.hltb import HLTBError, HLTBTimes, fetch_times, has_times

# Startup is busy (window, disk load, and usually an auto-import right after),
# and the auto-import's own HowLongToBeat lookups share this rate limiter. Wait
# a bit before adding to the queue, then keep waiting while an import runs.
_START_DELAY_SECONDS = 20
_IMPORT_RETRY_SECONDS = 30


class HLTBBackfill:
    """One background sweep over the library for missing completion times."""

    def __init__(self) -> None:
        # GLib source id of the pending start, so it can be cancelled on
        # shutdown and never armed twice.
        self._timeout_id: Optional[int] = None
        # A single sweep at a time. The guard is a lock rather than a plain flag
        # because `run_async` is reachable from the timer and (in future) from
        # the UI, and two sweeps would double every request.
        self._lock = threading.Lock()
        self._running = False
        # Set on shutdown. The worker checks it between games — an in-flight
        # request cannot be cancelled, so its result is simply dropped instead
        # of being written into games and widgets that are on their way out.
        self._stopped = False
        # Bumped by every stop. A worker carries the number it was started
        # with and quits when it changes: `start()` right after `stop()` (the
        # reset does exactly that) clears `_stopped`, and the old worker would
        # otherwise keep looking up a library that no longer exists.
        self._generation = 0

    # -- scheduling -----------------------------------------------------------

    def start(self) -> None:
        """Arm the one-shot sweep. Safe to call once at startup."""
        self._stopped = False
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
        self._timeout_id = GLib.timeout_add_seconds(
            _START_DELAY_SECONDS, self._on_timer
        )

    def stop(self) -> None:
        """Cancel a pending sweep and disown one already running."""
        self._stopped = True
        self._generation += 1
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def _on_timer(self) -> bool:
        self._timeout_id = None
        if self._stopped:
            return False

        # An import already fetches times for the games it adds, through the
        # same rate limiter. Sweeping alongside it would only make the import
        # the user is watching slower, so wait for it to finish.
        app = shared.win.get_application() if shared.win is not None else None
        if app is not None and app.state == shared.AppState.IMPORT:
            self._timeout_id = GLib.timeout_add_seconds(
                _IMPORT_RETRY_SECONDS, self._on_timer
            )
            return False

        self.run_async()
        return False

    # -- the sweep ------------------------------------------------------------

    def run_async(self) -> None:
        """Start one sweep off the main thread, unless one is already running."""
        if self._stopped or not shared.schema.get_boolean("hltb-metadata"):
            return

        # Snapshot on the main thread: the store's mappings are mutated by
        # imports, and iterating them from a worker would risk a "dictionary
        # changed size during iteration" mid-sweep.
        games = [
            game
            for game in shared.store
            if not game.removed
            and not game.blacklisted
            and not game.has_hltb_times
            and (game.name or "").strip()
        ]
        if not games:
            return

        with self._lock:
            if self._running:
                return
            self._running = True

        logging.info("HowLongToBeat backfill queued for %d games", len(games))
        threading.Thread(
            target=self._worker, args=(games, self._generation), daemon=True
        ).start()

    def _worker(self, games: list[Game], generation: int) -> None:
        found = 0
        try:
            for game in games:
                if self._stopped or generation != self._generation:
                    break
                # Re-checked per game, not just in the snapshot: the pipeline or
                # the details dialog may have filled this one in meanwhile, and
                # the setting may have been switched off mid-sweep.
                if game.removed or game.has_hltb_times:
                    continue
                if not shared.schema.get_boolean("hltb-metadata"):
                    break

                try:
                    times = fetch_times(shared_helper(), game.name, game.hltb_id)
                except HLTBError as error:
                    # A miss is the common case (plenty of games have no entry)
                    # and a network failure is not worth a dialog either: the
                    # next launch sweeps again.
                    logging.debug(
                        "HowLongToBeat backfill missed %s", game.name, exc_info=error
                    )
                    continue
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.warning(
                        "Unexpected error in HowLongToBeat backfill for %s",
                        game.name,
                        exc_info=True,
                    )
                    continue

                if not has_times(times):
                    continue
                found += 1
                GLib.idle_add(self._apply, game, times)
        finally:
            with self._lock:
                self._running = False
            logging.info(
                "HowLongToBeat backfill done: %d of %d games filled in",
                found,
                len(games),
            )

    # -- applying results (main thread) ---------------------------------------

    def _apply(self, game: Game, times: HLTBTimes) -> bool:
        """Write one game's times and repaint it. Runs on the main thread."""
        # `has_hltb_times` again, not just in the worker: the fetch button in
        # the details may have answered while this lookup was in flight, and
        # the sweep only ever fills what is missing — it must not overwrite a
        # correction the user just made.
        if self._stopped or game.removed or game.has_hltb_times:
            return False
        # Identidade no store, não só o snapshot: um reset apaga a biblioteca
        # e os arquivos enquanto o worker ainda anda pela lista dele, e o
        # `save()` abaixo regravaria o JSON de um jogo que o usuário acabou de
        # apagar — que então renascia na grade e no launch seguinte. O mesmo
        # idioma do `_in_library` do MetadataRefresh.
        store = getattr(shared, "store", None)
        if store is None or store.get(game.game_id) is not game:
            return False

        # update_values only carries the keys the lookup returned, so a game
        # with only a main-story estimate keeps whatever the other two held.
        game.update_values(dict(times))
        game.save()
        game.update()

        # The details page renders its times once, when it is shown; a game
        # filled in while the user is looking at it would otherwise keep the
        # empty row until they navigated away and back.
        win = shared.win
        if (
            win is not None
            and getattr(win, "active_game", None) is game
            and win.navigation_view.get_visible_page() == win.details_page
        ):
            win.update_hltb_block(game)
        return False
