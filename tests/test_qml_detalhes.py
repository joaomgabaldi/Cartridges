# test_qml_detalhes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A página de detalhes na tela e a navegação até ela (QML offscreen, sem a ponte do QWindowKit)."""

from PIL import Image
from PySide6.QtCore import Q_ARG, QMetaObject, QPoint, Qt, QUrl
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from tests.test_qml_biblioteca import _achar, _App, _esperar, _jogos, _tres


def _foco_dentro_de(app, nome):
    item = app.janela.property("activeFocusItem")
    while item is not None:
        if item.objectName() == nome:
            return True
        item = item.parentItem()
    return False


def _clicar(app, item):
    ponto = item.mapToScene(item.boundingRect().center()).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(ponto.x(), ponto.y()))


def _cartoes(app, nome_da_grade="grade"):
    """Os cartões da grade (itens com `jogoId`), na ordem do índice."""
    grade = app.achar(nome_da_grade)
    achados = []
    pilha = [grade.property("contentItem")]
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, QQuickItem):
            if atual.property("jogoId") and atual.property("larguraDaCapa"):
                achados.append(atual)
            pilha.extend(atual.childItems())
    return sorted(achados, key=lambda c: (c.mapToScene(c.boundingRect().topLeft()).y(), c.mapToScene(c.boundingRect().topLeft()).x()))


def _abrir_pelo_cartao(app, indice=0):
    _clicar(app, _cartoes(app)[indice])
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    return app.achar("paginaDoJogo")


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


def test_jogar_e_excluir_emitem_sinais(app_qt):
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
    assert recebidos == ["jogar", "excluir"]
    app.fechar()
