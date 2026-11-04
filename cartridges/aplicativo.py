# aplicativo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo`: o que o QML pede ao app (importar) e as preferências que ele acompanha."""

import ctypes
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QCoreApplication, QObject, QUrl, Signal, Slot

from cartridges import shared
from cartridges.importer.importer import Importer
from cartridges.importer.shortcuts_source import ShortcutsSource
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.utils import soltar_atalhos


@dataclass(eq=False)
class _Pedido:
    """Um diálogo pedido pelo domínio: "dialogo" (`dialogoPedido`) ou "confirmacao" (`confirmacaoPedida`)."""

    tipo: str
    sinal: tuple
    resposta: Callable[..., None]
    preferencias: Any = None


def _animacoes_do_sistema() -> bool:
    ligado = ctypes.c_int(1)
    if not ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.pointer(ligado), 0):
        return True
    return bool(ligado.value)


class Aplicativo(QObject):
    importandoChanged = Signal()  # noqa: N815
    colunasMaximasChanged = Signal()  # noqa: N815
    tocarSempreChanged = Signal()  # noqa: N815
    dialogoPedido = Signal(str, str, list)  # noqa: N815
    confirmacaoPedida = Signal(str, str, str, str, bool)  # noqa: N815
    animacoesDoSistemaChanged = Signal()  # noqa: N815

    def __init__(self, avisos: FilaDeAvisos | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos if avisos is not None else FilaDeAvisos(self)
        self._importando = False
        self.verificador_de_atualizacoes = None
        self.varredura_conquistas = None
        self.reiniciar = False
        self._pilha: list[_Pedido] = []
        self._na_tela: dict[str, _Pedido | None] = {"dialogo": None, "confirmacao": None}
        self._colunas = shared.schema.get_uint("library-rows")
        self._tocar_sempre = shared.schema.get_boolean("cover-autoplay")
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
        return self._avisos

    @Property(bool, notify=importandoChanged)
    def importando(self) -> bool:
        return self._importando

    @Property(int, notify=colunasMaximasChanged)
    def colunasMaximas(self) -> int:  # noqa: N802
        return self._colunas

    @Property(bool, notify=tocarSempreChanged)
    def tocarSempre(self) -> bool:  # noqa: N802
        return self._tocar_sempre

    @Property(bool, notify=animacoesDoSistemaChanged)
    def animacoesDoSistema(self) -> bool:  # noqa: N802
        return self._animacoes_do_sistema

    def reler_animacoes(self) -> None:
        ligadas = _animacoes_do_sistema()
        if ligadas != self._animacoes_do_sistema:
            self._animacoes_do_sistema = ligadas
            self.animacoesDoSistemaChanged.emit()

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
        """``silenciosa``: a importação disparada pelo app não avisa quando nada é achado; a pedida pelo usuário avisa
        sempre.
        """
        if self._importando:
            atual = shared.importer
            if ao_terminar is not None and atual is not None:
                anterior = atual.ao_terminar

                def encadeado() -> None:
                    if anterior is not None:
                        anterior()
                    ao_terminar()

                atual.ao_terminar = encadeado
            return
        importador = shared.importer = Importer(self)
        importador.ao_terminar = ao_terminar
        importador.silenciosa = silenciosa
        if varrer_atalhos or shared.schema.get_boolean("shortcuts"):
            importador.add_source(ShortcutsSource())
        importador.run()

    @Property(bool, notify=dialogoPedido)
    def dialogoComPreferencias(self) -> bool:  # noqa: N802
        pedido = self._na_tela["dialogo"]
        return pedido is not None and pedido.preferencias is not None

    def pedir_dialogo(
        self,
        titulo: str,
        corpo: str,
        itens: list,
        ao_fechar: Callable[[], None],
        preferencias: str | None = None,
    ) -> None:
        """``preferencias``: página que o botão "Preferências" abre (``""`` = a primeira); None = sem o botão."""
        self._empilhar(_Pedido("dialogo", (titulo, corpo, itens), ao_fechar, preferencias))

    def _empilhar(self, pedido: _Pedido) -> None:
        self._pilha.append(pedido)
        self._mostrar(pedido)

    def _mostrar(self, pedido: _Pedido) -> None:
        self._na_tela[pedido.tipo] = pedido
        (self.dialogoPedido if pedido.tipo == "dialogo" else self.confirmacaoPedida).emit(*pedido.sinal)

    def _tirar_do_topo(self, tipo: str) -> _Pedido | None:
        if not self._pilha or self._pilha[-1].tipo != tipo:
            return None
        pedido = self._pilha.pop()
        self._na_tela[tipo] = None
        return pedido

    def _mostrar_o_topo(self) -> None:
        if self._pilha and self._na_tela[self._pilha[-1].tipo] is not self._pilha[-1]:
            self._mostrar(self._pilha[-1])

    def pedir_confirmacao(
        self,
        titulo: str,
        corpo: str,
        rotulo: str,
        ao_responder: Callable[[bool], None],
        destrutivo: bool = False,
    ) -> None:
        """Pergunta com dois botões; ``ao_responder(True)`` se confirmou, ``False`` se saiu."""
        sair = "Cancelar" if destrutivo else "Dispensar"
        self._empilhar(_Pedido("confirmacao", (titulo, corpo, rotulo, sair, destrutivo), ao_responder))

    @Slot(bool)
    def confirmacaoRespondida(self, confirmou: bool) -> None:  # noqa: N802
        pedido = self._tirar_do_topo("confirmacao")
        if pedido is None:
            return
        try:
            pedido.resposta(confirmou)
        finally:
            self._mostrar_o_topo()

    @Slot(bool)
    @Slot()
    def dialogoFechado(self, abrir_preferencias: bool = False) -> None:  # noqa: N802
        """``abrir_preferencias``: foi o botão "Preferências"; ``ao_fechar`` espera a tela fechar, se ela abriu."""
        pedido = self._tirar_do_topo("dialogo")
        if pedido is None:
            return
        try:
            self._ao_fechar_o_dialogo(pedido.resposta, pedido.preferencias, abrir_preferencias)
        finally:
            self._mostrar_o_topo()

    def _ao_fechar_o_dialogo(self, ao_fechar: Callable[[], None] | None, pagina: str | None, abrir_preferencias: bool) -> None:
        if ao_fechar is None:
            return
        preferencias = shared.preferencias
        if abrir_preferencias and pagina is not None and preferencias is not None and preferencias.abrir(pagina):
            ligacao: list = []
            fraco = weakref.ref(preferencias)  # a conexão vive no próprio objeto: referência forte formaria um ciclo

            def fechou() -> None:
                p = fraco()
                if p is not None and not p.aberto:
                    p.alterado.disconnect(ligacao[0])
                    ao_fechar()

            ligacao.append(preferencias.alterado.connect(fechou))
        else:
            ao_fechar()

    @Slot(str)
    def avisar(self, texto: str) -> None:
        self._avisos.adicionar(texto)

    @Slot()
    def pedir_reinicio(self) -> None:
        self.reiniciar = True
        QCoreApplication.quit()

    @Slot("QVariantList")
    def soltar(self, urls: list) -> None:
        caminhos = []
        for url in urls:
            url = url if isinstance(url, QUrl) else QUrl(str(url))
            caminhos.append(Path(url.toLocalFile()) if url.isLocalFile() else None)
        textos, importar = soltar_atalhos.ao_soltar(caminhos, self._importando)
        if importar:
            aguarde = self._avisos.adicionar("Importando atalhos…", segundos=0)
            self.importar(varrer_atalhos=True, ao_terminar=lambda: self._avisos.dispensar(aguarde))
        for texto in textos:
            self._avisos.adicionar(texto)
