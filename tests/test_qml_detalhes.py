# test_qml_detalhes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A página de detalhes na tela e a navegação até ela (QML offscreen, sem a ponte do QWindowKit)."""

import pytest
from PIL import Image
from PySide6.QtCore import Q_ARG, QMetaObject, QPoint, Qt, QUrl
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.jogo import Jogo
from tests.apoio_qml_biblioteca import _achar, _App, _esperar, _jogos, _tres
from tests.apoio_qml_detalhes import _abrir_pelo_cartao, _cartoes, _clicar, _foco_dentro_de


@pytest.fixture(autouse=True)
def _sem_jogo_de_verdade(monkeypatch):
    """Os botões agora agem no `Jogo`: nenhum clique de teste inicia um programa."""
    monkeypatch.setattr(Jogo, "launch", lambda self, *a: True)


def test_abrir_pelo_cartao_empurra_a_pagina(app_qt):
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app, 1)
    assert app.detalhes.jogoId == "imported_2"
    assert app.janela.property("tituloDaBarra") == "Beta"
    assert app.achar("botaoVoltar").property("visible") is True
    # Foco ao abrir: "Jogar".
    assert _esperar(lambda: _foco_dentro_de(app, "botaoJogarDaPagina"))
    assert pagina.property("visible") is True
    app.fechar()


def test_enter_da_busca_abre_o_primeiro(app_qt):
    app = _App(_tres())
    app.achar("pagina").setProperty("buscaAberta", True)
    assert _esperar(lambda: _foco_dentro_de(app, "campoDeBusca"))
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    assert app.detalhes.jogoId == "imported_1"
    app.fechar()


def test_enter_da_grade_abre_o_atual(app_qt):
    app = _App(_tres())
    app.achar("grade").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    QTest.keyClick(app.janela, Qt.Key.Key_Right)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    assert app.detalhes.jogoId == "imported_2"
    app.fechar()


def test_esc_volta_e_foca_o_cartao(app_qt):
    app = _App(_tres())
    _abrir_pelo_cartao(app, 2)
    assert _esperar(lambda: _foco_dentro_de(app, "botaoJogarDaPagina"))
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    grade = app.achar("grade")
    assert _esperar(lambda: grade.property("activeFocus") is True)
    assert grade.property("currentIndex") == 2
    assert app.detalhes.jogoId == "imported_3"  # o modelo ainda guarda; o que importa é que parou de seguir
    assert app.detalhes._jogo is None  # noqa: SLF001
    app.fechar()


def test_botao_voltar_da_barra_fecha_a_pagina(app_qt):
    app = _App(_tres())
    _abrir_pelo_cartao(app)
    QMetaObject.invokeMethod(app.achar("botaoVoltar"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    app.fechar()


def test_logo_esconde_o_titulo(app_qt, tmp_path):
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    titulo, logo = _achar(pagina, "tituloDoJogo"), _achar(pagina, "logoDoJogo")
    assert titulo.property("visible") is True and logo.property("visible") is False
    Image.new("RGBA", (300, 80), "red").save(tmp_path / "logo.png")
    app.detalhes._mesclar({"logo": QUrl.fromLocalFile(str(tmp_path / "logo.png")).toString(), "larguraDoLogo": 300})  # noqa: SLF001
    assert _esperar(lambda: logo.property("visible") is True)
    assert titulo.property("visible") is False
    app.fechar()


def test_fundo_desfocado_carrega_na_thread_principal(app_qt):
    # Provedor Python na thread de imagens trava: ela espera o GIL segurando o mutex do cache.
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    assert _achar(pagina, "fundoDesfocado").property("asynchronous") is False
    app.fechar()


def test_logo_grande_e_decodificado_na_escala_da_tela(app_qt, tmp_path):
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    logo = _achar(pagina, "logoDoJogo")
    Image.new("RGBA", (3000, 900), "red").save(tmp_path / "grande.png")
    app.detalhes._mesclar({"logo": QUrl.fromLocalFile(str(tmp_path / "grande.png")).toString(), "larguraDoLogo": 240})  # noqa: SLF001
    assert _esperar(lambda: logo.property("visible") is True)
    assert logo.property("implicitHeight") <= 72 * 4  # não os 900 px do arquivo
    app.fechar()


def test_logo_truncado_volta_ao_titulo(app_qt, tmp_path):
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    titulo, logo = _achar(pagina, "tituloDoJogo"), _achar(pagina, "logoDoJogo")
    Image.new("RGBA", (300, 80), "red").save(tmp_path / "inteiro.png")
    # O cabeçalho passa na leitura de `load_logo`, mas o resto do arquivo falta.
    (tmp_path / "truncado.png").write_bytes((tmp_path / "inteiro.png").read_bytes()[:40])
    app.detalhes._mesclar({"logo": QUrl.fromLocalFile(str(tmp_path / "truncado.png")).toString(), "larguraDoLogo": 300})  # noqa: SLF001
    assert _esperar(lambda: titulo.property("visible") is True)
    assert logo.property("visible") is False
    app.fechar()


def test_zerado_mostra_excluir_e_nao_jogar(app_qt):
    app = _App(_jogos((1, "Alfa", {}), (2, "Zero", {"removed": True, "status": "beaten"})))
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    _esperar()
    _clicar(app, _cartoes(app, "gradeDeZerados")[0])
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    pagina = app.achar("paginaDoJogo")
    assert _achar(pagina, "botaoJogarDaPagina").property("visible") is False
    assert _achar(pagina, "botaoRemover").property("visible") is False
    assert _achar(pagina, "botaoBuscarDaPagina").property("visible") is False
    assert _achar(pagina, "botaoExcluir").property("visible") is True
    # Foco ao abrir um zerado: o botão de status.
    assert _esperar(lambda: _foco_dentro_de(app, "botaoStatus"))
    app.fechar()


def test_sair_volta_para_zerados_quando_veio_de_la(app_qt):
    app = _App(_jogos((1, "Alfa", {}), (2, "Zero", {"removed": True, "status": "beaten"})))
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    _esperar()
    _clicar(app, _cartoes(app, "gradeDeZerados")[0])
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    assert _esperar(lambda: _foco_dentro_de(app, "paginaDeZerados"))
    # E o `sair` do modelo (o jogo foi excluído) também fecha a página.
    assert _esperar(lambda: _achar(app.janela, "paginaDoJogo") is None)  # a transição de volta termina antes do clique
    _clicar(app, _cartoes(app, "gradeDeZerados")[0])
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    app.loja.jogo_excluido.emit("imported_2")
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    app.fechar()


def test_textos_de_terceiros_em_texto_puro(app_qt):
    app = _App(_jogos((1, "A & <b>B</b>", {"developer": "<i>Dev</i>", "description": "<h1>Sinopse</h1> &amp; mais"})))
    pagina = _abrir_pelo_cartao(app)
    assert _achar(pagina, "tituloDoJogo").property("text") == "A & <b>B</b>"
    assert _achar(pagina, "descricao").property("text") == "<h1>Sinopse</h1> &amp; mais"
    assert _achar(pagina, "desenvolvedora").property("text") == "<i>Dev</i>"
    # O nome também vai para a barra de título: literal, em texto puro.
    barra = app.achar("tituloDaBarraTexto")
    assert barra.property("text") == "A & <b>B</b>"
    assert QQmlExpression(QQmlEngine.contextForObject(barra), barra, "textFormat").evaluate()[0] == 0
    textos, pilha = [], [pagina]
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, QQuickItem):
            if atual.metaObject().className().startswith("QQuickText"):
                textos.append(atual)
            pilha.extend(atual.childItems())
        pilha.extend(atual.children())
    assert len(textos) > 10
    for texto in textos:
        assert QQmlExpression(QQmlEngine.contextForObject(texto), texto, "textFormat").evaluate()[0] == 0, texto.property("text")  # Text.PlainText
    app.fechar()


def test_controle_move_o_foco_entre_os_botoes_e_b_volta(app_qt):
    app = _App(_tres())
    _abrir_pelo_cartao(app)
    assert _esperar(lambda: _foco_dentro_de(app, "botaoJogarDaPagina"))
    app.controle.mover.emit(1, 0)
    assert _foco_dentro_de(app, "botaoEditar")
    app.controle.mover.emit(-1, 0)
    assert _foco_dentro_de(app, "botaoJogarDaPagina")
    app.controle.voltar.emit()
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    app.fechar()


def test_botoes_so_emitem_sinais(app_qt):
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    recebidos = []
    pagina.editar.connect(lambda: recebidos.append("editar"))
    pagina.remover.connect(lambda: recebidos.append("remover"))
    QMetaObject.invokeMethod(_achar(pagina, "botaoEditar"), "click", Qt.ConnectionType.DirectConnection)
    QMetaObject.invokeMethod(_achar(pagina, "botaoRemover"), "click", Qt.ConnectionType.DirectConnection)
    assert recebidos == ["editar", "remover"]
    app.fechar()


def test_enter_da_busca_e_voltar_focam_o_cartao_aberto(app_qt):
    app = _App(_tres())
    app.achar("pagina").setProperty("buscaAberta", True)
    assert _esperar(lambda: _foco_dentro_de(app, "campoDeBusca"))
    app.achar("campoDeBusca").setProperty("text", "a")  # Alfa, Beta e Gama
    _esperar()
    grade = app.achar("grade")
    grade.setProperty("currentIndex", 2)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    assert app.detalhes.jogoId == "imported_1"
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    assert grade.property("currentIndex") == 0
    app.fechar()


def test_mostrar_devolve_falso_para_id_desconhecido_e_a_pagina_nao_abre(app_qt):
    app = _App(_tres())
    assert app.detalhes.mostrar("imported_1") is True
    assert app.detalhes.mostrar("nao-existe") is False
    app.detalhes.esquecer()
    # O modelo ainda guarda "imported_1", mas o jogo saiu da loja: a página não pode abrir sem segui-lo.
    app.loja.por_id.pop("imported_1")
    QMetaObject.invokeMethod(app.janela, "abrirDetalhes", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "imported_1"))
    _esperar()
    assert app.janela.property("paginaAtual") == "todos"
    app.fechar()


def test_controle_a_abre_a_pagina_e_ativa_o_botao_focado(app_qt):
    app = _App(_tres())
    app.controle.ativar.emit()  # A na grade: abre o cartão atual
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    assert _esperar(lambda: _foco_dentro_de(app, "botaoJogarDaPagina"))
    pagina = app.achar("paginaDoJogo")
    recebidos = []
    pagina.jogar.connect(lambda: recebidos.append("jogar"))
    pagina.editar.connect(lambda: recebidos.append("editar"))
    app.controle.ativar.emit()  # A em "Jogar"
    app.controle.mover.emit(1, 0)
    app.controle.ativar.emit()  # A em "Editar"
    assert recebidos == ["jogar", "editar"]
    app.controle.voltar.emit()  # B
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    app.fechar()


def test_jogar_emite_o_sinal_e_excluir_so_pergunta(app_qt):
    app = _App(_jogos((1, "Alfa", {}), (2, "Zero", {"removed": True, "status": "beaten"})))
    pagina = _abrir_pelo_cartao(app)
    recebidos = []
    pagina.jogar.connect(lambda: recebidos.append("jogar"))
    QMetaObject.invokeMethod(_achar(pagina, "botaoJogarDaPagina"), "click", Qt.ConnectionType.DirectConnection)
    assert recebidos == ["jogar"]
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: _achar(app.janela, "paginaDoJogo") is None)
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    _esperar()
    _clicar(app, _cartoes(app, "gradeDeZerados")[0])
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    pagina = app.achar("paginaDoJogo")
    pagina.excluir.connect(lambda: recebidos.append("excluir"))
    QMetaObject.invokeMethod(_achar(pagina, "botaoExcluir"), "click", Qt.ConnectionType.DirectConnection)
    # O botão só pergunta; o sinal sai depois da confirmação.
    assert recebidos == ["jogar"]
    app.fechar()


def test_excluir_pede_confirmacao(app_qt):
    zero = {"removed": True, "status": "beaten", "executable": ""}
    app = _App(_jogos((1, "Zero", zero)))
    excluidos = []
    app.loja.excluir = lambda jogo: excluidos.append(jogo)
    app.detalhes.mostrar("imported_1")
    QMetaObject.invokeMethod(app.janela, "abrirDetalhes", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "imported_1"))
    _esperar()
    pagina = app.achar("paginaDoJogo")
    dialogo = _achar(pagina, "dialogoExcluir")
    assert dialogo.property("visible") is False
    QMetaObject.invokeMethod(_achar(pagina, "botaoExcluir"), "click", Qt.ConnectionType.DirectConnection)
    assert dialogo.property("visible") is True
    assert dialogo.property("titulo") == "Excluir Zero?"
    assert dialogo.property("corpo") == "Tem certeza que deseja excluir este jogo? Esta ação é irreversível."
    assert dialogo.property("destrutivo") is True
    # Cancelar (Esc) não exclui.
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert dialogo.property("visible") is False and excluidos == []
    QMetaObject.invokeMethod(_achar(pagina, "botaoExcluir"), "click", Qt.ConnectionType.DirectConnection)
    QMetaObject.invokeMethod(_achar(dialogo, "botaoConfirmarDoDialogo"), "click", Qt.ConnectionType.DirectConnection)
    assert len(excluidos) == 1
    app.fechar()


def _abrir_excluir(app):
    app.detalhes.mostrar("imported_1")
    QMetaObject.invokeMethod(app.janela, "abrirDetalhes", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", "imported_1"))
    _esperar()
    pagina = app.achar("paginaDoJogo")
    botao = _achar(pagina, "botaoExcluir")
    botao.forceActiveFocus()
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    return pagina, _achar(pagina, "dialogoExcluir"), botao


def test_dialogo_destrutivo_e_modal_para_teclado_e_controle(app_qt):
    app = _App(_jogos((1, "Zero", {"removed": True, "status": "beaten", "executable": ""})))
    pagina, dialogo, botao = _abrir_excluir(app)
    # Foco inicial no Cancelar (a ação é destrutiva).
    assert _foco_dentro_de(app, "botaoCancelarDoDialogo")
    cliques = []
    for nome in ("botaoEditar", "botaoExcluir", "botaoStatus"):
        _achar(pagina, nome).clicked.connect(lambda n=nome: cliques.append(n))
    for tecla in (Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Tab, Qt.Key.Key_Tab, Qt.Key.Key_Tab):
        QTest.keyClick(app.janela, tecla)
        assert dialogo.property("visible") is True
        assert _foco_dentro_de(app, "botaoCancelarDoDialogo") or _foco_dentro_de(app, "botaoConfirmarDoDialogo")
    # Seis teclas deixaram o foco no Cancelar; esquerda e direita alternam entre os dois botões.
    assert _foco_dentro_de(app, "botaoCancelarDoDialogo")
    QTest.keyClick(app.janela, Qt.Key.Key_Right)
    assert _foco_dentro_de(app, "botaoConfirmarDoDialogo")
    QTest.keyClick(app.janela, Qt.Key.Key_Left)
    assert _foco_dentro_de(app, "botaoCancelarDoDialogo")
    # O A do controle só aperta o botão do diálogo: Cancelar.
    app.controle.mover.emit(1, 0)
    assert _foco_dentro_de(app, "botaoConfirmarDoDialogo")
    app.controle.mover.emit(-1, 0)
    assert _foco_dentro_de(app, "botaoCancelarDoDialogo")
    app.controle.ativar.emit()
    assert dialogo.property("visible") is False and cliques == []
    # Ao fechar, o foco volta ao botão que abriu.
    assert _foco_dentro_de(app, "botaoExcluir")
    app.fechar()


def test_balao_e_menus_nao_vazam_o_foco_para_a_pagina(app_qt):
    app = _App(_jogos((1, "Alfa", {"status": "playing"})))
    pagina = _abrir_pelo_cartao(app)
    for botao, popup in (("botaoStatus", "menuDeStatus"), ("botaoBuscarDaPagina", "menuDeBuscas"), ("botaoAnotacao", "balaoDaAnotacao")):
        QMetaObject.invokeMethod(_achar(pagina, botao), "click", Qt.ConnectionType.DirectConnection)
        _esperar()
        aberto = _achar(pagina, popup)
        assert aberto.property("opened") is True
        for tecla in (Qt.Key.Key_Left, Qt.Key.Key_Right, Qt.Key.Key_Tab, Qt.Key.Key_Up):
            QTest.keyClick(app.janela, tecla)
            assert aberto.property("opened") is True, (popup, tecla)
        item = app.janela.property("activeFocusItem")
        dentro = False
        while item is not None:
            dentro = dentro or item == aberto or item.parentItem() == aberto.property("contentItem") or item == aberto.property("contentItem")
            item = item.parentItem()
        assert dentro, popup
        aberto.close()
        _esperar()
    app.fechar()


def _app_com_atualizacao(monkeypatch):
    """Um jogo com a faixa "Atualização disponível"; a página e o navegador são falsos (nada é aberto de verdade)."""
    from cartridges.modelos import detalhes as modelo_dos_detalhes  # noqa: PLC0415
    from cartridges.utils import open_uri  # noqa: PLC0415

    abertos = []
    monkeypatch.setattr(modelo_dos_detalhes, "abrir_url", lambda url: abertos.append(url) or True)
    monkeypatch.setattr(open_uri.QDesktopServices, "openUrl", lambda url: abertos.append(url) or True)
    app = _App(_jogos((1, "Alfa", {"track_updates": True, "update_available_ts": 10, "update_url": "https://r.example/x"})))
    monkeypatch.setattr(app.jogos[0], "save", lambda: None)
    _abrir_pelo_cartao(app, 0)
    assert _esperar(lambda: app.achar("avisoDeAtualizacao").property("visible") is True)
    _clicar(app, app.achar("avisoDeAtualizacao"))
    dialogo = app.achar("dialogoAtualizacao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    assert abertos == ["https://r.example/x"]
    return app, dialogo, abertos


def test_voce_instalou_a_atualizacao_foco_padrao_e_ja_instalei(app_qt, monkeypatch):
    """Como a `main`: o padrão é "Já instalei" (`set_default_response("confirm")`); ele esconde a faixa."""
    app, dialogo, _abertos = _app_com_atualizacao(monkeypatch)
    assert dialogo.property("corpo") == "A página da atualização foi aberta no navegador. Confirme após instalá-la para ocultar o aviso."
    assert dialogo.property("rotuloConfirmar") == "Já instalei" and dialogo.property("rotuloCancelar") == "Ainda não"
    assert dialogo.property("titulo") == "Você instalou a atualização?"
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoAtualizacao"))
    assert dialogo.findChild(QQuickItem, "botaoConfirmarDoDialogo").property("activeFocus") is True
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert _esperar(lambda: app.achar("avisoDeAtualizacao").property("visible") is False)
    assert app.jogos[0].update_available_ts == 0
    app.fechar()


@pytest.mark.parametrize("tecla", [None, Qt.Key.Key_Escape])
def test_voce_instalou_a_atualizacao_ainda_nao_nao_descarta(app_qt, monkeypatch, tecla):
    """"Ainda não" e Esc (o `set_close_response("cancel")` da `main`) não descartam; a faixa segue viva."""
    app, dialogo, abertos = _app_com_atualizacao(monkeypatch)
    if tecla is None:
        _clicar(app, dialogo.findChild(QQuickItem, "botaoCancelarDoDialogo"))
    else:
        QTest.keyClick(app.janela, tecla)
    assert _esperar(lambda: dialogo.property("visible") is False)
    _esperar()  # um descarte adiado (callLater) apareceria aqui
    assert app.achar("avisoDeAtualizacao").property("visible") is True
    assert app.jogos[0].update_available_ts == 10
    _clicar(app, app.achar("avisoDeAtualizacao"))
    assert _esperar(lambda: dialogo.property("visible") is True)
    assert abertos == ["https://r.example/x"] * 2
    app.fechar()


def test_closing_the_notes_popover_saves_the_text(app_qt):
    """O balão grava ao fechar, com o mesmo tratamento de espaços da edição: só Enter conta como vazio."""
    app = _App(_jogos((1, "Alfa", {"status": "playing"})))
    pagina = _abrir_pelo_cartao(app)
    balao = _achar(pagina, "balaoDaAnotacao")
    for digitado, gravado in (("\n  Parei no capítulo 4.\nCofre: 8815  \n", "Parei no capítulo 4.\nCofre: 8815"), ("\n\n", "")):
        balao.open()
        assert _esperar(lambda: balao.property("opened") is True)
        _achar(balao.property("contentItem"), "campoDaAnotacao").setProperty("text", digitado)
        balao.close()
        assert _esperar(lambda: app.jogos[0].notes == gravado)
    app.fechar()


def test_a_anotacao_nao_aparece_no_meio_das_informacoes(app_qt):
    """A anotação se lê só no balão do botão: o bloco com o texto no meio das informações saiu (pedido de 18/10/2026)."""
    app = _App(_jogos((1, "Alfa", {"status": "playing", "notes": "Cofre: 8815"})))
    pagina = _abrir_pelo_cartao(app)
    balao = _achar(pagina, "balaoDaAnotacao")

    def itens_com_texto(texto):
        """Os objetos da página (fora do balão) cujo `text` é `texto`, descendo por itens e por filhos QObject."""
        achados, pilha, vistos = [], [pagina], {}
        while pilha:
            atual = pilha.pop()
            if id(atual) in vistos or atual == balao:
                continue
            vistos[id(atual)] = atual  # guardar o objeto impede o reuso do id
            if atual.property("text") == texto:
                achados.append(atual)
            pilha.extend(atual.children())
            if isinstance(atual, QQuickItem):
                pilha.extend(atual.childItems())
        return achados

    assert itens_com_texto("Alfa"), "a varredura enxerga os textos da página (o título)"
    assert itens_com_texto("Cofre: 8815") == [], "a anotação só entra no balão"
    app.fechar()


def test_capa_ilegivel_na_pagina_mostra_a_capa_padrao(app_qt):
    """Como na grade: um arquivo de capa quebrado mostra o placeholder, e não um quadro vazio."""
    (shared.covers_dir / "imported_1.tiff").write_bytes(b"nao e uma imagem")
    app = _App(_jogos((1, "Alfa", {})))
    pagina = _abrir_pelo_cartao(app)
    capa = _achar(pagina, "capaDaPagina")
    assert _esperar(lambda: capa.property("source").toString().endswith("library_placeholder.svg"))
    app.fechar()
