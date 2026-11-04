# restaurando.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A janela da abertura enquanto um backup agendado é restaurado.

Sem ela, um backup grande deixava o app minutos sem nenhuma janela, parecendo que não tinha aberto. Mostra o andamento
e não fecha: a restauração foi pedida e confirmada nas Preferências, e no fim o app abre sozinho (`app.main`).
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot


def entregar_so_ao_mudar(entregar: Callable[[float], Any]) -> Callable[[float], None]:
    """Embrulha ``entregar`` (a entrega à tela, chamada pela thread de trabalho) para só passar adiante quando a
    porcentagem inteira muda: o trabalho avisa a cada pedaço de 1 MB e a cada arquivo pequeno, e cada entrega agendada
    custa uma volta do laço de eventos."""
    ultima = -1

    def avancar(fracao: float) -> None:
        nonlocal ultima
        porcentagem = int(fracao * 100)
        if porcentagem != ultima:
            ultima = porcentagem
            entregar(fracao)

    return avancar


class Restaurando(QObject):
    """O contexto `restaurando` do motor da janela: o andamento e se ela já pode fechar."""

    alterado = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._porcentagem = 0
        self._pode_fechar = False

    @Property(float, notify=alterado)
    def fracao(self) -> float:
        return self._porcentagem / 100

    @Property(str, notify=alterado)
    def porcentagem(self) -> str:
        return f"{self._porcentagem}%"

    @Property(bool, notify=alterado)
    def podeFechar(self) -> bool:  # noqa: N802
        return self._pode_fechar

    @Slot(float)
    def avancar(self, fracao: float) -> None:
        """A fração restaurada (0 a 1). Só redesenha quando a porcentagem inteira muda."""
        porcentagem = int(fracao * 100)
        if porcentagem != self._porcentagem:
            self._porcentagem = porcentagem
            self.alterado.emit()

    @Slot()
    def terminar(self) -> None:
        """Daqui em diante a janela aceita fechar (quem a fecha é o `app`)."""
        if not self._pode_fechar:
            self._pode_fechar = True
            self.alterado.emit()
