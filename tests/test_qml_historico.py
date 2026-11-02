# test_qml_historico.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O histórico de sessões na tela: o tempo de jogo clicável, o diálogo e o gráfico (QML offscreen, D54)."""

import pytest
from PIL import Image
from PySide6.QtCore import QMetaObject, QPointF, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from cartridges.jogo import Jogo
from cartridges.modelos import historico as modulo
from cartridges.utils import session_log
from tests.apoio_qml_biblioteca import _achar, _App, _assentar, _esperar, _jogos
from tests.apoio_qml_detalhes import _abrir_pelo_cartao, _clicar
from tests.apoio_qml_historico import _caixa, _expr, _todos


@pytest.fixture(autouse=True)
def _sem_jogo_de_verdade(monkeypatch):
    monkeypatch.setattr(Jogo, "launch", lambda self, *a, **k: True)


def _app(**extra):
    return _App(_jogos((1, "Alfa", {"playtime": 5400, **extra}), (2, "Beta", {})))


def _sessoes(quantas, jogo="imported_1", segundos=3600):
    import time  # noqa: PLC0415

    for i in range(quantas):
        session_log.record(jogo, segundos, end=int(time.time()) - i * 86400)


def _abrir(app, indice=0):
    app.historico.abrir(app.jogos[indice].game_id)
    assert _esperar(lambda: app.achar("dialogoDoHistorico").property("visible") is True)
    _assentar()
    return app.achar("dialogoDoHistorico")


def _clique_no_botao(item):
    QMetaObject.invokeMethod(item, "click", Qt.ConnectionType.DirectConnection)
    _assentar()


# -- o tempo de jogo na página de detalhes -------------------------------------------------------


def test_tempo_de_jogo_clicavel_so_com_sessoes(app_qt):
    app = _app()
    pagina = _abrir_pelo_cartao(app, 0)
    tempo = _achar(pagina, "tempoDeJogo")
    area = _achar(pagina, "areaDoTempoDeJogo")
    # Sem sessão gravada (o tempo de um backup, por exemplo) é só um rótulo.
    assert tempo.property("text") == "Tempo de jogo: 1,5 horas"
    assert tempo.property("clicavel") is False
    assert tempo.property("dica") == ""
    assert _expr(tempo, "font.underline") is False
    assert area.property("enabled") is False
    assert _expr(area, "cursorShape") == Qt.CursorShape.ArrowCursor.value

    session_log.record("imported_1", 5400, end=1_700_000_000)
    app.detalhes._mostrado().update()  # noqa: SLF001; como o fim de uma sessão: `record` e depois `update`
    assert _esperar(lambda: tempo.property("clicavel") is True)
    # O sublinhado é na cor do próprio texto: nem link nem botão.
    assert _expr(tempo, "font.underline") is True
    assert tempo.property("dica") == "Ver o histórico de sessões"
    assert area.property("enabled") is True
    assert _expr(area, "cursorShape") == Qt.CursorShape.PointingHandCursor.value
    app.fechar()


def test_clicar_abre_o_historico(app_qt):
    app = _app()
    session_log.record("imported_1", 5400, end=1_700_000_000)
    pagina = _abrir_pelo_cartao(app, 0)
    dialogo = app.achar("dialogoDoHistorico")
    assert dialogo.property("visible") is False
    assert app.historico.aberto is False

    _clicar(app, _achar(pagina, "areaDoTempoDeJogo"))

    assert _esperar(lambda: app.historico.aberto)
    assert app.historico.nome == "Alfa"
    assert _esperar(lambda: dialogo.property("visible") is True)
    app.fechar()


def test_clicar_sem_sessoes_nao_abre_nada(app_qt):
    app = _app()
    pagina = _abrir_pelo_cartao(app, 0)

    _clicar(app, _achar(pagina, "tempoDeJogo"))
    _esperar()

    assert app.historico.aberto is False
    app.fechar()


def test_jogo_nunca_jogado_sem_tempo(app_qt):
    app = _app()
    pagina = _abrir_pelo_cartao(app, 1)
    assert _achar(pagina, "tempoDeJogo").property("visible") is False
    assert _achar(pagina, "tempoDeJogo").property("clicavel") is False
    app.fechar()


# -- o diálogo ------------------------------------------------------------------------------------


def test_fundo_fica_desabilitado_com_o_historico_aberto(app_qt):
    app = _app()
    _sessoes(2)
    _abrir_pelo_cartao(app, 0)
    assert app.achar("botaoMenu").property("enabled") is True
    _abrir(app)
    assert app.achar("pilha").property("enabled") is False
    assert app.achar("botaoMenu").property("enabled") is False
    assert app.achar("botaoVoltar").property("enabled") is False
    app.fechar()


def test_esc_e_o_botao_fecham(app_qt):
    app = _app()
    _sessoes(2)
    _abrir_pelo_cartao(app, 0)
    _abrir(app)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.historico.aberto is False)
    assert app.achar("dialogoDoHistorico").property("visible") is False
    # De volta aos detalhes, que seguem à vista.
    assert app.janela.property("paginaAtual") == "jogo"

    _abrir(app)
    _clique_no_botao(app.achar("botaoFecharHistorico"))
    assert app.historico.aberto is False
    app.fechar()


def test_dialogo_tem_nome_acessivel_sem_titulo_visivel(app_qt):
    app = _app()
    _sessoes(1)
    dialogo = _abrir(app)
    # O nome que o leitor de tela anuncia (o atributo anexado, lido pelo próprio QML), e o papel de diálogo.
    assert _expr(dialogo, "Accessible.name") == "Histórico de sessões"
    assert _expr(dialogo, "Accessible.role") == _expr(dialogo, "Accessible.Dialog")
    # Sem título visível: o logo (ou o nome do jogo) é a manchete.
    visiveis = [t for t in _todos(dialogo, "nomeDoHistorico") if t.property("visible")]
    assert [t.property("text") for t in visiveis] == ["Alfa"]
    app.fechar()


def test_periodo_com_tres_botoes_exclusivos(app_qt):
    app = _app()
    _sessoes(3)
    _abrir(app)
    botoes = {n: app.achar(n) for n in ("botaoSemana", "botaoMes", "botaoTodoOPeriodo")}
    assert [botoes[n].property("text") for n in botoes] == ["Semana", "Mês", "Todo o período"]
    assert {n: b.property("checked") for n, b in botoes.items()} == {"botaoSemana": False, "botaoMes": True, "botaoTodoOPeriodo": False}

    _clique_no_botao(botoes["botaoSemana"])
    assert app.historico.periodo == "week"
    assert {n: b.property("checked") for n, b in botoes.items()} == {"botaoSemana": True, "botaoMes": False, "botaoTodoOPeriodo": False}
    _clique_no_botao(botoes["botaoTodoOPeriodo"])
    assert app.historico.periodo == "all"
    assert app.achar("totalDoPeriodo").property("text") == "3 horas no período"
    app.fechar()


def test_tabela_rola_a_partir_de_440_e_o_painel_acompanha(app_qt):
    """Passou de umas 8 linhas, a tabela rola em vez de esticar a caixa, e o painel do gráfico para na mesma altura."""
    app = _app()
    _sessoes(30)
    _abrir(app)
    tabela, painel = app.achar("tabelaDeSessoes"), app.achar("painelDoGrafico")
    assert tabela.height() == 440
    assert tabela.property("contentHeight") > tabela.height()
    assert _caixa(painel)[1] == _caixa(tabela)[1]
    assert painel.height() == tabela.height()
    app.fechar()


def test_painel_tem_a_altura_da_tabela_quando_ela_cabe(app_qt):
    app = _app()
    _sessoes(7)
    _abrir(app)
    tabela, painel = app.achar("tabelaDeSessoes"), app.achar("painelDoGrafico")
    assert tabela.height() < 440
    assert _caixa(painel)[1] == _caixa(tabela)[1]
    assert painel.height() == tabela.height()
    assert tabela.property("contentHeight") == tabela.height()
    app.fechar()


def test_grafico_com_uma_sessao_tem_o_piso(app_qt):
    """Uma tabela de uma linha não arrasta o gráfico junto: ele fica no piso legível, e a tabela fica mais baixa que o painel."""
    app = _app()
    _sessoes(1)
    _abrir(app)
    grafico = app.achar("graficoDoHistorico")
    assert grafico.width() >= 320
    assert grafico.height() >= 240
    assert app.achar("tabelaDeSessoes").height() < app.achar("painelDoGrafico").height()
    app.fechar()


def test_sem_sessao_so_o_cabecalho_e_a_frase(app_qt):
    app = _app()
    _abrir(app)
    assert app.achar("resumoDoHistorico").property("text") == "Nenhuma sessão registrada."
    assert app.achar("colunasDoHistorico").property("visible") is False
    app.fechar()


def test_botao_mostrar_mais_so_com_mais_a_mostrar(app_qt):
    app = _app()
    _sessoes(120)
    _abrir(app)
    botao = app.achar("botaoMostrarMais")
    assert botao.property("visible") is True
    assert botao.property("text") == "Mostrar mais sessões"
    _clique_no_botao(botao)
    assert len(app.historico.sessoes) == 120
    assert _esperar(lambda: botao.property("visible") is False)
    app.fechar()


def test_logo_e_resumo_centralizados_na_caixa_toda(app_qt, monkeypatch, tmp_path):
    app = _app()
    _sessoes(2)
    Image.new("RGBA", (2858, 552), "red").save(tmp_path / "logo.png")
    monkeypatch.setattr(modulo.game_logo, "cached_logo_path", lambda _jogo: tmp_path / "logo.png")
    dialogo = _abrir(app)
    logo, resumo, colunas = app.achar("logoDoHistorico"), app.achar("resumoDoHistorico"), app.achar("colunasDoHistorico")
    assert _esperar(lambda: logo.property("visible") is True)
    assert app.achar("nomeDoHistorico").property("visible") is False
    centro = _caixa(app.achar("cartaoDoHistorico"))[0] + app.achar("cartaoDoHistorico").width() / 2
    for item in (logo, resumo):
        x, _y, largura, _a = _caixa(item)
        assert abs(x + largura / 2 - centro) <= 1
    assert logo.width() == 621 and abs(logo.height() - 120) <= 1
    assert resumo.property("text").startswith("Últimos 7 dias")
    assert _caixa(resumo)[1] + resumo.height() <= _caixa(colunas)[1]
    assert dialogo.property("visible") is True
    app.fechar()


def test_logo_largo_manda_a_largura_da_caixa(app_qt, monkeypatch, tmp_path):
    app = _app()
    _sessoes(1)
    Image.new("RGBA", (4000, 400), "red").save(tmp_path / "logo.png")
    monkeypatch.setattr(modulo.game_logo, "cached_logo_path", lambda _jogo: tmp_path / "logo.png")
    _abrir(app)
    logo = app.achar("logoDoHistorico")
    assert _esperar(lambda: logo.property("visible") is True)
    assert logo.width() == 992 and abs(logo.height() - 99.2) <= 1
    app.fechar()


def test_nome_em_texto_puro(app_qt):
    app = _App(_jogos((1, "A & B <i>itálico</i>", {"playtime": 600})))
    session_log.record("imported_1", 600)
    _abrir(app)
    nome = app.achar("nomeDoHistorico")
    assert nome.property("visible") is True
    assert nome.property("text") == "A & B <i>itálico</i>"
    assert _expr(nome, "textFormat") == 0  # Text.PlainText
    # E as datas e os tempos das linhas também.
    for linha in _todos(app.achar("dialogoDoHistorico"), "tituloDaSessao"):
        assert _expr(linha, "textFormat") == 0
    app.fechar()


# -- excluir uma sessão -----------------------------------------------------------------------------


def test_confirmacao_tem_o_texto_da_main(app_qt):
    app = _app()
    session_log.record("imported_1", 1800, end=1_700_100_000)
    session_log.record("imported_1", 3600, end=1_700_000_000)
    _abrir(app)
    lixeiras = _todos(app.achar("tabelaDeSessoes"), "botaoExcluirSessao")
    assert len(lixeiras) == 2
    assert lixeiras[0].property("dica") == "Excluir esta sessão"
    confirmacao = app.achar("dialogoExcluirSessao")
    assert confirmacao.property("visible") is False

    # A de cima é a mais recente (30 min, 15 de novembro de 2023).
    primeira = min(lixeiras, key=lambda b: _caixa(b)[1])
    _clique_no_botao(primeira)

    assert confirmacao.property("visible") is True
    assert confirmacao.property("titulo") == "Excluir esta sessão?"
    assert confirmacao.property("corpo") == (
        "Tem certeza que deseja excluir a sessão de 30 min, em 15 de novembro de 2023? "
        "O tempo será descontado do total do jogo. Esta ação é irreversível."
    )
    assert confirmacao.property("rotuloConfirmar") == "Excluir"
    assert confirmacao.property("destrutivo") is True
    assert app.jogos[0].playtime == 5400  # nada mudou até confirmar
    app.fechar()


def test_cancelar_a_confirmacao_nao_muda_nada(app_qt):
    app = _app()
    session_log.record("imported_1", 3600, end=1_700_000_000)
    _abrir(app)
    _clique_no_botao(_todos(app.achar("tabelaDeSessoes"), "botaoExcluirSessao")[0])
    _clique_no_botao(_achar(app.achar("dialogoExcluirSessao"), "botaoCancelarDoDialogo"))

    assert app.achar("dialogoExcluirSessao").property("visible") is False
    assert app.jogos[0].playtime == 5400
    assert len(app.historico.sessoes) == 1
    assert app.historico.aberto is True
    app.fechar()


def test_confirmar_exclui_e_desconta_do_total(app_qt):
    app = _app()
    session_log.record("imported_1", 3600, end=1_700_000_000)
    session_log.record("imported_1", 1800, end=1_700_100_000)
    _abrir(app)
    lixeiras = _todos(app.achar("tabelaDeSessoes"), "botaoExcluirSessao")
    _clique_no_botao(min(lixeiras, key=lambda b: _caixa(b)[1]))
    _clique_no_botao(_achar(app.achar("dialogoExcluirSessao"), "botaoConfirmarDoDialogo"))

    assert app.jogos[0].playtime == 3600
    assert [s["segundos"] for s in app.historico.sessoes] == [3600]
    assert app.historico.aberto is True
    assert len(_todos(app.achar("tabelaDeSessoes"), "linhaDaSessao")) == 1
    app.fechar()


def test_trocar_o_periodo_mantem_as_linhas_da_tabela(app_qt):
    app = _app()
    _sessoes(3)
    _abrir(app)
    antes = _todos(app.achar("tabelaDeSessoes"), "linhaDaSessao")
    assert len(antes) == 3

    app.historico.definirPeriodo("week")
    _assentar()

    depois = _todos(app.achar("tabelaDeSessoes"), "linhaDaSessao")
    # Os mesmos objetos: o `Repeater` não refez a tabela só porque o gráfico mudou.
    assert sorted(map(id, depois)) == sorted(map(id, antes))
    assert app.historico.periodo == "week"
    app.fechar()
# -- o gráfico --------------------------------------------------------------------------------------


def test_grafico_desenha_os_tres_periodos_sem_erro(app_qt):
    import time  # noqa: PLC0415

    erros = []
    anterior = qInstallMessageHandler(lambda tipo, _ctx, msg: erros.append(msg) if tipo in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg) else None)
    try:
        app = _app()
        session_log.record("imported_1", 3600, end=int(time.time()))
        session_log.record("imported_1", 1800, end=int(time.time()) - 100 * 86400)
        session_log.record("imported_1", 1800, end=int(time.time()) - 400 * 86400)
        _abrir(app)
        grafico = app.achar("graficoDoHistorico")
        for nome, periodo in (("botaoSemana", "week"), ("botaoTodoOPeriodo", "all"), ("botaoMes", "month")):
            antes = grafico.property("desenhos")
            _clique_no_botao(app.achar(nome))
            assert _esperar(lambda: grafico.property("desenhos") > antes), periodo
        app.fechar()
    finally:
        qInstallMessageHandler(anterior)
    # Só o que sai dos arquivos do histórico (o resto é ruído do Qt offscreen ou de outras telas).
    assert [e for e in erros if "Historico" in e or "PaginaDoJogo" in e] == []


def test_dica_do_grafico_acompanha_o_mouse(app_qt):
    app = _app()
    _sessoes(2)
    _abrir(app)
    grafico = app.achar("graficoDoHistorico")
    assert grafico.property("dicaDoMouse") == ""
    # O primeiro e o último dia do período são as pontas do gráfico.
    grafico.setProperty("xDoMouse", 44)
    assert grafico.property("dicaDoMouse") == app.historico.dica(0.0)
    grafico.setProperty("xDoMouse", grafico.width() - 12)
    assert grafico.property("dicaDoMouse") == app.historico.dica(1.0)
    app.fechar()


def test_garantir_foco_deixa_o_foco_onde_esta_dentro_do_dialogo(app_qt):
    """O `dentro()` subia por `parentItem` (inexistente no QML): o foco sempre ia ao botão de fechar."""
    app = _app()
    _sessoes(3)
    dialogo = _abrir(app)
    app.achar("botaoSemana").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: app.janela.property("activeFocusItem") is app.achar("botaoSemana"))
    QMetaObject.invokeMethod(dialogo, "garantirFoco", Qt.ConnectionType.DirectConnection)
    assert app.janela.property("activeFocusItem") is app.achar("botaoSemana")
    app.fechar()


def test_foco_numa_sessao_abaixo_da_dobra_rola_a_tabela(app_qt):
    app = _app()
    _sessoes(40)
    _abrir(app)
    tabela = app.achar("tabelaDeSessoes")
    assert _expr(tabela, "contentY") == 0
    ultima = max(_todos(tabela, "botaoExcluirSessao"), key=lambda b: _caixa(b)[1])
    ultima.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: _expr(tabela, "contentY") > 0)
    app.fechar()


def test_foco_depois_do_ultimo_mostrar_mais_vai_ao_botao_de_fechar(app_qt):
    """O botão escondido continua "dentro" do diálogo: o `garantirFoco` olha também a visibilidade."""
    app = _app()
    _sessoes(120)
    _abrir(app)
    botao = app.achar("botaoMostrarMais")
    botao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: app.janela.property("activeFocusItem") is botao)
    _clique_no_botao(botao)
    assert _esperar(lambda: botao.property("visible") is False)
    assert _esperar(lambda: app.janela.property("activeFocusItem") is app.achar("botaoFecharHistorico"))
    app.fechar()
