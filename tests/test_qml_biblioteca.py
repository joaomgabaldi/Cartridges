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

from kyron import aplicativo as aplicativo_modulo
from kyron import shared
from kyron.utils.app_updater import AppUpdater
from kyron.utils.news_checker import NewsChecker
from kyron.aplicativo import Aplicativo
from kyron.jogo import Jogo
from kyron.modelos.big_picture import BigPicture, ProvedorDoFundo
from kyron.modelos.conquistas import ConquistasDoJogo
from kyron.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from kyron.modelos.controle import ControleDaGrade
from kyron.modelos.detalhes import DetalhesDoJogo
from kyron.modelos.edicao import ModeloDaEdicao
from kyron.modelos.historico import HistoricoDeSessoes
from kyron.modelos.novidades import Novidades
from kyron.modelos.saves import SavesDoJogo
from kyron.modelos.preferencias import Preferencias
from kyron.modelos.restauracao import ContinuacaoDaRestauracao
from kyron.modelos.sessao import ModeloDaSessao
from kyron.modelos.sobre import Sobre
from kyron.modelos.zerados_manuais import SeletorDeZerados
from kyron.modelos.tarefas import PainelDasTarefas
from kyron.ponte import Ponte
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


def test_menu_do_popover_usa_as_cores_do_tema(app_qt):
    app = _App(_tres())
    menu = app.achar("menuPrincipal")
    # Fundo e texto do mesmo tema (o `Tema.escuro` do Windows); o padrão do Basic seria #26282a no texto.
    from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

    escuro = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    assert _cor(menu.property("background"), "color") == ("#36363a" if escuro else "#ffffff")
    item = app.achar("ordenar-Jogados recentemente")
    assert _cor(item.property("contentItem"), "color") == ("#ffffff" if escuro else "#000006")
    assert item.property("implicitHeight") == 32
    app.fechar()


def test_submenus_deslizam_no_mesmo_popover_e_voltam(app_qt):
    """"Filtrar por" e "Ordenar por" trocam a página do mesmo popover, com o cabeçalho "‹ Título" para voltar."""
    app = _App(_tres())
    menu = app.achar("menuPrincipal")
    menu.open()
    assert _esperar(lambda: menu.property("opened") is True)
    assert menu.property("pagina") == "raiz"
    assert app.achar("entrada-ordenar").property("visible") is True
    assert app.achar("ordenar-Tamanho").property("visible") is False
    QMetaObject.invokeMethod(app.achar("entrada-ordenar"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: menu.property("pagina") == "ordenar" and menu.property("opened") is True)
    assert app.achar("ordenar-Tamanho").property("visible") is True
    assert app.achar("entrada-ordenar").property("visible") is False
    # Só um popover: o menu continua o mesmo e a altura é a da página (10 itens + cabeçalho + separador).
    assert menu.property("height") > 10 * 32
    # O cabeçalho volta; depois, Filtrar por > Status.
    QMetaObject.invokeMethod(app.achar("cabecalho-ordenar"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: menu.property("pagina") == "raiz" and menu.property("opened") is True)
    QMetaObject.invokeMethod(app.achar("entrada-filtrar"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: menu.property("pagina") == "filtrar" and menu.property("opened") is True)
    QMetaObject.invokeMethod(app.achar("entrada-status"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: menu.property("pagina") == "status" and menu.property("opened") is True)
    app.achar("menuPrincipal").setProperty("pagina", "status")  # os itens de outra página ficam desabilitados
    QMetaObject.invokeMethod(app.achar("status-Zerado"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: menu.property("opened") is False and app.filtros.status == "beaten")
    # Escolher fecha o popover, e a próxima abertura recomeça na raiz.
    assert _esperar(lambda: menu.property("pagina") == "raiz")
    app.fechar()


def test_menu_principal_navega_pelo_teclado_e_pelo_controle(app_qt):
    """Com o controle: Enter entra, Esquerda volta, Esc fecha (o controle entrega estas teclas ao item em foco)."""
    app = _App(_tres())
    menu = app.achar("menuPrincipal")
    menu.open()
    assert _esperar(lambda: menu.property("opened") is True)
    _tecla(app, Qt.Key.Key_Down)
    _tecla(app, Qt.Key.Key_Down)  # Ordenar por
    app.controle.teclar(int(Qt.Key.Key_Return))
    assert _esperar(lambda: menu.property("pagina") == "ordenar" and menu.property("opened") is True)
    _tecla(app, Qt.Key.Key_Left)
    assert _esperar(lambda: menu.property("pagina") == "raiz" and menu.property("opened") is True)
    app.controle.teclar(int(Qt.Key.Key_Escape))
    assert _esperar(lambda: menu.property("opened") is False)
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
    app.achar("menuPrincipal").setProperty("pagina", "filtrar")  # os itens de outra página ficam desabilitados
    QMetaObject.invokeMethod(limpar, "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: (app.filtros.genero, app.filtros.ano, app.filtros.status) == ("", "", ""))
    assert limpar.property("exibido") is False
    app.fechar()


def test_escolher_filtro_move_a_marca_e_limpar_aparece_e_some(app_qt):
    app = _App(_tres())
    limpar = app.achar("limpar")
    assert limpar.property("exibido") is False
    assert app.achar("status-Todos").property("checked") is True
    app.achar("menuPrincipal").setProperty("pagina", "status")  # os itens de outra página ficam desabilitados
    QMetaObject.invokeMethod(app.achar("status-Zerado"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: app.filtros.status == "beaten")
    assert app.filtros.status == "beaten"
    assert app.achar("status-Zerado").property("checked") is True
    assert app.achar("status-Todos").property("checked") is False
    assert limpar.property("exibido") is True
    app.achar("menuPrincipal").setProperty("pagina", "filtrar")
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
    # O menu continua ligado ao jogo do cartão em que foi aberto.
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


def test_anel_so_por_teclado_e_botoes_so_pelo_ponteiro(app_qt):
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
    # O teclado acende o anel, mas só o ponteiro e o menu aberto mostram os botões.
    assert atual.property("nome") == "Beta" and atual.property("mostrarBotoes") is False
    assert _achar(atual, "anelDeFoco").property("ativo") is True
    app.fechar()


def _cartao_animado(app):
    grade = app.achar("grade")
    delegados = [item for item in grade.property("contentItem").childItems() if item.property("jogoId")]
    cartao = delegados[0].childItems()[0]
    return cartao, _achar(cartao, "capaAnimada")


def _jogo_com_capa_animada():
    from PIL import Image

    from kyron.utils import copias_animadas

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
    # "Animar capas" desligado: nada anima sem o mouse em cima, e o arquivo nem é aberto.
    assert animada.property("playing") is False and animada.property("source").toString() == ""
    # Ligado: toca.
    shared.schema.set_boolean("cover-autoplay", True)
    assert _esperar(lambda: app.aplicativo.tocarSempre)
    assert _esperar(lambda: animada.property("playing") is True)
    assert animada.property("source").toString() == cartao.property("capaAnimada")
    assert _esperar(lambda: animada.property("visible"))  # a animação carregou e cobre a capa parada
    # Fora da vista da grade nada toca; a capa para no quadro atual e guarda o arquivo por 30 s.
    cartao.setProperty("naVista", False)
    assert animada.property("playing") is False and animada.property("source").toString() == cartao.property("capaAnimada")
    assert cartao.property("retendo") is True
    # Passados os 30 s (ou além de 8 pausadas) larga o arquivo e volta ao primeiro quadro.
    QMetaObject.invokeMethod(cartao, "liberar", Qt.ConnectionType.DirectConnection)
    assert animada.property("source").toString() == ""
    # Desligado de novo e sem o mouse: nada toca. Com o mouse em cima, toca mesmo assim.
    cartao.setProperty("naVista", True)
    shared.schema.set_boolean("cover-autoplay", False)
    assert _esperar(lambda: not app.aplicativo.tocarSempre)
    assert cartao.property("animando") is False
    # (O offscreen não produz o hover do `HoverHandler`: `passando` é a propriedade que ele alimenta, e o teste a liga.)
    cartao.setProperty("passando", True)
    assert _esperar(lambda: cartao.property("animando") is True and animada.property("playing") is True)
    assert cartao.property("mostrarBotoes") is True
    cartao.setProperty("passando", False)
    assert _esperar(lambda: cartao.property("animando") is False and animada.property("playing") is False)
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
    assert animada.property("source").toString() == cartao.property("capaAnimada")  # pausada, com o quadro guardado
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
    assert _esperar(lambda: animada.property("playing") is False)
    # Pausada no quadro atual, com o arquivo guardado por 30 s, e não largada.
    assert _cartao.property("retendo") is True and animada.property("source").toString() == _cartao.property("capaAnimada")
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
    # Na grade, a borda vibra o tique leve, não o toque firme.
    app = _App(_tres())
    grade = app.achar("grade")
    colunas = grade.property("colunas")
    assert colunas >= 1
    app.controle.mover.emit(-1, 0)
    assert grade.property("currentIndex") == 0, "na borda esquerda a seleção fica"
    assert app.leitor.vibracoes == [(0.0, 0.14)], "e o controle vibra como a `main`"
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
    assert app.leitor.vibracoes == [(0.0, 0.14)], "no último jogo vibra o tique, como o `FlowBox` da `main`"
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
    assert app.leitor.vibracoes == [(0.0, 0.14)], "e o controle vibra o tique (C-11)"
    app.leitor.vibracoes.clear()
    app.controle.mover.emit(0, 1)
    assert grade.property("activeFocus") is True
    assert app.leitor.vibracoes == [(0.0, 0.14)]
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

    from kyron.utils import copias_animadas  # noqa: PLC0415

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
    from kyron.utils import copias_animadas  # noqa: PLC0415

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
    from kyron.utils import copias_animadas  # noqa: PLC0415

    app, _capa, _copia, cartao, animada = _cartao_com_copia(monkeypatch, lixo=False)
    assert _esperar(lambda: animada.property("playing") is True)
    assert _esperar(lambda: animada.property("visible"), limite=3.0)
    copias_animadas.soltar("imported_1")
    shared.schema.reset("cover-autoplay")
    app.fechar()


def test_copia_animada_corrompida_deixa_a_capa_parada_visivel(app_qt, monkeypatch):
    """Sem refazer: a cópia lixo fica, o `AnimatedImage` a tenta e não carrega, e a capa parada segue à vista."""
    from kyron.utils import copias_animadas  # noqa: PLC0415

    app, capa, copia, cartao, animada = _cartao_com_copia(monkeypatch, lixo=True)
    parada = _achar(cartao, "capaParada")
    assert _esperar(lambda: animada.property("playing") is True)
    # A animada tentou abrir justamente a cópia lixo...
    assert _esperar(lambda: animada.property("source").toString().split("?")[0].endswith(copia.name))
    # ...e, pelo mesmo tempo que a cópia boa leva para aparecer (teste vizinho), não carregou.
    assert not _esperar(lambda: animada.property("visible"), limite=3.0)
    # A cópia não foi refeita e a capa parada é a capa real, não o espaço vazio.
    assert copia.read_bytes() == LIXO
    assert parada.property("source").toString() == cartao.property("capa") != ""
    assert parada.property("source").toString().split("?")[0].endswith(capa.name)
    copias_animadas.soltar("imported_1")
    shared.schema.reset("cover-autoplay")
    app.fechar()


def test_janela_maximizada_volta_maximizada_depois_de_sair_da_frente(app_qt):
    """Pelo caminho do app: `sair_da_frente` minimiza, `present()` devolve a janela maximizada."""
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
    """No `Aplicativo.qml` de verdade, com uma tarefa, o botão do canto só pode aparecer sem nada por cima."""
    from kyron.modelos import tarefas  # noqa: PLC0415

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
        app.achar("dialogoDeErros").fechar()  # o "Dispensar": a resposta volta pela fila
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


def test_itens_de_ano_tem_o_nome_do_grupo(app_qt):
    app = _App(_jogos((1, "Alfa", {"release_date": "01/05/2023"})))
    try:
        app.filtros.recalcularOpcoes()
        assert app.filtros.anos == ["2023"]
        assert app.achar("ano-2023")
        assert _achar(app.janela, "genero-2023") is None
    finally:
        app.fechar()


# -- grade, cartão, busca, atalhos, estados vazios e tarefas --------------------------------------------------


def _tecla(app, tecla, modificadores=Qt.KeyboardModifier.NoModifier, texto=""):
    from PySide6.QtCore import QCoreApplication, QEvent  # noqa: PLC0415
    from PySide6.QtGui import QKeyEvent  # noqa: PLC0415

    for tipo in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QCoreApplication.sendEvent(app.janela, QKeyEvent(tipo, tecla, modificadores, texto))
    _esperar()


def test_grade_tem_o_passo_e_o_cartao_da_main(app_qt):
    """Passo de 218x365 (200+6+12, 347+6+12), cartão de 200x347 com rodapé de 47, a 18 do topo."""
    app = _App(_tres())
    app.janela.resize(1170, 795)
    _esperar()
    grade = app.achar("grade")
    assert grade.property("cellWidth") == 218 and grade.property("cellHeight") == 365
    cartao = next(c for c in _cartoes(grade) if c.property("nome") == "Alfa")
    assert (cartao.width(), cartao.height(), cartao.property("alturaDoNome")) == (200, 347, 47)
    # 1170 de largura: (1170 - 30 + 12) / 218 = 5 colunas, como o gabarito.
    assert grade.property("colunas") == 5
    # O cartão fica a 9 da borda da célula; a célula, a topMargin (9) do topo: 18 no total (15 + 3).
    assert grade.property("topMargin") == 9
    app.fechar()


def test_espaco_abre_e_tecla_menu_nao_abre(app_qt):
    """Espaço abre os detalhes como o Enter; a tecla Menu e Shift+F10 não abrem nada."""
    app = _App(_tres())
    grade = app.achar("grade")
    grade.forceActiveFocus()
    _esperar()
    _tecla(app, Qt.Key.Key_Menu)
    _tecla(app, Qt.Key.Key_F10, Qt.KeyboardModifier.ShiftModifier)
    assert app.achar("menuDoJogo").property("visible") is False
    assert app.todos.busca == "" and app.achar("pagina").property("buscaAberta") is False
    _tecla(app, Qt.Key.Key_Space, texto=" ")
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    assert app.achar("pagina").property("buscaAberta") is False  # o espaço não vira busca
    app.fechar()


def test_tab_percorre_os_cartoes(app_qt):
    app = _App(_tres())
    grade = app.achar("grade")
    grade.forceActiveFocus()
    _esperar()
    _tecla(app, Qt.Key.Key_Tab)
    _tecla(app, Qt.Key.Key_Tab)
    assert grade.property("currentIndex") == 2
    _tecla(app, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert grade.property("currentIndex") == 1
    app.fechar()


def test_digitar_com_o_foco_num_botao_da_barra_abre_a_busca(app_qt):
    """A captura de teclas é a página inteira (o Espaço não conta: aciona o botão)."""
    app = _App(_tres())
    botao = app.achar("botaoMenu")
    botao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _esperar()
    _tecla(app, Qt.Key.Key_G, texto="g")
    assert app.achar("pagina").property("buscaAberta") is True
    assert app.achar("campoDeBusca").property("text") == "g"
    assert _esperar(lambda: app.todos.busca == "g")  # depois dos 150 ms de espera
    app.fechar()


def test_busca_espera_150_ms_e_o_enter_aplica_na_hora(app_qt):
    """O filtro espera; Enter aplica; o botão de limpar só existe com texto."""
    app = _App(_tres())
    app.achar("pagina").setProperty("buscaAberta", True)
    campo = app.achar("campoDeBusca")
    limpar = app.achar("limparBusca")
    assert limpar.property("visible") is False
    campo.setProperty("text", "Beta")
    assert app.todos.busca == "" and limpar.property("visible") is True
    assert _esperar(lambda: app.todos.busca == "Beta")
    campo.setProperty("text", "Gama")
    assert app.todos.busca == "Beta"
    QMetaObject.invokeMethod(campo, "accepted", Qt.ConnectionType.DirectConnection)
    assert app.todos.busca == "Gama"
    assert _esperar(lambda: app.achar("barraDeBusca").property("height") == 46)  # 6 + 34 + 6
    app.fechar()


def test_esc_e_alt_esquerda_voltam_de_jogos_zerados(app_qt):
    from PySide6.QtTest import QTest  # noqa: PLC0415

    app = _App(_tres())
    for esc in (True, False):
        QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
        assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
        if esc:
            app.achar("gradeDeZerados").forceActiveFocus()
            _tecla(app, Qt.Key.Key_Escape)
        else:
            QTest.keyClick(app.janela, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
        assert _esperar(lambda: app.janela.property("paginaAtual") == "todos"), esc
    app.fechar()


def test_a_barra_de_titulo_acende_a_linha_com_a_grade_rolada(app_qt):
    """`sombraDaBarra` segue o `contentY` da grade (o topo é -topMargin, não 0)."""
    app = _App(_jogos(*[(n, f"Jogo {n:03}", {}) for n in range(1, 61)]))
    grade = app.achar("grade")
    _esperar()
    assert app.janela.property("sombraDaBarra") is False
    grade.setProperty("contentY", 300.0)
    assert _esperar(lambda: app.janela.property("sombraDaBarra") is True)
    grade.setProperty("contentY", -grade.property("topMargin"))
    assert _esperar(lambda: app.janela.property("sombraDaBarra") is False)
    app.fechar()


def test_roda_do_mouse_anda_por_mola_ate_o_destino_e_nao_passa_dos_limites(app_qt):
    """Cada entalhe soma 120 px ao destino; a mola assenta nele (sem repique) e para no topo."""
    from PySide6.QtCore import Q_ARG  # noqa: PLC0415

    app = _App(_jogos(*[(n, f"Jogo {n:03}", {}) for n in range(1, 61)]))
    grade = app.achar("grade")
    _esperar()
    topo = grade.property("contentY")
    mola = app.achar("rolagemPorMola")
    QMetaObject.invokeMethod(mola, "empurrar", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", 1))
    assert _esperar(lambda: not mola.property("correndo"), limite=5.0)
    assert abs(grade.property("contentY") - (topo + 120)) <= 0.5
    QMetaObject.invokeMethod(mola, "empurrar", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", -10))
    assert _esperar(lambda: not mola.property("correndo"), limite=5.0)
    assert abs(grade.property("contentY") - topo) <= 0.5  # o clamp: não sobe além do topo
    app.fechar()


def test_cartao_halo_carregando_e_botoes_da_main(app_qt):
    """Halo só com atualização, capa some carregando, botões de 34 sem dica própria."""
    jogos = _tres()
    jogos[0].loading = 1
    jogos[1].track_updates = True
    jogos[1].update_available_ts = 10
    app = _App(jogos)
    grade = app.achar("grade")
    por_nome = {c.property("nome"): c for c in _cartoes(grade)}
    assert _esperar(lambda: _achar(por_nome["Beta"], "haloDaAtualizacao") is not None)
    assert _achar(por_nome["Alfa"], "haloDaAtualizacao") is None and _achar(por_nome["Gama"], "haloDaAtualizacao") is None
    assert _achar(por_nome["Alfa"], "capaParada").parentItem().property("opacity") == 0
    assert _achar(por_nome["Alfa"], "carregando").property("running") is True
    assert _achar(por_nome["Gama"], "capaParada").parentItem().property("opacity") == 1
    jogar = _achar(por_nome["Gama"], "botaoJogar")
    assert (jogar.width(), jogar.height()) == (34, 34) and jogar.property("dica") == "Iniciar"
    assert _achar(jogar, "dica") is None  # os botões do cartão não têm dica
    mais = _achar(por_nome["Gama"], "botaoMais")
    assert mais.x() == 200 - 34 - 6 and mais.y() == 6
    app.fechar()


def test_estado_vazio_e_aviso_de_soltar_da_main(app_qt):
    app = _App([])
    assert app.achar("estadoVazio").property("iconeDoApp") is True
    assert abs(app.achar("avisoDeSoltar").property("color").alphaF() - 0.88) < 0.01
    app.fechar()
    app = _App(_tres())
    app.achar("pagina").setProperty("buscaAberta", True)
    app.achar("campoDeBusca").setProperty("text", "zzz")
    assert _esperar(lambda: app.achar("estadoVazio").property("visible"))
    icone = _achar(app.achar("estadoVazio"), "iconeDoEstado")
    assert icone.property("nome") == "system-search" and icone.width() == 128 and icone.property("opacity") == 0.55
    app.fechar()


def test_botao_das_tarefas_da_main(app_qt):
    """Osd de 34, giro de 1,2 s e a dica."""
    app = _App(_tres())
    assert app.achar("giroDasTarefas").property("duration") == 1200
    circulo = app.achar("circuloDasTarefas")
    assert (circulo.width(), circulo.height()) == (34, 34)
    dica = _achar(circulo, "dica")
    assert dica is not None and dica.property("texto") == "Tarefas em andamento"
    app.fechar()


def test_a_linha_da_rolagem_e_uma_so_abaixo_da_busca_aberta(app_qt):
    """Com a busca aberta a linha do topo fica sob ela e a da barra de título apaga; nunca duas."""
    app = _App(_jogos(*[(n, f"Jogo {n:03}", {}) for n in range(1, 61)]))
    grade = app.achar("grade")
    _esperar()
    grade.setProperty("contentY", 300.0)
    assert _esperar(lambda: app.janela.property("sombraDaBarra") is True)
    assert app.achar("linhaDaBusca").property("visible") is False
    app.achar("pagina").setProperty("buscaAberta", True)
    assert _esperar(lambda: app.janela.property("sombraDaBarra") is False)
    assert app.achar("linhaDaBusca").property("visible") is True
    app.fechar()


def test_roda_real_do_mouse_aciona_a_mola_e_o_teclado_a_cancela(app_qt):
    """Um evento de roda de verdade chega ao `WheelHandler`; mover a rolagem por fora (Tab, setas) para a mola."""
    from PySide6.QtCore import QCoreApplication, QPoint, QPointF  # noqa: PLC0415
    from PySide6.QtGui import QWheelEvent  # noqa: PLC0415

    app = _App(_jogos(*[(n, f"Jogo {n:03}", {}) for n in range(1, 121)]))
    app.janela.show()
    grade = app.achar("grade")
    _esperar()
    topo = grade.property("contentY")
    mola = app.achar("rolagemPorMola")
    mola.setProperty("ativa", True)  # no harness `Tema.animacoes` é falso e a mola fica desligada
    # Uma roda descendo (angleDelta negativo): o `contentY` desce por mola até o destino de 120 px.
    pos = QPointF(400, 300)
    evento = QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
    QCoreApplication.sendEvent(app.janela, evento)
    assert _esperar(lambda: mola.property("correndo") is True)
    assert _esperar(lambda: not mola.property("correndo"), limite=5.0)
    assert abs(grade.property("contentY") - (topo + 120)) <= 0.5
    # Em curso, uma rolagem vinda do teclado cancela a mola em vez de ser sobrescrita no quadro seguinte.
    QCoreApplication.sendEvent(app.janela, QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                                                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
    assert _esperar(lambda: mola.property("correndo") is True)
    grade.setProperty("contentY", 2000.0)  # o mesmo efeito de `positionViewAtIndex`
    assert _esperar(lambda: mola.property("correndo") is False)
    assert abs(grade.property("contentY") - 2000.0) < 1
    app.fechar()


def test_o_limite_de_8_capas_pausadas_e_global(app_qt):
    """O limite de pausadas abertas vale para todas as grades juntas (um só registro)."""
    motor = QQmlEngine()
    componente = QQmlComponent(motor)
    componente.setData(
        b"""import QtQuick
import "file:///""" + QML.as_posix().encode() + b"""\"
QtObject {
    property var liberadas: []
    Component.onCompleted: {
        for (var i = 0; i < 10; ++i) {
            CapasPausadas.registrar(criar(i))
        }
    }
    function criar(n) { return { liberar: function() { liberadas = liberadas.concat([n]) } } }
}""",
        QUrl.fromLocalFile(str(QML / "_pausadas.qml")),
    )
    objeto = componente.create()
    assert objeto is not None, componente.errorString()
    assert objeto.property("liberadas").toVariant() == [0, 1]  # a mais antiga sai primeiro, a partir da nona


def _nome_do_atual(menu):
    return menu.property("atual")


def test_setas_so_andam_pelos_itens_da_pagina_atual(app_qt):
    """Os itens das outras páginas são ocultos e desabilitados; nem ↓ nem o controle os alcançam."""
    app = _App(_tres())
    menu = app.achar("menuPrincipal")
    menu.open()
    assert _esperar(lambda: menu.property("opened") is True)
    vistos = []
    for _ in range(8):  # dá a volta na raiz
        _tecla(app, Qt.Key.Key_Down)
        vistos.append(_nome_do_atual(menu))
    assert set(vistos) == {"entrada-filtrar", "entrada-ordenar", "itemPreferencias", "itemSobre"}, vistos
    # Dentro de "Ordenar por": o primeiro ↓ cai no primeiro item de ordenação, e nenhum sai da página.
    QMetaObject.invokeMethod(app.achar("entrada-ordenar"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: menu.property("pagina") == "ordenar" and menu.property("opened") is True)
    vistos = []
    for _ in range(14):
        _tecla(app, Qt.Key.Key_Down)
        vistos.append(_nome_do_atual(menu))
    assert all(n and (n.startswith("ordenar-") or n == "cabecalho-ordenar") for n in vistos), vistos
    app.fechar()


def test_trocar_de_pagina_nao_fecha_o_popover(app_qt):
    """O clique e o Enter nos itens de navegação trocam a página sem passar por fechado."""
    from PySide6.QtCore import QPointF  # noqa: PLC0415
    from PySide6.QtTest import QTest  # noqa: PLC0415

    app = _App(_tres())
    app.janela.show()
    menu = app.achar("menuPrincipal")
    fechamentos = []
    menu.closed.connect(lambda: fechamentos.append(1))
    menu.open()
    assert _esperar(lambda: menu.property("opened") is True)
    entrada = app.achar("entrada-ordenar")
    centro = entrada.mapToScene(QPointF(entrada.width() / 2, entrada.height() / 2)).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, pos=centro)
    assert _esperar(lambda: menu.property("pagina") == "ordenar")
    _esperar()
    assert menu.property("opened") is True and fechamentos == []
    # O Enter (o controle entrega a tecla ao item em foco) também.
    QMetaObject.invokeMethod(app.achar("cabecalho-ordenar"), "forceActiveFocus", Qt.ConnectionType.DirectConnection)
    app.controle.teclar(int(Qt.Key.Key_Return))
    assert _esperar(lambda: menu.property("pagina") == "raiz")
    _esperar()
    assert menu.property("opened") is True and fechamentos == []
    app.fechar()


def test_push_durante_a_saida_animada_nao_e_apagado(app_qt):
    """Um `empurrar` com a saída em curso termina a saída na hora e a página nova fica (depth 1, estado dos detalhes)."""
    from PySide6.QtCore import Q_ARG  # noqa: PLC0415

    app = _App(_tres())
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    app.janela.setProperty("_saindoDaPilha", True)  # o harness desliga as animações: simula a saída em curso
    QMetaObject.invokeMethod(app.janela, "abrirDetalhes", Qt.ConnectionType.DirectConnection,
                             Q_ARG("QVariant", "imported_1"))
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    assert app.janela.property("_saindoDaPilha") is False
    assert app.achar("pilha").property("depth") == 1
    assert app.detalhes.jogoId == "imported_1"
    app.fechar()


def test_soltar_atalho_fica_desligado_com_a_confirmacao_da_pagina_do_jogo(app_qt):
    """O alvo de soltar segue `modalAberto` (que inclui as confirmações da página do jogo)."""
    from PySide6.QtCore import Q_ARG  # noqa: PLC0415

    app = _App(_tres())
    QMetaObject.invokeMethod(app.janela, "abrirDetalhes", Qt.ConnectionType.DirectConnection,
                             Q_ARG("QVariant", "imported_1"))
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    assert app.achar("alvoDeSoltar").property("enabled") is True
    QMetaObject.invokeMethod(app.achar("dialogoExcluir"), "abrir", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("modalAberto") is True)
    assert app.achar("alvoDeSoltar").property("enabled") is False
    app.fechar()


def test_o_botao_do_menu_principal_abre_e_fecha_o_menu(app_qt):
    """O segundo clique no botão fecha o menu (antes o aperto fechava e o clique reabria)."""
    from PySide6.QtCore import QPointF  # noqa: PLC0415
    from PySide6.QtTest import QTest  # noqa: PLC0415

    app = _App(_tres())
    botao, menu = app.achar("botaoMenu"), app.achar("menuPrincipal")
    centro = botao.mapToScene(QPointF(botao.width() / 2, botao.height() / 2)).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, pos=centro)
    assert _esperar(lambda: menu.property("opened") is True)
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, pos=centro)
    assert _esperar(lambda: menu.property("visible") is False)
    app.fechar()


def test_voltar_com_o_menu_principal_aberto_nao_volta_de_pagina(app_qt):
    """A tecla Voltar é do menu aberto; Alt+← o fecha ao voltar, e ele não fica sobre a outra página."""
    from PySide6.QtTest import QTest  # noqa: PLC0415

    app = _App(_tres())
    QMetaObject.invokeMethod(app.achar("botaoZerados"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "zerados")
    menu = app.achar("menuPrincipal")
    menu.open()
    assert _esperar(lambda: menu.property("opened") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Back)
    _esperar()
    assert app.janela.property("paginaAtual") == "zerados"
    menu.open()
    assert _esperar(lambda: menu.property("opened") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    _esperar()
    assert app.janela.property("paginaAtual") == "todos"
    assert menu.property("opened") is False  # o menu não fica aberto sobre a outra página
    app.fechar()


def test_poucos_jogos_ficam_a_esquerda_da_grade(app_qt):
    """A grade fica centrada pelas colunas que cabem, e não pelos jogos que há."""
    app = _App(_tres())
    app.janela.show()
    grade = app.achar("grade")
    assert grade.property("colunas") > 3
    esperado = (grade.width() - grade.property("colunas") * grade.property("larguraDaCelula")) / 2
    assert grade.property("leftMargin") == pytest.approx(esperado)
    app.fechar()


def test_a_volta_pelo_teclado_acende_o_anel_e_espera_o_proximo_hover(app_qt):
    """O hover em si o offscreen não produz: o reenvio com o mouse parado foi conferido em janela real."""
    from PySide6.QtCore import QMetaObject  # noqa: PLC0415

    app = _App(_tres())
    app.janela.show()
    grade = app.achar("grade")
    QMetaObject.invokeMethod(grade, "marcarTeclado", Qt.ConnectionType.DirectConnection)
    assert grade.property("porTeclado") is True
    assert grade.property("_registrarPonteiro") is True
    app.fechar()
