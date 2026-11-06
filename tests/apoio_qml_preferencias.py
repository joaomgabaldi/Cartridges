# apoio_qml_preferencias.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_qml_preferencias.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

import pytest
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem

from kyron.utils import window_geometry
from tests.apoio_qml_biblioteca import _App, _esperar, _jogos


@pytest.fixture
def app(app_qt, monkeypatch):
    from tests.apoio_preferencias_qt import PRINCIPAL, SEGUNDO  # noqa: PLC0415

    monkeypatch.setattr(window_geometry, "monitors", lambda: [PRINCIPAL, SEGUNDO])
    janela = _App(_jogos((1, "Alfa", {}), (2, "Beta", {})))
    yield janela
    janela.fechar()


def _abrir(app, pagina=""):
    assert app.preferencias.abrir(pagina)
    assert _esperar(lambda: app.achar("dialogoDePreferencias").property("visible") is True)


def _avaliar(objeto, expressao):
    valor = QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]
    return valor.toVariant() if hasattr(valor, "toVariant") else valor


def _clique(app, nome):
    QMetaObject.invokeMethod(app.achar(nome), "click", Qt.ConnectionType.DirectConnection)


def _textos(raiz):
    """Todo `text` de todo item abaixo de `raiz`, visível ou não."""
    achados, pilha = [], [raiz]
    while pilha:
        atual = pilha.pop()
        texto = atual.property("text")
        if isinstance(texto, str) and texto:
            achados.append(texto)
        pilha.extend(atual.childItems() if isinstance(atual, QQuickItem) else [])
    return achados


def _linha(app, nome):
    linha = app.achar(nome)
    return linha.property("titulo"), linha.property("subtitulo")


def _enabled(app, nome):
    return app.achar(nome).property("enabled") is True


@pytest.fixture
def fitas_espiadas(monkeypatch):
    """Uma fita configurada e as prévias e arranques anotados, sem acender nada."""
    from kyron.utils import session_fita  # noqa: PLC0415

    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "192.0.2.10", "k")])
    anotadas = []
    monkeypatch.setattr(session_fita, "previa", lambda cor, *_a: anotadas.append(cor))
    monkeypatch.setattr(session_fita, "reacender", lambda: anotadas.append("reacender"))
    return anotadas
