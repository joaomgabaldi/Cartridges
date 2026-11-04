# tarefas.py
#
# Copyright 2026 joaomgabaldi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que o app está fazendo em segundo plano, num lugar só."""

import weakref
from collections.abc import Callable
from typing import Optional

import shiboken6
from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QCoreApplication,
    QModelIndex,
    QObject,
    QPoint,
    Qt,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QGuiApplication, QWindow

from cartridges import shared
from cartridges.utils import window_geometry
from cartridges.utils.thread_principal import eh_thread_principal, na_thread_principal


class Tarefa(QObject):
    """Um trabalho em andamento: o nome e quantos de quantos já foram."""

    mudou = Signal()

    def __init__(self, nome: str, total: int = 0) -> None:
        super().__init__()
        self._nome = nome
        self._feitos = 0
        self._total = total

    @Property(str, constant=True)
    def nome(self) -> str:
        return self._nome

    @Property(int, notify=mudou)
    def feitos(self) -> int:
        return self._feitos

    @Property(int, notify=mudou)
    def total(self) -> int:
        return self._total

    def atualizar(self, feitos: int, total: Optional[int] = None) -> None:
        na_thread_principal(self._atualizar, feitos, total)

    def _atualizar(self, feitos: int, total: Optional[int]) -> None:
        if total is not None:
            self._total = total
        self._feitos = feitos
        self.mudou.emit()

    def terminar(self) -> None:
        na_thread_principal(lista.remover, self)


class ListaDeTarefas(QAbstractListModel):
    """As tarefas em andamento, na ordem em que começaram."""

    NOME = Qt.ItemDataRole.UserRole + 1
    FEITOS = NOME + 1
    TOTAL = NOME + 2

    def __init__(self) -> None:
        super().__init__()
        self._tarefas: list[Tarefa] = []

    def roleNames(self) -> dict:  # noqa: N802
        return {
            self.NOME: QByteArray(b"nome"),
            self.FEITOS: QByteArray(b"feitos"),
            self.TOTAL: QByteArray(b"total"),
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802, B008
        return 0 if parent.isValid() else len(self._tarefas)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._tarefas):
            return None
        tarefa = self._tarefas[index.row()]
        match role:
            case self.NOME:
                return tarefa.nome
            case self.FEITOS:
                return tarefa.feitos
            case self.TOTAL:
                return tarefa.total
        return None

    def adicionar(self, tarefa: Tarefa) -> None:
        linha = len(self._tarefas)
        self.beginInsertRows(QModelIndex(), linha, linha)
        self._tarefas.append(tarefa)
        self.endInsertRows()
        tarefa.mudou.connect(self._tarefa_mudou)

    def remover(self, tarefa: Tarefa) -> None:
        if tarefa not in self._tarefas:
            return
        linha = self._tarefas.index(tarefa)
        tarefa.mudou.disconnect(self._tarefa_mudou)
        self.beginRemoveRows(QModelIndex(), linha, linha)
        del self._tarefas[linha]
        self.endRemoveRows()

    def _tarefa_mudou(self) -> None:
        tarefa = self.sender()
        if tarefa in self._tarefas:
            indice = self.index(self._tarefas.index(tarefa))
            self.dataChanged.emit(indice, indice, [self.FEITOS, self.TOTAL])


# Criada na importação, que o app faz na thread principal (`app.py`): um QObject nasce na thread que o cria, e é nela
# que a lista recebe os sinais das tarefas.
lista = ListaDeTarefas()


def comecar(nome: str, total: int) -> Tarefa:
    tarefa = Tarefa(nome, total)
    if not eh_thread_principal():
        # Nasceu na thread do trabalho; os sinais dela são emitidos na principal.
        tarefa.moveToThread(QCoreApplication.instance().thread())
    na_thread_principal(lista.adicionar, tarefa)
    return tarefa


def pode_mostrar(quantas: int, pagina: str, modal_aberto: bool, big_picture: bool, sessao: bool) -> bool:
    return quantas > 0 and pagina in ("todos", "zerados") and not (modal_aberto or big_picture or sessao)


def acao_ao_fechar(saves_em_andamento: bool, janela_aberta: bool, tarefas: int) -> str:
    if saves_em_andamento:
        return "mostrar_e_esconder"
    if not janela_aberta:
        return "fechar"
    return "esconder" if tarefas > 0 else "fechar_as_duas"


def _sair() -> None:
    QCoreApplication.quit()


_painel: Optional["weakref.ref[PainelDasTarefas]"] = None


def _painel_esperando() -> Optional["PainelDasTarefas"]:
    painel = _painel() if _painel is not None else None
    return painel if painel is not None and shiboken6.isValid(painel) and painel.principalEscondida else None


def painel_aberto_sem_a_principal() -> Optional["PainelDasTarefas"]:
    painel = _painel() if _painel is not None else None
    return painel if painel is not None and painel.aberta and painel.principalEscondida else None


def fechamento_esperando() -> bool:
    return _painel_esperando() is not None


def cancelar_fechamento() -> bool:
    if (painel := _painel_esperando()) is None:
        return False
    painel.mostrarPrincipal()
    return True


class PainelDasTarefas(QObject):
    """O que a tela das tarefas pede ao Python: quantas há, se a janela está aberta e onde pô-la; e o fechamento da
    principal com trabalho em andamento.
    """

    alterado = Signal()
    frente = Signal()
    avisoPedido = Signal(str, str)  # noqa: N815

    def __init__(self) -> None:
        super().__init__()
        self._quantas = lista.rowCount()
        self._aberta = False
        self._janela: Optional[QWindow] = None
        self._escondida = False
        self._saindo = False
        # A espera de sair até o fim dos saves (`janelaFechada`).
        self._espera = QTimer(self)
        self._espera.setInterval(250)
        self._espera.timeout.connect(self._conferir_a_espera)
        self._escondidas_na_espera: list[QWindow] = []
        self._ao_fechar_aviso: Optional[Callable[[], None]] = None
        global _painel  # noqa: PLW0603
        _painel = weakref.ref(self)
        self.gravar_geometria: Callable[[], None] = lambda: None
        # Referência fraca implícita: o Qt desliga a conexão quando o painel é destruído.
        lista.rowsInserted.connect(self._contar)
        lista.rowsRemoved.connect(self._contar)
        lista.modelReset.connect(self._contar)

    @Property(QObject, constant=True)
    def lista(self) -> QObject:  # noqa: N802
        return lista

    @Property(int, notify=alterado)
    def quantas(self) -> int:
        return self._quantas

    @Property(bool, notify=alterado)
    def aberta(self) -> bool:
        return self._aberta

    @Property(bool, notify=alterado)
    def principalEscondida(self) -> bool:  # noqa: N802
        return self._escondida and self._janela is not None and not self._janela.isVisible()

    def pedir_aviso(self, titulo: str, corpo: str, ao_fechar: Callable[[], None]) -> None:
        anterior = self._ao_fechar_aviso
        if anterior is not None:
            def ambos() -> None:
                anterior()
                ao_fechar()

            self._ao_fechar_aviso = ambos
            return
        self._ao_fechar_aviso = ao_fechar
        self.avisoPedido.emit(titulo, corpo)

    @Slot()
    def avisoFechado(self) -> None:  # noqa: N802
        ao_fechar, self._ao_fechar_aviso = self._ao_fechar_aviso, None
        if ao_fechar is not None:
            ao_fechar()

    @Slot()
    def encerrando(self) -> None:
        self._saindo = True

    def definir_janela(self, janela: QWindow) -> None:
        self._janela = janela

    def _contar(self, *_args) -> None:
        if (quantas := lista.rowCount()) != self._quantas:
            self._quantas = quantas
            self.alterado.emit()

    @Slot(int, str, bool, bool, bool, result=bool)
    def podeMostrar(self, quantas: int, pagina: str, modal: bool, big_picture: bool, sessao: bool) -> bool:  # noqa: N802
        return pode_mostrar(quantas, pagina, modal, big_picture, sessao)

    @Slot()
    def mostrar(self) -> None:
        if self._aberta:
            self.frente.emit()
            return
        self._aberta = True
        self.alterado.emit()

    @Slot()
    def janelaFechada(self) -> None:  # noqa: N802
        if self._aberta:
            self._aberta = False
            self.alterado.emit()
        if self._janela is None or self._janela.isVisible():
            return
        from cartridges.saves import backup_de_saves  # noqa: PLC0415  (ele importa este módulo)

        if not self._saindo and backup_de_saves.em_andamento():
            # Antes de esta janela acabar de fechar: senão o Qt sairia sozinho com a última janela fechada.
            QGuiApplication.setQuitOnLastWindowClosed(False)
            self._escondidas_na_espera = [
                j for j in QGuiApplication.topLevelWindows() if j.isVisible() and j.objectName() != "janelaDasTarefas"
            ]
            for janela in self._escondidas_na_espera:
                janela.hide()
            self._espera.start()
            return
        QTimer.singleShot(0, _sair)

    def _conferir_a_espera(self) -> None:
        if self._janela is not None and self._janela.isVisible():
            self._desfazer_a_espera()
            return
        from cartridges.saves import backup_de_saves  # noqa: PLC0415

        if not backup_de_saves.em_andamento():
            self._espera.stop()
            QGuiApplication.setQuitOnLastWindowClosed(True)
            _sair()

    def _desfazer_a_espera(self) -> None:
        if not self._espera.isActive():
            return
        self._espera.stop()
        QGuiApplication.setQuitOnLastWindowClosed(True)
        janelas, self._escondidas_na_espera = self._escondidas_na_espera, []
        for janela in janelas:
            try:
                janela.setVisible(True)
            except RuntimeError:
                continue

    @Slot(result=bool)
    def principalFechando(self) -> bool:  # noqa: N802
        self.gravar_geometria()
        # O `closing` que vem do `quit()` (o reinício, o fim da sessão do Windows, a janela das tarefas fechada com a
        # principal escondida): recusá-lo cancelaria o `quit()` com a sessão já encerrada pelo `saindo`.
        if self._saindo:
            return True
        # Aqui dentro: o `backup_de_saves` importa este módulo.
        from cartridges.saves import backup_de_saves  # noqa: PLC0415

        acao = acao_ao_fechar(backup_de_saves.em_andamento(), self._aberta, self._quantas)
        if acao == "mostrar_e_esconder":
            self.mostrar()
        if acao in ("mostrar_e_esconder", "esconder"):
            self._escondida = True
            self.alterado.emit()
            if self._janela is not None:
                self._janela.hide()
            return False
        if acao == "fechar_as_duas":
            self._aberta = False
            self.alterado.emit()
            # O `Loader` desfaz a janela das tarefas sem evento de fechamento: o Qt não vê a última janela fechada.
            QTimer.singleShot(0, _sair)
        if shared.sessao is not None:
            shared.sessao.principalFechando()
        return True

    @Slot()
    def mostrarPrincipal(self) -> None:  # noqa: N802
        if (janela := self._janela) is None:
            return
        self._desfazer_a_espera()
        if self._escondida:
            self._escondida = False
            self.alterado.emit()
        janela.setWindowStates(janela.windowStates() & ~Qt.WindowState.WindowMinimized)
        janela.setVisible(True)
        janela.raise_()
        janela.requestActivate()

    @Slot(QWindow, float, float, float, float)
    def posicionar(self, janela: QWindow, x: float, y: float, largura: float, altura: float) -> None:
        botao = (round(x), round(y), round(largura), round(altura))
        janela.setFramePosition(QPoint(*window_geometry.posicao_acima_do_botao(botao, janela.frameGeometry().height())))
