# test_qml_janela_da_sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A janela "Jogando {nome}" da sessão manual (D50): moldura nativa, 300x150, canto da área de trabalho."""

import pytest
from PySide6.QtCore import QMetaObject, Qt

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos import sessao as modulo
from cartridges.modelos.sessao import canto_inferior_direito
from cartridges.process_session import ProcessSession
from cartridges.session_window import SessionWindow
from cartridges.utils import session_log
from tests.test_qml_biblioteca import _achar, _App, _esperar, _jogos


@pytest.fixture(autouse=True)
def isolado(monkeypatch):
    """Nenhuma chamada Win32 de verdade e nenhum histórico gravado."""
    monkeypatch.setattr(modulo, "_area_de_trabalho", lambda: (0, 0, 1920, 1040))
    monkeypatch.setattr(modulo, "_retangulo_da_janela", lambda _hwnd: (0, 0, 316, 189))
    monkeypatch.setattr(modulo, "_user32", lambda: pytest.fail("Win32 de verdade"))
    registros = []
    monkeypatch.setattr(session_log, "record", lambda jogo_id, s: registros.append((jogo_id, s)))
    return registros


def _app(monkeypatch, nome="A & B"):
    app = _App(_jogos((1, nome, {"status": "playing"})))
    app.jogos[0].save = lambda: None
    app.jogos[0].update = lambda: None
    monkeypatch.setattr(shared, "sessao", app.sessao, raising=False)
    app.sessao.definir_janela(app.janela)
    return app


def _abrir(app):
    SessionWindow(app.jogos[0]).present()
    carregador = app.achar("carregadorDaJanelaManual")
    _esperar(lambda: carregador.property("item") is not None)
    return carregador.property("item")


def test_titulo_e_tamanho_fixo(app_qt, monkeypatch):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    janela = _abrir(app)
    assert janela.title() == "Jogando A & B"
    assert (janela.width(), janela.height()) == (300, 150)
    assert (janela.minimumWidth(), janela.minimumHeight()) == (300, 150)
    assert (janela.maximumWidth(), janela.maximumHeight()) == (300, 150)
    assert _achar(janela, "botaoTermineiDaJanela") is not None
    app.fechar()


def test_botao_encerra_e_registra(app_qt, monkeypatch, isolado):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    janela = _abrir(app)
    botao = _achar(janela, "botaoTermineiDaJanela")
    assert botao.property("text") == "Já terminei de jogar"
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: not app.sessao.janelaManual)
    assert SessionWindow.active is None
    assert app.sessao.emAndamento is False
    assert [r[0] for r in isolado] == ["imported_1"]
    _esperar(lambda: app.achar("carregadorDaJanelaManual").property("item") is None)
    app.fechar()


def test_fechar_pela_moldura_encerra_e_registra(app_qt, monkeypatch, isolado):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    janela = _abrir(app)
    janela.close()
    _esperar(lambda: SessionWindow.active is None)
    assert SessionWindow.active is None
    assert app.sessao.emAndamento is False
    assert len(isolado) == 1
    app.fechar()


def test_canto_inferior_direito():
    assert canto_inferior_direito((0, 0, 1920, 1040), 300, 150) == (1608, 878)
    assert canto_inferior_direito((100, 50, 1100, 650), 300, 150, margem=0) == (800, 500)


def test_posicionar_usa_o_hwnd_da_janela_e_nao_rouba_o_foco(app_qt, monkeypatch):
    chamadas = []

    class Funcao:
        def __call__(self, *args):
            chamadas.append(args)

    class Fake:
        SetWindowPos = Funcao()  # noqa: N815

    monkeypatch.setattr(modulo, "_user32", lambda: Fake())

    class Janela:
        def winId(self):  # noqa: N802
            return 4242

    modelo = modulo.ModeloDaSessao(None)
    modelo.posicionarJanelaManual(Janela())
    # Janela 316x189 (com moldura) na área 1920x1040, margem 12: o canto fica em 1592,839.
    assert chamadas == [(4242, 0, 1592, 839, 0, 0, 0x0015)]


def test_falha_no_win32_deixa_onde_esta(app_qt, monkeypatch, caplog):
    def falha():
        raise OSError("sem Win32")

    monkeypatch.setattr(modulo, "_area_de_trabalho", falha)

    class Janela:
        def winId(self):  # noqa: N802
            return 1

    with caplog.at_level("ERROR"):
        modulo.ModeloDaSessao(None).posicionarJanelaManual(Janela())  # não levanta
    assert "Não foi possível posicionar a janela Jogando" in caplog.text


def test_queda_para_a_manual_mantem_a_camada_e_um_relogio_so(app_qt, monkeypatch):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    jogo = app.jogos[0]
    camada = app.achar("camadaDaSessao")
    app.sessao.show_session_blocker(jogo)  # o rastreio por processo veste a sessão
    assert app.sessao.emAndamento and not app.sessao.janelaManual
    SessionWindow(jogo).present()  # o `fall_back`: só o rastreador muda de mãos
    assert app.sessao.emAndamento and app.sessao.janelaManual
    assert ProcessSession.active is None
    assert SessionWindow.active is not None
    carregador = app.achar("carregadorDaJanelaManual")
    _esperar(lambda: carregador.property("item") is not None)
    assert camada.property("visible") is True
    app.sessao.terminar()
    assert app.sessao.emAndamento is False and SessionWindow.active is None
    app.fechar()


def test_fechar_a_principal_com_a_manual_aberta_sai_e_grava(app_qt, monkeypatch, isolado):
    """Como na `main`: o app sai; o `aboutToQuit` (`encerrar`) grava o tempo no jogo e uma linha no histórico."""
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    jogo = app.jogos[0]
    app.janela.show()
    _abrir(app)
    saidas = []
    # O que o `aboutToQuit` faz: `encerrar()`. O `quit` de verdade acabaria o laço de eventos dos testes.
    app.sessao._sair = lambda: (saidas.append(1), app.sessao.encerrar())  # noqa: SLF001
    SessionWindow.active.session_start -= 42  # 42 s jogados
    app.janela.close()
    assert saidas == [1]
    assert jogo.playtime == 42
    assert isolado == [("imported_1", 42)]
    app.fechar()


def test_fechar_a_principal_sem_sessao_nao_sai(app_qt, monkeypatch):
    app = _app(monkeypatch)
    app.sessao._sair = lambda: pytest.fail("saiu sem sessão manual")  # noqa: SLF001
    app.janela.show()
    app.janela.close()
    _esperar()
    app.fechar()


def test_terminar_pela_manual_com_a_principal_escondida(app_qt, monkeypatch, isolado):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    app.janela.show()
    janela = _abrir(app)
    app.janela.hide()  # fechada pela barra de tarefas, sem passar pelo `closing`
    _esperar()
    assert SessionWindow.active is not None and janela.isVisible()
    QMetaObject.invokeMethod(_achar(janela, "botaoTermineiDaJanela"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: SessionWindow.active is None)
    assert app.janela.isVisible()  # a principal volta
    assert len(isolado) == 1
    app.fechar()
