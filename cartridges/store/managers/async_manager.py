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
import os
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable, Literal

from cartridges.store.managers.manager import Manager
from cartridges.utils.thread_principal import na_thread_principal

if TYPE_CHECKING:
    from cartridges.jogo import Jogo



class _PoolDaemon:
    """Fila + N threads daemon. O `atexit` do `concurrent.futures` faz `join` de toda thread de
    `ThreadPoolExecutor`, o que seguraria a saída por uma requisição de até 30 s; thread daemon não."""

    def __init__(self, n: int, prefixo: str) -> None:
        self._fila: queue.SimpleQueue = queue.SimpleQueue()
        self._fechado = False
        for i in range(n):
            threading.Thread(target=self._laco, name=f"{prefixo}-{i}", daemon=True).start()

    def _laco(self) -> None:
        while True:
            funcao, args = self._fila.get()
            try:
                funcao(*args)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Erro inesperado na thread de rede")  # a thread não morre

    def submit(self, funcao: Callable[..., Any], *args: Any) -> None:
        if self._fechado:
            raise RuntimeError("pool encerrado")
        self._fila.put((funcao, args))

    @property
    def fechado(self) -> bool:
        return self._fechado

    def encerrar(self) -> None:
        """Descarta o que está na fila; o que já roda morre com o processo."""
        self._fechado = True
        while True:
            try:
                self._fila.get_nowait()
            except queue.Empty:
                return


_rede = _PoolDaemon(min(32, (os.cpu_count() or 1) + 4), "rede")
_gravacao = ThreadPoolExecutor(max_workers=4, thread_name_prefix="gravacao")


def rodar_na_rede(funcao: Callable[..., Any], *args: Any) -> None:
    """Roda `funcao` numa thread daemon do pool de rede (a importação roda as fontes aqui)."""
    _rede.submit(funcao, *args)


def encerrar() -> None:
    """Fim do app: descarta a fila de rede e espera a de gravação terminar."""
    _rede.encerrar()
    _gravacao.shutdown(wait=True)


class AsyncManager(Manager):
    """Manager that can run asynchronously"""

    blocking = False
    # "rede" (daemon, descartável na saída) ou "gravacao" (drenada na saída; nunca perde uma gravação).
    executor: Literal["rede", "gravacao"] = "rede"
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
        args = (game, additional_data, callback, cancellable)
        try:
            (_gravacao if self.executor == "gravacao" else _rede).submit(self._task_thread_func, *args)
        except RuntimeError:  # depois de encerrar(): o app está fechando
            if self.executor == "gravacao":
                self._task_thread_func(*args)  # uma gravação nunca se perde: roda aqui mesmo
            else:
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
            # App fechando: nada de emitir para um Qt em desmontagem (só a rede; a gravação entrega sempre).
            if self.executor == "gravacao" or not _rede.fechado:
                na_thread_principal(callback, self)
