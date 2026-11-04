# ponte.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A `Ponte`: leva os sinais dos jogos ao QML."""

import weakref
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.utils.thread_principal import eh_thread_principal, na_thread_principal


def _ainda_existe(jogo: Jogo) -> bool:
    loja = shared.store
    return loja is not None and loja.get(jogo.game_id) is jogo and (shared.games_dir / f"{jogo.game_id}.json").exists()


class Ponte(QObject):
    """Os textos seguem como texto puro (o QML os mostra em PlainText)."""

    confirmacaoPedida = Signal(str, str)
    sairDaFrente = Signal()

    def __init__(self, fila: FilaDeAvisos | None = None) -> None:
        super().__init__()
        self.fila = fila if fila is not None else FilaDeAvisos(self)
        self._pendente: Callable[[], Any] | None = None
        self._ligados: "weakref.WeakSet[Jogo]" = weakref.WeakSet()

    def ligar(self, jogo: Jogo) -> None:
        """Liga os sinais do jogo, uma vez por jogo. Não prende o jogo nem a ponte."""
        if not eh_thread_principal():
            raise RuntimeError("Ponte.ligar: só na thread principal")
        if jogo in self._ligados:
            return
        self._ligados.add(jogo)
        ponte, ref_jogo = weakref.ref(self), weakref.ref(jogo)

        def aviso(texto: str, acao: str) -> None:
            # O `aviso` pode sair de uma thread de trabalho; a fila é só da principal.
            if (p := ponte()) is None:
                return
            if eh_thread_principal():
                p._avisar(ref_jogo, texto, acao)  # noqa: SLF001
            else:
                na_thread_principal(p._avisar, ref_jogo, texto, acao)  # noqa: SLF001

        def confirmar(lancar: Callable[[], Any]) -> None:
            if (p := ponte()) is not None and (j := ref_jogo()) is not None:
                p._pedir(j, lancar)  # noqa: SLF001

        jogo.aviso.connect(aviso)
        jogo.sair_da_frente.connect(self.sairDaFrente)
        jogo.confirmar_comando.connect(confirmar)

    def ligar_store(self, store: Any) -> None:
        """`jogo_excluido` sai de threads do importador: a conexão enfileirada leva à principal."""
        store.jogo_excluido.connect(self.dispensar_desfazer, Qt.ConnectionType.QueuedConnection)

    @Slot(str)
    def dispensar_desfazer(self, game_id: str) -> None:
        """Um jogo excluído não tem o que desfazer."""
        self.fila.dispensar_chave((game_id, "remove"))

    def _avisar(self, ref_jogo: "weakref.ref[Jogo]", texto: str, acao: str) -> None:
        if acao != "remove" or (jogo := ref_jogo()) is None:
            self.fila.adicionar(texto)
            return

        def desfazer() -> None:
            # O jogo pode ter saído enquanto o aviso estava na tela: gravar o ressuscitaria.
            if (j := ref_jogo()) is not None and _ainda_existe(j):
                j.removed = False
                j.save()
                j.update()

        self.fila.adicionar(texto, "Desfazer", desfazer, chave=(jogo.game_id, acao))

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
