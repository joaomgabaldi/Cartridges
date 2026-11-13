# test_qml_dialogos_adiados.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preferências, edição e Sobre nascem depois de a janela aparecer (`cortinaDaAbertura.revelada`), ou já no primeiro pedido."""

import pytest
from PySide6.QtCore import Property, QObject, Signal

from tests.apoio_edicao import jogo
from tests.apoio_fita import pastas  # noqa: F401  # a pasta descartável das fitas (autouse)
from tests.apoio_qml_biblioteca import _achar, _App, _esperar

NOMES = ("dialogoDePreferencias", "dialogoDeEdicao", "dialogoSobre")


class _CortinaFalsa(QObject):
    reveladaMudou = Signal()  # noqa: N815

    def __init__(self):
        super().__init__()
        self._revelada = False

    @Property(bool, notify=reveladaMudou)
    def revelada(self):
        return self._revelada

    def revelar(self):
        self._revelada = True
        self.reveladaMudou.emit()


@pytest.fixture
def cortina():
    return _CortinaFalsa()


@pytest.fixture
def app(app_qt, store, cortina):  # noqa: ARG001
    janela = _App([jogo(store, 1, name="Alfa")], cortina_da_abertura=cortina)
    yield janela
    janela.fechar()


def _existe(app, nome):
    return _achar(app.janela, nome) is not None


def _foco_dentro_de(app, nome):
    item = app.janela.property("activeFocusItem")
    while item is not None:
        if item.objectName() == nome:
            return True
        item = item.parentItem()
    return False


def test_antes_da_cortina_os_dialogos_nao_existem_e_depois_sim(app, cortina):
    assert not any(_existe(app, nome) for nome in NOMES)
    cortina.revelar()
    assert _esperar(lambda: all(_existe(app, nome) for nome in NOMES))


def test_pedir_as_preferencias_antes_cria_na_hora_com_o_foco_dentro(app):
    assert app.preferencias.abrir("metadados")
    assert app.achar("dialogoDePreferencias").property("visible") is True
    assert app.achar("dialogoDePreferencias").property("secao") == "metadados"
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDePreferencias"))
    assert not _existe(app, "dialogoDeEdicao")


def test_pedir_a_edicao_antes_cria_na_hora_com_o_foco_dentro(app):
    app.edicao.abrir("shortcuts_z1")
    assert app.achar("dialogoDeEdicao").property("visible") is True
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDeEdicao"))
    assert not _existe(app, "dialogoDePreferencias")


def test_pedir_o_sobre_antes_cria_na_hora_com_o_foco_dentro(app):
    app.sobre.abrir()
    assert app.achar("dialogoSobre").property("visible") is True
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoSobre"))


def test_fechar_as_preferencias_sobre_a_edicao_devolve_o_foco_a_edicao(app, cortina):
    cortina.revelar()
    assert _esperar(lambda: all(_existe(app, nome) for nome in NOMES))
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDeEdicao"))
    assert app.preferencias.abrir()
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDePreferencias"))
    app.preferencias.fechar()
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDeEdicao"))
