# pipeline.py
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

import logging
import threading
from typing import Iterable

from gi.repository import GObject

from cartridges.game import Game
from cartridges.store.managers.manager import Manager


class Pipeline(GObject.Object):
    """Class representing a set of managers for a game.

    Thread safety: ``advance``/``manager_callback`` are reached both from the
    main thread (async manager callbacks) and from import worker threads
    (blocking managers run inline). Every mutation or read of the state sets is
    therefore guarded by an RLock — re-entrant because a blocking manager calls
    ``manager_callback`` (→ ``advance``) synchronously from within ``advance``.
    """

    game: Game
    additional_data: dict

    waiting: set[Manager]
    running: set[Manager]
    done: set[Manager]

    def __init__(
        self, game: Game, additional_data: dict, managers: Iterable[Manager]
    ) -> None:
        super().__init__()
        self.game = game
        self.additional_data = additional_data
        self.waiting = set(managers)
        self.running = set()
        self.done = set()
        self._lock = threading.RLock()

    @property
    def not_done(self) -> set[Manager]:
        """Get the managers that are not done yet"""
        with self._lock:
            return self.waiting | self.running

    @property
    def is_done(self) -> bool:
        with self._lock:
            return len(self.waiting) == 0 and len(self.running) == 0

    @property
    def blocked(self) -> set[Manager]:
        """Get the managers that cannot run because their dependencies aren't done"""
        with self._lock:
            not_done = self.waiting | self.running
            blocked = set()
            for waiting in self.waiting:
                for other in not_done:
                    if waiting == other:
                        continue
                    if type(other) in waiting.run_after:
                        blocked.add(waiting)
        return blocked

    @property
    def ready(self) -> set[Manager]:
        """Get the managers that can be run"""
        with self._lock:
            return self.waiting - self.blocked

    @property
    def progress(self) -> float:
        """Get the pipeline progress. Should only be a rough idea."""
        with self._lock:
            n_done = len(self.done)
            n_total = len(self.waiting) + len(self.running) + n_done
        try:
            progress = n_done / n_total
        except ZeroDivisionError:
            progress = 1
        return progress

    def advance(self) -> None:
        """Spawn tasks for managers that are able to run for a game"""

        # Claim the runnable managers under the lock so two threads advancing
        # concurrently can never schedule the same manager twice
        with self._lock:
            managers = self.ready
            blocking = set(filter(lambda manager: manager.blocking, managers))
            parallel = managers - blocking
            to_run = (*parallel, *blocking)
            for manager in to_run:
                self.waiting.remove(manager)
                self.running.add(manager)

        # Run outside the lock: blocking managers may take long (network) and
        # async callbacks from other threads must not be stalled meanwhile
        for manager in to_run:
            manager.process_game(self.game, self.additional_data, self.manager_callback)

    def manager_callback(self, manager: Manager) -> None:
        """Method called by a manager when it's done"""
        logging.debug("%s done for %s", manager.name, self.game.game_id)
        with self._lock:
            self.running.discard(manager)
            self.done.add(manager)
        self.emit("advanced")
        self.advance()

    @GObject.Signal(name="advanced")
    def advanced(self):  # type: ignore
        """Signal emitted when the pipeline has advanced"""
