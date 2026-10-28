# ponte.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A `Ponte`: leva os sinais dos jogos ao QML."""

import weakref
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal, Slot

from cartridges.jogo import Jogo
from cartridges.utils.thread_principal import eh_thread_principal


class Ponte(QObject):
    """Os textos seguem como texto puro (o QML os mostra em PlainText)."""

    avisoRecebido = Signal(str)
    confirmacaoPedida = Signal(str, str)
    sairDaFrente = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._pendente: Callable[[], Any] | None = None
        self._ligados: dict[str, weakref.ref] = {}

    def ligar(self, jogo: Jogo) -> None:
        """Liga os sinais do jogo, uma vez por jogo. Não prende o jogo nem a ponte."""
        if not eh_thread_principal():
            raise RuntimeError("Ponte.ligar: só na thread principal")
        antigo = self._ligados.get(jogo.game_id)
        if antigo is not None and antigo() is jogo:
            return
        self._ligados[jogo.game_id] = weakref.ref(jogo)
        ponte, ref_jogo = weakref.ref(self), weakref.ref(jogo)

        def aviso(texto: str, _acao: str) -> None:
            # O `aviso` pode sair de uma thread de trabalho; o sinal da ponte, de um
            # QObject da principal, chega enfileirado ao QML.
            if (p := ponte()) is not None:
                p.avisoRecebido.emit(texto)

        def confirmar(lancar: Callable[[], Any]) -> None:
            if (p := ponte()) is not None and (j := ref_jogo()) is not None:
                p._pedir(j, lancar)  # noqa: SLF001

        jogo.aviso.connect(aviso)
        jogo.sair_da_frente.connect(self.sairDaFrente)
        jogo.confirmar_comando.connect(confirmar)

    def _pedir(self, jogo: Jogo, lancar: Callable[[], Any]) -> None:
        self._pendente = lancar
        corpo = (
            "Este jogo foi restaurado de um backup. Antes de iniciá-lo pela primeira vez, "
            f"confira se o comando abaixo é o esperado:\n\n{jogo.comando_visivel}"
        )
        if jogo.run_as_admin:
            corpo += "\n\nO jogo será executado como administrador."
        self.confirmacaoPedida.emit(f"Iniciar {jogo.name}?", corpo)

    @Slot()
    def confirmar(self) -> None:
        lancar, self._pendente = self._pendente, None
        if lancar is not None:
            lancar()

    @Slot()
    def cancelar(self) -> None:
        self._pendente = None
