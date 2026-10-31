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


def acao_ao_fechar(saves_em_andamento: bool, janela_aberta: bool, tarefas: int) -> str:
    """O que fechar a principal faz, na ordem da `main` (D78).

    Os saves vêm primeiro: fechar agora deixaria o Ludusavi órfão. Com a janela das tarefas aberta e alguma tarefa, a
    principal só some; sem tarefa, a janela das tarefas vai junto (senão manteria o app vivo sozinha). Fechar depois a
    janela das tarefas, com a principal escondida, encerra o app; com os saves ainda em andamento, só quando eles
    acabam (`PainelDasTarefas.janelaFechada`).
    """
    if saves_em_andamento:
        return "mostrar_e_esconder"
    if not janela_aberta:
        return "fechar"
    return "esconder" if tarefas > 0 else "fechar_as_duas"


def _sair() -> None:
    QCoreApplication.quit()


class PainelDasTarefas(QObject):
    """O que a tela das tarefas pede ao Python: quantas há, se a janela está aberta e onde pô-la; e o fechamento
    da principal com trabalho em andamento (D78)."""

    alterado = Signal()
    frente = Signal()  # a janela já aberta deve vir para a frente

    def __init__(self) -> None:
        super().__init__()
        self._quantas = lista.rowCount()
        self._aberta = False
        self._janela: Optional[QWindow] = None
        self._escondida = False
        self._saindo = False
        # A espera de sair até o fim dos saves (`janelaFechada`). O backup não avisa o fim: pergunta-se a
        # `em_andamento()` na thread principal, sem bloqueá-la.
        self._espera = QTimer(self)
        self._espera.setInterval(250)
        self._espera.timeout.connect(self._conferir_a_espera)
        self._escondidas_na_espera: list[QWindow] = []
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
        # A visibilidade de agora também: o fim de uma sessão traz a principal de volta sem passar por aqui.
        return self._escondida and self._janela is not None and not self._janela.isVisible()

    @Slot()
    def encerrando(self) -> None:
        """O `quit()` começou (`AplicacaoQt.saindo`): daqui em diante o `closing` da principal não recusa."""
        self._saindo = True

    def definir_janela(self, janela: QWindow) -> None:
        """A principal, que o fechamento esconde e a segunda abertura mostra."""
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
        """Abre a janela; aberta, só a traz para a frente."""
        if self._aberta:
            self.frente.emit()
            return
        self._aberta = True
        self.alterado.emit()

    @Slot()
    def janelaFechada(self) -> None:  # noqa: N802
        """A janela das tarefas fechou. Com a principal escondida, era a única do app: ele encerra.

        Com os saves ainda em andamento, o encerramento espera o fim deles, com todas as janelas escondidas: sair agora
        mataria a thread do backup e deixaria o `ludusavi.exe` órfão (uma restauração pararia no meio). A segunda
        abertura desfaz a espera (`mostrarPrincipal`).
        """
        if self._aberta:
            self._aberta = False
            self.alterado.emit()
        # A visibilidade de agora, e não a marca: o fim de uma sessão traz a principal de volta (`sessao.present`).
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
        # Na volta do laço: um `quit()` dentro do `closing` fecharia de novo, por dentro, a janela que está fechando,
        # e o `aboutToQuit` (a parede e as fitas) rodaria com ela ainda na tela.
        QTimer.singleShot(0, _sair)

    def _conferir_a_espera(self) -> None:
        if self._janela is not None and self._janela.isVisible():
            self._desfazer_a_espera()  # a principal voltou por outro caminho: o app segue aberto
            return
        from cartridges.saves import backup_de_saves  # noqa: PLC0415

        if not backup_de_saves.em_andamento():
            self._espera.stop()
            QGuiApplication.setQuitOnLastWindowClosed(True)  # um quit recusado não deixa o processo sem janela
            _sair()

    def _desfazer_a_espera(self) -> None:
        if not self._espera.isActive():
            return
        self._espera.stop()
        QGuiApplication.setQuitOnLastWindowClosed(True)
        janelas, self._escondidas_na_espera = self._escondidas_na_espera, []
        for janela in janelas:
            try:
                janela.show()
            except RuntimeError:  # já destruída (o aviso de conquista que saiu por tempo)
                continue

    @Slot(result=bool)
    def principalFechando(self) -> bool:  # noqa: N802
        """O `closing` da principal: True deixa fechar; False a esconde (o app segue com a janela das tarefas)."""
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
            self._aberta = False  # o `Loader` desfaz a janela das tarefas
            self.alterado.emit()
        # A sessão manual e o aviso de conquista na tela agendam o `_sair` (plano 6).
        if shared.sessao is not None:
            shared.sessao.principalFechando()
        return True

    @Slot()
    def mostrarPrincipal(self) -> None:  # noqa: N802
        """A segunda abertura do app: a principal volta (escondida ou minimizada) e vem para a frente.

        Durante a espera do fim dos saves para sair, a espera é desfeita: o app segue aberto, com as janelas de antes.
        """
        if (janela := self._janela) is None:
            return
        self._desfazer_a_espera()
        if self._escondida:
            self._escondida = False
            self.alterado.emit()
        janela.setWindowStates(janela.windowStates() & ~Qt.WindowState.WindowMinimized)
        janela.show()
        janela.raise_()
        janela.requestActivate()

    @Slot(QWindow, float, float, float, float)
    def posicionar(self, janela: QWindow, x: float, y: float, largura: float, altura: float) -> None:
        """Leva a moldura da janela para logo acima do botão, cujo retângulo é (x, y, largura, altura) na tela."""
        botao = (round(x), round(y), round(largura), round(altura))
        janela.setFramePosition(QPoint(*window_geometry.posicao_acima_do_botao(botao, janela.frameGeometry().height())))
