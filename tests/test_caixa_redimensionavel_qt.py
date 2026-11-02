# test_caixa_redimensionavel_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A caixa do "Onde eu parei" muda de tamanho pelo puxador e lembra o tamanho (regra pura e QML)."""

from PySide6.QtCore import QMetaObject, QPoint, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.utils import caixa_redimensionavel as caixa
from tests.apoio_qml_biblioteca import _achar, _App, _esperar, _jogos
from tests.apoio_qml_detalhes import _abrir_pelo_cartao


def _guardado():
    return shared.state_schema.get_int("notas-largura"), shared.state_schema.get_int("notas-altura")


def test_arrastar_soma_o_deslocamento_dentro_dos_limites():
    maximo = (900, 600)
    assert caixa.novo_tamanho((320, 120), (100, 50), maximo) == (420, 170)
    # Nunca menor que o tamanho de sempre, nem maior que a janela deixa.
    assert caixa.novo_tamanho((320, 120), (-500, -500), maximo) == caixa.MINIMO
    assert caixa.novo_tamanho((320, 120), (5000, 5000), maximo) == maximo


def test_tamanho_guardado_vale_para_as_duas_caixas():
    """O balão da tela do jogo e o da tela de sessão são a mesma caixa: o tamanho deixado num vale para o outro."""
    uma, outra = caixa.CaixaDaAnotacao(), caixa.CaixaDaAnotacao()
    uma.arrastar(320, 120, 180, 180, 2000, 1000, 2000, 1000)
    uma.gravar()
    outra.restaurar(2000, 1000, 2000, 1000)

    assert _guardado() == (500, 300)
    assert (outra.largura, outra.altura) == (500, 300)


def test_tamanho_guardado_menor_que_o_minimo_nao_vale():
    """Um valor mexido à mão não pode encolher a caixa a nada."""
    shared.state_schema.set_int("notas-largura", 10)
    shared.state_schema.set_int("notas-altura", 10)
    c = caixa.CaixaDaAnotacao()

    c.restaurar(2000, 1000, 2000, 1000)

    assert (c.largura, c.altura) == caixa.MINIMO


def test_tamanho_guardado_cabe_na_janela_ao_reabrir():
    """Um tamanho deixado com a janela grande não passa da janela pequena."""
    shared.state_schema.set_int("notas-largura", 5000)
    shared.state_schema.set_int("notas-altura", 5000)
    c = caixa.CaixaDaAnotacao()

    c.restaurar(800, 600, 800, 600)

    assert (c.largura, c.altura) == (round(800 * caixa.FRACAO_MAXIMA[0]), round(600 * caixa.FRACAO_MAXIMA[1]))


def test_arrasto_grava_so_ao_soltar():
    c = caixa.CaixaDaAnotacao()
    c.arrastar(320, 120, 100, 30, 2000, 1000, 2000, 1000)
    assert (c.largura, c.altura) == (420, 150)
    antes = _guardado()
    assert antes == caixa.MINIMO  # o padrão do esquema: nada gravado ainda
    c.arrastar(320, 120, 5000, 5000, 900, 600, 900, 600)  # muito além: o máximo da janela segura
    assert (c.largura, c.altura) == (810, 480)
    assert _guardado() == antes
    c.gravar()
    assert _guardado() == (810, 480)


def test_espaco_livre_limita_o_tamanho_sem_regravar():
    """O balão não é empurrado para dentro da janela: o espaço livre à direita e abaixo dele também limita."""
    c = caixa.CaixaDaAnotacao()
    c.arrastar(320, 120, 5000, 5000, 1000, 800, 500, 300)
    assert (c.largura, c.altura) == (500, 300)
    shared.state_schema.set_int("notas-largura", 700)
    shared.state_schema.set_int("notas-altura", 400)
    c.restaurar(1000, 800, 450, 250)
    assert (c.largura, c.altura) == (450, 250)
    assert _guardado() == (700, 400)  # o guardado fica para quando a janela voltar a ser grande


def _arrastar_puxador(app, balao, dx, dy):
    puxador = _achar(balao.property("contentItem"), "puxadorDaAnotacao")
    centro = puxador.mapToScene(puxador.boundingRect().center()).toPoint()
    p = QPoint(centro.x(), centro.y())
    QTest.mousePress(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
    for passo in range(1, 11):
        QTest.mouseMove(app.janela, QPoint(p.x() + dx * passo // 10, p.y() + dy * passo // 10))
        _esperar()
    QTest.mouseRelease(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(p.x() + dx, p.y() + dy))
    _esperar()


def _fundo_do_puxador(balao):
    puxador = _achar(balao.property("contentItem"), "puxadorDaAnotacao")
    return puxador.mapToScene(puxador.boundingRect().bottomRight())


def test_puxador_aumenta_a_caixa_e_grava_ao_soltar(app_qt):
    app = _App(_jogos((1, "Alfa", {"status": "playing"})))
    pagina = _abrir_pelo_cartao(app)
    QMetaObject.invokeMethod(_achar(pagina, "botaoAnotacao"), "click", Qt.ConnectionType.DirectConnection)
    balao = _achar(pagina, "balaoDaAnotacao")
    assert _esperar(lambda: balao.property("opened") is True)
    assert balao.property("contentItem").property("width") == 320
    assert _guardado() == caixa.MINIMO
    puxador = _achar(balao.property("contentItem"), "puxadorDaAnotacao")
    assert QQmlExpression(QQmlEngine.contextForObject(puxador), puxador, "ToolTip.text").evaluate()[0] == "Arraste para mudar o tamanho"

    _arrastar_puxador(app, balao, 60, 40)

    # A largura cresce para os dois lados (`FATOR_DA_LARGURA = 2` da `main`): o puxador acompanha o mouse.
    assert (app.caixa_da_anotacao.largura, app.caixa_da_anotacao.altura) == (440, 160)
    assert balao.property("contentItem").property("width") == 440
    assert balao.property("contentItem").property("height") == 160
    assert _guardado() == (440, 160)
    app.fechar()


def test_puxador_nunca_sai_da_janela(app_qt):
    """Numa janela pequena, arrastar muito além do limite deixa o puxador dentro da janela (jogo e sessão), e o
    mesmo ao reabrir com o tamanho gravado."""
    app = _App(_jogos((1, "Alfa", {"status": "playing"})))
    app.janela.resize(1000, 700)
    _esperar()
    pagina = _abrir_pelo_cartao(app)
    QMetaObject.invokeMethod(_achar(pagina, "botaoAnotacao"), "click", Qt.ConnectionType.DirectConnection)
    balao = _achar(pagina, "balaoDaAnotacao")
    assert _esperar(lambda: balao.property("opened") is True)
    _arrastar_puxador(app, balao, 400, 300)  # o cursor para na janela; o limite é do balão
    fundo = _fundo_do_puxador(balao)
    assert fundo.x() <= app.janela.width() and fundo.y() <= app.janela.height()
    assert app.caixa_da_anotacao.largura > caixa.MINIMO[0]
    balao.close()
    _esperar()
    # Reabrir (jogo e sessão) com um tamanho gravado maior que o espaço: cabe.
    shared.state_schema.set_int("notas-largura", 5000)
    shared.state_schema.set_int("notas-altura", 5000)
    QMetaObject.invokeMethod(_achar(pagina, "botaoAnotacao"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: balao.property("opened") is True)
    fundo = _fundo_do_puxador(balao)
    assert fundo.x() <= app.janela.width() and fundo.y() <= app.janela.height()
    balao.close()
    app.sessao.show_session_blocker(app.jogos[0])
    assert _esperar(lambda: app.achar("camadaDaSessao").property("visible"))
    QMetaObject.invokeMethod(app.achar("botaoAnotacaoDaSessao"), "click", Qt.ConnectionType.DirectConnection)
    balao = app.achar("balaoDaSessao")
    assert _esperar(lambda: balao.property("opened") is True)
    fundo = _fundo_do_puxador(balao)
    assert fundo.x() <= app.janela.width() and fundo.y() <= app.janela.height()
    app.fechar()


def test_tamanho_vale_para_a_outra_caixa_ao_abrir(app_qt):
    """O tamanho deixado na caixa da tela do jogo vale para a da tela de sessão (e volta ao reabrir o app)."""
    shared.state_schema.set_int("notas-largura", 450)
    shared.state_schema.set_int("notas-altura", 250)
    app = _App(_jogos((1, "Alfa", {"status": "playing"})))
    app.sessao.show_session_blocker(app.jogos[0])
    assert _esperar(lambda: app.achar("camadaDaSessao").property("visible"))
    QMetaObject.invokeMethod(app.achar("botaoAnotacaoDaSessao"), "click", Qt.ConnectionType.DirectConnection)
    balao = app.achar("balaoDaSessao")
    assert _esperar(lambda: balao.property("opened") is True)
    assert balao.property("contentItem").property("width") == 450
    app.fechar()
