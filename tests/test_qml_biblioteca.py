# test_qml_biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As páginas da biblioteca e de Jogos Zerados (QML offscreen, sem a ponte do QWindowKit)."""

import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt, QTimer, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from cartridges.aplicativo import Aplicativo
from cartridges.jogo import Jogo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.ponte import Ponte

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
QQuickStyle.setStyle("Basic")


def _esperar(ate=None, limite=3.0):
    limite = 0.3 if ate is None else limite
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(30, laco.quit)
        laco.exec()
        if ate is not None and ate():
            return True
    return ate is None


def _achar(raiz, nome):
    """O objeto de `objectName` igual a `nome`, descendo pelos itens visuais e pelos filhos QObject."""
    pilha = [raiz]
    while pilha:
        atual = pilha.pop()
        if atual.objectName() == nome:
            return atual
        pilha.extend(atual.children())
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
        elif isinstance(atual, QQuickWindow):
            pilha.append(atual.contentItem())
    return None


def _jogos(*itens):
    return [Jogo({"game_id": f"imported_{n}", "source": "imported", "name": nome, **extra}) for n, nome, extra in itens]


class _App:
    def __init__(self, jogos):
        self.modelo = ModeloDaBiblioteca()
        for jogo in jogos:
            self.modelo.atualizar(jogo)
        self.filtros = FiltrosDaBiblioteca(self.modelo)
        self.filtros.modo = "a-z"
        self.todos = FiltroDaPagina(self.modelo, self.filtros, "biblioteca")
        self.zerados = FiltroDaPagina(self.modelo, self.filtros, "zerados")
        self.aplicativo = Aplicativo()
        self.ponte = Ponte()
        self.motor = QQmlEngine()
        contexto = self.motor.rootContext()
        for nome, valor in (
            ("filtros", self.filtros), ("paginaTodos", self.todos), ("paginaZerados", self.zerados),
            ("aplicativo", self.aplicativo), ("ponte", self.ponte),
        ):  # fmt: skip
            contexto.setContextProperty(nome, valor)
        componente = QQmlComponent(self.motor, QUrl.fromLocalFile(str(QML / "Aplicativo.qml")))
        self.janela = componente.createWithInitialProperties({"semAgente": True})
        assert self.janela is not None, componente.errorString()
        self.componente = componente
        _esperar()

    def achar(self, nome):
        objeto = _achar(self.janela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()


def _tres():
    return _jogos((1, "Alfa", {}), (2, "Beta", {}), (3, "Gama", {}))


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
