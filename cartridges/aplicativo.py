# aplicativo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo`: o que o QML pede ao app (importar) e as preferências que ele acompanha."""

import logging
import weakref

from PySide6.QtCore import Property, QObject, Signal, Slot

from cartridges import shared
from cartridges.modelos.avisos import FilaDeAvisos


class Aplicativo(QObject):
    importandoChanged = Signal()  # noqa: N815
    colunasMaximasChanged = Signal()  # noqa: N815

    def __init__(self, avisos: FilaDeAvisos | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos if avisos is not None else FilaDeAvisos(self)
        self._importando = False
        self._colunas = shared.schema.get_uint("library-rows")
        # A `Configuracoes` entrega o aviso na thread principal; a referência fraca não prende o objeto.
        eu = weakref.ref(self)
        shared.schema.connect("changed::library-rows", lambda *_: (a := eu()) and a._ler_colunas())

    def _ler_colunas(self) -> None:
        colunas = shared.schema.get_uint("library-rows")
        if colunas != self._colunas:
            self._colunas = colunas
            self.colunasMaximasChanged.emit()

    @Property(QObject, constant=True)
    def avisos(self) -> FilaDeAvisos:
        """A fila única de avisos do app (a mesma da `Ponte`)."""
        return self._avisos

    @Property(bool, notify=importandoChanged)
    def importando(self) -> bool:
        return self._importando

    @Property(int, notify=colunasMaximasChanged)
    def colunasMaximas(self) -> int:  # noqa: N802
        """`library-rows`: 0 deixa as colunas acompanharem a largura da janela."""
        return self._colunas

    @Slot()
    def importar(self) -> None:
        # shortcut: só registra no log, a Task 6 do plano 2 implementa a importação.
        logging.info("Importar: ainda não implementado")
