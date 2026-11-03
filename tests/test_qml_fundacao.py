# test_qml_fundacao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A fundação visual da auditoria GTK × Qt: `Tema`, `MolduraDoDialogo`, a pilha dos diálogos e o aviso na janela das tarefas."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QMetaObject, QObject, QPointF, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtTest import QTest

from cartridges.modelos import tarefas
from cartridges.modelos.provedor_de_icones import ProvedorDeIcones
from cartridges.utils import ajustes_do_windows, erro_inesperado
from tests.apoio_qml_biblioteca import QML, _achar, _App, _esperar, _jogos
from tests.apoio_qml_detalhes import _abrir_pelo_cartao, _clicar

_JANELA = """
import QtQuick
import QtQuick.Layouts
import "file:///%s"
Window {
    width: 1170
    height: 795
    visible: true
    property int fechamentos: 0
    property int perdidos: 0
    Item { id: quem; objectName: "quem"; focus: true; width: 10; height: 10; activeFocusOnTab: true }
    MolduraDoDialogo {
        id: moldura
        objectName: "moldura"
        largura: 640
        altura: 2000
        focoInicial: botao
        onFecharPedido: { fechamentos++; aberto = false }
        onRetornoPerdido: perdidos++
        CabecalhoDoDialogo { titulo: "Título"; onFechar: moldura.fecharPedido() }
        Botao { id: botao; objectName: "botao"; text: "Ok" }
    }
}
"""


@pytest.fixture
def janela(app_qt):
    motor = QQmlEngine()
    motor.addImageProvider("icone", ProvedorDeIcones())
    componente = QQmlComponent(motor)
    componente.setData((_JANELA % QML.as_posix()).encode("utf-8"), QUrl("file:///fundacao.qml"))
    raiz = componente.create()
    assert raiz is not None, componente.errorString()
    raiz.requestActivate()
    assert _esperar(lambda: raiz.isExposed())
    yield raiz
    raiz.close()
    raiz.deleteLater()


def test_medidas_do_adw_dialog(janela):
    moldura = _achar(janela.contentItem(), "moldura")
    moldura.setProperty("aberto", True)
    cartao = _achar(moldura, "cartaoDoDialogo")
    assert _esperar(lambda: moldura.property("visible") is True)
    # Margem vertical de 30 a 795 de altura (gabarito); 640 de largura, centrado; raio 15.
    assert (cartao.property("x"), cartao.property("y")) == (265, 30)
    assert (cartao.property("width"), cartao.property("height")) == (640, 735)
    assert cartao.property("radius") == 15
    # O cabeçalho é um filho do layout: 47 de altura.
    cabecalho = _achar(moldura, "tituloDoCabecalho").parentItem()
    assert cabecalho.property("height") == 47


def test_esc_pede_e_o_foco_volta_a_quem_abriu(janela):
    moldura = _achar(janela.contentItem(), "moldura")
    quem = _achar(janela.contentItem(), "quem")
    quem.forceActiveFocus()
    moldura.setProperty("aberto", True)
    botao = _achar(moldura, "botao")
    assert _esperar(lambda: botao.property("activeFocus") is True)
    QTest.keyClick(janela, Qt.Key.Key_Escape)
    assert janela.property("fechamentos") == 1
    assert _esperar(lambda: quem.property("activeFocus") is True)
    assert janela.property("perdidos") == 0


def test_nao_fechavel_ignora_o_esc(janela):
    moldura = _achar(janela.contentItem(), "moldura")
    moldura.setProperty("fechavel", False)
    moldura.setProperty("aberto", True)
    botao = _achar(moldura, "botao")
    assert _esperar(lambda: botao.property("activeFocus") is True)
    QTest.keyClick(janela, Qt.Key.Key_Escape)
    assert moldura.property("aberto") is True


def test_clique_fora_nao_fecha_o_flutuante_e_fecha_a_folha(janela):
    """`dialog_backdrop.py` da `main`: fora do diálogo flutuante, nada; na folha de baixo, fecha."""
    moldura = _achar(janela.contentItem(), "moldura")
    moldura.setProperty("aberto", True)
    assert _esperar(lambda: moldura.property("visible") is True)
    _esperar(limite=0.05)
    QTest.mouseClick(janela, Qt.MouseButton.LeftButton, pos=_ponto(10, 400))
    assert janela.property("fechamentos") == 0
    janela.setWidth(400)
    assert _esperar(lambda: moldura.property("emFolha") is True)
    QTest.mouseClick(janela, Qt.MouseButton.LeftButton, pos=_ponto(200, 5))
    assert janela.property("fechamentos") == 1


def _ponto(x, y):
    from PySide6.QtCore import QPoint  # noqa: PLC0415

    return QPoint(x, y)


# --- animação: em outro processo, sem a opção dos testes ---------------------------------------------

_ANIMADA = r"""
import builtins, sys, time
builtins._ = lambda m: m
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlComponent, QQmlEngine
from cartridges.modelos.provedor_de_icones import ProvedorDeIcones
app = QGuiApplication([])
motor = QQmlEngine()
motor.addImageProvider("icone", ProvedorDeIcones())
c = QQmlComponent(motor)
c.setData(("import QtQuick\nimport 'file:///%s'\nWindow { width: 800; height: 600; visible: true; "
           "MolduraDoDialogo { objectName: 'm'; largura: 300 } }" % sys.argv[1]).encode(), QUrl("file:///a.qml"))
j = c.create()
assert j is not None, c.errorString()
m = j.contentItem().childItems()[0]
def girar(ms):
    l = QEventLoop(); QTimer.singleShot(ms, l.quit); l.exec()
m.setProperty("aberto", True)
assert m.property("visible") is True
maior = 0
for _ in range(40):
    girar(10)
    maior = max(maior, m.property("progresso"))
assert maior > 1.02, f"a mola passa de 1 ao abrir: {maior}"
assert abs(m.property("progresso") - 1) < 1e-6, m.property("progresso")
m.setProperty("aberto", False)
assert m.property("visible") is True, "continua à vista durante a saída"
inicio = time.monotonic()
while m.property("visible") and time.monotonic() - inicio < 2:
    girar(5)
    assert m.property("progresso") >= -1e-6, "ao fechar não passa de 0"
duracao = time.monotonic() - inicio
assert m.property("visible") is False
assert duracao < 0.6, duracao
print("OK")
"""


def test_a_mola_da_libadwaita_ao_abrir_e_fechar():
    raiz = Path(__file__).resolve().parent.parent
    ambiente = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(raiz))
    rodou = subprocess.run(
        [sys.executable, "-c", _ANIMADA, QML.as_posix()], env=ambiente, capture_output=True, text=True, timeout=60, check=False
    )
    assert "OK" in rodou.stdout, rodou.stdout + rodou.stderr


# --- Tema ---------------------------------------------------------------------------------------------


def test_cor_de_destaque_vem_crua_do_registro(monkeypatch):
    class Chave:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(ajustes_do_windows.winreg, "OpenKey", lambda *_a: Chave())
    monkeypatch.setattr(ajustes_do_windows.winreg, "QueryValueEx", lambda *_a: (0xFFD47800, 4))
    assert ajustes_do_windows.cor_de_destaque() == "#0078d4"


@pytest.mark.parametrize("valor", ["#0078d4", bytes([0, 120, 212, 255])])  # REG_SZ, REG_BINARY de um tema de terceiros
def test_cor_de_destaque_que_nao_e_dword_e_ignorada(monkeypatch, valor):
    class Chave:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    monkeypatch.setattr(ajustes_do_windows.winreg, "OpenKey", lambda *_a: Chave())
    monkeypatch.setattr(ajustes_do_windows.winreg, "QueryValueEx", lambda *_a: (valor, 1))
    assert ajustes_do_windows.cor_de_destaque() is None


def test_cor_de_destaque_sem_a_chave(monkeypatch):
    def falha(*_a):
        raise OSError

    monkeypatch.setattr(ajustes_do_windows.winreg, "OpenKey", falha)
    assert ajustes_do_windows.cor_de_destaque() is None
    ajustes_do_windows.aplicar_cor_de_destaque()  # não levanta


# --- B05: o erro com a principal escondida vai à janela das tarefas ----------------------------------


class _PainelFalso(QObject):
    def __init__(self):
        super().__init__()
        self.pedidos = []
        self.aberta = True
        self.principalEscondida = True

    def pedir_aviso(self, titulo, corpo, ao_fechar):
        self.pedidos.append((titulo, corpo, ao_fechar))


def test_erro_com_a_principal_escondida_abre_na_janela_das_tarefas(app_qt, monkeypatch):
    painel = _PainelFalso()
    monkeypatch.setattr(tarefas, "painel_aberto_sem_a_principal", lambda: painel)

    class Aplicativo:
        pedir_dialogo = None  # nunca chamado

    monkeypatch.setattr(erro_inesperado.shared, "aplicativo", Aplicativo(), raising=False)
    erro_inesperado._abrir()  # noqa: SLF001
    assert [p[0] for p in painel.pedidos] == ["Ocorreu um erro inesperado"]


def test_painel_so_conta_com_a_janela_aberta_e_a_principal_escondida(monkeypatch):
    import weakref  # noqa: PLC0415

    painel = _PainelFalso()
    monkeypatch.setattr(tarefas, "_painel", weakref.ref(painel))
    assert tarefas.painel_aberto_sem_a_principal() is painel
    painel.aberta = False
    assert tarefas.painel_aberto_sem_a_principal() is None
    painel.aberta, painel.principalEscondida = True, False
    assert tarefas.painel_aberto_sem_a_principal() is None


# --- J05, J01, J02, B14: a janela de verdade ---------------------------------------------------------


@pytest.fixture
def app(app_qt):
    aplicacao = _App(_jogos((1, "Alfa", {})))
    aplicacao.janela.show()
    yield aplicacao
    aplicacao.fechar()


def _centro(item):
    return item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()


def test_o_clique_atravessa_a_area_e_chega_ao_botao_da_barra(app):
    """A área ocupa a janela inteira, por cima da barra, e não pode roubar o clique dela."""
    botao = app.achar("botaoMenu")
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, pos=_centro(botao))
    assert _esperar(lambda: app.achar("menuPrincipal").property("opened") is True)


def test_um_modal_cobre_e_tranca_a_barra(app):
    barra = app.achar("barraDeTitulo")
    assert barra.property("enabled") is True
    app.aplicativo.pedir_confirmacao("Pergunta?", "Corpo", "Sim", lambda _c: None)
    assert _esperar(lambda: barra.property("enabled") is False)
    confirmacao = app.achar("confirmacaoDoApp")
    # Cobre da primeira linha da janela em diante, e a página fica abaixo da barra.
    assert confirmacao.mapToScene(QPointF(0, 0)).y() == 0
    assert app.achar("pagina").property("y") == barra.property("height") == 47
    botao = app.achar("botaoMenu")
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, pos=_centro(botao))
    assert app.achar("menuPrincipal").property("opened") is False
    confirmacao.setProperty("aberto", False)
    app.aplicativo.confirmacaoRespondida(False)
    assert _esperar(lambda: barra.property("enabled") is True)


def test_a_confirmacao_de_excluir_da_pagina_do_jogo_tranca_a_barra(app):
    """J05: o diálogo de PaginaDoJogo também trava e cobre a barra (nada de Voltar com a pergunta aberta)."""
    pagina = _abrir_pelo_cartao(app)
    barra = app.achar("barraDeTitulo")
    assert barra.property("enabled") is True
    QMetaObject.invokeMethod(_achar(pagina, "botaoExcluir"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: barra.property("enabled") is False)
    assert barra.property("z") == 0
    voltar = app.achar("botaoVoltar")
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, pos=_centro(voltar))
    assert app.janela.property("paginaAtual") == "jogo"
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: barra.property("enabled") is True)


def test_tamanho_padrao_e_minimo_da_main(app):
    janela = app.janela
    assert (janela.width(), janela.height()) == (1170, 795)
    assert (janela.minimumWidth(), janela.minimumHeight()) == (360, 100)


def test_menu_principal_so_nas_duas_bibliotecas(app):
    botao = app.achar("botaoMenu")
    assert botao.property("visible") is True
    _clicar(app, app.achar("botaoZerados"))
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    assert botao.property("visible") is True
    _clicar(app, app.achar("botaoVoltar"))
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    _abrir_pelo_cartao(app)
    assert botao.property("visible") is False


# --- AdwAlertDialog: medidas tiradas da libadwaita real (`resultado-F.md`) --------------------------


def _alerta_aberto(app, corpo, rotulo="Sim"):
    app.aplicativo.pedir_confirmacao("T", corpo, rotulo, lambda _c: None)
    alerta = app.achar("confirmacaoDoApp")
    assert _esperar(lambda: alerta.property("visible") is True)
    return alerta, _achar(alerta, "cartaoDoDialogo")


def test_alerta_curto_e_mais_estreito_e_longo_tem_372(app):
    alerta, cartao = _alerta_aberto(app, "Corpo")
    # Com a fonte real, 300; o offscreen não tem fonte, e os quadradinhos alargam os botões.
    assert 300 <= cartao.property("width") < 372
    assert cartao.property("radius") == 18
    alerta.setProperty("corpo", "palavra " * 40)
    assert _esperar(lambda: cartao.property("width") == 372)
    botoes = [_achar(alerta, n) for n in ("botaoCancelarDoDialogo", "botaoConfirmarDoDialogo")]
    assert botoes[0].property("width") == botoes[1].property("width") == (372 - 48 - 12) / 2
    assert botoes[0].property("height") == 44
    assert botoes[0].property("x") < botoes[1].property("x")


def test_alerta_empilha_com_o_primeiro_embaixo(app):
    alerta, cartao = _alerta_aberto(app, "Corpo", "Buscar tudo de novo em todos os jogos da biblioteca " * 2)
    cancelar = _achar(alerta, "botaoCancelarDoDialogo")
    confirmar = _achar(alerta, "botaoConfirmarDoDialogo")
    assert cartao.property("width") == 372
    assert cancelar.property("y") - confirmar.property("y") == 56
    assert cancelar.property("x") == confirmar.property("x") == 24


def test_alerta_nunca_vira_folha(app):
    alerta, _ = _alerta_aberto(app, "Corpo")
    app.janela.setWidth(360)
    _esperar(limite=0.1)
    assert alerta.property("emFolha") is False


# --- LinhaDeEscolha: o popover alarga até o maior texto ----------------------------------------------

_ESCOLHA = """
import QtQuick
import "file:///%s"
Window {
    width: 900
    height: 400
    visible: true
    LinhaDeEscolha {
        objectName: "escolha"
        width: 800
        titulo: "Idioma"
        model: ["Curta", "Uma opção bem mais longa que a largura mínima do popover"]
    }
}
"""


def test_popover_da_escolha_alarga_pelo_texto(app_qt):
    motor = QQmlEngine()
    motor.addImageProvider("icone", ProvedorDeIcones())
    componente = QQmlComponent(motor)
    componente.setData((_ESCOLHA % QML.as_posix()).encode("utf-8"), QUrl("file:///escolha.qml"))
    raiz = componente.create()
    assert raiz is not None, componente.errorString()
    assert _esperar(lambda: raiz.isExposed())
    escolha = _achar(raiz.contentItem(), "escolha")
    assert escolha.property("larguraDoPopover") == 180
    QTest.mouseClick(raiz, Qt.MouseButton.LeftButton, pos=_centro(escolha))
    assert _esperar(lambda: escolha.property("larguraDoPopover") > 300)
    raiz.close()
    raiz.deleteLater()
