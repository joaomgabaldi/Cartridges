# thread_principal.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entrega de chamadas à thread principal (a do `QCoreApplication`).

De qualquer thread, inclusive da principal, a função é enfileirada e roda no laço de eventos, na ordem das chamadas.
"""

import threading
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal


class _Ponte(QObject):
    _chamar = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._chamar.connect(self._executar, Qt.ConnectionType.QueuedConnection)

    def _executar(self, chamada: tuple) -> None:
        funcao, args = chamada
        funcao(*args)


def eh_thread_principal() -> bool:
    return threading.current_thread() is threading.main_thread()


# O QObject recebe as entregas na thread que o criou: só a principal o cria, senão as chamadas
# iriam para uma thread sem laço de eventos.
_ponte: _Ponte | None = _Ponte() if eh_thread_principal() else None


def na_thread_principal(funcao: Callable[..., Any], *args: Any) -> None:
    global _ponte  # noqa: PLW0603
    if _ponte is None:
        if not eh_thread_principal():
            raise RuntimeError("na_thread_principal: a ponte ainda não existe; chame uma vez da thread principal")
        _ponte = _Ponte()
    _ponte._chamar.emit((funcao, args))  # noqa: SLF001
