# test_janela_restaurando.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A janela que aparece na abertura enquanto um backup agendado é restaurado."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer, QUrl
from PySide6.QtQml import QQmlApplicationEngine

from cartridges.modelos.restaurando import Restaurando, entregar_so_ao_mudar

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml" / "JanelaRestaurando.qml"


def _esperar(ms=100):
    fim = time.monotonic() + ms / 1000
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()


def _achar(item, nome):
    if item.objectName() == nome:
        return item
    for filho in item.childItems():
        if (achado := _achar(filho, nome)) is not None:
            return achado
    return None


@pytest.fixture
def janela(app_qt):  # noqa: ARG001
    motor = QQmlApplicationEngine()
    from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    restaurando = Restaurando(motor)
    motor.rootContext().setContextProperty("restaurando", restaurando)
    motor.load(QUrl.fromLocalFile(str(QML)))
    assert motor.rootObjects(), "a janela da restauração não carregou"
    raiz = motor.rootObjects()[0]
    _esperar()
    yield restaurando, raiz, lambda nome: _achar(raiz.contentItem(), nome)
    restaurando.terminar()
    raiz.close()
    motor.deleteLater()
    _esperar(30)


def test_textos(janela):
    restaurando, raiz, achar = janela
    assert raiz.title() == "Kyron"
    assert raiz.isVisible()
    assert achar("tituloDaRestauracao").property("text") == "Restaurando o backup"
    assert achar("textoDaRestauracao").property("text") == "O aplicativo será aberto quando a restauração terminar."
    assert achar("porcentagemDaRestauracao").property("text") == "0%"
    assert restaurando.porcentagem == "0%" and restaurando.fracao == 0
    assert raiz.width() == 420 and raiz.minimumWidth() == 420 and raiz.maximumWidth() == 420
    assert raiz.minimumHeight() == raiz.maximumHeight() == raiz.height()  # sem redimensionar


def test_avancar_mostra_a_porcentagem(janela):
    restaurando, _raiz, achar = janela
    mudancas = []
    restaurando.alterado.connect(lambda: mudancas.append(restaurando.porcentagem))
    restaurando.avancar(0.425)
    assert restaurando.porcentagem == "42%"
    assert abs(restaurando.fracao - 0.42) < 1e-9
    restaurando.avancar(0.429)  # o mesmo inteiro: nada redesenha
    assert mudancas == ["42%"]
    _esperar(30)
    assert achar("porcentagemDaRestauracao").property("text") == "42%"
    assert abs(achar("barraDaRestauracao").property("value") - 0.42) < 1e-9
    restaurando.avancar(1.0)
    assert restaurando.porcentagem == "100%"


def test_nao_fecha_antes_de_terminar(janela):
    restaurando, raiz, _achar_ = janela
    raiz.close()
    _esperar(30)
    assert raiz.isVisible()
    assert not restaurando.podeFechar
    restaurando.terminar()
    assert restaurando.podeFechar
    raiz.close()
    _esperar(30)
    assert not raiz.isVisible()


def test_tem_barra_de_titulo_so_com_minimizar(janela):
    _restaurando, raiz, _achar_ = janela
    flags = raiz.flags()
    assert flags & Qt.WindowType.WindowTitleHint
    assert flags & Qt.WindowType.CustomizeWindowHint
    assert flags & Qt.WindowType.WindowMinimizeButtonHint
    assert not flags & Qt.WindowType.WindowCloseButtonHint
    assert not flags & Qt.WindowType.WindowMaximizeButtonHint
    assert not flags & Qt.WindowType.FramelessWindowHint  # a moldura nativa


def test_so_entrega_quando_a_porcentagem_inteira_muda():
    entregas = []
    avancar = entregar_so_ao_mudar(lambda fracao: entregas.append(fracao))
    for i in range(1, 100_001):  # milhares de pedaços minúsculos
        avancar(i / 100_000)
    assert len(entregas) <= 101
    assert entregas[-1] == 1.0
