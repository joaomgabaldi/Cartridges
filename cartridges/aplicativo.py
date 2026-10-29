# aplicativo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo`: o que o QML pede ao app (importar) e as preferências que ele acompanha."""

import ctypes
import weakref
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from cartridges import shared
from cartridges.importer.importer import Importer
from cartridges.importer.shortcuts_source import ShortcutsSource
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.utils import soltar_atalhos


def _animacoes_do_sistema() -> bool:
    """"Efeitos de animação" do Windows (SPI_GETCLIENTAREAANIMATION), o que o GTK da `main` seguia."""
    ligado = ctypes.c_int(1)
    if not ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.pointer(ligado), 0):
        return True
    return bool(ligado.value)


class Aplicativo(QObject):
    importandoChanged = Signal()  # noqa: N815
    colunasMaximasChanged = Signal()  # noqa: N815
    tocarSempreChanged = Signal()  # noqa: N815
    # Diálogo de erros da importação: título, corpo e a lista [{titulo, subtitulo}] (texto puro).
    dialogoPedido = Signal(str, str, list)  # noqa: N815

    def __init__(self, avisos: FilaDeAvisos | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos if avisos is not None else FilaDeAvisos(self)
        self._importando = False
        # Posto por `app.py`; a tela de preferências chama `check_async()` nele.
        self.verificador_de_atualizacoes = None
        self._ao_fechar_dialogo: Callable[[], None] | None = None
        self._colunas = shared.schema.get_uint("library-rows")
        self._tocar_sempre = shared.schema.get_boolean("cover-autoplay")
        # shortcut: lido uma vez na abertura; a `main` religava no WM_SETTINGCHANGE. Sai se alguém mudar o ajuste com o app aberto e reclamar.
        self._animacoes_do_sistema = _animacoes_do_sistema()
        # A `Configuracoes` entrega o aviso na thread principal; a referência fraca não prende o objeto.
        eu = weakref.ref(self)
        shared.schema.connect("changed::library-rows", lambda *_: (a := eu()) and a._ler_colunas())
        shared.schema.connect("changed::cover-autoplay", lambda *_: (a := eu()) and a._ler_tocar_sempre())

    def _ler_tocar_sempre(self) -> None:
        tocar = shared.schema.get_boolean("cover-autoplay")
        if tocar != self._tocar_sempre:
            self._tocar_sempre = tocar
            self.tocarSempreChanged.emit()

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

    @Property(bool, notify=tocarSempreChanged)
    def tocarSempre(self) -> bool:  # noqa: N802
        """`cover-autoplay` ("Animar capas"): as capas animadas à vista tocam sem o mouse."""
        return self._tocar_sempre

    @Property(bool, constant=True)
    def animacoesDoSistema(self) -> bool:  # noqa: N802
        """Os efeitos de animação do Windows estão ligados; desligados, nenhuma capa anima."""
        return self._animacoes_do_sistema

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
