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

"""O que o app está fazendo em segundo plano, num lugar só.

Cada trabalho longo (importação, HowLongToBeat, metadados, tamanho em disco)
avisa aqui quando começa, a cada jogo e quando termina. O botão do canto da
biblioteca e a janela "Tarefas em andamento" só leem ``lista``: um trabalho
novo entra com três chamadas, sem mexer em nenhum dos dois.

Os trabalhos rodam em threads, e a lista é lida pela interface: toda mudança é
entregue na thread principal. A ordem das entregas é a das chamadas, então um
``terminar()`` logo depois do ``comecar()`` nunca chega antes dele.
"""

from typing import Optional

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QCoreApplication,
    QModelIndex,
    QObject,
    QPoint,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QWindow

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
    """As tarefas em andamento, na ordem em que começaram. Só a thread principal mexe."""

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
        # `sender()` em vez de uma lambda: a conexão não prende nem o modelo nem a tarefa.
        tarefa.mudou.connect(self._tarefa_mudou)

    def remover(self, tarefa: Tarefa) -> None:
        # Repetir o `terminar()` não faz nada: a tarefa já não está aqui.
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


# Criada na importação, que o app faz na thread principal (`app.py`): um QObject nasce na
# thread que o cria, e é nela que a lista recebe os sinais das tarefas.
lista = ListaDeTarefas()


def comecar(nome: str, total: int) -> Tarefa:
    tarefa = Tarefa(nome, total)
    if not eh_thread_principal():
        # Nasceu na thread do trabalho; os sinais dela são emitidos na principal.
        tarefa.moveToThread(QCoreApplication.instance().thread())
    na_thread_principal(lista.adicionar, tarefa)
    return tarefa


def pode_mostrar(quantas: int, pagina: str, modal_aberto: bool, big_picture: bool, sessao: bool) -> bool:
    """O botão do canto só aparece com tarefa, numa das duas bibliotecas e sem nada por cima (D77)."""
    return quantas > 0 and pagina in ("todos", "zerados") and not (modal_aberto or big_picture or sessao)


class PainelDasTarefas(QObject):
    """O que a tela das tarefas pede ao Python: quantas há, se a janela está aberta e onde pô-la."""

    alterado = Signal()
    frente = Signal()  # a janela já aberta deve vir para a frente

    def __init__(self) -> None:
        super().__init__()
        self._quantas = lista.rowCount()
        self._aberta = False
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

    def _contar(self, *_args) -> None:
        if (quantas := lista.rowCount()) != self._quantas:
            self._quantas = quantas
            self.alterado.emit()

    @Slot(int, str, bool, bool, bool, result=bool)
    def podeMostrar(self, quantas: int, pagina: str, modal: bool, big_picture: bool, sessao: bool) -> bool:  # noqa: N802
        return pode_mostrar(quantas, pagina, modal, big_picture, sessao)

    @Slot()
    def mostrar(self) -> None:
        """Abre a janela; aberta, só a traz para a frente."""
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

    @Slot(QWindow, float, float)
    def posicionar(self, janela: QWindow, x: float, y: float) -> None:
        """Leva a moldura da janela para logo acima do botão, cujo canto de cima é (x, y) em coordenadas da tela."""
        # shortcut: o botão é sempre 34 x 34 (D77); lido do QML se um dia mudar de tamanho.
        botao = (round(x), round(y), 34, 34)
        janela.setFramePosition(QPoint(*window_geometry.posicao_acima_do_botao(botao, janela.frameGeometry().height())))
