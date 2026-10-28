# biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modelo da biblioteca: o que o QML enxerga de cada jogo, e as páginas que o filtram.

Um modelo-fonte (`ModeloDaBiblioteca`) guarda uma `Linha` por jogo, sem ordem própria; cada página
(biblioteca, zerados) é um `FiltroDaPagina` sobre ele, que ordena e filtra pelas regras puras de
`ordem.py`. O QML só lê os papéis, nunca um `Jogo`; por isso o modelo guarda fotografias e o
`Jogo` (que pode ter nascido numa thread do importador) só é tocado na thread principal, em
`atualizar` e `iniciar`.
"""

from enum import IntEnum
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QSortFilterProxyModel,
    Qt,
    QUrl,
    Signal,
    Slot,
)

from cartridges import shared
from cartridges.jogo import ANIMATED_SUFFIXES, STATUS_LABELS, Jogo
from cartridges.modelos import ordem
from cartridges.modelos.ordem import Linha
from cartridges.utils import copias_animadas, restauracao

# Como em `configuracoes.py`: `cartridges` não tem `__init__`, a partir deste arquivo.
_PLACEHOLDER = Path(__file__).resolve().parent.parent.parent / "data" / "library_placeholder.svg"


def _pendente(game_id: str) -> bool:
    """Jogo restaurado cujo atalho não foi achado: só existe na janela de pendências."""
    return restauracao.e_pendente(game_id)


def _paginas_de(linha: Linha) -> tuple[str, ...]:
    return (*(() if linha.removido else ("biblioteca",)), *(("zerados",) if linha.zerado else ()))


class ModeloDaBiblioteca(QAbstractListModel):
    class Papel(IntEnum):
        JogoId = Qt.ItemDataRole.UserRole + 1
        Nome = Qt.ItemDataRole.UserRole + 2
        Capa = Qt.ItemDataRole.UserRole + 3
        Zerado = Qt.ItemDataRole.UserRole + 4
        Carregando = Qt.ItemDataRole.UserRole + 5
        CapaAnimada = Qt.ItemDataRole.UserRole + 6

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._linhas: list[Linha] = []
        self._jogos: dict[str, Jogo] = {}
        self._contagem = {"biblioteca": 0, "zerados": 0}
        # Só depois da limpeza da pasta das cópias (`ativar_copias`): ela apaga todo `.tmp`.
        self._copias_ativas = False
        # (jogo, capa) cuja cópia terminou sem sair (capa parada, ilegível, disco): não pede de novo.
        self._sem_copia: set[tuple[str, str]] = set()

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.Papel.JogoId: QByteArray(b"jogoId"),
            self.Papel.Nome: QByteArray(b"nome"),
            self.Papel.Capa: QByteArray(b"capa"),
            self.Papel.Zerado: QByteArray(b"zerado"),
            self.Papel.Carregando: QByteArray(b"carregando"),
            self.Papel.CapaAnimada: QByteArray(b"capaAnimada"),
        }

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008
        return 0 if parent.isValid() else len(self._linhas)

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._linhas):
            return None
        linha = self._linhas[index.row()]
        return {
            self.Papel.JogoId: linha.jogo_id,
            self.Papel.Nome: linha.nome,
            self.Papel.Capa: linha.capa,
            self.Papel.Zerado: linha.zerado,
            self.Papel.Carregando: linha.carregando,
            self.Papel.CapaAnimada: linha.capa_animada,
        }.get(role)

    def linha(self, i: int) -> Linha:
        return self._linhas[i]

    def linhas(self) -> list[Linha]:
        return list(self._linhas)

    def contagem(self, pagina: str) -> int:
        """Quantos jogos a página tem, sem contar filtros."""
        return self._contagem[pagina]

    @Property(str, constant=True)
    def placeholder(self) -> str:
        return QUrl.fromLocalFile(str(_PLACEHOLDER)).toString()

    def _linha_de(self, jogo_id: str) -> int:
        # shortcut: varredura linear, O(n) por jogo; troca por um índice se a importação em massa pesar.
        return next((i for i, linha in enumerate(self._linhas) if linha.jogo_id == jogo_id), -1)

    def _contar(self, linha: Linha, delta: int) -> None:
        for pagina in _paginas_de(linha):
            self._contagem[pagina] += delta

    @Slot(str)
    def retirar(self, game_id: str) -> None:
        """Tira o jogo do modelo. Só na thread principal."""
        if (i := self._linha_de(game_id)) >= 0:
            self.beginRemoveRows(QModelIndex(), i, i)
            self._contar(self._linhas.pop(i), -1)
            self.endRemoveRows()
        self._jogos.pop(game_id, None)

    @Slot(str, str)
    def trocar_id(self, antigo: str, novo: str) -> None:  # noqa: ARG002
        """Um jogo adotado mudou de id: sai a linha do antigo; a do novo entra pelo `atualizar` normal."""
        self.retirar(antigo)

    def ligar_store(self, store: Any) -> None:
        """Os dois sinais saem de threads do importador: a conexão enfileirada leva à principal."""
        store.jogo_excluido.connect(self.retirar, Qt.ConnectionType.QueuedConnection)
        store.capa_trocou_de_id.connect(self.trocar_id, Qt.ConnectionType.QueuedConnection)

    def atualizar(self, jogo: Jogo) -> None:
        """Insere, atualiza ou tira o jogo do modelo. Só na thread principal.

        Ficam os jogos da biblioteca e os zerados (removidos); bloqueados, desinstalados comuns e
        pendentes de restauração saem.
        """
        if jogo.blacklisted or (jogo.removed and not jogo.zerado) or _pendente(jogo.game_id):
            self.retirar(jogo.game_id)
            return
        nova = Linha.de(jogo)
        self._jogos[jogo.game_id] = jogo
        if self._copias_ativas and (caminho := self._capa_animada_sem_copia(nova)):
            copias_animadas.preparar([(jogo.game_id, caminho)])
        if (i := self._linha_de(jogo.game_id)) < 0:
            self.beginInsertRows(QModelIndex(), len(self._linhas), len(self._linhas))
            self._linhas.append(nova)
            self._contar(nova, 1)
            self.endInsertRows()
        elif self._linhas[i] != nova:
            self._contar(self._linhas[i], -1)
            self._linhas[i] = nova
            self._contar(nova, 1)
            self.dataChanged.emit(self.index(i), self.index(i))

    def ativar_copias(self) -> None:
        """Libera o pedido das cópias animadas (a pasta já foi limpa) e pede as que faltam. Só na principal."""
        self._copias_ativas = True
        copias_animadas.ao_terminar_copia = self.copia_terminou
        capas = [(linha.jogo_id, caminho) for linha in self._linhas if (caminho := self._capa_animada_sem_copia(linha))]
        if capas:
            copias_animadas.preparar(capas)

    def _capa_animada_sem_copia(self, linha: Linha) -> Path | None:
        """O arquivo da capa, se ela é animada e a cópia da grade falta (e não falhou antes)."""
        if linha.capa_animada or (linha.jogo_id, linha.capa) in self._sem_copia:
            return None
        jogo = self._jogos.get(linha.jogo_id)
        caminho = jogo.get_cover_path() if jogo is not None else None
        return caminho if caminho is not None and caminho.suffix in ANIMATED_SUFFIXES else None

    def copia_terminou(self, game_id: str, resultado: str) -> None:
        """Uma cópia ficou pronta (ou não saiu): atualiza a linha. Só na thread principal."""
        jogo = self._jogos.get(game_id)
        if jogo is None:
            return
        if resultado != "pronta" and (i := self._linha_de(game_id)) >= 0:
            self._sem_copia.add((game_id, self._linhas[i].capa))
        self.atualizar(jogo)

    @Slot(str)
    def iniciar(self, jogoId: str) -> None:  # noqa: N803
        if (jogo := self._jogos.get(jogoId)) is not None:
            jogo.launch()

    @Slot(str)
    def remover(self, jogoId: str) -> None:  # noqa: N803
        """"Remover" do menu do jogo: o aviso com "Desfazer" sai do próprio `remove_game`."""
        if (jogo := self._jogos.get(jogoId)) is not None:
            jogo.remove_game()


class FiltrosDaBiblioteca(QObject):
    """Gênero, ano, status e modo de ordenação: um só estado para as duas páginas, só da sessão."""

    STATUS = [{"rotulo": rotulo, "valor": valor} for valor, rotulo in STATUS_LABELS.items()]  # noqa: RUF012

    generoChanged = Signal()  # noqa: N815
    anoChanged = Signal()  # noqa: N815
    statusChanged = Signal()  # noqa: N815
    modoChanged = Signal()  # noqa: N815
    opcoesChanged = Signal()  # noqa: N815

    def __init__(self, fonte: ModeloDaBiblioteca, parent: Any = None) -> None:
        super().__init__(parent)
        self._fonte = fonte
        self._genero = self._ano = self._status = ""
        # Lido uma vez: a ordenação compara milhares de pares, e cada leitura vai ao registro.
        self._modo = shared.state_schema.get_string("sort-mode")
        self._generos: list[str] = []
        self._anos: list[str] = []
        self.recalcularOpcoes()

    @Property(str, notify=generoChanged)
    def genero(self) -> str:
        return self._genero

    @genero.setter
    def genero(self, valor: str) -> None:
        if valor != self._genero:
            self._genero = valor
            self.generoChanged.emit()

    @Property(str, notify=anoChanged)
    def ano(self) -> str:
        return self._ano

    @ano.setter
    def ano(self, valor: str) -> None:
        if valor != self._ano:
            self._ano = valor
            self.anoChanged.emit()

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @status.setter
    def status(self, valor: str) -> None:
        if valor != self._status:
            self._status = valor
            self.statusChanged.emit()

    @Property(str, notify=modoChanged)
    def modo(self) -> str:
        return self._modo

    @modo.setter
    def modo(self, valor: str) -> None:
        if valor != self._modo:
            self._modo = valor
            shared.state_schema.set_string("sort-mode", valor)
            self.modoChanged.emit()

    @Property("QVariantList", notify=opcoesChanged)
    def generos(self) -> list[str]:
        return self._generos

    @Property("QVariantList", notify=opcoesChanged)
    def anos(self) -> list[str]:
        return self._anos

    @Property("QVariantList", constant=True)
    def opcoesDeStatus(self) -> list[dict[str, str]]:  # noqa: N802
        return self.STATUS

    @Slot()
    def limpar(self) -> None:
        self.genero = self.ano = self.status = ""

    @Slot()
    def recalcularOpcoes(self) -> None:  # noqa: N802
        """Refeito ao abrir o menu, não a cada mudança: um import em andamento o mexeria sem ninguém olhar."""
        self._generos, self._anos = ordem.opcoes(self._fonte.linhas())
        # Um valor escolhido que saiu da biblioteca deixaria a grade vazia, apontando para uma opção que o menu nem oferece.
        if self._genero and self._genero not in self._generos:
            self.genero = ""
        if self._ano and self._ano not in self._anos:
            self.ano = ""
        self.opcoesChanged.emit()


class FiltroDaPagina(QSortFilterProxyModel):
    """Uma página (biblioteca ou zerados) sobre o modelo-fonte: ordem, filtros e busca."""

    buscaChanged = Signal()  # noqa: N815
    vaziaChanged = Signal()  # noqa: N815
    semResultadosChanged = Signal()  # noqa: N815

    def __init__(
        self,
        fonte: ModeloDaBiblioteca,
        filtros: FiltrosDaBiblioteca,
        pagina: Literal["biblioteca", "zerados"],
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self._fonte = fonte
        self._filtros = filtros
        self._pagina = pagina
        self._busca = ""
        self._vazia = True
        self._sem_resultados = False
        self.setSourceModel(fonte)
        self.setDynamicSortFilter(True)
        self.sort(0)
        filtros.generoChanged.connect(self._refiltrar)
        filtros.anoChanged.connect(self._refiltrar)
        filtros.statusChanged.connect(self._refiltrar)
        filtros.modoChanged.connect(self.invalidate)
        for sinal in (
            fonte.rowsInserted, fonte.rowsRemoved, fonte.modelReset, fonte.dataChanged,
            self.rowsInserted, self.rowsRemoved, self.modelReset, self.layoutChanged,
        ):  # fmt: skip
            sinal.connect(self._reavaliar)
        self._reavaliar()

    def _refiltrar(self) -> None:
        self.beginFilterChange()  # invalidateFilter() está obsoleto desde o Qt 6.10
        self.endFilterChange()

    def _reavaliar(self) -> None:
        vazia = self._fonte.contagem(self._pagina) == 0
        sem_resultados = not vazia and self.rowCount() == 0
        if vazia != self._vazia:
            self._vazia = vazia
            self.vaziaChanged.emit()
        if sem_resultados != self._sem_resultados:
            self._sem_resultados = sem_resultados
            self.semResultadosChanged.emit()

    @Property(str, notify=buscaChanged)
    def busca(self) -> str:
        return self._busca

    @busca.setter
    def busca(self, valor: str) -> None:
        if valor != self._busca:
            self._busca = valor
            self._refiltrar()
            self.buscaChanged.emit()

    @Property(bool, notify=vaziaChanged)
    def vazia(self) -> bool:
        return self._vazia

    @Property(bool, notify=semResultadosChanged)
    def semResultados(self) -> bool:  # noqa: N802
        return self._sem_resultados

    @Property(str, constant=True)
    def placeholder(self) -> str:
        return self._fonte.placeholder

    @Slot(result=str)
    def primeiro(self) -> str:
        """O `jogoId` da primeira linha, para o Enter da busca."""
        return self.data(self.index(0, 0), ModeloDaBiblioteca.Papel.JogoId) or ""

    @Slot(str)
    def iniciar(self, jogoId: str) -> None:  # noqa: N803
        self._fonte.iniciar(jogoId)

    @Slot(str)
    def remover(self, jogoId: str) -> None:  # noqa: N803
        self._fonte.remover(jogoId)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:  # noqa: ARG002, N802
        linha = self._fonte.linha(source_row)
        if self._pagina == "zerados":
            if not linha.zerado:
                return False
            busca = ""  # a busca é só da biblioteca
        else:
            if linha.removido:
                return False
            busca = self._busca
        return ordem.passa(linha, busca, self._filtros.genero, self._filtros.ano, self._filtros.status)

    def lessThan(self, source_left: QModelIndex | QPersistentModelIndex, source_right: QModelIndex | QPersistentModelIndex) -> bool:  # noqa: N802
        modo = self._filtros.modo
        return ordem.chave(self._fonte.linha(source_left.row()), modo) < ordem.chave(self._fonte.linha(source_right.row()), modo)
