# apoio_janela_atualizacao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo.qml` inteiro com um `AppUpdater` no contexto, para os testes das atualizações (D82).

Não importa o `conftest` nem outro teste. Nada de verdade: o atualizador não busca nem baixa (quem o exercita troca
`_buscar_release`/`download_installer`), e `_abrir_instalador` é o guarda `sem_instalador_de_verdade`.
"""

import time
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.modelos.novidades import Novidades
from cartridges.modelos.preferencias import Preferencias
from cartridges.modelos.restauracao import ContinuacaoDaRestauracao
from cartridges.modelos.saves import SavesDoJogo
from cartridges.modelos.sobre import Sobre
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.ponte import Ponte
from cartridges.utils.app_updater import AppUpdater
from cartridges.utils.news_checker import NewsChecker

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
QQuickStyle.setStyle("Basic")


def esperar(ate=None, limite=5.0):
    limite = 0.3 if ate is None else limite
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(20, laco.quit)
        laco.exec()
        if ate is not None and ate():
            return True
    return ate is None


def achar(raiz, nome):
    pilha = [raiz]
    vistos = {}  # um item é filho QObject e filho visual: sem isto a árvore é percorrida 2^profundidade vezes
    while pilha:
        atual = pilha.pop()
        if id(atual) in vistos:
            continue
        vistos[id(atual)] = atual  # guardar o objeto impede o reuso do id
        if atual.objectName() == nome:
            return atual
        pilha.extend(atual.children())
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
        elif isinstance(atual, QQuickWindow):
            pilha.append(atual.contentItem())
    return None


def avaliar(objeto, expressao):
    return QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]


class _DetalhesFalsos(QObject):
    alterado = Signal()
    jogoId = ""  # noqa: N815
    loja = SimpleNamespace(get=lambda _id: None)


class Janela:
    def __init__(self, com_atualizador=True, com_novidades=True, com_sobre=True):
        self.modelo = ModeloDaBiblioteca()
        self.filtros = FiltrosDaBiblioteca(self.modelo)
        self.ponte = Ponte()
        self.aplicativo = Aplicativo(self.ponte.fila)
        self.edicao = ModeloDaEdicao(self.aplicativo)
        self.historico = HistoricoDeSessoes(SimpleNamespace(get=lambda _id: None))
        self.saves = SavesDoJogo(self.aplicativo)
        self.preferencias = shared.preferencias = Preferencias(self.ponte.fila, lambda: True)
        self.painel_das_tarefas = PainelDasTarefas()
        self.restauracao = ContinuacaoDaRestauracao(self.aplicativo)
        self.big_picture = BigPicture(self.modelo)
        self.sessao = ModeloDaSessao(self.ponte.fila)
        self.conquistas = ConquistasDoJogo(_DetalhesFalsos(), self.sessao)
        self.atualizador = AppUpdater() if com_atualizador else None
        self.checker = NewsChecker()
        self.novidades = Novidades(self.ponte.fila, self.checker)
        self.sobre = Sobre(self.ponte.fila)
        self.motor = QQmlEngine()
        self.motor.addImageProvider("fundo", ProvedorDoFundo())
        contexto = self.motor.rootContext()
        for nome, valor in (
            ("filtros", self.filtros),
            ("paginaTodos", FiltroDaPagina(self.modelo, self.filtros, "biblioteca")),
            ("paginaZerados", FiltroDaPagina(self.modelo, self.filtros, "zerados")),
            ("aplicativo", self.aplicativo),
            ("ponte", self.ponte),
            ("controle", ControleDaGrade(estado_do_app=lambda: Qt.ApplicationState.ApplicationInactive)),
            ("edicao", self.edicao),
            ("bigPicture", self.big_picture),
            ("sessao", self.sessao),
            ("historico", self.historico),
            ("saves", self.saves),
            ("conquistasDoJogo", self.conquistas),
            ("preferencias", self.preferencias),
            ("painelDasTarefas", self.painel_das_tarefas),
            ("restauracao", self.restauracao),
            *([("atualizador", self.atualizador)] if self.atualizador is not None else []),
            *([("novidades", self.novidades)] if com_novidades else []),
            *([("sobre", self.sobre)] if com_sobre else []),
        ):
            contexto.setContextProperty(nome, valor)
        componente = QQmlComponent(self.motor, QUrl.fromLocalFile(str(QML / "Aplicativo.qml")))
        self.janela = componente.createWithInitialProperties({"semAgente": True})
        assert self.janela is not None, componente.errorString()
        self.componente = componente
        esperar()

    def achar(self, nome):
        objeto = achar(self.janela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def foco_dentro_de(self, nome):
        item = self.janela.property("activeFocusItem")
        while item is not None:
            if item.objectName() == nome:
                return True
            item = item.parentItem()
        return False

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()
