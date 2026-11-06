# manager.py
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
from abc import abstractmethod
from time import sleep
from typing import TYPE_CHECKING, Any, Callable, Container

from kyron.errors.error_producer import ErrorProducer
from kyron.errors.friendly_error import FriendlyError

if TYPE_CHECKING:
    from kyron.jogo import Jogo


class Manager(ErrorProducer):
    """Ação pós-criação de um jogo. Pode se ligar a sinais do jogo e cancelar suas tarefas num erro crítico (então gera um cancellable novo); pode ser repetida em certos erros."""

    run_after: Container[type["Manager"]] = tuple()
    blocking: bool = True

    retryable_on: Container[type[Exception]] = tuple()
    continue_on: Container[type[Exception]] = tuple()
    signals: Container[type[str]] = set()
    retry_delay: int = 3
    max_tries: int = 3

    @property
    def name(self) -> str:
        return type(self).__name__

    @abstractmethod
    def main(self, game: "Jogo", additional_data: dict) -> None:
        """
        Manager specific logic triggered by the run method
        * Implemented by final child classes
        * May block its thread
        * May raise retryable exceptions that will trigger a retry if possible
        * May raise other exceptions that will be reported
        """

    def run(self, game: "Jogo", additional_data: dict) -> None:
        tries = 1

        def handle_error(error: Exception) -> None:
            nonlocal tries

            base_error = error
            if isinstance(error, FriendlyError) and error.__cause__ is not None:
                error = error.__cause__

            log_args = (
                type(error).__name__,
                self.name,
                f"{game.name} ({game.game_id})",
            )

            out_of_retries_format = "Out of retries dues to %s in %s for %s"
            retrying_format = "Retrying %s in %s for %s"
            unretryable_format = "Unretryable %s in %s for %s"

            # isinstance, não tipo exato: o requests embrulha falhas de conexão em subclasses próprias.
            if isinstance(error, tuple(self.continue_on)):
                return

            if isinstance(error, tuple(self.retryable_on)):
                # `tries` começa em 1 (a tentativa inicial): `max_tries` é o total de tentativas.
                if tries >= self.max_tries:
                    logging.error(out_of_retries_format, *log_args)
                    self.report_error(base_error)
                else:
                    logging.error(retrying_format, *log_args)
                    sleep(self.retry_delay)
                    tries += 1
                    try_manager_logic()

            else:
                logging.error(unretryable_format, *log_args, exc_info=error)
                self.report_error(base_error)

        def try_manager_logic() -> None:
            try:
                self.main(game, additional_data)
            except Exception as error:  # pylint: disable=broad-exception-caught
                handle_error(error)

        try_manager_logic()

    def process_game(
        self, game: "Jogo", additional_data: dict, callback: Callable[["Manager"], Any]
    ) -> None:
        self.run(game, additional_data)
        callback(self)
