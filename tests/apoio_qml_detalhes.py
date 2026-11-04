# apoio_qml_detalhes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_qml_detalhes.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

from PySide6.QtCore import QPoint, Qt
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from tests.apoio_qml_biblioteca import _esperar


def _foco_dentro_de(app, nome):
    item = app.janela.property("activeFocusItem")
    while item is not None:
        if item.objectName() == nome:
            return True
        item = item.parentItem()
    return False


def _clicar(app, item):
    ponto = item.mapToScene(item.boundingRect().center()).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(ponto.x(), ponto.y()))


def _cartoes(app, nome_da_grade="grade"):
    """Os cartões da grade (itens com `jogoId`), na ordem do índice."""
    grade = app.achar(nome_da_grade)
    achados = []
    pilha = [grade.property("contentItem")]
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, QQuickItem):
            if atual.property("jogoId") and atual.property("larguraDaCapa"):
                achados.append(atual)
            pilha.extend(atual.childItems())
    return sorted(achados, key=lambda c: (c.mapToScene(c.boundingRect().topLeft()).y(), c.mapToScene(c.boundingRect().topLeft()).x()))


def _abrir_pelo_cartao(app, indice=0):
    _clicar(app, _cartoes(app)[indice])
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    return app.achar("paginaDoJogo")
