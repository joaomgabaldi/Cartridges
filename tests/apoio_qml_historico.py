# apoio_qml_historico.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_qml_historico.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

from PySide6.QtCore import QPointF
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem


def _todos(raiz, nome):
    achados, pilha, vistos = [], [raiz], {}
    while pilha:
        atual = pilha.pop()
        if id(atual) in vistos:
            continue
        vistos[id(atual)] = atual  # vivo até o fim: o id não se repete
        if atual.objectName() == nome:
            achados.append(atual)
        pilha.extend(atual.children())
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
    return achados


def _caixa(item):
    topo = item.mapToScene(QPointF(0, 0))  # não o `boundingRect()`: o de um Text é o da parte pintada
    return topo.x(), topo.y(), item.width(), item.height()


def _expr(objeto, texto):
    return QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, texto).evaluate()[0]
