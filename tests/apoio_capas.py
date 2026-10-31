# apoio_capas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gerente de capas falso, compartilhado pelos testes das Preferências.

Módulo à parte: importar um `test_*.py` de outro arquivo roda a coleta de novo.
"""


class _ManagerDeCapas:
    signals: set = set()

    def __init__(self, erros=()):
        self.callbacks, self.erros, self.resets = [], list(erros), 0

    def reset_cancellable(self):
        self.resets += 1

    def collect_errors(self):
        return self.erros

    def process_game(self, _game, _data, callback):
        self.callbacks.append(callback)
