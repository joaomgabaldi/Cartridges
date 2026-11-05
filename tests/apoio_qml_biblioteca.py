# apoio_qml_biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_qml_biblioteca.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

import time
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.jogo import Jogo
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.detalhes import DetalhesDoJogo
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.modelos.novidades import Novidades
from cartridges.modelos.preferencias import Preferencias
from cartridges.modelos.restauracao import ContinuacaoDaRestauracao
from cartridges.modelos.saves import SavesDoJogo
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.modelos.sobre import Sobre
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.modelos.zerados_manuais import SeletorDeZerados
from cartridges.ponte import Ponte
from cartridges.utils.app_updater import AppUpdater
from cartridges.utils.caixa_redimensionavel import CaixaDaAnotacao
from cartridges.utils.news_checker import NewsChecker

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
QQuickStyle.setStyle("Basic")  # o estilo do app


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


def _assentar(fatias=3):
    """Deixa o QML recém-criado processar o que enfileirou (`Qt.callLater`, foco, polimento): poucas fatias, não 0,3 s fixos."""
    for _ in range(fatias):
        laco = QEventLoop()
        QTimer.singleShot(15, laco.quit)
        laco.exec()


def _achar(raiz, nome):
    """O objeto de `objectName` igual a `nome`, descendo pelos itens visuais e pelos filhos QObject."""
    pilha = [raiz]
    vistos = {}  # um item é filho QObject e filho visual: sem isto a árvore é percorrida 2^profundidade vezes
    while pilha:
        atual = pilha.pop()
        if id(atual) in vistos:
            continue
        vistos[id(atual)] = atual  # guardar o objeto impede o reuso do id
        try:  # um item já deletado (a janela solta da sessão, por exemplo) não derruba a busca
            if atual.objectName() == nome:
                return atual
            pilha.extend(atual.children())
            if isinstance(atual, QQuickItem):
                pilha.extend(atual.childItems())
            elif isinstance(atual, QQuickWindow) and atual is raiz:  # outra janela é outra árvore
                pilha.append(atual.contentItem())
        except RuntimeError:
            continue
    return None


def _jogos(*itens):
    return [Jogo({"game_id": f"imported_{n}", "source": "imported", "name": nome, **extra}) for n, nome, extra in itens]


class _LeitorFalso:
    disponivel = True

    def __init__(self):
        self.vibracoes = []

    def ler(self):
        return None

    def vibrar(self, esquerdo=0.0, direito=0.0):
        self.vibracoes.append((esquerdo, direito))

    def soltar(self):
        pass


class _LojaFalsa(QObject):
    """O que o `DetalhesDoJogo` pede à `Store`: achar o jogo e saber das exclusões."""

    jogo_excluido = Signal(str)

    def __init__(self, jogos):
        super().__init__()
        self.por_id = {jogo.game_id: jogo for jogo in jogos}

    def get(self, game_id):
        return self.por_id.get(game_id)


class _App:
    def __init__(self, jogos, animacoes=True, cortina=None):
        self.jogos = jogos
        self.loja = _LojaFalsa(jogos)
        self.detalhes = DetalhesDoJogo(self.loja)
        self.modelo = ModeloDaBiblioteca()
        for jogo in jogos:
            self.modelo.atualizar(jogo)
        self.filtros = FiltrosDaBiblioteca(self.modelo)
        self.filtros.modo = "a-z"
        self.todos = FiltroDaPagina(self.modelo, self.filtros, "biblioteca")
        self.zerados = FiltroDaPagina(self.modelo, self.filtros, "zerados")
        self.ponte = Ponte()
        self.aplicativo = Aplicativo(self.ponte.fila)
        self.edicao = ModeloDaEdicao(self.aplicativo)
        self.historico = HistoricoDeSessoes(self.loja)
        # O `SavesDoJogo` liga o `jogo_excluido` da store; uma store de verdade, posta por quem importa o `_App`, fica.
        # A falsa sai no `fechar`: deixada, os testes de outros arquivos achariam os jogos daqui.
        self._store_de_antes = shared.store
        if not hasattr(shared.store, "jogo_excluido"):
            shared.store = self.loja
        self.saves = SavesDoJogo(self.aplicativo)
        self.preferencias = shared.preferencias = Preferencias(self.ponte.fila, lambda: True)
        # Sem `cortina`, a troca é direta (o offscreen tem HWND falso).
        self.big_picture = BigPicture(
            self.modelo, fabrica_da_cortina=cortina or (lambda _hwnd: None), animacoes_do_sistema=animacoes
        )
        self.painel_das_tarefas = PainelDasTarefas()
        self.restauracao = ContinuacaoDaRestauracao(self.aplicativo)
        self.atualizador = AppUpdater()
        self.novidades = Novidades(self.ponte.fila, NewsChecker())
        self.sobre = Sobre(self.ponte.fila)
        self.zerados_manuais = SeletorDeZerados()
        self.caixa_da_anotacao = CaixaDaAnotacao()
        self.leitor = _LeitorFalso()
        self.sessao = ModeloDaSessao(self.ponte.fila)
        self.conquistas = ConquistasDoJogo(self.detalhes, self.sessao)
        leitor = self.leitor  # o lambda não captura `self`: senão `_App` <-> controle é um ciclo
        shared.schema.set_boolean("gamepad", True)
        self.controle = ControleDaGrade(
            fabrica_do_leitor=lambda: leitor,
            estado_do_app=lambda: Qt.ApplicationState.ApplicationActive,
        )
        self.motor = QQmlEngine()
        from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
        self.motor.addImageProvider("icone", ProvedorDeIcones())
        self.motor.addImageProvider("desfoque", self.detalhes.provedor)
        self.motor.addImageProvider("fundo", ProvedorDoFundo())
        contexto = self.motor.rootContext()
        for nome, valor in (
            ("filtros", self.filtros), ("paginaTodos", self.todos), ("paginaZerados", self.zerados),
            ("aplicativo", self.aplicativo), ("ponte", self.ponte), ("controle", self.controle),
            ("detalhes", self.detalhes), ("edicao", self.edicao), ("bigPicture", self.big_picture),
            ("sessao", self.sessao), ("historico", self.historico), ("saves", self.saves),
            ("conquistasDoJogo", self.conquistas), ("preferencias", self.preferencias),
            ("painelDasTarefas", self.painel_das_tarefas),
            ("restauracao", self.restauracao),
            ("atualizador", self.atualizador),
            ("novidades", self.novidades),
            ("sobre", self.sobre),
            ("zeradosManuais", self.zerados_manuais),
            ("caixaDaAnotacao", self.caixa_da_anotacao),
        ):  # fmt: skip
            contexto.setContextProperty(nome, valor)
        componente = QQmlComponent(self.motor, QUrl.fromLocalFile(str(QML / "Aplicativo.qml")))
        self.janela = componente.createWithInitialProperties({"semAgente": True})
        assert self.janela is not None, componente.errorString()
        self.componente = componente
        _assentar()

    def achar(self, nome):
        objeto = _achar(self.janela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()
        if shared.store is self.loja:
            shared.store = self._store_de_antes


def _tres():
    return _jogos((1, "Alfa", {}), (2, "Beta", {}), (3, "Gama", {}))
