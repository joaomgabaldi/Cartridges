# apoio_conquistas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_conquistas_qt.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

from PySide6.QtCore import QObject, Signal

from cartridges.jogo import Jogo


class _Loja:
    """O que o modelo pede à `Store`: achar o jogo."""

    def __init__(self, *jogos):
        self.por_id = {jogo.game_id: jogo for jogo in jogos}

    def get(self, game_id):
        return self.por_id.get(game_id)


class _Detalhes(QObject):
    """O que o modelo pede aos detalhes: o sinal, o jogo mostrado e a loja."""

    alterado = Signal()

    def __init__(self, *jogos):
        super().__init__()
        self.jogoId = ""
        self.loja = _Loja(*jogos)

    def mostrar(self, game_id):
        self.jogoId = game_id
        self.alterado.emit()


def _jogo(numero=1, **extra):
    return Jogo({"game_id": f"imported_{numero}", "source": "imported", "name": f"Jogo {numero}", **extra})
