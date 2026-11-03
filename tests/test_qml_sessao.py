# test_qml_sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tela da sessão (D49): o Aplicativo inteiro, `semAgente`, sem nenhum jogo de verdade."""

import pytest
from PIL import Image
from PySide6.QtCore import QMetaObject, Qt, QUrl
from PySide6.QtGui import QFont, QFontMetricsF
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtTest import QTest

from cartridges.jogo import Jogo
from cartridges.modelos import sessao as modulo_da_sessao
from cartridges.process_session import ProcessSession
from tests.apoio_qml_biblioteca import _achar, _App, _esperar, _jogos
from tests.apoio_qml_big_picture import _aberto_com, _entrar, _itens
from tests.apoio_qml_detalhes import _abrir_pelo_cartao, _clicar, _foco_dentro_de
from tests.apoio_qml_historico import _expr


@pytest.fixture(autouse=True)
def lancamentos(monkeypatch):
    """Os `launch` pedidos (um `pytest.fail` dentro de um slot do QML seria engolido pelo PySide)."""
    chamadas = []
    monkeypatch.setattr(Jogo, "launch", lambda self, *a, **k: chamadas.append(self.game_id))
    return chamadas


class _ProcessoFalso:
    elapsed = 0

    def __init__(self):
        self.parou = []

    def stop(self, record=False):
        self.parou.append(record)


def _app(*itens):
    app = _App(_jogos(*(itens or ((1, "Alfa", {"status": "playing"}), (2, "Beta", {"status": "playing"})))))
    for jogo in app.jogos:
        jogo.save = lambda: None
    return app


def _comecar(app, indice=0):
    app.sessao.show_session_blocker(app.jogos[indice])
    _esperar(lambda: app.achar("camadaDaSessao").property("visible"))
    _esperar()


def _cartao_focado(app):
    QMetaObject.invokeMethod(app.achar("pagina"), "focarGrade", Qt.ConnectionType.DirectConnection)
    _esperar()


def _tecla(app, tecla):
    QTest.keyClick(app.janela, tecla)
    _esperar()


def test_camada_cobre_a_barra_e_a_grade(app_qt):
    app = _app()
    camada = app.achar("camadaDaSessao")
    assert camada.property("visible") is False
    assert app.achar("barraDeTitulo").property("visible") is True
    _comecar(app)
    assert camada.property("visible") is True
    assert app.achar("barraDeTitulo").property("visible") is False  # a camada cobre a barra também
    assert app.janela.property("telaCheia") is True
    assert app.achar("pagina").property("enabled") is False
    # Só diálogo aberto recusa o arrasto (`window.py:572`, R7): na sessão a `main` ainda importa o atalho solto.
    assert app.achar("alvoDeSoltar").property("enabled") is True
    assert camada.property("color").alpha() == 235  # rgba(0, 0, 0, 0.92)
    app.fechar()


def test_foco_no_botao_ao_comecar(app_qt):
    app = _app()
    _comecar(app)
    assert _foco_dentro_de(app, "botaoJaTerminei")
    assert app.achar("botaoJaTerminei").property("text") == "Já terminei de jogar"
    app.fechar()


def test_teclado_nao_alcanca_a_grade_com_a_sessao(app_qt, lancamentos):
    app = _app()
    _cartao_focado(app)
    assert _foco_dentro_de(app, "grade")  # o cenário: um cartão com o foco antes de a sessão começar
    _comecar(app)
    for tecla in (Qt.Key.Key_Return, Qt.Key.Key_Space, Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Tab, Qt.Key.Key_Space):
        _tecla(app, tecla)
        assert app.janela.property("paginaAtual") == "todos"  # nenhum cartão abriu os detalhes
        # Enter no "Onde eu parei" abre o balão (SES-08), e o foco vai à caixa dele: é da camada, não da grade.
        assert _foco_dentro_de(app, "camadaDaSessao") or _foco_dentro_de(app, "campoDaAnotacao"), tecla
        assert not _foco_dentro_de(app, "grade"), tecla
        assert not _foco_dentro_de(app, "barraDeTitulo"), tecla
        if _foco_dentro_de(app, "campoDaAnotacao"):
            _tecla(app, Qt.Key.Key_Escape)
    # Mesmo que algo devolva o foco ao cartão (o que um `forceActiveFocus` atrasado faria), a grade desligada não o aceita.
    QMetaObject.invokeMethod(app.achar("pagina"), "focarGrade", Qt.ConnectionType.DirectConnection)
    _esperar()
    for tecla in (Qt.Key.Key_Return, Qt.Key.Key_Space):
        _tecla(app, tecla)
    assert app.janela.property("paginaAtual") == "todos"
    assert lancamentos == []
    app.fechar()


def test_ja_terminei_chama_terminar(app_qt, monkeypatch):
    app = _app()
    processo = _ProcessoFalso()
    monkeypatch.setattr(ProcessSession, "active", processo)
    _comecar(app)
    QMetaObject.invokeMethod(app.achar("botaoJaTerminei"), "click", Qt.ConnectionType.DirectConnection)
    assert processo.parou == [True]
    app.fechar()


def test_logo_ou_nome_no_topo(app_qt, monkeypatch, tmp_path):
    app = _app()
    _comecar(app)
    assert app.achar("nomeDaSessao").property("visible") is True
    assert app.achar("nomeDaSessao").property("text") == "Alfa"
    assert app.achar("logoDaSessao").property("visible") is False
    app.sessao.hide_session_blocker()
    Image.new("RGBA", (400, 100), "red").save(tmp_path / "logo.png")
    monkeypatch.setattr(modulo_da_sessao.game_logo, "cached_logo_path", lambda jogo: tmp_path / "logo.png")
    _comecar(app)
    assert app.sessao.larguraDoLogo == 400
    assert app.sessao.logo.startswith("file:")
    assert _esperar(lambda: app.achar("logoDaSessao").property("visible") is True)
    assert app.achar("nomeDaSessao").property("visible") is False
    app.fechar()


def test_nome_com_marcacao_em_texto_puro(app_qt):
    app = _app((1, "A & B <i>itálico</i>", {}))
    _comecar(app)
    nome = app.achar("nomeDaSessao")
    assert nome.property("text") == "A & B <i>itálico</i>"
    assert QQmlExpression(QQmlEngine.contextForObject(nome), nome, "textFormat").evaluate()[0] == 0  # Text.PlainText
    assert QQmlExpression(QQmlEngine.contextForObject(nome), nome, "wrapMode").evaluate()[0] != 0  # quebra
    app.fechar()


def test_relogio_escondido_sem_monitor(app_qt):
    app = _app()
    _comecar(app)
    assert app.achar("relogioDaSessao").property("visible") is False
    app.fechar()


def test_relogio_acompanha_o_tique(app_qt, monkeypatch):
    monkeypatch.setattr(modulo_da_sessao.window_geometry, "session_geometry", lambda: object())
    app = _app()
    _comecar(app)
    relogio = app.achar("relogioDaSessao")
    assert relogio.property("visible") is True
    app.sessao.session_elapsed = lambda: 125

    app.sessao._tique.timeout.emit()  # noqa: SLF001
    _esperar()

    assert relogio.property("text") == "0:02:05"
    app.fechar()
def test_anotacao_da_sessao_vai_ao_jogo_da_sessao(app_qt):
    app = _app()
    _abrir_pelo_cartao(app, 1)  # os detalhes de Beta ficam por baixo
    _comecar(app, 0)
    assert app.achar("camadaDaSessao").property("visible") is True
    QMetaObject.invokeMethod(app.achar("botaoAnotacaoDaSessao"), "click", Qt.ConnectionType.DirectConnection)
    balao = app.achar("balaoDaSessao")
    assert _esperar(lambda: balao.property("opened") is True)
    campo = _achar(balao.property("contentItem"), "campoDaAnotacao")
    campo.setProperty("text", "  fase do castelo  ")
    balao.close()
    assert _esperar(lambda: app.jogos[0].notes == "fase do castelo")
    assert not app.jogos[1].notes
    app.fechar()


def test_balao_aberto_deixa_o_botao_marcado(app_qt):
    """M4/M5: o `MenuButton` da `main` fica `:checked` com o balão aberto, e a dica não fica por cima dele."""
    app = _app()
    _comecar(app)
    botao = app.achar("botaoAnotacaoDaSessao")
    assert botao.property("checked") is False
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    balao = app.achar("balaoDaSessao")
    assert _esperar(lambda: balao.property("opened") is True)
    assert botao.property("checked") is True
    balao.close()
    assert _esperar(lambda: botao.property("checked") is False)
    app.fechar()


def test_anotacao_digitada_chega_ao_jogo_mesmo_se_a_sessao_acaba_com_o_balao_aberto(app_qt):
    app = _app()
    _comecar(app)
    QMetaObject.invokeMethod(app.achar("botaoAnotacaoDaSessao"), "click", Qt.ConnectionType.DirectConnection)
    balao = app.achar("balaoDaSessao")
    assert _esperar(lambda: balao.property("opened") is True)
    _achar(balao.property("contentItem"), "campoDaAnotacao").setProperty("text", "no chefe")
    app.sessao.hide_session_blocker()  # a camada some e o balão fecha sozinho
    assert _esperar(lambda: not balao.property("opened"))
    assert _esperar(lambda: app.jogos[0].notes == "no chefe")
    app.fechar()


def test_grade_para_de_animar_na_sessao(app_qt):
    app = _app()
    assert app.achar("grade").property("ativa") is True
    _comecar(app)
    assert app.achar("grade").property("ativa") is False
    app.fechar()


def test_avisos_ficam_na_frente_da_sessao(app_qt):
    app = _app()
    _comecar(app)
    camada, avisos = app.achar("camadaDaSessao"), app.achar("camadaDeAvisos")
    irmaos = camada.parentItem().childItems()
    assert irmaos.index(avisos) > irmaos.index(camada)
    chamado = []
    app.ponte.fila.adicionar("Alfa: 1 h de jogo", "Anotar", lambda: chamado.append(1))
    botao = app.achar("botaoDoAviso")
    assert _esperar(lambda: app.achar("aviso").property("opacity") == 1)
    _clicar(app, botao)
    assert chamado == [1]
    app.fechar()


def test_anotar_abre_os_detalhes_com_o_balao(app_qt):
    app = _app()
    app.sessao.session_toast(app.jogos[0], 3600)
    app.ponte.fila.clicar()
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    pagina = app.achar("paginaDoJogo")
    assert app.achar("tituloDoJogo").property("text") == "Alfa"
    assert _esperar(lambda: _achar(pagina, "balaoDaAnotacao").property("opened") is True)
    app.fechar()


def test_anotar_com_os_detalhes_de_outro_jogo_abertos(app_qt):
    app = _app()
    _abrir_pelo_cartao(app, 1)
    assert app.achar("tituloDoJogo").property("text") == "Beta"
    app.sessao.session_toast(app.jogos[0], 3600)
    app.ponte.fila.clicar()
    assert _esperar(lambda: app.achar("tituloDoJogo").property("text") == "Alfa")
    assert _esperar(lambda: app.achar("balaoDaAnotacao").property("opened") is True)
    app.fechar()


def test_fim_da_sessao_devolve_a_janela_inteira(app_qt):
    app = _app()
    _comecar(app)
    app.sessao.hide_session_blocker()
    assert _esperar(lambda: not app.achar("camadaDaSessao").property("visible"))
    assert app.achar("barraDeTitulo").property("visible") is True
    assert app.janela.property("telaCheia") is False
    assert app.achar("pagina").property("enabled") is True
    assert app.achar("alvoDeSoltar").property("enabled") is True
    assert app.achar("grade").property("ativa") is True
    app.fechar()


def test_capa_animada_dos_detalhes_para_na_sessao(app_qt, tmp_path):
    app = _app()
    gif = tmp_path / "capa.gif"
    Image.new("P", (50, 75)).save(gif, save_all=True, append_images=[Image.new("P", (50, 75), 1)], duration=100, loop=0)
    _abrir_pelo_cartao(app, 0)
    app.detalhes._mesclar({"capaAnimada": QUrl.fromLocalFile(str(gif)).toString()})  # noqa: SLF001
    animada = app.achar("capaAnimadaDaPagina")
    assert _esperar(lambda: animada.property("playing") is True and animada.property("source").toString() != "")
    _comecar(app, 1)
    assert _esperar(lambda: animada.property("playing") is False and animada.property("source").toString() == "")
    app.sessao.hide_session_blocker()
    assert _esperar(lambda: animada.property("playing") is True and animada.property("source").toString() != "")
    app.fechar()


def test_capa_animada_do_big_picture_para_na_sessao(app_qt, monkeypatch, tmp_path):
    app = _aberto_com(monkeypatch)
    gif = tmp_path / "capa.gif"
    Image.new("P", (50, 75)).save(gif, save_all=True, append_images=[Image.new("P", (50, 75), 1)], duration=100, loop=0)
    _entrar(app)
    app.big_picture._jogos[0]["capaAnimada"] = QUrl.fromLocalFile(str(gif)).toString()  # noqa: SLF001
    app.big_picture._animar_central = True  # noqa: SLF001
    app.big_picture.jogosMudaram.emit()
    app.big_picture.animarCentralMudou.emit()

    def tocando():
        return any(
            _achar(c, "capaAnimada").property("source").toString()
            for c in _itens(app.achar("bigPicture"), lambda i: i.objectName() == "capaDoBigPicture")
        )

    assert _esperar(tocando)
    app.sessao.show_session_blocker(app.jogos[1])
    assert _esperar(lambda: not tocando())
    app.sessao.hide_session_blocker()
    assert _esperar(tocando)
    app.fechar()


def test_controle_nao_age_por_baixo_da_camada(app_qt, monkeypatch, lancamentos):
    app = _aberto_com(monkeypatch)
    _entrar(app)
    posicao = app.achar("bigPicture").property("posicao")
    app.sessao.show_session_blocker(app.jogos[0])
    _esperar()
    for sinal in (
        lambda: app.controle.ativar.emit(), lambda: app.controle.voltar.emit(),
        lambda: app.controle.mover.emit(1, 0), lambda: app.controle.mover.emit(0, 1),
        lambda: app.controle.pular.emit(10), lambda: app.controle.menuPrincipal.emit(),
        lambda: app.controle.menuDoJogo.emit(), lambda: app.controle.buscar.emit(),
    ):
        sinal()
        _esperar()
        assert (app.big_picture.visivel, app.big_picture.ocupada) == (True, False)  # nem abriu o jogo nem saiu
        assert app.achar("bigPicture").property("posicao") == posicao
        assert app.achar("menuPrincipal").property("opened") is False
        assert app.janela.property("paginaAtual") == "todos"
    assert lancamentos == []
    app.fechar()


def test_controle_nao_abre_menu_nem_detalhes_na_grade_com_a_sessao(app_qt, lancamentos):
    app = _app()
    _cartao_focado(app)
    _comecar(app)
    for sinal in (app.controle.ativar, app.controle.menuPrincipal, app.controle.menuDoJogo, app.controle.buscar):
        sinal.emit()
        _esperar()
        assert app.janela.property("paginaAtual") == "todos"
        assert app.achar("menuPrincipal").property("opened") is False
        assert app.achar("menuDoJogo").property("visible") is False
    assert lancamentos == []
    app.fechar()


# -- Auditoria GTK x Qt, pacote D (sessão) ----------------------------------------------------------


def test_enter_aciona_o_ja_terminei_e_abre_o_balao(app_qt, monkeypatch):
    """SES-08: o `Gtk.Button` responde a Enter e a Espaço; o `Button` do Qt só respondia a Espaço."""
    app = _app()
    processo = _ProcessoFalso()
    monkeypatch.setattr(ProcessSession, "active", processo)
    _comecar(app)
    assert _foco_dentro_de(app, "botaoJaTerminei")
    _tecla(app, Qt.Key.Key_Return)
    assert processo.parou == [True]
    _tecla(app, Qt.Key.Key_Enter)  # o Enter do teclado numérico também
    assert processo.parou == [True, True]
    _tecla(app, Qt.Key.Key_Tab)
    assert _foco_dentro_de(app, "botaoAnotacaoDaSessao")
    _tecla(app, Qt.Key.Key_Return)
    assert _esperar(lambda: app.achar("balaoDaSessao").property("opened") is True)
    app.fechar()


def test_foco_aberto_pelo_teclado_tem_anel_e_pelo_mouse_nao(app_qt):
    """SES-07: o anel só vem se o teclado já estava em uso quando o jogo abriu (`grab_focus` depois do clique, na `main`)."""
    app = _app()
    _cartao_focado(app)
    _tecla(app, Qt.Key.Key_Right)  # o teclado em uso: a grade mostra o anel do cartão
    assert app.achar("grade").property("porTeclado") is True
    _comecar(app)
    assert _foco_dentro_de(app, "botaoJaTerminei")
    assert app.achar("botaoJaTerminei").property("visualFocus") is True
    app.fechar()

    # Com o mouse (outra janela, sem o gesto de teclado de antes): abre os detalhes e clica em "Jogar" (o `launch` é falso), como a pessoa faria.
    app = _app()
    _abrir_pelo_cartao(app, 0)
    _clicar(app, app.achar("botaoJogarDaPagina"))
    _comecar(app)
    assert _foco_dentro_de(app, "botaoJaTerminei")
    assert app.achar("botaoJaTerminei").property("activeFocus") is True
    assert app.achar("botaoJaTerminei").property("visualFocus") is False
    app.fechar()


def test_botoes_da_camada_sao_os_da_main(app_qt):
    """SES-04/09/10/12: pílula de 44 com 12 px em negrito e padding 32; relógio e nome em title-1; "Onde eu parei" com a seta."""
    app = _app()
    _comecar(app)
    botao, anotar = app.achar("botaoJaTerminei"), app.achar("botaoAnotacaoDaSessao")
    assert botao.height() == 44 and botao.property("leftPadding") == 32 and botao.property("rightPadding") == 32
    assert botao.property("estilo") == "sugestao" and botao.property("pilula") is True
    assert (anotar.height(), anotar.property("leftPadding")) == (34, 10)
    assert anotar.property("estilo") == "plano"
    assert _expr(anotar, "contentItem.children[0].font.pixelSize") == 12
    assert _expr(anotar, "contentItem.children[0].font.weight") == 700
    assert _expr(anotar, "contentItem.children[1].nome") == "pan-down"  # a seta ao lado do texto
    nome = app.achar("nomeDaSessao")
    assert _expr(nome, "font.pixelSize") == 22 and _expr(nome, "font.weight") == 800
    app.fechar()


def _nome_de_largura(minimo, maximo):
    """Um nome cujo texto em title-1 mede entre `minimo` e `maximo` px, com a fonte que houver (a offscreen não tem fontes)."""
    fonte = QFont("Segoe UI")
    fonte.setPixelSize(22)
    fonte.setWeight(QFont.Weight.ExtraBold)
    medida, nome = QFontMetricsF(fonte), "Jogo"
    while medida.horizontalAdvance(nome) < minimo:
        nome += " jogo"
    assert medida.horizontalAdvance(nome) <= maximo
    return nome


def test_nome_ocupa_a_largura_natural_e_so_quebra_no_limite_da_janela(app_qt):
    """SES-11: a coluna não é presa a 640; só o logo é. O nome quebra em `largura - 48`."""
    app = _app((1, _nome_de_largura(700, 1100), {}))
    app.janela.setWidth(1170)
    _comecar(app)
    nome = app.achar("nomeDaSessao")
    assert _esperar(lambda: nome.width() > 640)  # antes: coluna presa a min(largura - 48, 640)
    assert nome.property("lineCount") == 1
    app.fechar()

    app = _app((1, "palavra " * 40, {}))
    app.janela.setWidth(1170)
    _comecar(app)
    nome = app.achar("nomeDaSessao")
    assert _esperar(lambda: nome.property("lineCount") > 1)
    assert nome.width() == 1170 - 48
    app.fechar()


def test_anotacao_da_camada_grava_em_jogo_zerado(app_qt):
    """SES-16: na `main` a caixa da camada nunca é só leitura; só uma caixa não editável deixa de gravar."""
    app = _app((1, "Alfa", {"status": "beaten", "removed": True}))
    assert app.jogos[0].zerado
    _comecar(app)
    QMetaObject.invokeMethod(app.achar("botaoAnotacaoDaSessao"), "click", Qt.ConnectionType.DirectConnection)
    balao = app.achar("balaoDaSessao")
    assert _esperar(lambda: balao.property("opened") is True)
    _achar(balao.property("contentItem"), "campoDaAnotacao").setProperty("text", "no último chefe")
    balao.close()
    assert _esperar(lambda: app.jogos[0].notes == "no último chefe")
    app.fechar()
