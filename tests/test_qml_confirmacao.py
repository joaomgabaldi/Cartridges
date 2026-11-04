# test_qml_confirmacao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A pergunta do domínio (`Aplicativo.pedir_confirmacao`, D72) e a fila de diálogos, no `Aplicativo.qml` inteiro."""

import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.modelos.saves import SavesDoJogo
from cartridges.modelos.preferencias import Preferencias
from cartridges.modelos.restauracao import ContinuacaoDaRestauracao
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.ponte import Ponte

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
QQuickStyle.setStyle("Basic")


def _esperar(ate=None, limite=5.0):
    limite = 0.3 if ate is None else limite
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(20, laco.quit)
        laco.exec()
        if ate is not None and ate():
            return True
    return ate is None


def _eh_texto_puro(texto):
    """`textFormat` é um enum do QtQuick que o Python não converte: a conta fica no QML."""
    return QQmlExpression(QQmlEngine.contextForObject(texto), texto, "textFormat === Text.PlainText").evaluate()[0]


def _achar(raiz, nome):
    pilha = [raiz]
    while pilha:
        atual = pilha.pop()
        if atual.objectName() == nome:
            return atual
        pilha.extend(atual.children())
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
        elif isinstance(atual, QQuickWindow):
            pilha.append(atual.contentItem())
    return None


class _DetalhesFalsos(QObject):
    alterado = Signal()
    jogoId = ""  # noqa: N815
    loja = SimpleNamespace(get=lambda _id: None)


class _Janela:
    def __init__(self):
        self.modelo = ModeloDaBiblioteca()
        self.filtros = FiltrosDaBiblioteca(self.modelo)
        self.ponte = Ponte()
        self.aplicativo = Aplicativo(self.ponte.fila)
        self.edicao = ModeloDaEdicao(self.aplicativo)
        self.historico = HistoricoDeSessoes(SimpleNamespace(get=lambda _id: None))
        self.saves = SavesDoJogo(self.aplicativo)
        self.preferencias = shared.preferencias = Preferencias(self.ponte.fila, lambda: True)
        self.painel_das_tarefas = PainelDasTarefas()
        self.restauracao = ContinuacaoDaRestauracao(self.aplicativo)
        self.big_picture = BigPicture(self.modelo)
        self.sessao = ModeloDaSessao(self.ponte.fila)
        self.conquistas = ConquistasDoJogo(_DetalhesFalsos(), self.sessao)
        self.motor = QQmlEngine()
        from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
        self.motor.addImageProvider("icone", ProvedorDeIcones())
        self.motor.addImageProvider("fundo", ProvedorDoFundo())
        contexto = self.motor.rootContext()
        for nome, valor in (
            ("filtros", self.filtros),
            ("paginaTodos", FiltroDaPagina(self.modelo, self.filtros, "biblioteca")),
            ("paginaZerados", FiltroDaPagina(self.modelo, self.filtros, "zerados")),
            ("aplicativo", self.aplicativo),
            ("ponte", self.ponte),
            ("controle", ControleDaGrade(estado_do_app=lambda: Qt.ApplicationState.ApplicationInactive)),
            ("edicao", self.edicao),
            ("bigPicture", self.big_picture),
            ("sessao", self.sessao),
            ("historico", self.historico),
            ("saves", self.saves),
            ("conquistasDoJogo", self.conquistas),
            ("preferencias", self.preferencias),
            ("painelDasTarefas", self.painel_das_tarefas),
            ("restauracao", self.restauracao),
        ):
            contexto.setContextProperty(nome, valor)
        componente = QQmlComponent(self.motor, QUrl.fromLocalFile(str(QML / "Aplicativo.qml")))
        self.janela = componente.createWithInitialProperties({"semAgente": True})
        assert self.janela is not None, componente.errorString()
        self.componente = componente
        _esperar()

    def achar(self, nome):
        objeto = _achar(self.janela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def dentro_da_confirmacao(self, nome):
        objeto = _achar(self.achar("confirmacaoDoApp"), nome)
        assert objeto is not None, f"sem objeto {nome!r} na confirmação"
        return objeto

    def foco_na_confirmacao(self):
        item = self.janela.property("activeFocusItem")
        while item is not None:
            if item.objectName() == "confirmacaoDoApp":
                return True
            item = item.parentItem()
        return False

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()


@pytest.fixture
def janela(app_qt):  # noqa: ARG001
    j = _Janela()
    yield j
    j.fechar()


def _responder_pelo_botao(janela, nome):
    """Aciona o botão pelo teclado: o foco vai a ele e Enter o clica."""
    janela.dentro_da_confirmacao(nome).forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)


def test_confirmacao_mostra_o_texto_em_texto_puro(janela):
    titulo = "Restaurar Tom & <b>Jerry</b>?"
    janela.aplicativo.pedir_confirmacao(titulo, "Corpo & <i>x</i>", "Restaurar", lambda _c: None)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    texto = janela.dentro_da_confirmacao("tituloDoDialogo")
    assert texto.property("text") == titulo
    assert _eh_texto_puro(texto) is True
    corpo = janela.dentro_da_confirmacao("corpoDoDialogo")
    assert corpo.property("text") == "Corpo & <i>x</i>"
    assert _eh_texto_puro(corpo) is True
    assert janela.dentro_da_confirmacao("botaoConfirmarDoDialogo").property("text") == "Restaurar"
    # Com a pergunta à vista a janela não aceita atalhos arrastados.
    assert janela.achar("alvoDeSoltar").property("enabled") is False


def test_confirmacao_destrutiva_comeca_no_cancelar_e_diz_cancelar(janela):
    janela.aplicativo.pedir_confirmacao("Excluir?", "Corpo", "Excluir", lambda _c: None, destrutivo=True)
    assert _esperar(lambda: janela.achar("confirmacaoDoApp").property("visible") is True)
    cancelar = janela.dentro_da_confirmacao("botaoCancelarDoDialogo")
    assert cancelar.property("text") == "Cancelar"
    assert _esperar(lambda: cancelar.property("activeFocus") is True)
    assert janela.dentro_da_confirmacao("botaoConfirmarDoDialogo").property("activeFocus") is False


def test_confirmacao_simples_diz_dispensar(janela):
    janela.aplicativo.pedir_confirmacao("Saves sem backup", "Corpo", "Editar jogo", lambda _c: None)
    assert _esperar(lambda: janela.achar("confirmacaoDoApp").property("visible") is True)
    assert janela.dentro_da_confirmacao("botaoCancelarDoDialogo").property("text") == "Dispensar"
    # Como o AdwAlertDialog sem resposta padrão (`create_dialog`): o foco começa no primeiro botão.
    sair = janela.dentro_da_confirmacao("botaoCancelarDoDialogo")
    assert _esperar(lambda: sair.property("activeFocus") is True)


def test_esc_responde_que_nao(janela):
    respostas = []
    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", respostas.append)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: confirmacao.property("visible") is False)
    assert respostas == [False]


def test_confirmar_responde_que_sim_uma_vez(janela):
    respostas = []
    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", respostas.append)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    _responder_pelo_botao(janela, "botaoConfirmarDoDialogo")
    assert _esperar(lambda: confirmacao.property("visible") is False)
    assert respostas == [True]


def test_o_pedido_novo_cobre_a_confirmacao_e_ela_volta_ao_fechar(janela):
    """R5: pilha, como o `Adw.Dialog.present` da `main`: o mais recente é o que se vê e responde."""
    respostas = []
    janela.aplicativo.pedir_confirmacao("Primeira", "A", "Sim", lambda c: respostas.append(("a", c)))
    janela.aplicativo.pedir_confirmacao("Segunda", "B", "Sim", lambda c: respostas.append(("b", c)), destrutivo=True)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    assert janela.dentro_da_confirmacao("tituloDoDialogo").property("text") == "Segunda"
    assert janela.dentro_da_confirmacao("botaoCancelarDoDialogo").property("text") == "Cancelar"
    assert respostas == []

    _responder_pelo_botao(janela, "botaoConfirmarDoDialogo")
    assert _esperar(lambda: janela.dentro_da_confirmacao("tituloDoDialogo").property("text") == "Primeira")
    assert confirmacao.property("visible") is True
    assert janela.dentro_da_confirmacao("botaoCancelarDoDialogo").property("text") == "Dispensar"
    assert respostas == [("b", True)]

    janela.janela.show()
    janela.janela.requestActivate()
    assert _esperar(janela.foco_na_confirmacao)
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: confirmacao.property("visible") is False)
    assert respostas == [("b", True), ("a", False)]


def test_o_dialogo_novo_cobre_o_anterior_e_ele_volta_ao_fechar(janela):
    fechados = []
    janela.aplicativo.pedir_dialogo("Um", "A", [], lambda: fechados.append(1))
    janela.aplicativo.pedir_dialogo("Dois", "B", [], lambda: fechados.append(2))
    dialogo = janela.achar("dialogoDeErros")
    assert _esperar(lambda: dialogo.property("visible") is True)
    assert dialogo.property("titulo") == "Dois"
    assert fechados == []

    dialogo.fechar()
    assert _esperar(lambda: dialogo.property("titulo") == "Um")
    assert dialogo.property("visible") is True
    assert fechados == [2]

    dialogo.fechar()
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert fechados == [2, 1]


def test_o_dialogo_cobre_a_confirmacao_e_o_teclado_e_do_de_cima(janela):
    janela.janela.show()
    janela.janela.requestActivate()
    respostas, fechados = [], []
    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", respostas.append)
    janela.aplicativo.pedir_dialogo("Aviso", "Corpo", [], lambda: fechados.append(1))
    confirmacao = janela.achar("confirmacaoDoApp")
    dialogo = janela.achar("dialogoDeErros")
    assert _esperar(lambda: dialogo.property("visible") is True)
    # A pergunta fica por baixo, à vista; o de cima é o último a abrir, e só ele recebe o teclado.
    assert confirmacao.property("visible") is True
    assert dialogo.property("z") > confirmacao.property("z")
    assert _esperar(lambda: janela.janela.property("activeFocusItem").objectName() == "botaoDoDialogo")

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)  # responde ao diálogo, não à pergunta
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert confirmacao.property("visible") is True
    assert fechados == [1]
    assert respostas == []
    assert _esperar(janela.foco_na_confirmacao)

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)  # o foco voltou à pergunta
    assert _esperar(lambda: confirmacao.property("visible") is False)
    assert respostas == [False]


def test_a_confirmacao_cobre_o_dialogo_mesmo_pedida_depois(janela):
    janela.aplicativo.pedir_dialogo("Aviso", "Corpo", [], lambda: None)
    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", lambda _c: None)
    confirmacao = janela.achar("confirmacaoDoApp")
    dialogo = janela.achar("dialogoDeErros")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    assert confirmacao.property("z") > dialogo.property("z")


def test_confirmacao_por_cima_das_preferencias(janela):
    janela.janela.show()
    janela.janela.requestActivate()
    assert janela.preferencias.abrir()
    assert _esperar(lambda: janela.achar("dialogoDePreferencias").property("visible") is True)
    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", lambda _c: None)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    assert _esperar(janela.foco_na_confirmacao)
    # A pergunta está à frente: o Tab circula entre os botões dela, sem sair para as Preferências.
    QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
    _esperar()
    assert janela.foco_na_confirmacao()
    assert janela.preferencias.aberto is True


def test_tab_nao_tira_o_foco_do_aviso_e_esc_ainda_fecha(janela):
    janela.janela.show()
    janela.janela.requestActivate()
    fechados = []
    janela.aplicativo.pedir_dialogo("Aviso", "Corpo", [], lambda: fechados.append(1))
    dialogo = janela.achar("dialogoDeErros")
    assert _esperar(lambda: dialogo.property("visible") is True)

    def foco_no_dialogo():
        item = janela.janela.property("activeFocusItem")
        while item is not None:
            if item is dialogo:
                return True
            item = item.parentItem()
        return False

    assert _esperar(foco_no_dialogo)
    for tecla in (Qt.Key.Key_Tab, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
        QTest.keyClick(janela.janela, tecla)
        _esperar()
        assert foco_no_dialogo()
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert fechados == [1]


def test_erro_a_confirmacao_b_erro_c_dispensar_c_deixa_o_foco_em_b(janela):
    """m5: o diálogo de erros reaproveitado (C) fecha com B ainda na tela: o foco fica em B, não vai à grade de trás."""
    janela.janela.show()
    janela.janela.requestActivate()
    from tests.apoio_qml_biblioteca import _achar as achar_rapido  # noqa: PLC0415  (a daqui é exponencial na árvore inteira)

    achar_rapido(janela.janela, "grade").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    janela.aplicativo.pedir_dialogo("A", "Corpo", [], lambda: None)
    janela.aplicativo.pedir_confirmacao("B?", "Corpo", "Sim", lambda _c: None)
    janela.aplicativo.pedir_dialogo("C", "Corpo", [], lambda: None)
    erros = janela.achar("dialogoDeErros")
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: erros.property("titulo") == "C" and erros.property("visible") is True)
    erros.fechar()
    assert _esperar(lambda: erros.property("visible") is False)
    assert confirmacao.property("visible") is True
    assert _esperar(janela.foco_na_confirmacao)
    _esperar()
    assert janela.foco_na_confirmacao()
