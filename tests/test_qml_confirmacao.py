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
from cartridges.modelos.sessao import ModeloDaSessao
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
        self.big_picture = BigPicture(self.modelo)
        self.sessao = ModeloDaSessao(self.ponte.fila)
        self.conquistas = ConquistasDoJogo(_DetalhesFalsos(), self.sessao)
        self.motor = QQmlEngine()
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
    confirmar = janela.dentro_da_confirmacao("botaoConfirmarDoDialogo")
    assert _esperar(lambda: confirmar.property("activeFocus") is True)


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


def test_dois_pedidos_de_confirmacao_aparecem_um_depois_do_outro(janela):
    respostas = []
    janela.aplicativo.pedir_confirmacao("Primeira", "A", "Sim", lambda c: respostas.append(("a", c)))
    janela.aplicativo.pedir_confirmacao("Segunda", "B", "Sim", lambda c: respostas.append(("b", c)), destrutivo=True)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    # O segundo espera: a tela ainda mostra o primeiro e nenhuma resposta foi dada.
    assert janela.dentro_da_confirmacao("tituloDoDialogo").property("text") == "Primeira"
    assert respostas == []

    _responder_pelo_botao(janela, "botaoConfirmarDoDialogo")
    assert _esperar(lambda: janela.dentro_da_confirmacao("tituloDoDialogo").property("text") == "Segunda")
    assert confirmacao.property("visible") is True
    assert janela.dentro_da_confirmacao("botaoCancelarDoDialogo").property("text") == "Cancelar"
    assert respostas == [("a", True)]

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: confirmacao.property("visible") is False)
    assert respostas == [("a", True), ("b", False)]


def test_dois_dialogos_seguidos_aparecem_um_depois_do_outro(janela):
    fechados = []
    janela.aplicativo.pedir_dialogo("Um", "A", [], lambda: fechados.append(1))
    janela.aplicativo.pedir_dialogo("Dois", "B", [], lambda: fechados.append(2))
    dialogo = janela.achar("dialogoDeErros")
    assert _esperar(lambda: dialogo.property("visible") is True)
    assert dialogo.property("titulo") == "Um"
    assert fechados == []

    dialogo.fechar()
    assert _esperar(lambda: dialogo.property("titulo") == "Dois")
    assert dialogo.property("visible") is True
    assert fechados == [1]

    dialogo.fechar()
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert fechados == [1, 2]


def test_dialogo_e_confirmacao_seguidos_aparecem_um_depois_do_outro(janela):
    janela.janela.show()
    janela.janela.requestActivate()
    respostas, fechados = [], []
    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", respostas.append)
    janela.aplicativo.pedir_dialogo("Aviso", "Corpo", [], lambda: fechados.append(1))
    confirmacao = janela.achar("confirmacaoDoApp")
    dialogo = janela.achar("dialogoDeErros")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    # O diálogo espera a resposta da pergunta: não aparece por baixo dela nem rouba o teclado.
    assert dialogo.property("visible") is False
    assert _esperar(janela.foco_na_confirmacao)

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)  # responde à pergunta, não ao diálogo
    assert _esperar(lambda: dialogo.property("visible") is True)
    assert confirmacao.property("visible") is False
    assert respostas == [False]
    assert fechados == []

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)  # agora o diálogo é quem recebe o teclado
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert fechados == [1]


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
