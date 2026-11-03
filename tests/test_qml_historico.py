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
    _clicar(app, _achar(app.achar("dialogoDoHistorico"), "fecharDoCabecalho"))  # o X do cabeçalho, com o mouse de verdade
    assert _esperar(lambda: app.historico.aberto is False)
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
    cartao = _achar(dialogo, "cartaoDoDialogo")
    centro = _caixa(cartao)[0] + cartao.width() / 2
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
    largura = min(992, _achar(app.achar("dialogoDoHistorico"), "cartaoDoDialogo").width() - 48)  # a caixa é a do `Adw.Dialog`
    assert logo.width() == largura and abs(logo.height() - largura / 10) <= 1
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
    for linha in _todos(app.achar("dialogoDoHistorico"), "linhaDaSessaoTitulo"):
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
    assert [e for e in erros if "Historico" in e or "PaginaDoJogo" in e] == [], erros


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
    assert _esperar(lambda: app.janela.property("activeFocusItem") is _achar(app.achar("dialogoDoHistorico"), "fecharDoCabecalho"))
    app.fechar()


# -- Auditoria GTK x Qt, pacote D (histórico) ------------------------------------------------------


def _dentro(app):
    return app.achar("dialogoDoHistorico")


@pytest.mark.parametrize("altura", [700, 600])
def test_com_1100_de_largura_o_grafico_fica_a_vista_sem_rolar_a_caixa(app_qt, altura):
    """SES-23: a tabela encolhe (`max_content_height` é só um teto) e o eixo do gráfico não fica abaixo da dobra."""
    app = _app()
    _sessoes(30)
    app.janela.setWidth(1100)
    app.janela.setHeight(altura)
    _abrir(app)
    cartao, rolagem = _achar(_dentro(app), "cartaoDoDialogo"), _achar(_dentro(app), "rolagemDoHistorico")
    tabela, grafico = app.achar("tabelaDeSessoes"), app.achar("graficoDoHistorico")
    if altura < 700:
        assert _esperar(lambda: tabela.height() < 440)  # antes: sempre 440 e a caixa rolava
    assert rolagem.property("contentHeight") <= rolagem.height() + 0.5  # a caixa não rola
    base_do_grafico = _caixa(grafico)[1] + grafico.height()
    assert base_do_grafico <= _caixa(cartao)[1] + cartao.height()
    assert cartao.height() <= altura - 2 * 20  # as margens do `Adw.Dialog` abaixo de 720 de altura
    assert grafico.height() >= 240  # o piso do gráfico
    assert tabela.property("contentHeight") > tabela.height()  # e a tabela rola por dentro
    app.fechar()


def test_janela_muito_baixa_rola_a_caixa_so_quando_nem_o_piso_cabe(app_qt):
    app = _app()
    _sessoes(30)
    app.janela.setWidth(1100)
    app.janela.setHeight(420)
    _abrir(app)
    rolagem = _achar(_dentro(app), "rolagemDoHistorico")
    assert _esperar(lambda: rolagem.property("contentHeight") > rolagem.height())
    assert app.achar("graficoDoHistorico").height() >= 240  # o piso nunca é espremido
    app.fechar()


def test_caixa_e_um_adw_dialog_com_cabecalho_de_47(app_qt):
    """SES-24/25/26/27/28: raio 15 com sombra e contorno, fundo escurecido do tema, animação e faixa de 47 com o X redondo."""
    app = _app()
    _sessoes(2)
    dialogo = _abrir(app)
    cartao = _achar(dialogo, "cartaoDoDialogo")
    assert cartao.property("radius") == 15 and cartao.width() <= 1040
    assert _expr(dialogo, "progresso") is not None  # a mola do `AdwFloatingSheet` (o teste roda sem animar)
    assert _expr(dialogo, "Tema.esmaecido.toString()") != "#80000000"
    fechar = _achar(dialogo, "fecharDoCabecalho")
    assert (fechar.width(), fechar.parentItem().height()) == (34, 47)
    assert _achar(dialogo, "tituloDoCabecalho").property("text") == ""  # `show_title=False`
    app.fechar()


def test_clicar_fora_nao_fecha_o_dialogo_flutuante_mas_fecha_a_folha_de_baixo(app_qt):
    """SES-39: janela estreita vira bottom sheet, que fecha ao tocar no fundo; larga, o fundo é seguro como na `main`."""
    app = _app()
    _sessoes(2)
    _abrir(app)
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPointF(8, 8).toPoint())
    _assentar()
    assert app.historico.aberto is True
    app.fechar()

    app = _app()
    _sessoes(2)
    app.janela.setWidth(420)
    app.janela.setHeight(700)
    dialogo = _abrir(app)
    assert _expr(dialogo, "emFolha") is True
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPointF(8, 8).toPoint())
    assert _esperar(lambda: app.historico.aberto is False)
    app.fechar()


def test_periodo_e_uma_trilha_so_com_as_medidas_do_toggle_group(app_qt):
    """SES-30: trilha de 34 a 10% (raio 9, padding 3); opções de 28 sem espaço entre si; a marcada em branco no claro."""
    app = _app()
    _sessoes(3)
    _abrir(app)
    semana, mes, todo = (app.achar(n) for n in ("botaoSemana", "botaoMes", "botaoTodoOPeriodo"))
    trilha = mes.parentItem().parentItem()
    assert (trilha.height(), trilha.property("radius")) == (34, 9)
    assert all(b.height() == 28 for b in (semana, mes, todo))
    assert _caixa(mes)[0] == _caixa(semana)[0] + semana.width()  # sem espaço entre elas
    assert _caixa(todo)[0] == _caixa(mes)[0] + mes.width()
    assert _caixa(semana)[0] - _caixa(trilha)[0] == 3  # o padding do grupo
    assert _expr(mes, "background.color.toString()") != _expr(semana, "background.color.toString()")
    # A marcada não usa a cor de destaque (era o que o Qt fazia).
    assert _expr(mes, "background.color.toString()") != _expr(mes, "Tema.destaque.toString()")
    app.fechar()


def test_periodo_responde_a_enter_pelo_teclado(app_qt):
    """SES-08: Enter aciona o botão focado, também nos do período."""
    app = _app()
    _sessoes(3)
    _abrir(app)
    semana = app.achar("botaoSemana")
    semana.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: app.janela.property("activeFocusItem") is semana)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.historico.periodo == "week")
    app.fechar()


def test_linhas_da_tabela_sao_as_da_main(app_qt):
    """SES-29/32/33/34: linha de 54 (50 + respiro) com título de 12 e subtítulo de 10, lixeira plana e "Mostrar mais" plano."""
    app = _app()
    _sessoes(120)
    _abrir(app)
    linhas = _todos(app.achar("tabelaDeSessoes"), "linhaDaSessao")
    assert 54 <= linhas[1].height() <= 55
    titulo, subtitulo = _achar(linhas[0], "linhaDaSessaoTitulo"), _achar(linhas[0], "linhaDaSessaoSubtitulo")
    assert (_expr(titulo, "font.pixelSize"), _expr(subtitulo, "font.pixelSize")) == (12, 10)
    lixeira = _achar(linhas[0], "botaoExcluirSessao")
    assert (lixeira.property("estilo"), lixeira.property("icone"), (lixeira.width(), lixeira.height())) == ("plano", "user-trash", (34, 34))
    mais = app.achar("botaoMostrarMais")
    assert mais.property("estilo") == "plano"
    app.fechar()


def test_tab_e_setas_andam_pelas_linhas_antes_da_lixeira(app_qt):
    """SES-35: cada linha recebe o foco do teclado (anel), antes da lixeira; ↑ e ↓ andam entre as linhas."""
    app = _app()
    _sessoes(4)
    _abrir(app)
    alvos = sorted(_todos(app.achar("tabelaDeSessoes"), "alvoDaLinhaDaSessao"), key=lambda a: _caixa(a)[1])
    assert len(alvos) == 4

    def foco():
        return app.janela.property("activeFocusItem")

    assert foco() is _achar(_dentro(app), "fecharDoCabecalho")
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert _esperar(lambda: foco() is alvos[0])
    assert alvos[0].property("visualFocus") is True  # o anel aparece (o foco veio do teclado)
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert _esperar(lambda: foco().objectName() == "botaoExcluirSessao")  # depois da linha, a lixeira dela
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert _esperar(lambda: foco() is alvos[1])  # e a linha seguinte
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    assert _esperar(lambda: foco() is alvos[2])
    QTest.keyClick(app.janela, Qt.Key.Key_Up)
    assert _esperar(lambda: foco() is alvos[1])
    app.fechar()


def test_home_end_e_paginas_andam_entre_as_linhas(app_qt):
    """M15: como o `GtkListBox`, Home vai à primeira linha, End à última e PageUp/PageDown saltam."""
    app = _app()
    _sessoes(4)
    _abrir(app)
    alvos = sorted(_todos(app.achar("tabelaDeSessoes"), "alvoDaLinhaDaSessao"), key=lambda a: _caixa(a)[1])

    def foco():
        return app.janela.property("activeFocusItem")

    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert _esperar(lambda: foco() is alvos[0])
    QTest.keyClick(app.janela, Qt.Key.Key_End)
    assert _esperar(lambda: foco() is alvos[-1])
    QTest.keyClick(app.janela, Qt.Key.Key_Home)
    assert _esperar(lambda: foco() is alvos[0])
    QTest.keyClick(app.janela, Qt.Key.Key_PageDown)
    assert _esperar(lambda: foco() is not alvos[0])
    QTest.keyClick(app.janela, Qt.Key.Key_PageUp)
    assert _esperar(lambda: foco() is alvos[0])
    app.fechar()


def test_x_do_historico_fica_atras_da_confirmacao(app_qt):
    """M1: com a confirmação de exclusão aberta, o Tab não chega ao X do histórico que ficou atrás dela."""
    app = _app()
    _sessoes(2)
    dialogo = _abrir(app)
    x = _achar(dialogo, "fecharDoCabecalho")
    _clique_no_botao(_todos(app.achar("tabelaDeSessoes"), "botaoExcluirSessao")[0])
    assert app.achar("dialogoExcluirSessao").property("visible") is True
    assert x.property("enabled") is False
    for _ in range(8):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        assert app.janela.property("activeFocusItem") is not x
    app.fechar()


def test_vazio_a_margem_de_baixo_e_da_caixa_inteira(app_qt):
    """SES-36: sem sessão o cartão não termina colado no resumo: sobram os 24 de baixo."""
    app = _app()
    dialogo = _abrir(app)
    cartao, resumo = _achar(dialogo, "cartaoDoDialogo"), app.achar("resumoDoHistorico")
    folga = _caixa(cartao)[1] + cartao.height() - (_caixa(resumo)[1] + resumo.height())
    assert folga >= 24
    app.fechar()


def test_resumo_e_total_em_12_px(app_qt):
    """SES-31."""
    app = _app()
    _sessoes(2)
    _abrir(app)
    assert _expr(app.achar("resumoDoHistorico"), "font.pixelSize") == 12
    assert _expr(app.achar("totalDoPeriodo"), "font.pixelSize") == 12
    app.fechar()


def test_dica_do_grafico_tem_o_atraso_de_500_ms(app_qt):
    """SES-21/22: a dica do app (fundo escuro da Adwaita) com o atraso fixo do GTK, também no gráfico (era 0)."""
    app = _app()
    _sessoes(2)
    _abrir(app)
    dica = _achar(app.achar("graficoDoHistorico"), "dica")
    assert dica.property("delay") == 500
    assert _achar(app.achar("tabelaDeSessoes"), "botaoExcluirSessao").property("dica") == "Excluir esta sessão"
    app.fechar()


# -- Rodada de correções 1 (I1): a saída do histórico leva o conteúdo ---------------------------------

_SAIDA = r"""
import builtins, sys, time
builtins._ = lambda m: m
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
app = QGuiApplication(["x"])  # sem a opção dos testes: a animação de saída roda
from cartridges.utils import session_log
agora = int(time.time())
session_log.load = lambda gid: [{"end": agora - i * 86400, "seconds": 3600} for i in range(30 if gid.endswith("_1") else 2)]
from tests.apoio_qml_biblioteca import _achar, _App, _esperar, _jogos
from tests.apoio_qml_historico import _todos
app_ = _App(_jogos((1, "Alfa", {"playtime": 5400}), (2, "Beta", {})))
j = app_.janela
j.show()

def estado():
    d = _achar(j, "dialogoDoHistorico")
    cartao = _achar(d, "cartaoDoDialogo")
    nome = [t for t in _todos(d, "nomeDoHistorico") if t.property("visible")]
    return (round(cartao.height()), nome[0].property("text") if nome else None, len(_todos(d, "linhaDaSessao")), d.property("visible"))

def sair(como):
    d = _achar(j, "dialogoDoHistorico")
    antes = estado()
    assert antes[0] > 400 and antes[1] == "Alfa" and antes[2] == 30, antes
    cartao = _achar(d, "cartaoDoDialogo")  # leitura barata: só propriedades de itens já achados
    nome = next(t for t in _todos(d, "nomeDoHistorico") if t.property("visible"))
    linha = _todos(d, "linhaDaSessao")[0]
    def barato():
        return (round(cartao.height()), nome.property("text"), nome.property("visible"), linha.property("titulo") != "")
    esperado = barato()
    if como == "esc":
        QTest.keyClick(j, Qt.Key.Key_Escape)
    else:
        x = _achar(d, "fecharDoCabecalho")
        p = x.mapToScene(x.boundingRect().center()).toPoint()
        QTest.mouseClick(j, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(p.x(), p.y()))
    amostras, inicio = [], time.monotonic()
    while d.property("visible") and time.monotonic() - inicio < 3:
        QTest.qWait(1)
        if d.property("visible") and cartao.property("opacity") > 0:  # à vista: é o que a pessoa vê durante a saída
            amostras.append(barato())
    assert not app_.historico.aberto
    if como == "x":  # a primeira rodada aquece o renderizador (o primeiro quadro leva quase 1 s)
        assert amostras, "a saída tem de durar alguns quadros"
    assert set(amostras) <= {esperado}, (como, esperado, sorted(set(amostras)))

for como in ("esc", "x"):
    app_.historico.abrir("imported_1")
    assert _esperar(lambda: estado()[3] and estado()[0] > 400)
    sair(como)
# Reabrir de outro jogo não mostra o velho.
app_.historico.abrir("imported_2")
assert _esperar(lambda: estado()[3] and estado()[1] == "Beta")
assert estado()[2] == 2 and app_.historico.nome == "Beta"
print("OK")
"""


def test_saida_do_historico_mantem_o_conteudo_durante_a_animacao(tmp_path):
    """I1: abrir e fechar pelo Esc e pelo X, com a animação ligada: a altura e o conteúdo do cartão não mudam até sumir."""
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    raiz = Path(__file__).resolve().parent.parent
    ambiente = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONPATH=str(raiz), APPDATA=str(tmp_path), LOCALAPPDATA=str(tmp_path), USERPROFILE=str(tmp_path))
    rodou = subprocess.run([sys.executable, "-c", _SAIDA, str(raiz)], env=ambiente, capture_output=True, text=True, timeout=120, check=False, cwd=raiz)
    assert "OK" in rodou.stdout, rodou.stdout + rodou.stderr


def test_anel_do_x_so_com_foco_do_teclado(app_qt):
    """Aberto com o clique no cartão, o X recebe o foco sem anel; Tab até ele (Shift+Tab da primeira linha) o mostra."""
    app = _app()
    _sessoes(2)
    _abrir_pelo_cartao(app, 0)
    dialogo = _abrir(app)
    x = _achar(dialogo, "fecharDoCabecalho")
    anel = _achar(x, "anelDeFoco")
    assert app.janela.property("activeFocusItem") is x
    assert _esperar(lambda: anel.property("ativo") is False)
    assert x.property("visualFocus") is False
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert _esperar(lambda: app.janela.property("activeFocusItem") is not x)
    QTest.keyClick(app.janela, Qt.Key.Key_Backtab)
    assert _esperar(lambda: app.janela.property("activeFocusItem") is x)
    assert _esperar(lambda: anel.property("ativo") is True)
    app.fechar()
