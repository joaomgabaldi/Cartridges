# apoio_controle_grade.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_controle_grade.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

from types import SimpleNamespace

from PySide6.QtCore import Qt

from kyron import shared
from kyron.modelos.controle import ControleDaGrade


ATIVO = Qt.ApplicationState.ApplicationActive
INATIVO = Qt.ApplicationState.ApplicationInactive


class LeitorFalso:
    disponivel = True

    def __init__(self):
        self.botoes = 0
        self.lx = 0
        self.ly = 0
        self.leituras = 0
        self.solto = False
        self.vibracoes = []

    def ler(self):
        self.leituras += 1
        return SimpleNamespace(wButtons=self.botoes, sThumbLX=self.lx, sThumbLY=self.ly)

    def vibrar(self, esquerdo=0.0, direito=0.0):
        self.vibracoes.append((esquerdo, direito))

    def soltar(self):
        self.solto = True


class Montagem:
    def __init__(self):
        shared.schema.set_boolean("gamepad", True)  # desligada por padrão
        self.leitor = LeitorFalso()
        self.fabricados = 0
        self.estado = ATIVO
        self.agora = 1_000_000
        self.controle = ControleDaGrade(
            fabrica_do_leitor=self._fabricar,
            estado_do_app=lambda: self.estado,
            relogio=lambda: self.agora,
        )
        self.eventos = []
        c = self.controle
        c.mover.connect(lambda dx, dy: self.eventos.append(("mover", dx, dy)))
        for nome in ("ativar", "voltar", "menuPrincipal", "menuDoJogo", "buscar", "usado"):
            getattr(c, nome).connect(lambda nome=nome: self.eventos.append(nome))

    def _fabricar(self):
        self.fabricados += 1
        return self.leitor

    def tique(self, avanco_us=0):
        self.agora += avanco_us
        self.controle._ler()

    def comandos(self):
        return [e for e in self.eventos if e != "usado"]
