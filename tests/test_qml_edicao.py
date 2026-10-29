# test_qml_edicao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O diálogo de edição e o "Adicionar jogo" (QML offscreen, sem a ponte do QWindowKit)."""

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.jogo import Jogo
from tests.apoio_edicao import jogo
from tests.test_qml_biblioteca import _achar, _App, _esperar
from tests.test_qml_detalhes import _abrir_pelo_cartao, _cartoes


@pytest.fixture(autouse=True)
def _sem_jogo_de_verdade(monkeypatch):
    monkeypatch.setattr(Jogo, "launch", lambda self, *a: True)


@pytest.fixture
def app(app_qt, store, monkeypatch):
    """A janela com três jogos de verdade na store (a `edicao` grava nela)."""
    jogos = [
        jogo(store, 1, name="Alfa", developer="Dev A", genre="Ação", rating=3, executable='"C:\\Jogos\\alfa.exe"'),
        jogo(store, 2, name="Beta"),
        jogo(store, 3, name="Gama"),
    ]
    janela = _App(jogos)
    monkeypatch.setattr(shared, "aplicativo", janela.aplicativo, raising=False)
    yield janela
    janela.fechar()


def _avaliar(objeto, expressao):
    valor = QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]
    return valor.toVariant() if hasattr(valor, "toVariant") else valor


def _rotulos(menu):
    return _avaliar(menu, "(function(){var r=[];for(var i=0;i<count;i++)r.push(itemAt(i).text);return r})()")


def _clique(app, nome):
    QMetaObject.invokeMethod(app.achar(nome), "click", Qt.ConnectionType.DirectConnection)


def test_editar_preenche_os_campos(app):
    app.edicao.abrir("shortcuts_z1")
    modelo = app.edicao
    assert modelo.aberto is True
    assert modelo.titulo == "Detalhes do jogo"
    assert modelo.rotuloDoAplicar == "Aplicar"
    assert (modelo.nome, modelo.desenvolvedora, modelo.genero, modelo.nota) == ("Alfa", "Dev A", "Ação", 3)
    assert modelo.executavel == '"C:\\Jogos\\alfa.exe"'
    # O QML mostra o que o modelo guarda.
    assert _esperar(lambda: app.achar("campoNome").property("text") == "Alfa")
    assert app.achar("campoDesenvolvedora").property("text") == "Dev A"
    assert app.achar("dialogoDeEdicao").property("visible") is True


def test_adicionar_titulo_e_botao(app):
    app.edicao.adicionar()
    assert app.edicao.aberto is True
    assert app.edicao.titulo == "Adicionar novo jogo"
    assert app.edicao.rotuloDoAplicar == "Adicionar"
    assert app.edicao.nome == "" and app.edicao.conquistas is True
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("text") == "Adicionar")


def test_adicionar_com_dialogo_aberto_nao_abre_outro(app):
    app.edicao.adicionar()
    app.edicao.nome = "Digitado"
    app.edicao.adicionar()
    app.edicao.abrir("shortcuts_z2")
    assert app.edicao.nome == "Digitado" and app.edicao.titulo == "Adicionar novo jogo"


def test_erro_de_validacao_mostra_dialogo_e_nao_fecha(app):
    app.edicao.adicionar()
    app.edicao.aplicar()
    erros = app.achar("dialogoDeErros")
    assert _esperar(lambda: erros.property("visible") is True)
    assert erros.property("titulo") == "Não foi possível adicionar o jogo"
    assert erros.property("corpo") == "O título do jogo não pode ficar vazio."
    assert app.edicao.aberto is True
    # Fechado o erro, o diálogo de edição segue aberto e com o foco.
    QMetaObject.invokeMethod(erros, "fechar", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: erros.property("visible") is False)
    assert app.edicao.aberto is True
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDeEdicao"))


def _foco_dentro_de(app, nome):
    item = app.janela.property("activeFocusItem")
    while item is not None:
        if item.objectName() == nome:
            return True
        item = item.parentItem()
    return False


def test_aplicar_grava_e_volta_aos_detalhes(app):
    _abrir_pelo_cartao(app, 0)
    _clique(app, "botaoEditar")
    assert _esperar(lambda: app.edicao.aberto)
    assert app.edicao.nome == "Alfa"
    app.edicao.nome = "Alfa Novo"
    app.edicao.aplicar()
    assert app.edicao.aberto is False
    assert shared.store.get("shortcuts_z1").name == "Alfa Novo"
    assert app.janela.property("paginaAtual") == "jogo"
    assert _esperar(lambda: app.detalhes.nome == "Alfa Novo")
    assert app.janela.property("tituloDaBarra") == "Alfa Novo"


def test_adicionar_cria_o_jogo_na_store(app):
    app.edicao.adicionar()
    app.edicao.nome = "Jogo novo"
    app.edicao.executavel = "cmd /c exit"
    app.edicao.aplicar()
    assert app.edicao.aberto is False
    novo = shared.store.get("imported_1")
    assert novo is not None and novo.name == "Jogo novo"


def test_ocupado_bloqueia_aplicar_e_enter(app):
    app.edicao.abrir("shortcuts_z1")
    app.edicao.iniciar_operacao()
    assert app.edicao.ocupado is True
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is False)
    app.edicao.nome = "Mudou"
    app.edicao.aplicar()
    assert app.edicao.aberto is True and shared.store.get("shortcuts_z1").name == "Alfa"
    # Enter na linha do executável também é bloqueado.
    app.achar("campoExecutavel").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    _esperar()
    assert app.edicao.aberto is True and shared.store.get("shortcuts_z1").name == "Alfa"
    app.edicao.terminar_operacao()
    assert app.edicao.ocupado is False
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is True)
    app.achar("campoExecutavel").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.edicao.aberto is False)
    assert shared.store.get("shortcuts_z1").name == "Mudou"


def test_clicar_na_nota_atual_remove(app):
    app.edicao.adicionar()
    app.edicao.definirNota(3)
    assert app.edicao.nota == 3
    app.edicao.definirNota(3)
    assert app.edicao.nota == 0
    app.edicao.definirNota(2)
    app.edicao.definirNota(4)
    assert app.edicao.nota == 4


def test_menu_do_jogo_tem_editar_e_remover(app):
    menu = app.achar("menuDoJogo")
    assert _rotulos(menu) == ["Editar", "Remover"]
    menu.setProperty("jogoId", "shortcuts_z2")
    _clique(app, "itemEditar")
    assert _esperar(lambda: app.edicao.aberto)
    assert app.edicao.nome == "Beta"


def test_clique_direito_abre_editar(app):
    cartao = next(c for c in _cartoes(app) if c.property("nome") == "Gama")
    ponto = cartao.mapToScene(cartao.boundingRect().center()).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, ponto)
    assert _esperar(lambda: app.edicao.aberto)
    assert app.edicao.nome == "Gama"


def test_menu_mais_tem_adicionar_acima_de_importar(app):
    menu = app.achar("menuDeAdicionar")
    assert _rotulos(menu) == ["Adicionar jogo", None, "Importar"]
    _clique(app, "itemAdicionarJogo")
    assert _esperar(lambda: app.edicao.aberto)
    assert app.edicao.titulo == "Adicionar novo jogo"


def test_zerado_que_saiu_da_store_fecha_sem_erro_e_sem_gravar(app, store):
    zerado = jogo(store, 40, removed=True, status="beaten", playtime=120)
    app.edicao.abrir(zerado.game_id)
    assert app.edicao.aberto is True
    store.excluir(zerado, apagar_sessoes=False)
    app.edicao.nome = ""  # inválido, mas o guarda vem antes da validação
    pedidos = []
    app.aplicativo.dialogoPedido.connect(lambda *a: pedidos.append(a))
    salvou = []
    zerado.salvar.connect(lambda: salvou.append(1))
    app.edicao.aplicar()
    _esperar()
    assert app.edicao.aberto is False
    assert pedidos == [] and salvou == []
    assert store.get(zerado.game_id) is None and zerado.name == "Jogo 40"


def test_zerado_esconde_executavel_e_atualizacoes(app, store):
    zerado = jogo(store, 41, removed=True, status="beaten")
    app.edicao.abrir(zerado.game_id)
    assert app.edicao.zerado is True
    assert _esperar(lambda: app.achar("campoNome").property("visible") is True)
    assert app.achar("campoExecutavel").property("visible") is False
    assert app.achar("alternanciaDeAtualizacoes").property("visible") is False
    app.edicao.cancelar()
    app.edicao.abrir("shortcuts_z1")  # um jogo comum mostra os dois grupos
    assert _esperar(lambda: app.achar("campoExecutavel").property("visible") is True)
    assert app.achar("alternanciaDeAtualizacoes").property("visible") is True


def test_textos_de_terceiros_em_texto_puro(app, store):
    jogo(store, 50, name="A & <b>B</b>", developer="<i>Dev</i>", executable="<u>x</u>")
    app.edicao.abrir("shortcuts_z50")
    dialogo = app.achar("dialogoDeEdicao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    textos, pilha = [], [dialogo]
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, QQuickItem) and atual.metaObject().className().startswith("QQuickText"):
            textos.append(atual)
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
        pilha.extend(atual.children())
    assert len(textos) > 20
    for texto in textos:
        assert _avaliar(texto, "textFormat") == 0, texto.property("text")  # Text.PlainText


def test_esc_cancela_sem_gravar_e_devolve_o_foco(app):
    _abrir_pelo_cartao(app, 0)
    _clique(app, "botaoEditar")
    assert _esperar(lambda: _foco_dentro_de(app, "campoNome"))
    app.edicao.nome = "Nao grava"
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.edicao.aberto)
    assert shared.store.get("shortcuts_z1").name == "Alfa"
    assert _esperar(lambda: _foco_dentro_de(app, "botaoEditar"))


def test_tab_gira_dentro_do_dialogo(app):
    app.edicao.adicionar()
    assert _esperar(lambda: _foco_dentro_de(app, "campoNome"))
    dialogo = app.achar("dialogoDeEdicao")
    for _ in range(40):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        item = app.janela.property("activeFocusItem")
        dentro = False
        while item is not None:
            dentro = dentro or item is dialogo
            item = item.parentItem()
        assert dentro
    # Shift+Tab a partir do primeiro campo cai no último botão, sem sair do diálogo.
    app.achar("campoNome").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert _esperar(lambda: _foco_dentro_de(app, "botaoAplicarDaEdicao"))


def _fora_do_dialogo(app):
    return not _foco_dentro_de(app, "dialogoDeEdicao")


def test_foco_volta_a_grade_depois_do_adicionar_pelo_menu(app):
    botao = app.achar("botaoAdicionar")
    botao.forceActiveFocus()
    _clique(app, "botaoAdicionar")
    menu = app.achar("menuDeAdicionar")
    assert _esperar(lambda: menu.property("opened") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.edicao.aberto)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.edicao.aberto)
    assert _esperar(lambda: _fora_do_dialogo(app) and app.janela.property("activeFocusItem") is not None)
    # Uma tecla chega à página: a grade passa a mostrar a seleção por teclado.
    QTest.keyClick(app.janela, Qt.Key.Key_Right)
    assert _esperar(lambda: app.achar("grade").property("porTeclado") is True)


def test_foco_volta_a_grade_depois_do_editar_pelo_menu_do_jogo(app):
    cartao = _cartoes(app)[0]
    cartao.forceActiveFocus()
    QMetaObject.invokeMethod(cartao, "abrirMenu", Qt.ConnectionType.DirectConnection)
    menu = app.achar("menuDoJogo")
    assert _esperar(lambda: menu.property("opened") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.edicao.aberto)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.edicao.aberto)
    assert _esperar(lambda: _fora_do_dialogo(app) and app.janela.property("activeFocusItem") is not None)
    QTest.keyClick(app.janela, Qt.Key.Key_Right)
    assert _esperar(lambda: app.achar("grade").property("porTeclado") is True)


def test_appid_invalido_fica_vermelho_e_bloqueia_o_aplicar(app):
    app.edicao.abrir("shortcuts_z1")
    assert app.edicao.appidValido is True
    app.edicao.appid = "12a"
    assert app.edicao.appidValido is False
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is False)
    assert app.achar("campoAppid").property("erro") is True
    app.edicao.aplicar()  # o Enter nas linhas ainda cai na validação: o erro é dito
    assert _esperar(lambda: app.achar("dialogoDeErros").property("visible") is True)
    assert app.achar("dialogoDeErros").property("corpo") == "O AppID da Steam deve conter apenas números."
    app.edicao.appid = "123"
    assert app.edicao.appidValido is True
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is True)
    assert app.achar("campoAppid").property("erro") is False


def test_zerado_virado_desinstalado_comum_sai_dos_detalhes(app, store):
    zerado = jogo(store, 60, removed=True, status="beaten")
    app.loja.por_id[zerado.game_id] = zerado
    QMetaObject.invokeMethod(app.janela, "abrirDetalhes", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", zerado.game_id))
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    _clique(app, "botaoEditar")
    assert _esperar(lambda: app.edicao.aberto)
    app.edicao.statusIndice = 0  # "Sem status": deixa de ser zerado
    app.edicao.aplicar()
    assert zerado.zerado is False
    assert _esperar(lambda: app.janela.property("paginaAtual") != "jogo")
