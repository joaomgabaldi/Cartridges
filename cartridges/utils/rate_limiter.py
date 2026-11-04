# rate_limiter.py
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

from collections import deque
from contextlib import AbstractContextManager
from threading import BoundedSemaphore, Lock, Thread
from time import sleep, time
from typing import Any, Sized


class PickHistory(Sized):
    """Conta quantas retiradas houve num período."""

    period: int

    timestamps: list[float]
    timestamps_lock: Lock

    def __init__(self, period: int) -> None:
        self.period = period
        self.timestamps = []
        self.timestamps_lock = Lock()

    def remove_old_entries(self) -> None:
        now = time()
        cutoff = now - self.period
        with self.timestamps_lock:
            self.timestamps = [entry for entry in self.timestamps if entry > cutoff]

    def add(self, *new_timestamps: float) -> None:
        """Sem argumentos, adiciona o instante atual."""
        if len(new_timestamps) == 0:
            new_timestamps = (time(),)
        with self.timestamps_lock:
            self.timestamps.extend(new_timestamps)

    def __len__(self) -> int:
        self.remove_old_entries()
        with self.timestamps_lock:
            return len(self.timestamps)

    @property
    def start(self) -> float:
        self.remove_old_entries()
        with self.timestamps_lock:
            try:
                entry = self.timestamps[0]
            except IndexError:
                entry = time()
        return entry

    def copy_timestamps(self) -> list[float]:
        self.remove_old_entries()
        with self.timestamps_lock:
            return self.timestamps.copy()


# pylint: disable=too-many-instance-attributes
class RateLimiter(AbstractContextManager):
    """Limitador por balde de tokens; não se usa direto. As subclasses definem:

    * refill_period_seconds: o período em que vale o máximo de tokens
    * refill_period_tokens: quantos tokens o período permite
    * burst_tokens: quantos podem ser consumidos de uma vez
    """

    refill_period_seconds: int
    refill_period_tokens: int
    burst_tokens: int

    pick_history: PickHistory
    bucket: BoundedSemaphore
    queue: deque[Lock]
    queue_lock: Lock

    __n_tokens_lock: Lock
    __n_tokens = 0

    @property
    def n_tokens(self) -> int:
        with self.__n_tokens_lock:
            return self.__n_tokens

    @n_tokens.setter
    def n_tokens(self, value: int) -> None:
        with self.__n_tokens_lock:
            self.__n_tokens = value

    def _init_pick_history(self) -> None:
        """Cria o histórico vazio; as subclasses o sobrescrevem ou estendem."""
        self.pick_history = PickHistory(self.refill_period_seconds)

    def seed_history(self) -> int:
        """Cobra do balde as retiradas que `_init_pick_history` trouxe de volta; devolve quantos tokens consumiu.

        Restaurar o histórico tem de custar tokens, senão um reinício após uma importação grande emitiria outras 100 requisições (300 num período de 200). Os acquires não bloqueiam: roda no ``__init__``, antes da thread de recarga.
        """
        consumed = 0
        for _ in range(min(len(self.pick_history), self.burst_tokens)):
            if not self.bucket.acquire(blocking=False):
                break
            consumed += 1
        self.n_tokens -= consumed
        return consumed

    def __init__(self) -> None:

        self._init_pick_history()

        self.__n_tokens_lock = Lock()
        self.queue_lock = Lock()
        self.queue = deque()

        # O balde precisa existir antes de ser drenado pelo histórico restaurado.
        self.bucket = BoundedSemaphore(self.burst_tokens)
        self.n_tokens = self.burst_tokens
        self.seed_history()

        refill_thread = Thread(target=self.refill_thread_func, daemon=True)
        refill_thread.start()

    @property
    def refill_spacing(self) -> float:
        """O intervalo de recarga atual: mesmo após uma rajada, o limite do período não é excedido."""
        tokens_left = self.refill_period_tokens - len(self.pick_history)  # type: ignore
        seconds_left = self.pick_history.start + self.refill_period_seconds - time()  # type: ignore
        try:
            spacing_seconds = seconds_left / tokens_left
        except ZeroDivisionError:
            # Sem tokens restantes: espera o fim do período
            spacing_seconds = seconds_left

        natural_spacing = self.refill_period_seconds / self.refill_period_tokens
        return max(natural_spacing, spacing_seconds)

    def refill(self) -> None:
        sleep(self.refill_spacing)
        try:
            self.bucket.release()
        except ValueError:
            pass
        else:
            self.n_tokens += 1

    def refill_thread_func(self) -> None:
        while True:
            self.refill()

    def update_queue(self) -> None:
        update_thread = Thread(target=self.queue_update_thread_func, daemon=True)
        update_thread.start()

    def queue_update_thread_func(self) -> None:
        with self.queue_lock:
            if len(self.queue) == 0:
                return
            # Sem `with`: não se devolve ao balde
            self.bucket.acquire()  # pylint: disable=consider-using-with
            self.n_tokens -= 1
            lock = self.queue.pop()
            lock.release()

    def add_to_queue(self) -> Lock:
        lock = Lock()
        # Trancado até a vez na fila
        lock.acquire()  # pylint: disable=consider-using-with
        with self.queue_lock:
            self.queue.appendleft(lock)
        return lock

    def acquire(self) -> None:
        lock = self.add_to_queue()
        self.update_queue()
        lock.acquire()  # pylint: disable=consider-using-with
        self.pick_history.add()  # type: ignore

    def __enter__(self) -> None:
        self.acquire()

    def __exit__(self, *_args: Any) -> None:
        pass
