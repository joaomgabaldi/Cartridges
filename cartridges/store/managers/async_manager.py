# async_manager.py
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
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable

from cartridges.store.managers.manager import Manager
from cartridges.utils.thread_principal import na_thread_principal

if TYPE_CHECKING:
    from cartridges.jogo import Jogo

_executor = ThreadPoolExecutor(thread_name_prefix="manager")


def encerrar() -> None:
    """Descarta o que está na fila para o interpretador poder sair (chamado ao fechar o app)."""
    _executor.shutdown(wait=False, cancel_futures=True)


class AsyncManager(Manager):
    """Manager that can run asynchronously"""

    blocking = False
    cancellable: threading.Event

    def __init__(self) -> None:
        super().__init__()
        self.cancellable = threading.Event()

    def cancel_tasks(self):
        """Cancel all tasks for this manager"""
        self.cancellable.set()

    def reset_cancellable(self):
        """Reset the cancellable for this manager.
        Already scheduled Tasks will no longer be cancellable."""
        self.cancellable = threading.Event()

    def process_game(
        self, game: "Jogo", additional_data: dict, callback: Callable[["Manager"], Any]
    ) -> None:
        """Create a task to process the game in a separate thread"""
        # Capturado aqui: um reset troca o evento, e a tarefa já enfileirada
        # continua vendo o cancelamento do seu lote.
        cancellable = self.cancellable
        try:
            _executor.submit(
                self._task_thread_func, game, additional_data, callback, cancellable
            )
        except RuntimeError:  # depois de encerrar(): o app está fechando
            logging.debug("%s: tarefa descartada, app encerrando", self.name)

    def _task_thread_func(self, game, additional_data, callback, cancellable):
        """Task thread entry point"""
        # Como o Gio.Task: cancelada, a tarefa não roda, mas a conclusão ainda é
        # entregue; sem ela o pipeline nunca termina e a importação não acaba.
        try:
            if not cancellable.is_set():
                self.run(game, additional_data)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Erro inesperado em %s", self.name)
        finally:
            na_thread_principal(callback, self)
