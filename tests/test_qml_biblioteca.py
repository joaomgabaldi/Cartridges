# test_qml_biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As páginas da biblioteca e de Jogos Zerados (QML offscreen, sem a ponte do QWindowKit)."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from cartridges import aplicativo as aplicativo_modulo
from cartridges import shared
from cartridges.utils.app_updater import AppUpdater
from cartridges.utils.news_checker import NewsChecker
from cartridges.aplicativo import Aplicativo
from cartridges.jogo import Jogo
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.detalhes import DetalhesDoJogo
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.modelos.novidades import Novidades
from cartridges.modelos.saves import SavesDoJogo
from cartridges.modelos.preferencias import Preferencias
from cartridges.modelos.restauracao import ContinuacaoDaRestauracao
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.modelos.sobre import Sobre
from cartridges.modelos.zerados_manuais import SeletorDeZerados
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.ponte import Ponte
from tests.apoio_qml_biblioteca import QML, _App, _achar, _esperar, _jogos, _tres

QQuickStyle.setStyle("Basic")


@pytest.fixture(autouse=True)
def _store_limpa(monkeypatch):
    """`shared.store` volta ao que era ao fim de cada teste (o `SavesDoJogo` liga o sinal dela)."""
    monkeypatch.setattr(shared, "store", None, raising=False)


def test_estado_vazio_com_biblioteca_vazia(app_qt):
    app = _App([])
    vazio = app.achar("estadoVazio")
    assert vazio.property("visible") is True
    assert vazio.property("titulo") == "Nenhum jogo"
    assert vazio.property("descricao") == "Use o botão + para adicionar jogos."
    app.fechar()


def test_busca_sem_resultado_mostra_nenhum_encontrado(app_qt):
    app = _App(_tres())
    assert app.achar("estadoVazio").property("visible") is False
    app.achar("pagina").setProperty("buscaAberta", True)
    app.achar("campoDeBusca").setProperty("text", "zzz")
    _esperar(lambda: app.achar("estadoVazio").property("visible"))
    vazio = app.achar("estadoVazio")
    assert vazio.property("visible") is True
    assert vazio.property("titulo") == "Nenhum jogo encontrado"
    assert vazio.property("descricao") == "Tente outra busca ou outro filtro."
    # Fechar a busca por qualquer caminho limpa o texto.
    app.achar("pagina").setProperty("buscaAberta", False)
    _esperar(lambda: not app.achar("estadoVazio").property("visible"))
    assert app.todos.busca == ""
    assert app.achar("campoDeBusca").property("text") == ""
    app.fechar()


def test_a_grade_cria_os_cartoes(app_qt):
    app = _App(_tres())
    grade = app.achar("grade")
    delegados = [item for item in grade.property("contentItem").childItems() if item.property("jogoId")]
    assert sorted(item.childItems()[0].property("nome") for item in delegados) == ["Alfa", "Beta", "Gama"]
    app.fechar()


def test_menu_ordenar_tem_os_dez_itens(app_qt):
    app = _App(_tres())
    menu = app.achar("menuPrincipal")
    assert menu.property("rotulosDeFiltrar").toVariant() == ["Gêneros", "Ano de lançamento", "Status"]
    assert menu.property("rotulosDeOrdenar").toVariant() == [
        "Jogados recentemente", "Título (A–Z)", "Título (Z–A)", "Lançamento (mais recente)",
        "Lançamento (mais antigo)", "Adicionados recentemente", "Adicionados há mais tempo",
        "Mais jogados", "Minha nota", "Tamanho",
    ]  # fmt: skip
    app.fechar()


def test_ir_para_zerados_e_voltar(app_qt):
    app = _App(_jogos((1, "Alfa", {}), (2, "Zero", {"removed": True, "status": "beaten"})))
    assert app.janela.property("paginaAtual") == "todos"
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    assert app.janela.property("paginaAtual") == "zerados"
    assert app.janela.property("tituloDaBarra") == "Jogos Zerados"
    grade = app.achar("gradeDeZerados")
    delegados = [item for item in grade.property("contentItem").childItems() if item.property("jogoId")]
    assert [item.childItems()[0].property("nome") for item in delegados] == ["Zero"]
    QMetaObject.invokeMethod(app.achar("botaoVoltar"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    assert app.janela.property("paginaAtual") == "todos"
    assert app.janela.property("tituloDaBarra") == "Todos os jogos"
    app.fechar()


def test_zerados_vazio_mostra_o_aviso(app_qt):
    app = _App(_tres())
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    vazio = app.achar("estadoVazioDeZerados")
    assert vazio.property("titulo") == "Nenhum jogo zerado"
    assert vazio.property("descricao") == "Os jogos desinstalados marcados como Zerado são exibidos aqui."
    app.fechar()


def _cor(objeto, propriedade):
    return objeto.property(propriedade).name()


def test_submenu_aninhado_usa_as_cores_do_tema(app_qt):
    app = _App(_tres())
    menu = app.achar("menuPrincipal")
    # Fundo e texto do Tema (claro ou escuro); o padrão do Basic seria #26282a no texto.
    assert _cor(menu.property("fundoDeOrdenar"), "color") in ("#2b2b2b", "#ffffff")
    item = menu.property("primeiroDeOrdenar")
    assert _cor(item.property("contentItem"), "color") in ("#ffffff", "#1a1a1a")
    assert item.property("implicitHeight") == 34
    app.fechar()


def test_clear_appears_only_while_a_filter_is_active(app_qt):
    """"Limpar" aparece com qualquer um dos três filtros (gênero, ano, status) e zera os três."""
    app = _App(_tres())
    limpar = app.achar("limpar")
    assert limpar.property("exibido") is False
    for campo, valor in (("genero", "RPG"), ("ano", "2020"), ("status", "beaten")):
        setattr(app.filtros, campo, valor)
        assert _esperar(lambda: limpar.property("exibido") is True), campo
        app.filtros.limpar()
        assert _esperar(lambda: limpar.property("exibido") is False), campo
    app.filtros.genero, app.filtros.ano, app.filtros.status = "RPG", "2020", "beaten"
    assert _esperar(lambda: limpar.property("exibido") is True)
    QMetaObject.invokeMethod(limpar, "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: (app.filtros.genero, app.filtros.ano, app.filtros.status) == ("", "", ""))
    assert limpar.property("exibido") is False
    app.fechar()


def test_escolher_filtro_move_a_marca_e_limpar_aparece_e_some(app_qt):
    app = _App(_tres())
    limpar = app.achar("limpar")
    assert limpar.property("exibido") is False
    assert app.achar("status-Todos").property("checked") is True
    QMetaObject.invokeMethod(app.achar("status-Zerado"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: app.filtros.status == "beaten")
    assert app.filtros.status == "beaten"
    assert app.achar("status-Zerado").property("checked") is True
    assert app.achar("status-Todos").property("checked") is False
    assert limpar.property("exibido") is True
    QMetaObject.invokeMethod(limpar, "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: app.filtros.status == "")
    assert app.filtros.status == ""
    assert app.achar("status-Todos").property("checked") is True
    assert limpar.property("exibido") is False
    app.fechar()


def test_foco_vai_para_zerados_e_volta(app_qt):
    from PySide6.QtCore import QCoreApplication, QEvent  # noqa: PLC0415
    from PySide6.QtGui import QKeyEvent  # noqa: PLC0415

    app = _App(_tres())

    def foco_dentro_de(nome):
        item = app.janela.property("activeFocusItem")
        while item is not None:
            if item.objectName() == nome:
                return True
            item = item.parentItem()
        return False

    def digitar(letra):
        for tipo in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            QCoreApplication.sendEvent(app.janela, QKeyEvent(tipo, ord(letra.upper()), Qt.KeyboardModifier.NoModifier, letra))
        _esperar()

    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: foco_dentro_de("paginaDeZerados"))
    assert foco_dentro_de("paginaDeZerados")
    digitar("z")
    assert app.todos.busca == ""  # a busca escondida de "Todos os jogos" não recebe a tecla
    QMetaObject.invokeMethod(app.achar("botaoVoltar"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: foco_dentro_de("pagina"))
    assert foco_dentro_de("pagina")
    app.fechar()


def _cartoes(grade):
    return [item.childItems()[0] for item in grade.property("contentItem").childItems() if item.property("jogoId")]


def test_cartao_tem_nome_acessivel(app_qt):
    app = _App(_tres())
    cartao = next(c for c in _cartoes(app.achar("grade")) if c.property("nome") == "Beta")
    assert cartao.property("nome") == "Beta"
    # Accessible.name / role não são propriedades do item: lê-se pelo atributo anexado via o próprio QML.
    assert cartao.property("nomeAcessivel") == "Beta"
    assert cartao.property("papelAcessivel") == "Button"
    app.fechar()


def test_zerado_sem_botoes(app_qt):
    app = _App(_jogos((1, "Alfa", {}), (2, "Zero", {"removed": True, "status": "beaten"})))
    comum = _cartoes(app.achar("grade"))[0]
    assert _achar(comum, "botaoJogar") is not None and _achar(comum, "botaoMais") is not None
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    zerado = _cartoes(app.achar("gradeDeZerados"))[0]
    assert zerado.property("nome") == "Zero"
    assert _achar(zerado, "botaoJogar") is None and _achar(zerado, "botaoMais") is None
    app.fechar()


def test_remover_pelo_menu_do_jogo(app_qt):
    app = _App(_tres())
    chamados = []
    app.modelo._jogos["imported_2"].remove_game = lambda: chamados.append("imported_2")  # noqa: SLF001
    menu = app.achar("menuDoJogo")
    menu.setProperty("jogoId", "imported_2")
    QMetaObject.invokeMethod(app.achar("itemRemover"), "click", Qt.ConnectionType.DirectConnection)
    assert chamados == ["imported_2"]
    app.fechar()


def test_aviso_aparece_na_tela_e_desfaz(app_qt, monkeypatch):
    app = _App(_tres())
    jogo = app.modelo._jogos["imported_1"]  # noqa: SLF001
    jogo.save = lambda: None
    monkeypatch.setattr(shared, "store", {jogo.game_id: jogo}, raising=False)  # a Store que o desfazer consulta
    shared.games_dir.mkdir(parents=True, exist_ok=True)
    (shared.games_dir / f"{jogo.game_id}.json").write_text("{}")
    app.ponte.ligar(jogo)
    jogo.remove_game()
    aviso = app.achar("aviso")
    _esperar(lambda: aviso.property("opacity") == 1)
    assert aviso.property("opacity") == 1
    assert app.achar("textoDoAviso").property("text") == "Alfa removido"
    assert app.achar("botaoDoAviso").property("text") == "Desfazer"
    app.ponte.fila.clicar()
    assert jogo.removed is False
    app.fechar()


def test_menu_do_cartao_aponta_para_o_jogo_dele(app_qt):
    # Do test_menu_do_card.py: o menu continua ligado ao jogo do cartão em que foi aberto.
    app = _App(_tres())
    cartoes = {c.property("nome"): c for c in _cartoes(app.achar("grade"))}
    menu = app.achar("menuDoJogo")
    for nome, jogo_id in (("Gama", "imported_3"), ("Alfa", "imported_1")):
        QMetaObject.invokeMethod(cartoes[nome], "abrirMenu", Qt.ConnectionType.DirectConnection)
        _esperar(lambda: menu.property("jogoId") == jogo_id)
        assert menu.property("jogoId") == jogo_id
        assert menu.property("visible") is True
        menu.close()
    app.fechar()


def test_anel_e_botoes_so_por_teclado(app_qt):
    from PySide6.QtCore import QCoreApplication, QEvent  # noqa: PLC0415
    from PySide6.QtGui import QKeyEvent  # noqa: PLC0415

    app = _App(_tres())
    grade = app.achar("grade")
    grade.forceActiveFocus()
    _esperar()
    primeiro = _cartoes(grade)
    primeiro = next(c for c in primeiro if c.property("nome") == "Alfa")
    assert grade.property("porTeclado") is False
    assert primeiro.property("focado") is False  # o foco da grade sozinho não acende o cartão
    assert primeiro.property("mostrarBotoes") is False
    for tipo in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QCoreApplication.sendEvent(app.janela, QKeyEvent(tipo, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    _esperar(lambda: grade.property("porTeclado") is True)
    atual = next(c for c in _cartoes(grade) if c.property("focado"))
    assert atual.property("nome") == "Beta" and atual.property("mostrarBotoes") is True
    app.fechar()


def _cartao_animado(app):
    grade = app.achar("grade")
    delegados = [item for item in grade.property("contentItem").childItems() if item.property("jogoId")]
    cartao = delegados[0].childItems()[0]
    return cartao, _achar(cartao, "capaAnimada")


def _jogo_com_capa_animada():
    from PIL import Image

    from cartridges.utils import copias_animadas

    caminho = shared.covers_dir / "imported_1.webp"
    quadros = [Image.new("RGBA", (8, 12), (tom, 0, 0, 255)) for tom in (0, 90)]
    quadros[0].save(caminho, "WEBP", save_all=True, append_images=quadros[1:], duration=[100, 100], loop=0, lossless=True)
    tamanho = copias_animadas.tamanhos()[0]
    assert copias_animadas.gerar(caminho, copias_animadas.caminho_para(caminho, tamanho), tamanho)
    return _jogos((1, "Alfa", {}))


def test_animacao_so_com_autoplay(app_qt, monkeypatch):
    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: True)  # não depende do ajuste do Windows
    shared.schema.set_boolean("cover-autoplay", False)
    app = _App(_jogo_com_capa_animada())
    cartao, animada = _cartao_animado(app)
    assert cartao.property("capaAnimada").startswith("file:///")
    # "Animar capas" desligado: nada anima, nem com o mouse em cima (a `main` também não), e o arquivo nem é aberto.
    assert animada.property("playing") is False and animada.property("source").toString() == ""
    # Ligado: toca.
    shared.schema.set_boolean("cover-autoplay", True)
    assert _esperar(lambda: app.aplicativo.tocarSempre)
    assert _esperar(lambda: animada.property("playing") is True)
    assert animada.property("source").toString() == cartao.property("capaAnimada")
    assert _esperar(lambda: animada.property("visible"))  # a animação carregou e cobre a capa parada
    # Fora da vista da grade, nada toca nem segura o arquivo.
    cartao.setProperty("naVista", False)
    assert animada.property("playing") is False and animada.property("source").toString() == ""
    shared.schema.reset("cover-autoplay")
    app.fechar()


def test_sem_efeitos_de_animacao_do_sistema_nada_anima(app_qt, monkeypatch):
    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: False)
    shared.schema.set_boolean("cover-autoplay", True)
    app = _App(_jogo_com_capa_animada())
    cartao, animada = _cartao_animado(app)
    assert app.aplicativo.tocarSempre is True and app.aplicativo.animacoesDoSistema is False
    assert cartao.property("tocarSempre") is False and animada.property("playing") is False
    shared.schema.reset("cover-autoplay")
    app.fechar()


def test_grade_coberta_pelos_zerados_para(app_qt, monkeypatch):
    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: True)  # não depende do ajuste do Windows
    shared.schema.set_boolean("cover-autoplay", True)
    app = _App(_jogo_com_capa_animada())
    cartao, animada = _cartao_animado(app)
    assert _esperar(lambda: animada.property("playing") is True)
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    assert _esperar(lambda: animada.property("playing") is False)
    assert animada.property("source").toString() == ""
    shared.schema.reset("cover-autoplay")
    app.fechar()


def test_rolagem_so_vale_depois_de_assentar(app_qt):
    app = _App(_jogo_com_capa_animada())
    grade = app.achar("grade")
    antes = grade.property("contentYParado")
    grade.setProperty("contentY", antes + 500)
    assert grade.property("contentYParado") == antes, "durante a rolagem os cartões não mudam"
    assert _esperar(lambda: grade.property("contentYParado") == antes + 500)
    app.fechar()


def test_capa_parada_nunca_anima(app_qt):
    app = _App(_jogos((1, "Alfa", {})))
    cartao, animada = _cartao_animado(app)
    assert cartao.property("capaAnimada") == "" and animada.property("playing") is False
    app.fechar()


def test_origem_ilegivel_mostra_a_capa_padrao(app_qt):
    """Uma capa que não se lê (arquivo quebrado) mostra o placeholder, e não um cartão vazio."""
    (shared.covers_dir / "imported_1.tiff").write_bytes(b"nao e uma imagem")
    app = _App(_jogos((1, "Alfa", {})))
    cartao, _animada = _cartao_animado(app)
    parada = _achar(cartao, "capaParada")
    assert cartao.property("capa").startswith("file:///")
    assert _esperar(lambda: parada.property("source").toString().endswith("library_placeholder.svg"))
    app.fechar()


def test_deve_tocar(app_qt, monkeypatch):
    """Opção, animações do Windows e sessão têm teste próprio; aqui, a janela minimizada para a capa e a devolve."""
    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: True)
    shared.schema.set_boolean("cover-autoplay", True)
    app = _App(_jogo_com_capa_animada())
    app.janela.show()
    _cartao, animada = _cartao_animado(app)
    assert _esperar(lambda: animada.property("playing") is True)
    app.janela.showMinimized()
    assert _esperar(lambda: animada.property("playing") is False and animada.property("source").toString() == "")
    app.janela.showNormal()
    assert _esperar(lambda: animada.property("playing") is True)
    shared.schema.reset("cover-autoplay")
    app.fechar()


def test_na_vista(app_qt):
    """Só o que cruza a janela da grade conta como à vista; metade dentro já conta."""
    app = _App(_jogos(*[(n, f"Jogo {n:03}", {}) for n in range(1, 121)]))
    grade = app.achar("grade")
    _esperar()
    delegado = next(i for i in grade.property("contentItem").childItems() if i.property("jogoId") == "imported_1")
    cartao = delegado.childItems()[0]
    assert cartao.property("naVista") is True
    for deslocamento, esperado in ((delegado.height() / 2, True), (delegado.height() + 1, False)):
        alvo = delegado.y() + deslocamento
        grade.setProperty("contentY", alvo)
        assert _esperar(lambda alvo=alvo: grade.property("contentYParado") == alvo)
        assert cartao.property("naVista") is esperado, deslocamento
    app.fechar()


def test_filtrar_com_a_grade_cabendo_na_tela_reavalia_o_autoplay(app_qt, monkeypatch):
    """Filtrar não rola nada: a capa filtrada para, e a que volta com a busca limpa toca de novo."""
    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: True)
    shared.schema.set_boolean("cover-autoplay", True)
    app = _App(_jogo_com_capa_animada())
    grade = app.achar("grade")
    _cartao, animada = _cartao_animado(app)
    assert _esperar(lambda: animada.property("playing") is True)
    app.todos.busca = "halo"
    assert _esperar(lambda: grade.property("count") == 0)
    app.todos.busca = ""
    assert _esperar(lambda: grade.property("count") == 1)
    _cartao, animada = _cartao_animado(app)
    assert _esperar(lambda: animada.property("playing") is True)
    shared.schema.reset("cover-autoplay")
    app.fechar()


# --- Controle do Xbox na interface -------------------------------------------------------------

def test_controle_move_a_selecao_e_vibra_na_borda(app_qt):
    app = _App(_tres())
    grade = app.achar("grade")
    colunas = grade.property("colunas")
    assert colunas >= 1
    app.controle.mover.emit(-1, 0)
    assert grade.property("currentIndex") == 0, "na borda esquerda a seleção fica"
    assert app.leitor.vibracoes == [(0.6, 0.2)], "e o controle vibra"
    app.leitor.vibracoes.clear()
    app.controle.mover.emit(1, 0)
    if colunas > 1:
        assert grade.property("currentIndex") == 1
        assert grade.property("porTeclado") is True
        assert app.leitor.vibracoes == [(0.0, 0.14)], "um cartão atravessado é um tique leve"
    app.fechar()


def test_controle_nao_passa_do_ultimo_jogo(app_qt):
    app = _App(_tres())
    grade = app.achar("grade")
    for _ in range(5):
        app.controle.mover.emit(0, 1)
    assert grade.property("currentIndex") < 3
    for _ in range(5):
        app.controle.mover.emit(1, 0)
    assert grade.property("currentIndex") == 2
    app.leitor.vibracoes.clear()
    app.controle.mover.emit(1, 0)
    assert app.leitor.vibracoes == [(0.6, 0.2)], "no último jogo vibra"
    app.fechar()


def test_controle_esquerda_direita_passam_de_linha(app_qt):
    shared.schema._gravar("library-rows", "u", 1)  # uma coluna: todo passo lateral muda de linha
    app = _App(_tres())
    grade = app.achar("grade")
    assert grade.property("colunas") == 1
    app.controle.mover.emit(1, 0)
    assert grade.property("currentIndex") == 1
    app.controle.mover.emit(-1, 0)
    assert grade.property("currentIndex") == 0
    app.fechar()


def test_controle_sobe_da_primeira_linha_para_a_barra_e_desce(app_qt):
    app = _App(_tres())
    grade = app.achar("grade")
    app.leitor.vibracoes.clear()
    app.controle.mover.emit(0, -1)
    botoes = ["botaoAdicionar", "botaoZerados", "botaoBusca", "botaoMenu"]
    com_foco = [n for n in botoes if app.achar(n).property("activeFocus")]
    assert len(com_foco) == 1, "um botão da barra recebe o foco"
    assert app.leitor.vibracoes == [], "e o controle não vibra"
    app.controle.mover.emit(0, 1)
    assert grade.property("activeFocus") is True
    app.fechar()


def test_controle_presente_acende_a_selecao(app_qt):
    app = _App(_tres())
    grade = app.achar("grade")
    assert grade.property("porTeclado") is False
    app.controle.presente.emit()
    assert grade.property("porTeclado") is True
    assert grade.property("activeFocus") is True
    app.fechar()


def test_controle_ativa_o_cartao_atual(app_qt):
    app = _App(_tres())
    grade = app.achar("grade")
    abertos = []
    grade.abrirDetalhes.connect(abertos.append)
    app.controle.ativar.emit()
    assert abertos == ["imported_1"]
    app.fechar()


def test_controle_start_abre_o_menu_e_b_volta_de_zerados(app_qt):
    app = _App(_jogos((1, "Alfa", {}), (2, "Zero", {"removed": True, "status": "beaten"})))
    menu = app.achar("menuPrincipal")
    app.controle.menuPrincipal.emit()
    assert _esperar(lambda: menu.property("opened") is True)
    menu.close()
    assert _esperar(lambda: menu.property("opened") is False)
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    app.controle.voltar.emit()
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    app.fechar()


def test_controle_alterna_a_busca(app_qt):
    app = _App(_tres())
    pagina = app.achar("pagina")
    app.controle.buscar.emit()
    assert pagina.property("buscaAberta") is True
    app.controle.buscar.emit()
    assert pagina.property("buscaAberta") is False
    app.controle.buscar.emit()
    app.controle.voltar.emit()
    assert pagina.property("buscaAberta") is False, "B fecha a busca"
    app.fechar()


def test_controle_esconde_o_ponteiro(app_qt):
    app = _App(_tres())
    assert app.janela.property("ponteiroEscondido") is False
    app.controle.usado.emit()
    assert app.janela.property("ponteiroEscondido") is True
    app.fechar()


def test_copia_animada_a_vista_e_largada_antes_de_apagar_e_refeita_se_velha(app_qt, monkeypatch):
    """O `AnimatedImage` segura o `.webp` aberto (WinError 32): `soltar` o larga, e uma cópia mais velha que a capa é refeita."""
    import os  # noqa: PLC0415

    import pytest  # noqa: PLC0415
    from PIL import Image  # noqa: PLC0415

    from cartridges.utils import copias_animadas  # noqa: PLC0415

    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: True)
    monkeypatch.setattr(copias_animadas, "ao_terminar_copia", None)
    monkeypatch.setattr(copias_animadas, "soltar_do_jogo", None)
    shared.schema.set_boolean("cover-autoplay", True)
    app = _App(_jogo_com_capa_animada())
    app.modelo.ativar_copias()
    capa = shared.covers_dir / "imported_1.webp"
    copia = copias_animadas.caminho_para(capa, copias_animadas.tamanhos()[0])
    cartao, animada = _cartao_animado(app)
    assert _esperar(lambda: animada.property("playing") is True and animada.property("visible"))
    with pytest.raises(PermissionError):
        copia.unlink()  # a premissa: com a animação à vista, o arquivo está preso

    copias_animadas.soltar("imported_1")

    assert animada.property("source").toString() == "" and cartao.property("capaAnimada") == ""
    os.rename(copia, f"{copia}.x")  # largado na hora, sem esperar o laço de eventos
    os.rename(f"{copia}.x", copia)
    # Uma capa nova, e a cópia velha (mais velha que ela) volta a tocar, agora com a cópia refeita.
    antigo = copia.read_bytes()
    app.modelo.atualizar(app.modelo._jogos["imported_1"])  # noqa: SLF001  # a cópia ainda existe: reaparece
    assert _esperar(lambda: animada.property("visible"))
    quadros = [Image.new("RGBA", (8, 12), (0, tom, 0, 255)) for tom in (0, 200)]
    quadros[0].save(capa, "WEBP", save_all=True, append_images=quadros[1:], duration=[100, 100], loop=0, lossless=True)
    agora = time.time()
    os.utime(copia, (agora - 100, agora - 100))
    os.utime(capa, (agora - 50, agora - 50))
    copias_animadas.preparar([("imported_1", capa)])
    assert _esperar(lambda: copia.stat().st_mtime > agora - 10 and copia.read_bytes() != antigo)
    assert _esperar(lambda: animada.property("visible") and cartao.property("capaAnimada").startswith("file:///"))
    copias_animadas.soltar("imported_1")
    copia.unlink()  # solta de novo, e apaga
    shared.schema.reset("cover-autoplay")
    app.fechar()


def _cartao_com_copia(monkeypatch, lixo):
    """Um cartão com autoplay ligado e a cópia animada pronta; com `lixo`, a cópia é trocada por bytes que não são WebP."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: True)
    monkeypatch.setattr(copias_animadas, "ao_terminar_copia", None)
    monkeypatch.setattr(copias_animadas, "soltar_do_jogo", None)
    shared.schema.set_boolean("cover-autoplay", True)
    jogos = _jogo_com_capa_animada()
    capa = shared.covers_dir / "imported_1.webp"
    copia = copias_animadas.caminho_para(capa, copias_animadas.tamanhos()[0])
    if lixo:
        copia.write_bytes(LIXO)
    app = _App(jogos)
    app.modelo.ativar_copias()
    return app, capa, copia, *_cartao_animado(app)


LIXO = b"isto nao e um webp"


def test_copia_animada_valida_aparece_em_ate_3_s(app_qt, monkeypatch):
    """Controle positivo do teste da cópia corrompida: com a cópia boa, a espera daquele teste bastaria para a animação aparecer."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    app, _capa, _copia, cartao, animada = _cartao_com_copia(monkeypatch, lixo=False)
    assert _esperar(lambda: animada.property("playing") is True)
    assert _esperar(lambda: animada.property("visible"), limite=3.0)
    copias_animadas.soltar("imported_1")
    shared.schema.reset("cover-autoplay")
    app.fechar()


def test_copia_animada_corrompida_deixa_a_capa_parada_visivel(app_qt, monkeypatch):
    """Sem o refazer da `main`: a cópia lixo fica, o `AnimatedImage` a tenta e não carrega, e a capa parada segue à vista."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    app, capa, copia, cartao, animada = _cartao_com_copia(monkeypatch, lixo=True)
    parada = _achar(cartao, "capaParada")
    assert _esperar(lambda: animada.property("playing") is True)
    # A animada tentou abrir justamente a cópia lixo...
    assert _esperar(lambda: animada.property("source").toString().split("?")[0].endswith(copia.name))
    # ...e, pelo mesmo tempo que a cópia boa leva para aparecer (teste vizinho), não carregou.
    assert not _esperar(lambda: animada.property("visible"), limite=3.0)
    # A cópia não foi refeita (diferença aceita da `main`) e a capa parada é a capa real, não o espaço vazio.
    assert copia.read_bytes() == LIXO
    assert parada.property("source").toString() == cartao.property("capa") != ""
    assert parada.property("source").toString().split("?")[0].endswith(capa.name)
    copias_animadas.soltar("imported_1")
    shared.schema.reset("cover-autoplay")
    app.fechar()


def test_janela_maximizada_volta_maximizada_depois_de_sair_da_frente(app_qt):
    """Review Focus 4, pelo caminho do app: `sair_da_frente` minimiza, `present()` devolve a janela maximizada."""
    app = _App(_tres())
    jogo = app.jogos[0]
    app.ponte.ligar(jogo)
    app.sessao.definir_janela(app.janela)
    app.janela.showMaximized()
    _esperar()
    assert app.janela.windowStates() & Qt.WindowState.WindowMaximized

    jogo.sair_da_frente.emit()
    _esperar()
    assert app.janela.windowStates() & Qt.WindowState.WindowMinimized
    app.sessao.present()

    assert app.janela.windowStates() == Qt.WindowState.WindowMaximized
    app.fechar()


def test_grade_com_jogos_chegando_depois_mostra_varias_colunas(app_qt):
    """Com a biblioteca vazia na abertura, a margem centralizadora não pode travar a grade em uma coluna."""
    app = _App([])
    app.janela.resize(1100, 700)
    _esperar()
    grade = app.achar("grade")
    for n in range(20):
        app.modelo.atualizar(_jogos((n, f"Jogo {n}", {}))[0])
        _esperar()  # um quadro entre as chegadas, como no app: cada tamanho tem a sua margem
    assert grade.property("count") == 20
    _esperar()
    colunas = grade.property("colunas")
    assert colunas >= 4
    xs = {round(i.x()) for i in grade.property("contentItem").childItems() if i.property("jogoId") and i.isVisible()}
    assert len(xs) == colunas, f"as células ocupam {len(xs)} colunas de {colunas}"
    app.fechar()


def test_botao_das_tarefas_some_com_modal_no_big_picture_e_na_sessao(app_qt, flush_idle):  # noqa: ARG001
    """No `Aplicativo.qml` de verdade, com uma tarefa, o botão do canto só pode aparecer sem nada por cima (D77)."""
    from cartridges.modelos import tarefas  # noqa: PLC0415

    app = _App(_tres())
    botao = app.achar("botaoDasTarefas")
    tarefa = tarefas.comecar("Importação", 1)
    flush_idle()
    try:
        assert botao.property("pode") is True

        fechados = []
        app.aplicativo.pedir_dialogo("Aviso", "Corpo", [], lambda: fechados.append(1))
        assert _esperar(lambda: app.janela.property("modalAberto") is True)
        assert botao.property("pode") is False
        app.achar("dialogoDeErros").fechar()  # o "Dispensar": a resposta volta pela fila da D72
        assert _esperar(lambda: botao.property("pode") is True)
        assert fechados == [1]

        app.big_picture.entrar()
        assert _esperar(lambda: app.big_picture.visivel)
        assert botao.property("pode") is False
        assert _esperar(lambda: not app.big_picture.ocupada)
        app.big_picture.sair()
        assert _esperar(lambda: not app.big_picture.visivel, limite=5)
        assert botao.property("pode") is True

        app.sessao.show_session_blocker(app.jogos[0])
        assert botao.property("pode") is False
        app.sessao.hide_session_blocker()
        assert botao.property("pode") is True
    finally:
        tarefas.lista.remover(tarefa)
        app.fechar()


def test_adicionar_jogo_desligado_durante_a_importacao(app_qt):
    app = _App(_tres())
    try:
        item = app.achar("itemAdicionarJogo")
        assert item.property("enabled") is True
        app.aplicativo.definir_importando(True)
        assert _esperar(lambda: item.property("enabled") is False)
        app.aplicativo.definir_importando(False)
        assert _esperar(lambda: item.property("enabled") is True)
    finally:
        app.fechar()
