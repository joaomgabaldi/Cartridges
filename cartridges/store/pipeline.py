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
from typing import TYPE_CHECKING, Iterable

from PySide6.QtCore import QObject, Signal

from cartridges.store.managers.manager import Manager

if TYPE_CHECKING:
    from cartridges.jogo import Jogo


class Pipeline(QObject):
    """Conjunto de managers de um jogo.

    `advance`/`manager_callback` são chamados pela thread principal (managers assíncronos) e pelas threads da importação
    (managers bloqueantes, inline): todo acesso ao estado usa um RLock, reentrante porque um manager bloqueante chama
    `manager_callback` (→ `advance`) de dentro do `advance`.
    """

    advanced = Signal()

    game: "Jogo"
    additional_data: dict

    waiting: set[Manager]
    running: set[Manager]
    done: set[Manager]

    def __init__(
        self, game: "Jogo", additional_data: dict, managers: Iterable[Manager]
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
        with self._lock:
            return self.waiting | self.running

    @property
    def is_done(self) -> bool:
        with self._lock:
            return len(self.waiting) == 0 and len(self.running) == 0

    @property
    def blocked(self) -> set[Manager]:
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
        with self._lock:
            return self.waiting - self.blocked

    def advance(self) -> None:
        # Reserva os managers sob o lock: duas threads avançando não agendam o mesmo manager duas vezes.
        with self._lock:
            managers = self.ready
            blocking = set(filter(lambda manager: manager.blocking, managers))
            parallel = managers - blocking
            to_run = (*parallel, *blocking)
            for manager in to_run:
                self.waiting.remove(manager)
                self.running.add(manager)

        # Fora do lock: manager bloqueante pode demorar (rede) e callbacks assíncronos de outras threads não podem esperar.
        for manager in to_run:
            manager.process_game(self.game, self.additional_data, self.manager_callback)

    def manager_callback(self, manager: Manager) -> None:
        logging.debug("%s done for %s", manager.name, self.game.game_id)
        with self._lock:
            self.running.discard(manager)
            self.done.add(manager)
        self.advanced.emit()
        self.advance()
