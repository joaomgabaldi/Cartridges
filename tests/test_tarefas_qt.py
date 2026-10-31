# test_tarefas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O botão do canto e a janela "Tarefas em andamento" (QML offscreen, D77); a regra de quando o botão pode aparecer."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import (
    Q_ARG,
    QEventLoop,
    QMetaObject,
    QCoreApplication,
    QPoint,
    QPointF,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QWheelEvent
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from cartridges.modelos import tarefas
from cartridges.modelos.tarefas import PainelDasTarefas, pode_mostrar
from cartridges.utils import window_geometry

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
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
        source: "JanelaDasTarefas.qml"
        onLoaded: item.alvo = botao.alvo
    }
}
"""


class _Cena:
    def __init__(self):
        self.painel = PainelDasTarefas()
        self.motor = QQmlEngine()
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
    flags = janela.flags()
    assert not flags & Qt.WindowType.WindowMaximizeButtonHint
    assert flags & Qt.WindowType.WindowMinimizeButtonHint
    assert flags & Qt.WindowType.WindowCloseButtonHint
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
    painel.alterado.connect(lambda: avisos.append(painel.quantas))
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
