# aplicativo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo`: o que o QML pede ao app (importar) e as preferências que ele acompanha."""

import ctypes
import weakref
from collections import deque
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Property, QCoreApplication, QObject, QUrl, Signal, Slot

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
    # A pergunta do domínio (D72): título, corpo, rótulo de confirmar, rótulo de sair e se é destrutiva.
    confirmacaoPedida = Signal(str, str, str, str, bool)  # noqa: N815
    animacoesDoSistemaChanged = Signal()  # noqa: N815

    def __init__(self, avisos: FilaDeAvisos | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos if avisos is not None else FilaDeAvisos(self)
        self._importando = False
        # Posto por `app.py`; a tela de preferências chama `check_async()` nele.
        self.verificador_de_atualizacoes = None
        # Posta por `app.py` depois das outras varreduras; a edição e a importação a chamam.
        self.varredura_conquistas = None
        # Lida pelo `main()` depois do `exec()`: o app sai e se reabre (D75).
        self.reiniciar = False
        self._ao_fechar_dialogo: Callable[[], None] | None = None
        # D72: uma fila FIFO só para os dois tipos de pedido; o da vez está na tela ("dialogo" ou
        # "confirmacao") e o resto espera a resposta dele. Assim só o de cima recebe o teclado.
        self._fila: deque[tuple[str, tuple]] = deque()
        self._na_tela: str | None = None
        self._ao_responder: Callable[[bool], None] | None = None
        # Página das Preferências que o diálogo oferece; None = sem o botão, "" = abre sem página.
        self._preferencias_do_dialogo: str | None = None
        self._colunas = shared.schema.get_uint("library-rows")
        self._tocar_sempre = shared.schema.get_boolean("cover-autoplay")
        # Relido a cada `WM_SETTINGCHANGE` (`reler_animacoes`, D88), como a `main`.
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

    @Property(bool, notify=animacoesDoSistemaChanged)
    def animacoesDoSistema(self) -> bool:  # noqa: N802
        """Os efeitos de animação do Windows estão ligados; desligados, nenhuma capa anima."""
        return self._animacoes_do_sistema

    def reler_animacoes(self) -> None:
        """Relê o ajuste do Windows (um `WM_SETTINGCHANGE` chegou) e avisa só se mudou."""
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

    @Property(bool, notify=dialogoPedido)
    def dialogoComPreferencias(self) -> bool:  # noqa: N802
        """O diálogo pedido oferece o botão "Preferências"."""
        return self._preferencias_do_dialogo is not None

    def pedir_dialogo(
        self,
        titulo: str,
        corpo: str,
        itens: list,
        ao_fechar: Callable[[], None],
        preferencias: str | None = None,
    ) -> None:
        """``preferencias``: a página que o botão "Preferências" abre (``""`` = a primeira); None = sem o botão.

        Com outro diálogo na tela, este espera o fim dele (D72).
        """
        self._fila.append(("dialogo", (titulo, corpo, itens, ao_fechar, preferencias)))
        self._mostrar_proximo()

    def _mostrar_proximo(self) -> None:
        if self._na_tela is not None or not self._fila:
            return
        tipo, pedido = self._fila.popleft()
        self._na_tela = tipo
        if tipo == "dialogo":
            titulo, corpo, itens, self._ao_fechar_dialogo, self._preferencias_do_dialogo = pedido
            self.dialogoPedido.emit(titulo, corpo, itens)
        else:
            titulo, corpo, rotulo, self._ao_responder, destrutivo = pedido
            self.confirmacaoPedida.emit(titulo, corpo, rotulo, "Cancelar" if destrutivo else "Dispensar", destrutivo)

    def pedir_confirmacao(
        self,
        titulo: str,
        corpo: str,
        rotulo: str,
        ao_responder: Callable[[bool], None],
        destrutivo: bool = False,
    ) -> None:
        """Pergunta com dois botões; ``ao_responder(True)`` se confirmou, ``False`` se saiu (Esc, X ou o botão de sair).

        O botão de sair é "Cancelar" se ``destrutivo``, senão "Dispensar" (a regra do `create_dialog`).
        Um pedido com outra confirmação na tela espera a resposta dela (D72).
        """
        self._fila.append(("confirmacao", (titulo, corpo, rotulo, ao_responder, destrutivo)))
        self._mostrar_proximo()

    @Slot(bool)
    def confirmacaoRespondida(self, confirmou: bool) -> None:  # noqa: N802
        if self._na_tela != "confirmacao":
            return
        ao_responder, self._ao_responder = self._ao_responder, None
        try:
            ao_responder(confirmou)
        finally:
            # Depois do callback: um pedido feito dentro dele fica atrás dos que já esperavam.
            self._na_tela = None
            self._mostrar_proximo()

    @Slot(bool)
    @Slot()
    def dialogoFechado(self, abrir_preferencias: bool = False) -> None:  # noqa: N802
        """``abrir_preferencias``: foi o botão "Preferências"; ``ao_fechar`` espera a tela fechar, se ela abriu."""
        if self._na_tela != "dialogo":
            return
        ao_fechar, self._ao_fechar_dialogo = self._ao_fechar_dialogo, None
        pagina, self._preferencias_do_dialogo = self._preferencias_do_dialogo, None
        try:
            self._ao_fechar_o_dialogo(ao_fechar, pagina, abrir_preferencias)
        finally:
            self._na_tela = None
            self._mostrar_proximo()

    def _ao_fechar_o_dialogo(self, ao_fechar: Callable[[], None] | None, pagina: str | None, abrir_preferencias: bool) -> None:
        if ao_fechar is None:
            return
        preferencias = shared.preferencias
        if abrir_preferencias and pagina is not None and preferencias is not None and preferencias.abrir(pagina):
            # Como o `closed` da `main`: uma vez só, quando as Preferências fecham.
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
        """Um aviso simples na fila do app (o QML não alcança a `FilaDeAvisos.adicionar`)."""
        self._avisos.adicionar(texto)

    @Slot()
    def pedir_reinicio(self) -> None:
        """Sai do app e o reabre: o `main()` solta a trava e chama o `relancar()` depois do `exec()` (D75).

        O `quit()`, e não o `exit()`: o fechamento passa pelo `saindo` e pelo `aboutToQuit` inteiros, e o `closing` da
        principal não o recusa (`PainelDasTarefas.encerrando`).
        """
        self.reiniciar = True
        QCoreApplication.quit()

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
