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
    assert _esperar(lambda: _foco_dentro_de(app, "botaoCancelarDoDialogo"))
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
    assert _esperar(lambda: _foco_dentro_de(app, "botaoExcluir"))
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
    assert _esperar(lambda: _achar(dialogo, "botaoConfirmarDoDialogo").property("activeFocus") is True)
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
        _clicar(app, _achar(dialogo, "botaoCancelarDoDialogo"))
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


# -- Auditoria GTK x Qt, pacote B: a página de detalhes como a da `main` --------------------------------------------


def _centro(item):
    return item.mapToScene(item.boundingRect().center())


def test_a_pagina_vira_coluna_ate_850(app_qt):
    """DE-06: o `Adw.Breakpoint (max-width: 850px)`: capa de 280 em cima, tudo numa coluna."""
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    app.janela.resize(1000, 795)
    assert _esperar(lambda: pagina.property("compacta") is False)
    assert pagina.property("larguraDaCapa") == 420
    capa = _achar(pagina, "capaDaPagina")
    texto = _achar(pagina, "tituloDoJogo")
    assert capa.parentItem().mapToScene(capa.parentItem().boundingRect().center()).y() <= texto.mapToScene(texto.boundingRect().center()).y() + 400
    larga_x = _centro(capa.parentItem()).x(), _centro(texto).x()
    assert larga_x[0] < larga_x[1]  # a capa à esquerda, o texto à direita
    app.janela.resize(850, 795)
    assert _esperar(lambda: pagina.property("compacta") is True)
    assert pagina.property("larguraDaCapa") == 280
    capa_y, texto_y = _centro(capa.parentItem()).y(), _centro(texto).y()
    assert texto_y > capa_y  # o texto desceu para baixo da capa
    assert abs(_centro(capa.parentItem()).x() - app.janela.width() / 2) < 2  # capa centrada
    app.fechar()


def test_barra_de_acao_botoes_de_34_e_jogar_de_44(app_qt):
    """DE-03, DE-04, DE-05: "Jogar" é uma pílula de 44; os redondos, 34x34, a 15 do "Jogar" e a 6 entre si."""
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    jogar, editar, remover, buscar = (_achar(pagina, n) for n in ("botaoJogarDaPagina", "botaoEditar", "botaoRemover", "botaoBuscarDaPagina"))
    assert jogar.property("height") == 44
    assert (editar.property("width"), editar.property("height")) == (34, 34)
    assert (buscar.property("width"), buscar.property("height")) == (34, 34)
    x = lambda item: item.mapToScene(item.boundingRect().topLeft()).x()  # noqa: E731
    assert round(x(editar) - (x(jogar) + jogar.property("width"))) == 15
    assert round(x(remover) - (x(editar) + 34)) == 6
    # Os ícones são os da `main` (Adwaita), não glifos da Segoe.
    assert (editar.property("icone"), remover.property("icone"), buscar.property("icone")) == ("document-edit", "user-trash", "system-search")
    app.fechar()


def test_jogar_usa_o_texto_e_o_fundo_invertidos_por_tema(app_qt):
    """DE-02: branco sobre preto a 80% no claro; preto a 80% sobre branco no escuro."""
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    jogar = _achar(pagina, "botaoJogarDaPagina")
    escuro = QQmlExpression(QQmlEngine.contextForObject(jogar), jogar, "Tema.escuro").evaluate()[0]
    fundo = QQmlExpression(QQmlEngine.contextForObject(jogar), jogar, "background.color").evaluate()[0]
    texto = QQmlExpression(QQmlEngine.contextForObject(jogar), jogar, "corDoTexto").evaluate()[0]
    if escuro:
        assert fundo.name() == "#ffffff" and texto.alpha() == 204 and texto.red() == 0
    else:
        assert texto.name() == "#ffffff" and fundo.alpha() == 204 and fundo.red() == 0
    app.fechar()


def test_o_foco_inicial_so_tem_anel_quando_a_entrada_foi_pelo_teclado(app_qt):
    """DE-26: abrir com o mouse põe o foco em "Jogar" sem o anel (`:focus-visible`); com o teclado, com ele."""
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)  # pelo clique
    jogar = _achar(pagina, "botaoJogarDaPagina")
    assert _esperar(lambda: jogar.property("activeFocus") is True)
    assert jogar.property("visualFocus") is False
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    app.achar("grade").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)  # pelo teclado
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    jogar = _achar(app.achar("paginaDoJogo"), "botaoJogarDaPagina")
    assert _esperar(lambda: jogar.property("visualFocus") is True)
    app.fechar()


def test_o_balao_da_anotacao_abre_centrado_no_botao_e_cresce_para_os_dois_lados(app_qt):
    """DE-31, DE-32: centrado no botão (com seta), e a largura anda o dobro do mouse (`FATOR_DA_LARGURA`)."""
    app = _App(_jogos((1, "Alfa", {"status": "playing"})))
    pagina = _abrir_pelo_cartao(app)
    botao = _achar(pagina, "botaoAnotacao")
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    balao = _achar(pagina, "balaoDaAnotacao")
    assert _esperar(lambda: balao.property("opened") is True)
    conteudo = balao.property("contentItem")
    assert abs(_centro(conteudo).x() - _centro(botao).x()) < 1.5
    # O puxador fica numa faixa própria, abaixo do texto: 16 de altura, depois da última linha do texto.
    puxador = _achar(conteudo, "puxadorDaAnotacao")
    assert puxador.property("height") == 16
    assert puxador.mapToScene(puxador.boundingRect().topLeft()).y() >= conteudo.mapToScene(conteudo.boundingRect().bottomLeft()).y() - 1
    balao.close()
    app.fechar()


def test_o_titulo_do_menu_de_buscas_e_um_rotulo_de_secao_e_o_menu_e_um_popover_com_seta(app_qt):
    """DE-17: "Buscar em…" não é um item apagado; o menu abre centrado no botão, com seta."""
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    botao = _achar(pagina, "botaoBuscarDaPagina")
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    menu = _achar(pagina, "menuDeBuscas")
    assert _esperar(lambda: menu.property("opened") is True)
    titulo = _achar(menu, "tituloDoMenuDeBuscas")
    assert titulo.property("texto") == "Buscar em…" and titulo.property("enabled") is True  # um rótulo, não um item apagado
    assert menu.property("setaEm") > 0
    assert abs(_centro(menu.property("contentItem")).x() - _centro(botao).x()) < 40  # o menu está centrado no botão
    menu.close()
    app.fechar()


def test_jogar_tem_hover_visivel_nos_dois_temas(app_qt):
    """I4/DE-03/Q2: o véu do hover é `currentColor` a 10% (o texto do botão), nos dois temas, não um branco fixo.

    O offscreen não aceita trocar o esquema de cores (`setColorScheme` fica em Unknown), então o escuro é provado pelo
    que o véu usa: a `corDoTexto`, que no escuro é preto a 80% (`test_jogar_usa_o_texto_e_o_fundo_invertidos_por_tema`),
    e nunca o branco fixo do código antigo; no tema que o ambiente der, a cor lida tem de ser a do texto."""
    from pathlib import Path  # noqa: PLC0415

    fonte = (Path(__file__).resolve().parent.parent / "cartridges" / "qml" / "PaginaDoJogo.qml").read_text(encoding="utf-8")
    veu = next(linha for linha in fonte.splitlines() if "botaoJogar.down ? Qt.rgba(0, 0, 6" in linha)
    assert "Qt.alpha(botaoJogar.corDoTexto" in veu and "Qt.rgba(1, 1, 1, 0.1)" not in veu
    app = _App(_tres())
    pagina = _abrir_pelo_cartao(app)
    jogar = _achar(pagina, "botaoJogarDaPagina")
    contexto = QQmlEngine.contextForObject(jogar)
    veu_pronto = QQmlExpression(contexto, jogar, "background.children[0].color").evaluate()[0]
    texto = QQmlExpression(contexto, jogar, "corDoTexto").evaluate()[0]
    assert (veu_pronto.red(), veu_pronto.green(), veu_pronto.blue()) == (texto.red(), texto.green(), texto.blue())
    assert 0 < veu_pronto.alpha() <= 26
    app.fechar()
