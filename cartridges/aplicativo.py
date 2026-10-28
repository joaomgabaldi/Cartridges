# aplicativo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo`: o que o QML pede ao app (importar) e as preferências que ele acompanha."""

import weakref
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from cartridges import shared
from cartridges.importer.importer import Importer
from cartridges.importer.shortcuts_source import ShortcutsSource
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.utils import soltar_atalhos


class Aplicativo(QObject):
    importandoChanged = Signal()  # noqa: N815
    colunasMaximasChanged = Signal()  # noqa: N815
    # Diálogo de erros da importação: título, corpo e a lista [{titulo, subtitulo}] (texto puro).
    dialogoPedido = Signal(str, str, list)  # noqa: N815

    def __init__(self, avisos: FilaDeAvisos | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos if avisos is not None else FilaDeAvisos(self)
        self._importando = False
        self._ao_fechar_dialogo: Callable[[], None] | None = None
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

    def definir_importando(self, importando: bool) -> None:
        if importando != self._importando:
            self._importando = importando
            self.importandoChanged.emit()

    @Slot()
    def importar(
        self,
        silenciosa: bool = False,
        varrer_atalhos: bool = False,
        ao_terminar: Callable[[], None] | None = None,
    ) -> None:
        """``varrer_atalhos`` varre a pasta de atalhos mesmo com a fonte desligada em Preferências.

        ``silenciosa``: a importação que o próprio app dispara não avisa quando nada é achado;
        a que o usuário pede avisa sempre, senão o clique parece não ter funcionado.
        """
        if self._importando:
            return
        importador = shared.importer = Importer(self)
        importador.ao_terminar = ao_terminar
        importador.silenciosa = silenciosa
        if varrer_atalhos or shared.schema.get_boolean("shortcuts"):
            importador.add_source(ShortcutsSource())
        importador.run()

    def pedir_dialogo(self, titulo: str, corpo: str, itens: list, ao_fechar: Callable[[], None]) -> None:
        self._ao_fechar_dialogo = ao_fechar
        self.dialogoPedido.emit(titulo, corpo, itens)

    @Slot()
    def dialogoFechado(self) -> None:  # noqa: N802
        ao_fechar, self._ao_fechar_dialogo = self._ao_fechar_dialogo, None
        if ao_fechar is not None:
            ao_fechar()

    @Slot("QVariantList")
    def soltar(self, urls: list) -> None:
        """Atalhos arrastados para a janela: copia para a pasta de atalhos e importa."""
        caminhos = []
        for url in urls:
            url = url if isinstance(url, QUrl) else QUrl(str(url))
            # Um arquivo sem caminho local (de rede, de um celular) fica de fora.
            caminhos.append(Path(url.toLocalFile()) if url.isLocalFile() else None)
        textos, importar = soltar_atalhos.ao_soltar(caminhos, self._importando)
        if importar:
            # A varredura leva alguns segundos e só avisa no fim; até lá, este fica na tela.
            # Os outros avisos esperam atrás dele, na fila.
            aguarde = self._avisos.adicionar("Importando atalhos…", segundos=0)
            self.importar(varrer_atalhos=True, ao_terminar=lambda: self._avisos.dispensar(aguarde))
        for texto in textos:
            self._avisos.adicionar(texto)
