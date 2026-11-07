# test_tarefas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O botão do canto e a janela "Tarefas em andamento" (QML offscreen); a regra de quando o botão pode aparecer;
fechar a principal com trabalho em andamento."""

import json
import os
import subprocess
import sys
import time
import uuid
import weakref
import winreg
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import (
    Q_ARG,
    QEvent,
    QEventLoop,
    QMetaObject,
    QCoreApplication,
    QPoint,
    QPointF,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QGuiApplication, QWheelEvent, QWindow
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from kyron import shared
from kyron.modelos import tarefas
from kyron.modelos.avisos import FilaDeAvisos
from kyron.modelos.sessao import ModeloDaSessao
from kyron.modelos.tarefas import PainelDasTarefas, acao_ao_fechar, pode_mostrar
from kyron.saves import backup_de_saves
from kyron.utils import window_geometry
from tests.apoio_registro import _apagar_chave

RAIZ = Path(__file__).resolve().parent.parent
QML = RAIZ / "kyron" / "qml"
QQuickStyle.setStyle("Basic")


@pytest.fixture(autouse=True)
def _lista_limpa():
    """A lista é global: cada teste começa e termina sem tarefa nenhuma."""
    _esvaziar()
    yield
    _esvaziar()


def _esvaziar():
    for tarefa in list(tarefas.lista._tarefas):  # noqa: SLF001
        tarefas.lista.remover(tarefa)


def _esperar(ate=None, limite=3.0):
    limite = 0.3 if ate is None else limite
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(30, laco.quit)
        laco.exec()
        if ate is not None and ate():
            return True
    return ate is None


def _todos(raiz, nome):
    """Todo objeto de `objectName` igual a `nome` sob `raiz`, pelos itens visuais e pelos filhos QObject."""
    achados, pilha, vistos = [], [raiz], {}
    while pilha:
        atual = pilha.pop()
        if id(atual) in vistos:
            continue
        vistos[id(atual)] = atual  # guardar o objeto impede o reuso do id
        try:
            if atual.objectName() == nome:
                achados.append(atual)
            pilha.extend(atual.children())
            if isinstance(atual, QQuickItem):
                pilha.extend(atual.childItems())
            elif isinstance(atual, QQuickWindow):
                pilha.append(atual.contentItem())
        except RuntimeError:
            continue
    return achados


def _chamar(objeto, nome, *args):
    QMetaObject.invokeMethod(
        objeto, nome, Qt.ConnectionType.DirectConnection, *[Q_ARG("QVariant", a) for a in args]
    )


# O botão sobre uma área com uma rolagem e um clique atrás (a capa), e o `Loader` da janela como no Aplicativo.qml.
_CENA = b"""import QtQuick
import QtQuick.Window
Window {
    id: raiz
    width: 400; height: 600; visible: true
    property string pagina: "todos"
    property bool modal: false
    property bool bp: false
    property bool sess: false
    property int cliquesAtras: 0
    Flickable {
        objectName: "rolagem"
        anchors.fill: parent
        contentWidth: width; contentHeight: 3000
        MouseArea { width: parent.width; height: 3000; onClicked: raiz.cliquesAtras++ }
    }
    BotaoDasTarefas {
        id: botao
        objectName: "botaoDasTarefas"
        anchors.fill: parent
        pagina: raiz.pagina
        modalAberto: raiz.modal
        emBigPicture: raiz.bp
        emSessao: raiz.sess
    }
    Loader {
        objectName: "carregadorDasTarefas"
        active: painelDasTarefas.aberta
        sourceComponent: Component { JanelaDasTarefas { alvo: botao.alvo; semAgente: true } }
    }
}
"""


class _Cena:
    def __init__(self):
        self.painel = PainelDasTarefas()
        self.motor = QQmlEngine()
        from kyron.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
        self.motor.addImageProvider("icone", ProvedorDeIcones())
        self.motor.rootContext().setContextProperty("painelDasTarefas", self.painel)
        self.componente = QQmlComponent(self.motor)
        self.componente.setData(_CENA, QUrl.fromLocalFile(str(QML / "_cena.qml")))
        self.janela = self.componente.create()
        assert self.janela is not None, self.componente.errorString()
        self.botao = self.achar("botaoDasTarefas")
        self.botao.setProperty("vigiarMouse", False)  # os testes movem o mouse por `aoMover`
        self.circulo = self.achar("circuloDasTarefas")
        _esperar()

    def achar(self, nome):
        achados = _todos(self.janela, nome)
        assert achados, f"sem objeto {nome!r}"
        return achados[0]

    def janela_das_tarefas(self):
        return self.achar("carregadorDasTarefas").property("item")

    def abrir_a_janela(self):
        self.painel.mostrar()
        carregador = self.achar("carregadorDasTarefas")
        assert _esperar(lambda: carregador.property("item") is not None)
        _esperar()  # os blocos do Repeater
        return carregador.property("item")

    def fechar(self):
        item = self.janela_das_tarefas()
        if item is not None:
            item.close()
        self.janela.close()
        self.janela.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)  # já: o motor e os modelos morrem com o arnês


@pytest.fixture
def cena(app_qt):  # noqa: ARG001
    c = _Cena()
    yield c
    c.fechar()
    _esperar()


def _a_vista(c):
    return c.botao.property("aVista")


# -- a janela -----------------------------------------------------------------------------------------------


def _textos(janela):
    """Os rótulos de cada bloco, de cima para baixo: [(nome, contagem), ...]."""
    nomes = sorted(_todos(janela, "nomeDaTarefa"), key=lambda t: t.mapToScene(QPointF(0, 0)).y())
    contagens = sorted(_todos(janela, "contagemDaTarefa"), key=lambda t: t.mapToScene(QPointF(0, 0)).y())
    return [(n.property("text"), c.property("text")) for n, c in zip(nomes, contagens, strict=True)]


def test_janela_mostra_cada_tarefa_e_acompanha(cena, flush_idle):
    importacao = tarefas.comecar("Importação", 30)
    tarefas.comecar("HowLongToBeat", 4)
    flush_idle()
    janela = cena.abrir_a_janela()
    assert _textos(janela) == [("Importação", "0 de 30"), ("HowLongToBeat", "0 de 4")]
    assert cena.achar("avisoDeVazio").property("visible") is False

    importacao.atualizar(3)
    flush_idle()
    assert _textos(janela)[0] == ("Importação", "3 de 30")


def test_janela_vazia_avisa(cena, flush_idle):
    tarefa = tarefas.comecar("Metadados", 2)
    flush_idle()
    janela = cena.abrir_a_janela()
    tarefa.terminar()
    flush_idle()
    _esperar()
    assert _textos(janela) == []
    vazio = cena.achar("avisoDeVazio")
    assert vazio.property("visible") is True
    assert vazio.property("text") == "Nenhuma tarefa em andamento"


def test_nome_da_tarefa_em_texto_puro(cena, flush_idle):
    tarefas.comecar("Tom & <b>Jerry</b>", 1)
    flush_idle()
    cena.abrir_a_janela()
    nome = cena.achar("nomeDaTarefa")
    assert nome.property("text") == "Tom & <b>Jerry</b>"
    assert nome.property("textoPuro") is True


def test_barra_de_cada_tarefa_aceita_o_nome_acessivel(cena, flush_idle):
    tarefas.comecar("Importação", 3)
    flush_idle()
    cena.abrir_a_janela()
    barra = cena.achar("barraDaTarefa")
    assert barra.property("nomeAcessivel") == "Importação"
    assert barra.property("papelAcessivel") == "ProgressBar"


def test_mostrar_duas_vezes_e_a_mesma_janela(cena):
    pedidos = []
    cena.painel.frente.connect(lambda: pedidos.append(1))
    cena.painel.mostrar()
    primeira = cena.janela_das_tarefas()
    assert primeira is not None and cena.painel.aberta
    assert primeira.opacity() == 0  # nasce invisível, até ir para o lugar
    assert pedidos == []

    cena.painel.mostrar()
    assert cena.janela_das_tarefas() is primeira
    assert pedidos == [1]
    assert _esperar(lambda: primeira.opacity() == 1)  # depois do primeiro quadro

    primeira.close()
    assert not cena.painel.aberta
    assert _esperar(lambda: cena.janela_das_tarefas() is None)


def test_janela_solta_nao_e_transiente_nem_modal_nem_redimensionavel(cena):
    janela = cena.abrir_a_janela()
    assert janela.transientParent() is None
    assert janela.modality() == Qt.WindowModality.NonModal
    # Sem moldura nativa: a barra é a do app, com só minimizar e fechar (`:minimize,close`); o QWindowKit a liga.
    flags = janela.flags()
    assert not flags & Qt.WindowType.WindowMaximizeButtonHint
    assert not flags & Qt.WindowType.WindowTitleHint and not flags & Qt.WindowType.CustomizeWindowHint
    barra = _todos(janela, "barraDasTarefas")[0]
    assert barra.property("comMaximizar") is False and barra.property("titulo") == "Tarefas em andamento"
    assert janela.width() == 360 and janela.minimumWidth() == 360 and janela.maximumWidth() == 360
    assert janela.minimumHeight() == janela.maximumHeight() == janela.height()


def test_altura_acompanha_o_conteudo(cena, flush_idle):
    primeira = tarefas.comecar("Importação", 3)
    tarefas.comecar("HowLongToBeat", 4)
    flush_idle()
    janela = cena.abrir_a_janela()
    com_duas = janela.height()
    assert com_duas > 100 and janela.minimumHeight() == janela.maximumHeight() == com_duas

    primeira.terminar()
    flush_idle()
    assert _esperar(lambda: janela.height() < com_duas)
    com_uma = janela.height()
    assert janela.minimumHeight() == janela.maximumHeight() == com_uma
    tarefas.comecar("Metadados", 2)
    flush_idle()
    assert _esperar(lambda: janela.height() > com_uma)


def test_esc_fecha_a_janela(cena):
    janela = cena.abrir_a_janela()
    QTest.keyClick(janela, Qt.Key.Key_Escape)
    assert not cena.painel.aberta
    assert _esperar(lambda: cena.janela_das_tarefas() is None)


def test_janela_vai_acima_do_botao_depois_do_primeiro_quadro(cena):
    janela = cena.abrir_a_janela()
    assert _esperar(lambda: janela.opacity() == 1)
    alvo = cena.achar("alvoDoBotao")
    ponto = alvo.mapToGlobal(QPointF(0, 0))
    esperado = window_geometry.posicao_acima_do_botao(
        (int(ponto.x()), int(ponto.y()), 34, 34), janela.frameGeometry().height()
    )
    assert (alvo.width(), alvo.height()) == (34, 34)
    assert (janela.frameGeometry().x(), janela.frameGeometry().y()) == esperado


def test_posicao_acima_do_botao_com_os_numeros_do_prototipo():
    # A moldura fica 12 px acima do botão, alinhada à esquerda dele.
    assert window_geometry.posicao_acima_do_botao((12, 1000, 34, 34), 150) == (12, 838)


# -- a regra de quando o botão pode aparecer -------------------------------------------------------------------


def test_pode_mostrar_regra_pura():
    # (quantas, pagina, modal, big_picture, sessao) -> pode
    tabela = [
        ((0, "todos", False, False, False), False),
        ((1, "todos", False, False, False), True),
        ((3, "zerados", False, False, False), True),
        ((1, "jogo", False, False, False), False),
        ((1, "todos", True, False, False), False),
        ((1, "zerados", False, True, False), False),
        ((1, "todos", False, False, True), False),
        ((0, "zerados", True, True, True), False),
    ]
    for argumentos, esperado in tabela:
        assert pode_mostrar(*argumentos) is esperado, argumentos


def test_sem_tarefa_o_botao_nunca_aparece(cena):
    assert cena.painel.quantas == 0
    assert cena.botao.property("pode") is False
    assert not _a_vista(cena)


def test_com_tarefa_aparece_so_nas_duas_bibliotecas_livres(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    assert cena.painel.quantas == 1
    assert cena.botao.property("pode") is True
    cena.janela.setProperty("pagina", "zerados")
    assert cena.botao.property("pode") is True
    for propriedade, valor in (("pagina", "jogo"), ("modal", True), ("bp", True), ("sess", True)):
        cena.janela.setProperty("pagina", "todos")
        for p, v in (("modal", False), ("bp", False), ("sess", False)):
            cena.janela.setProperty(p, v)
        cena.janela.setProperty(propriedade, valor)
        assert cena.botao.property("pode") is False, propriedade


def test_painel_acompanha_a_lista(app_qt, flush_idle):  # noqa: ARG001
    painel = PainelDasTarefas()
    avisos = []
    fraco = weakref.ref(painel)  # o lambda não prende o painel
    painel.alterado.connect(lambda: avisos.append(fraco().quantas))
    tarefa = tarefas.comecar("Importação", 2)
    flush_idle()
    assert painel.quantas == 1 and avisos == [1]
    tarefa.terminar()
    flush_idle()
    assert painel.quantas == 0 and avisos == [1, 0]
    painel.mostrar()
    assert painel.aberta
    painel.janelaFechada()
    assert not painel.aberta
    assert painel.lista is tarefas.lista


# -- o botão ------------------------------------------------------------------------------------------------


def test_tarefa_nova_faz_o_botao_entrar_e_o_fim_recolhe(cena, flush_idle):
    assert not _a_vista(cena)
    assert cena.circulo.property("enabled") is False

    tarefa = tarefas.comecar("Importação", 1)
    flush_idle()
    assert _a_vista(cena)
    assert cena.circulo.property("enabled") is True

    tarefa.terminar()
    flush_idle()
    assert not _a_vista(cena)
    assert cena.circulo.property("enabled") is False


def test_clicar_no_botao_recolhe_e_abre_a_janela(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    assert _esperar(lambda: cena.circulo.property("x") == 12)
    QTest.mouseClick(
        cena.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12 + 17, 600 - 12 - 17)
    )
    assert cena.painel.aberta
    assert not _a_vista(cena)
    assert cena.janela.property("cliquesAtras") == 0


def test_mouse_no_canto_traz_o_botao_de_volta(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "recolher")  # os 10 s da entrada já passaram
    assert not _a_vista(cena)

    _chamar(cena.botao, "aoEntrar")
    assert _a_vista(cena)


def test_sessao_esconde_o_botao(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    cena.janela.setProperty("sess", True)
    assert not _a_vista(cena)
    assert cena.circulo.property("enabled") is False
    _chamar(cena.botao, "aoEntrar")
    assert not _a_vista(cena)


def test_girar_para_quando_a_tarefa_acaba(cena, flush_idle):
    giro = cena.achar("giroDasTarefas")
    tarefa = tarefas.comecar("Importação", 1)
    flush_idle()
    assert cena.botao.property("girando") is True
    assert _esperar(lambda: giro.property("running"))

    tarefa.terminar()
    flush_idle()
    assert cena.botao.property("girando") is False
    assert not giro.property("running")


def test_canto_escondido_nao_recebe_entrada(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "recolher")
    assert _esperar(lambda: cena.circulo.property("x") < -34)
    # O clique no lugar do botão recolhido chega à capa e não abre nada.
    QTest.mouseClick(
        cena.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12 + 17, 600 - 12 - 17)
    )
    assert cena.janela.property("cliquesAtras") == 1
    assert not cena.painel.aberta


def test_botao_nao_rouba_a_roda_das_capas(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    rolagem = cena.achar("rolagem")
    assert _a_vista(cena) and rolagem.property("contentY") == 0
    ponto = QPointF(60, 580)  # dentro do canto de 72 x 72, fora do botão
    roda = QWheelEvent(
        ponto, cena.janela.mapToGlobal(ponto), QPoint(0, 0), QPoint(0, -240),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )  # fmt: skip
    QCoreApplication.sendEvent(cena.janela, roda)
    assert _esperar(lambda: rolagem.property("contentY") > 0)


def test_movimento_no_canto_mostra_e_fora_agenda_o_recuo(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "recolher")

    _chamar(cena.botao, "aoMover", 500, 100)
    assert not _a_vista(cena)

    _chamar(cena.botao, "aoMover", 10, 590)
    assert _a_vista(cena)
    assert cena.circulo.property("enabled") is True
    _chamar(cena.botao, "recolher")
    assert _a_vista(cena)  # com o mouse em cima, fica

    _chamar(cena.botao, "aoMover", 200, 590)
    assert cena.achar("recuoDasTarefas").property("running")
    _chamar(cena.botao, "recolher")
    assert not _a_vista(cena)


def test_so_a_faixa_junto_a_borda_chama_e_o_botao_a_vista_segura(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "recolher")

    _chamar(cena.botao, "aoMover", 30, 590)
    assert not _a_vista(cena)  # fora da faixa de 16 px

    _chamar(cena.botao, "aoMover", 10, 590)
    assert _a_vista(cena)

    # Da faixa até o botão, para clicar: o botão à vista segura a área.
    _chamar(cena.botao, "aoMover", 30, 575)
    assert not cena.achar("recuoDasTarefas").property("running")


def test_tempos_de_entrada_e_de_saida(cena, flush_idle):
    assert cena.botao.property("entradaMs") == 10000
    assert cena.botao.property("saidaMs") == 5000
    assert cena.botao.property("canto") == 72
    assert cena.botao.property("faixa") == 16
    recuo = cena.achar("recuoDasTarefas")
    tarefas.comecar("Importação", 1)
    flush_idle()
    assert recuo.property("running") and recuo.property("interval") == 10000
    _chamar(cena.botao, "aoMover", 10, 590)
    _chamar(cena.botao, "aoMover", 200, 100)
    assert recuo.property("running") and recuo.property("interval") == 5000


def test_o_mouse_de_verdade_no_canto_chama_o_botao(cena, flush_idle):
    cena.botao.setProperty("vigiarMouse", True)
    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "recolher")
    assert not _a_vista(cena)
    QTest.mouseMove(cena.janela, QPoint(300, 300))
    QTest.mouseMove(cena.janela, QPoint(10, 590))
    assert _esperar(lambda: _a_vista(cena))
    assert cena.botao.property("noCanto") is True
    QTest.mouseMove(cena.janela, QPoint(300, 300))
    assert _esperar(lambda: cena.botao.property("noCanto") is False)
    assert cena.achar("recuoDasTarefas").property("running")


def test_sair_da_janela_agenda_o_recuo(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "aoMover", 10, 590)
    assert not cena.achar("recuoDasTarefas").property("running")
    _chamar(cena.botao, "aoDeixar")
    assert cena.achar("recuoDasTarefas").property("running")


def test_o_mouse_em_cima_do_botao_nao_o_deixa_recuar(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "aoMover", 10, 590)
    _chamar(cena.botao, "aoDeixar")
    assert cena.achar("recuoDasTarefas").property("running")
    _chamar(cena.botao, "aoPassarNoBotao", True)
    assert cena.botao.property("noCanto") is True
    assert not cena.achar("recuoDasTarefas").property("running")
    _chamar(cena.botao, "aoPassarNoBotao", False)
    assert cena.botao.property("noCanto") is False
    assert cena.achar("recuoDasTarefas").property("running")


def test_sessao_esconde_o_botao_sem_deslizar(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    assert _esperar(lambda: cena.circulo.property("x") == 12)

    cena.janela.setProperty("sess", True)
    assert cena.circulo.property("x") < -34  # de uma vez, sem o deslize
    assert not cena.achar("deslizeDasTarefas").property("running")
    assert cena.botao.property("deslizar") is True  # o deslize volta para a próxima vez


def test_fim_da_tarefa_recolhe_deslizando(cena, flush_idle):
    tarefa = tarefas.comecar("Importação", 1)
    flush_idle()
    assert _esperar(lambda: cena.circulo.property("x") == 12)
    tarefa.terminar()
    flush_idle(0.02)
    assert cena.achar("deslizeDasTarefas").property("running")  # a caminho, e não de uma vez
    assert _esperar(lambda: cena.circulo.property("x") < -34)


def test_mouse_ainda_no_canto_depois_de_fechar_a_janela_traz_o_botao(cena, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "aoMover", 10, 590)
    _chamar(cena.botao, "esconder", True)  # o que o clique no botão faz
    assert not _a_vista(cena)

    _chamar(cena.botao, "aoMover", 12, 588)
    assert _a_vista(cena)


def test_movimento_sem_tarefas_nao_faz_nada_e_a_tarefa_nova_funciona(cena, flush_idle):
    _chamar(cena.botao, "aoMover", 10, 590)
    assert not _a_vista(cena)

    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "esconder", True)
    _chamar(cena.botao, "aoMover", 10, 590)
    assert _a_vista(cena)


def test_tarefa_que_comeca_com_o_mouse_parado_no_canto_nao_recua(cena, flush_idle):
    _chamar(cena.botao, "aoMover", 10, 590)

    tarefas.comecar("Importação", 1)
    flush_idle()
    _chamar(cena.botao, "recolher")  # os 10 s da entrada
    assert _a_vista(cena)


# -- fechar a principal com trabalho em andamento --------------------------------------------------------


class _SessaoFalsa:
    """O `shared.sessao`: só conta os `principalFechando()` que o painel repassa."""

    def __init__(self):
        self.fechando = 0

    def principalFechando(self):  # noqa: N802
        self.fechando += 1


@pytest.fixture
def fechamento(app_qt, monkeypatch):  # noqa: ARG001
    """O painel com uma principal de verdade (offscreen), sem saves em andamento e sem encerrar o processo."""
    monkeypatch.setattr(backup_de_saves, "_tarefas_abertas", 0)
    sessao = _SessaoFalsa()
    monkeypatch.setattr(shared, "sessao", sessao, raising=False)
    saidas = []
    monkeypatch.setattr(tarefas, "_sair", lambda: saidas.append(1))
    principal = QWindow()
    principal.resize(200, 200)
    principal.show()
    painel = PainelDasTarefas()
    painel.definir_janela(principal)
    yield SimpleNamespace(painel=painel, principal=principal, sessao=sessao, saidas=saidas)
    painel.mostrarPrincipal()  # desfaz uma espera de sair que o teste deixou
    QGuiApplication.setQuitOnLastWindowClosed(True)
    principal.destroy()
    _esperar()


def test_acao_ao_fechar_regra_pura():
    # (saves_em_andamento, janela_aberta, tarefas) -> ação
    tabela = [
        ((False, False, 0), "fechar"),
        ((False, False, 2), "fechar"),
        ((False, True, 0), "fechar_as_duas"),
        ((False, True, 1), "esconder"),
        ((True, False, 0), "mostrar_e_esconder"),
        ((True, False, 1), "mostrar_e_esconder"),
        ((True, True, 0), "mostrar_e_esconder"),
        ((True, True, 3), "mostrar_e_esconder"),
    ]
    for argumentos, esperado in tabela:
        assert acao_ao_fechar(*argumentos) == esperado, argumentos


def test_fechar_a_janela_com_a_principal_escondida_encerra_o_app(fechamento, flush_idle):
    f = fechamento
    tarefas.comecar("Importação", 1)
    flush_idle()
    f.painel.mostrar()
    assert f.painel.principalFechando() is False
    assert f.painel.principalEscondida and not f.principal.isVisible()
    f.painel.janelaFechada()
    _esperar()
    assert f.saidas == [1]
    assert not f.painel.aberta


def test_fechar_a_janela_com_a_principal_visivel_so_a_fecha(fechamento):
    f = fechamento
    f.painel.mostrar()
    f.painel.janelaFechada()
    _esperar()
    assert f.saidas == []
    assert not f.painel.aberta and f.principal.isVisible()


def test_fechar_a_principal_com_tarefa_e_janela_so_esconde(fechamento, flush_idle):
    f = fechamento
    tarefas.comecar("Importação", 1)
    flush_idle()
    f.painel.mostrar()
    assert f.painel.principalFechando() is False
    assert not f.principal.isVisible() and f.painel.principalEscondida
    assert f.painel.aberta
    assert f.sessao.fechando == 0


def test_fechar_a_principal_sem_tarefa_fecha_tambem_a_janela(fechamento):
    f = fechamento
    f.painel.mostrar()
    assert f.painel.principalFechando() is True
    assert not f.painel.aberta  # o Loader desfaz a janela das tarefas
    assert not f.painel.principalEscondida
    assert f.sessao.fechando == 1


def test_fechar_a_principal_com_tarefa_sem_janela_fecha_tudo(fechamento, flush_idle):
    f = fechamento
    tarefas.comecar("Importação", 1)
    flush_idle()
    assert f.painel.principalFechando() is True
    assert not f.painel.aberta and not f.painel.principalEscondida
    assert f.sessao.fechando == 1


def test_fechar_com_saves_em_andamento_esconde_e_mostra_as_tarefas(fechamento, monkeypatch):
    """O backup ou a restauração dos saves em curso não pode ficar órfão: o app não fecha, mas some da tela e abre a
    janela das tarefas, que o encerra ao ser fechada."""
    f = fechamento
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    assert not f.painel.aberta
    assert f.painel.principalFechando() is False
    assert f.painel.aberta
    assert not f.principal.isVisible() and f.painel.principalEscondida
    assert f.sessao.fechando == 0


def test_fechar_as_tarefas_com_saves_em_andamento_espera_o_fim_para_sair(fechamento, monkeypatch):
    """Fechar a janela das tarefas no meio dos saves não mata o Ludusavi: tudo some e o app sai quando eles acabam."""
    f = fechamento
    saves = [True]
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: saves[0])
    outra = QWindow()  # a janela "Jogando", por exemplo
    outra.show()
    try:
        assert f.painel.principalFechando() is False
        f.painel.janelaFechada()
        _esperar(limite=0.6)
        assert f.saidas == []
        assert not f.principal.isVisible() and not outra.isVisible()
        assert not QGuiApplication.quitOnLastWindowClosed()  # fechar a última janela não encerra por fora

        saves[0] = False
        assert _esperar(lambda: f.saidas == [1])
    finally:
        outra.destroy()


def test_principal_de_volta_por_outro_caminho_desfaz_a_espera(fechamento, monkeypatch):
    f = fechamento
    saves = [True]
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: saves[0])
    assert f.painel.principalFechando() is False
    f.painel.janelaFechada()
    _esperar()
    assert not QGuiApplication.quitOnLastWindowClosed()

    f.principal.show()  # por exemplo o `present` do fim de uma sessão
    saves[0] = False
    _esperar(limite=0.6)

    assert f.saidas == []
    assert not f.painel._espera.isActive()
    assert QGuiApplication.quitOnLastWindowClosed()


def test_espera_que_termina_restaura_o_sair_com_a_ultima_janela(fechamento, monkeypatch):
    f = fechamento
    saves = [True]
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: saves[0])
    assert f.painel.principalFechando() is False
    f.painel.janelaFechada()
    _esperar()
    saves[0] = False
    assert _esperar(lambda: f.saidas == [1])
    assert QGuiApplication.quitOnLastWindowClosed()


def test_segunda_abertura_durante_a_espera_traz_a_principal_e_nao_sai(fechamento, monkeypatch):
    f = fechamento
    saves = [True]
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: saves[0])
    outra = QWindow()
    outra.show()
    try:
        assert f.painel.principalFechando() is False
        f.painel.janelaFechada()
        _esperar()

        f.painel.mostrarPrincipal()
        assert f.principal.isVisible() and outra.isVisible()
        assert QGuiApplication.quitOnLastWindowClosed()
        saves[0] = False
        _esperar(limite=0.6)
        assert f.saidas == []  # a espera de sair foi desfeita: o app segue aberto
    finally:
        outra.destroy()


def test_quit_com_a_principal_escondida_e_saves_em_andamento_nao_e_recusado(fechamento, monkeypatch):
    """O `quit()` manda o `closing` também à principal escondida: ela deixa fechar, senão o app seguiria aberto com a
    sessão já encerrada pelo `saindo`."""
    f = fechamento
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    assert f.painel.principalFechando() is False
    f.painel.encerrando()  # o `saindo` do `quit()`, que depois manda o `closing` à principal escondida
    assert f.painel.principalFechando() is True
    assert f.sessao.fechando == 0


def test_principal_trazida_de_volta_por_fora_nao_fica_escondida(fechamento, flush_idle):
    """O fim de uma sessão (`sessao.present`) mostra a principal sem passar pelo painel."""
    f = fechamento
    tarefas.comecar("Importação", 1)
    flush_idle()
    f.painel.mostrar()
    assert f.painel.principalFechando() is False
    assert f.painel.principalEscondida
    f.principal.show()
    assert not f.painel.principalEscondida


def test_fechar_logo_depois_de_pedir_o_backup_dos_saves_esconde(fechamento, monkeypatch):
    """O backup conta desde o pedido: fechar o app antes de a thread chegar ao Ludusavi (a busca do nome, a espera
    pela trava) também não o perde."""
    f = fechamento
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    monkeypatch.setattr(backup_de_saves, "_biblioteca", list)
    monkeypatch.setattr(backup_de_saves, "_em_segundo_plano", lambda *_args: None)  # nem roda

    backup_de_saves.no_fim_da_sessao(SimpleNamespace(name="Meu Jogo"))
    assert f.painel.principalFechando() is False
    assert f.painel.aberta
    assert not f.principal.isVisible() and f.painel.principalEscondida


def test_fechar_a_principal_com_a_sessao_manual_e_saves_em_andamento_esconde(fechamento, monkeypatch):
    """Os saves (caso 1) vêm antes da sessão manual, que fecharia o app com o Ludusavi rodando."""
    f = fechamento
    sessao = ModeloDaSessao(FilaDeAvisos())
    sessao._manual = object()  # noqa: SLF001  (a janela "Jogando" na tela)
    sairs = []
    monkeypatch.setattr(sessao, "_sair", lambda: sairs.append(1))
    monkeypatch.setattr(shared, "sessao", sessao, raising=False)
    em_andamento = [True]
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: em_andamento[0])

    assert f.painel.principalFechando() is False
    _esperar()
    assert sairs == []
    assert not f.principal.isVisible() and f.painel.aberta

    # Sem saves, com a principal de volta e a janela das tarefas fechada, a sessão manual fecha o app como antes.
    em_andamento[0] = False
    f.painel.mostrarPrincipal()
    f.painel.janelaFechada()
    assert f.painel.principalFechando() is True
    _esperar()
    assert sairs == [1]
    sessao._manual = None  # noqa: SLF001


# Roda o `main()` de verdade num processo à parte, sobre uma pasta de dados temporária. A marca troca o
# `backup_de_saves.em_andamento`; os passos vêm por `QTimer`, depois das varreduras da abertura.
_FECHAR_COM_BACKUP = r"""
import json, os, sys, threading
from pathlib import Path
from types import SimpleNamespace

import requests


def _sem_rede(*_a, **_k):
    raise requests.ConnectionError("rede bloqueada no teste")


requests.sessions.Session.send = _sem_rede

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlEngine

from kyron import app as modulo_app, shared
from kyron.modelos import tarefas
from kyron.saves import backup_de_saves
from kyron.utils import single_instance

ANOTACOES = Path(sys.argv[1])
MODO = sys.argv[2]
anotado = {}


def anotar(**valores):
    anotado.update(valores)
    ANOTACOES.write_text(json.dumps(anotado), encoding="utf-8")


# A trava é a da pasta temporária, nunca a do Cartridges desta máquina (D76).
if single_instance.nomes()[0] == "Local\\io.github.joaomgabaldi.Cartridges.SingleInstance":
    sys.exit(3)
single_instance.present_running_instance = lambda: None
shared.schema.set_boolean("auto-import", False)
shared.schema.set_boolean("gamepad", False)
modulo_app.session_fita = SimpleNamespace(migrar_roxo_antigo=lambda: None, abrir=lambda: None, fechar=lambda: None)
modulo_app.session_wallpaper = SimpleNamespace(restaurar_orfaos=lambda: None)
# A pasta de dados vazia mostraria o assistente da primeira abertura (D86) no lugar da principal.
modulo_app.assistente.precisa_mostrar = lambda: False
backup_de_saves.atualizar_cache = lambda: None
marca = [False]
backup_de_saves.em_andamento = lambda: marca[0]

_fechar = modulo_app._fechar


def _fechar_anotado(*argumentos):
    _fechar(*argumentos)
    anotar(sobre_o_fim=True, saves_no_fim=marca[0])


modulo_app._fechar = _fechar_anotado


def janela(nome):
    return next((j for j in QGuiApplication.topLevelWindows() if j.objectName() == nome), None)


def principal():
    return next(j for j in QGuiApplication.topLevelWindows() if j.title() == "Kyron")


def passo_1():
    marca[0] = True
    principal().close()
    QTimer.singleShot(400, passo_2)


def passo_2():
    tarefas_ = janela("janelaDasTarefas")
    anotar(escondida=not principal().isVisible(), tarefas_visivel=bool(tarefas_ and tarefas_.isVisible()))
    QTimer.singleShot(200, passo_3)


def relogio():
    # Em até 15 s o processo sai sozinho; senão, sai com 7 (um `closing` recusado cancela o `quit()`).
    relogio = threading.Timer(15, os._exit, (7,))
    relogio.daemon = True
    relogio.start()


def passo_3():
    # Com os saves ainda em andamento: o app espera, sem janela à vista.
    janela("janelaDasTarefas").close()
    QTimer.singleShot(800, passo_4)


def passo_4():
    anotar(visiveis_na_espera=sum(1 for j in QGuiApplication.topLevelWindows() if j.isVisible()))
    marca[0] = False  # os saves acabaram
    relogio()


# O `quit()` de dentro do app (o reinício, o fim da sessão do Windows) com a principal à vista e trabalho em andamento.
def quit_com_trabalho():
    if MODO == "quit_saves":
        marca[0] = True
    else:
        tarefas.comecar("Importação", 1)
        QQmlEngine.contextForObject(principal()).contextProperty("painelDasTarefas").mostrar()
    QTimer.singleShot(400, quit_agora)


def quit_agora():
    tarefas_ = janela("janelaDasTarefas")
    anotar(principal_visivel=principal().isVisible(), tarefas_visivel=bool(tarefas_ and tarefas_.isVisible()))
    relogio()
    QCoreApplication.quit()


# A janela das tarefas aberta, sem tarefa nenhuma, e a principal fechada: o `Loader` desfaz a janela das tarefas.
def fechar_as_duas():
    QQmlEngine.contextForObject(principal()).contextProperty("painelDasTarefas").mostrar()
    QTimer.singleShot(400, fechar_a_principal)


def fechar_a_principal():
    tarefas_ = janela("janelaDasTarefas")
    anotar(tarefas_visivel=bool(tarefas_ and tarefas_.isVisible()))
    relogio()
    principal().close()


_comecar = modulo_app._comecar_varreduras


def _comecar_e_seguir(*argumentos):
    _comecar(*argumentos)
    QTimer.singleShot(500, {"fechar_tarefas": passo_1, "fechar_as_duas": fechar_as_duas}.get(MODO, quit_com_trabalho))


modulo_app._comecar_varreduras = _comecar_e_seguir
codigo = modulo_app.main(sys.argv[:1])
anotar(codigo=codigo)
sys.exit(codigo)
"""


def _main_num_processo(tmp_path, modo):
    """Roda o `_FECHAR_COM_BACKUP` no `modo` pedido; devolve o que ele anotou."""
    dados = tmp_path / "dados"
    dados.mkdir()
    anotacoes = tmp_path / "anotacoes.json"
    registro = rf"Software\KyronTestes\fechar-{uuid.uuid4()}"
    ambiente = {**os.environ, "KYRON_DADOS": str(dados), "KYRON_REGISTRO": registro, "QT_QPA_PLATFORM": "offscreen"}
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", _FECHAR_COM_BACKUP, str(anotacoes), modo], cwd=RAIZ, env=ambiente,
            capture_output=True, text=True, timeout=90, check=False,
        )  # fmt: skip
    finally:
        _apagar_chave(winreg.HKEY_CURRENT_USER, registro)  # o roteiro grava "auto-import" e "gamepad"
    assert resultado.returncode == 0, resultado.stderr[-3000:]
    return json.loads(anotacoes.read_text(encoding="utf-8"))


def test_fechar_as_tarefas_depois_do_fim_do_backup_encerra_o_app(tmp_path):
    """Com o backup rodando a principal some e a janela das tarefas fica. Fechada a janela das tarefas
    ainda no meio do backup, o processo segue vivo sem janela à vista; o backup acaba, e o app encerra pelo
    `aboutToQuit` inteiro."""
    anotado = _main_num_processo(tmp_path, "fechar_tarefas")
    assert anotado == {
        "escondida": True, "tarefas_visivel": True, "visiveis_na_espera": 0, "sobre_o_fim": True, "saves_no_fim": False,
        "codigo": 0,
    }  # fmt: skip


def test_quit_com_a_principal_a_vista_e_saves_em_andamento_encerra(tmp_path):
    """Um `quit()` de dentro do app (o reinício, o fim da sessão do Windows) não é recusado pelo caso 1 (saves em andamento)."""
    anotado = _main_num_processo(tmp_path, "quit_saves")
    assert anotado == {"principal_visivel": True, "tarefas_visivel": False, "sobre_o_fim": True, "saves_no_fim": True, "codigo": 0}


def test_quit_com_a_janela_das_tarefas_e_uma_tarefa_encerra(tmp_path):
    """Nem pelo caso 2: a janela das tarefas aberta e uma tarefa rodando."""
    anotado = _main_num_processo(tmp_path, "quit_tarefa")
    assert anotado == {"principal_visivel": True, "tarefas_visivel": True, "sobre_o_fim": True, "saves_no_fim": False, "codigo": 0}


def test_fechar_a_principal_com_a_janela_das_tarefas_e_sem_tarefa_encerra_o_processo(tmp_path):
    """O app de verdade: sem a saída agendada o processo ficava vivo e invisível (o relógio o derruba com 7)."""
    anotado = _main_num_processo(tmp_path, "fechar_as_duas")
    assert anotado == {"tarefas_visivel": True, "sobre_o_fim": True, "saves_no_fim": False, "codigo": 0}


def test_fechar_com_a_janela_das_tarefas_aberta_e_sem_tarefa_encerra_o_app(fechamento):
    """O `Loader` desfaz a janela das tarefas sem evento de fechamento: o Qt não vê a "última janela fechada" e o
    processo ficaria vivo e invisível. A saída é agendada, como a da sessão."""
    f = fechamento
    f.painel.mostrar()
    assert f.painel.principalFechando() is True
    assert _esperar(lambda: f.saidas == [1])


@pytest.mark.parametrize(
    ("antes", "escondida", "depois"),
    [
        (Qt.WindowState.WindowMaximized, True, Qt.WindowState.WindowMaximized),
        (Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized, False, Qt.WindowState.WindowMaximized),
        (Qt.WindowState.WindowNoState, True, Qt.WindowState.WindowNoState),
    ],
)
def test_mostrar_principal_mantem_o_estado_e_tira_so_o_minimizado(fechamento, flush_idle, antes, escondida, depois):
    """`QWindow.show()` chama `showNormal()` e perderia a maximização: a principal volta como estava."""
    f = fechamento
    f.principal.setWindowStates(antes)
    if escondida:
        f.painel.mostrar()
        tarefas.comecar("Importação", 1)
        flush_idle()
        assert f.painel.principalFechando() is False
        assert not f.principal.isVisible()
    f.painel.mostrarPrincipal()
    assert f.principal.isVisible()
    assert f.principal.windowStates() == depois


def test_mostrar_principal_durante_a_espera_devolve_as_janelas_maximizadas(fechamento, monkeypatch):
    """`_desfazer_a_espera` traz de volta as janelas escondidas pela espera dos saves (a "Jogando", por exemplo) sem
    perder a maximização."""
    f = fechamento
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    outra = QWindow()
    outra.setVisible(True)
    outra.setWindowStates(Qt.WindowState.WindowMaximized)
    try:
        assert f.painel.principalFechando() is False
        f.painel.janelaFechada()  # a espera do fim dos saves: tudo some
        assert not outra.isVisible() and f.painel._espera.isActive()
        f.painel.mostrarPrincipal()
        assert outra.isVisible()
        assert outra.windowStates() & Qt.WindowState.WindowMaximized
    finally:
        outra.destroy()


def test_nome_longo_alarga_a_janela_e_o_vazio_e_centrado(cena, flush_idle):
    """O nome não quebra e a janela cresce em largura (360 de mínimo); o aviso de vazio fica centrado."""
    tarefa = tarefas.comecar("Um nome de tarefa muito comprido " * 4, 3)
    flush_idle()
    janela = cena.abrir_a_janela()
    _esperar()
    assert janela.width() > 360
    assert janela.minimumWidth() == janela.maximumWidth() == janela.width()
    tarefa.terminar()
    flush_idle()
    _esperar()
    vazio = cena.achar("avisoDeVazio")
    from tests.apoio_janela_atualizacao import avaliar  # noqa: PLC0415

    assert avaliar(vazio, "horizontalAlignment === Text.AlignHCenter") is True
    assert janela.width() == 360


def test_segundo_erro_com_o_aviso_aberto_nao_troca_o_texto_e_libera_os_dois(app_qt):
    """O aviso à vista não muda por baixo de quem lê; ao fechá-lo, os dois erros inesperados são liberados."""
    painel = PainelDasTarefas()
    pedidos, liberados = [], []
    painel.avisoPedido.connect(lambda titulo, corpo: pedidos.append((titulo, corpo)))
    painel.pedir_aviso("Erro 1", "primeiro", lambda: liberados.append(1))
    painel.pedir_aviso("Erro 2", "segundo", lambda: liberados.append(2))
    assert pedidos == [("Erro 1", "primeiro")]
    painel.avisoFechado()
    assert liberados == [1, 2]
    painel.pedir_aviso("Erro 3", "terceiro", lambda: liberados.append(3))  # fechado, o próximo aviso abre de novo
    assert pedidos[-1] == ("Erro 3", "terceiro")


def test_o_vigia_do_hover_so_ocupa_o_canto_e_nao_a_pagina(cena, flush_idle):
    # Um HoverHandler do tamanho da página tirava o hover das capas abaixo do botão.
    vigia = cena.achar("vigiaDoCanto")
    _chamar(cena.botao, "recolher")
    assert vigia.property("width") == 16 and vigia.property("height") == 72
    assert vigia.property("y") == 600 - 72
    tarefas.comecar("Importação", 1)
    flush_idle()
    assert _a_vista(cena)
    assert vigia.property("width") == 72 and vigia.property("height") == 72
