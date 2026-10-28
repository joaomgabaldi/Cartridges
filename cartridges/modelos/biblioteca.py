# biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Modelo da grade da biblioteca: o que o QML enxerga de cada jogo.

O QML só lê os papéis (`jogoId`, `nome`, `capa`, `zerado`), nunca um `Jogo`; por isso o
modelo guarda uma fotografia por linha e o `Jogo` (que pode ter nascido numa thread do
importador) só é tocado na thread principal, em `atualizar` e `iniciar`.
"""

import bisect
from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QPersistentModelIndex,
    Qt,
    QUrl,
    Slot,
)

from cartridges.jogo import Jogo

# Como em `configuracoes.py`: `cartridges` não tem `__init__`, a partir deste arquivo.
_PLACEHOLDER = Path(__file__).resolve().parent.parent.parent / "data" / "library_placeholder.svg"


@dataclass
class _Linha:
    chave: tuple[str, str]
    jogo_id: str
    nome: str
    capa: str
    zerado: bool


class ModeloDaBiblioteca(QAbstractListModel):
    class Papel(IntEnum):
        JogoId = Qt.ItemDataRole.UserRole + 1
        Nome = Qt.ItemDataRole.UserRole + 2
        Capa = Qt.ItemDataRole.UserRole + 3
        Zerado = Qt.ItemDataRole.UserRole + 4

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._linhas: list[_Linha] = []
        self._jogos: dict[str, Jogo] = {}

    def roleNames(self) -> dict[int, QByteArray]:
        return {
            self.Papel.JogoId: QByteArray(b"jogoId"),
            self.Papel.Nome: QByteArray(b"nome"),
            self.Papel.Capa: QByteArray(b"capa"),
            self.Papel.Zerado: QByteArray(b"zerado"),
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
        }.get(role)

    @Property(str, constant=True)
    def placeholder(self) -> str:
        return QUrl.fromLocalFile(str(_PLACEHOLDER)).toString()

    def _linha_de(self, jogo_id: str) -> int:
        # Por id, e não pela chave: o nome pode ter mudado desde que a linha entrou.
        return next((i for i, linha in enumerate(self._linhas) if linha.jogo_id == jogo_id), -1)

    def atualizar(self, jogo: Jogo) -> None:
        """Insere, atualiza ou tira o jogo da grade. Só na thread principal."""
        antiga = self._linha_de(jogo.game_id)
        if jogo.removed or jogo.blacklisted:
            if antiga >= 0:
                self.beginRemoveRows(QModelIndex(), antiga, antiga)
                del self._linhas[antiga]
                self.endRemoveRows()
            self._jogos.pop(jogo.game_id, None)
            return

        capa = jogo.get_cover_path()
        nova = _Linha(
            (jogo.name.casefold(), jogo.game_id),
            jogo.game_id,
            jogo.name,
            QUrl.fromLocalFile(str(capa)).toString() if capa else "",
            jogo.zerado,
        )
        self._jogos[jogo.game_id] = jogo
        if antiga >= 0:
            sem_antiga = self._linhas[:antiga] + self._linhas[antiga + 1 :]
            if bisect.bisect_left(sem_antiga, nova.chave, key=lambda linha: linha.chave) == antiga:
                self._linhas[antiga] = nova  # continua no mesmo lugar
                indice = self.index(antiga)
                self.dataChanged.emit(indice, indice)
                return
            self.beginRemoveRows(QModelIndex(), antiga, antiga)
            del self._linhas[antiga]
            self.endRemoveRows()
        i = bisect.bisect_left(self._linhas, nova.chave, key=lambda linha: linha.chave)
        self.beginInsertRows(QModelIndex(), i, i)
        self._linhas.insert(i, nova)
        self.endInsertRows()

    @Slot(str)
    def iniciar(self, jogoId: str) -> None:  # noqa: N803
        if (jogo := self._jogos.get(jogoId)) is not None:
            jogo.launch()
