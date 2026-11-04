# apoio_edicao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apoio dos testes da edição (`cartridges.edicao`) e da ligação de zerados.

Módulo à parte, e não um teste: importar `tests.conftest` ou um `test_*.py` de
outro arquivo roda a coleta de novo (ver a armadilha da Task 4 do plano 3).
"""

import time

from PySide6.QtCore import QEventLoop, QTimer


def jogo(store, numero, **campos):
    """Um `Jogo` de verdade, já registrado na store (sem pipeline)."""
    from cartridges.jogo import Jogo  # noqa: PLC0415

    game = Jogo(
        {
            "source": "shortcuts",
            "game_id": f"shortcuts_z{numero}",
            "name": f"Jogo {numero}",
            "executable": "x",
            "added": 0,
            **campos,
        }
    )
    if store is not None:
        store.source_games.setdefault("shortcuts", {})[game.game_id] = game
        store.games_by_id[game.game_id] = game
    return game


class StubSgdb:
    """No lugar do `SgdbManager`: anota os pedidos e devolve na hora, sem rede."""

    signals: set = set()

    def __init__(self, erros=()):
        self.pedidos: list = []
        self.erros = list(erros)

    def reset_cancellable(self):
        pass

    def collect_errors(self):
        erros, self.erros = self.erros, []
        return erros

    def process_game(self, game, _data, callback):
        self.pedidos.append(game.game_id)
        callback(self)


def stub_sgdb(store, erros=()):
    from cartridges.store.managers.sgdb_manager import SgdbManager  # noqa: PLC0415

    falso = StubSgdb(erros)
    store.managers[SgdbManager] = falso
    return falso


def girar(limite=0.1):
    """Gira o laço de eventos: o que foi enfileirado para a thread principal chega."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
