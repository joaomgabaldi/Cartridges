# big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que a tela do Big Picture lê: a lista de jogos, o jogo central e o fundo.

`BigPicture` segue o `ModeloDaBiblioteca` (a mesma lista que a grade mostra, ordenada do jogado
mais recentemente ao mais antigo) e guarda o índice do jogo central; o QML só lê as propriedades e
chama os slots de navegação. `ProvedorDoFundo` entrega o degradê pontilhado em pixels reais.
"""

import logging
import weakref

from PySide6.QtCore import Property, QModelIndex, QObject, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QWindow
from PySide6.QtQuick import QQuickImageProvider, QSGRendererInterface

from cartridges import shared
from cartridges.modelos import regras_do_big_picture as regras
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.modelos.ordem import Linha

_SO_CAPA = {ModeloDaBiblioteca.Papel.Capa, ModeloDaBiblioteca.Papel.CapaAnimada}


class ProvedorDoFundo(QQuickImageProvider):
    """`image://fundo/LxA`: o degradê pontilhado no tamanho em pixels reais."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id_: str, size: QSize, requested_size: QSize) -> QImage:  # noqa: ARG002, N802
        try:
            largura, altura = (max(1, int(v)) for v in id_.split("x"))
            dados = regras.bytes_do_fundo(largura, altura)  # vivo até o .copy(): o QImage não copia
            imagem = QImage(dados, largura, altura, largura * 3, QImage.Format.Format_RGB888).copy()
        except Exception:
            logging.warning("Falha ao gerar o fundo do Big Picture", exc_info=True)
            imagem = QImage(1, 1, QImage.Format.Format_RGB888)
            imagem.fill(QColor("black"))
        size.setWidth(imagem.width())
        size.setHeight(imagem.height())
        return imagem


def tem_3d(janela: QWindow) -> bool:
    """Sem renderizador, ou com o de software, o Cover Flow não roda bem."""
    renderizador = janela.rendererInterface()
    return renderizador is not None and renderizador.graphicsApi() != QSGRendererInterface.GraphicsApi.Software


def _dados(linha: Linha) -> dict[str, str]:
    return {
        "jogoId": linha.jogo_id,
        "nome": linha.nome,
        "desenvolvedora": linha.desenvolvedora,
        "capa": linha.capa,
        "capaAnimada": linha.capa_animada,
    }


class BigPicture(QObject):
    """A lista do Big Picture e o jogo central. Só na thread principal."""

    alterado = Signal()  # índice, rótulos, vazia, ocupada
    jogosMudaram = Signal()  # noqa: N815  # só a lista (um passo do carrossel não a notifica)
    animarCentralMudou = Signal()  # noqa: N815
    filaPedida = Signal(bool)  # noqa: N815  # True: a fila de entrada; False: a de saída (o QML a anima)
    saiu = Signal(str)  # o jogo central na saída: o foco volta ao cartão dele na grade

    def __init__(
        self, modelo: ModeloDaBiblioteca, parent: QObject | None = None, *, animacoes_do_sistema: bool = True
    ) -> None:
        super().__init__(parent)
        # shortcut: as animações do Windows são lidas uma vez pelo `Aplicativo`; sai junto com a releitura dele.
        self._animacoes_do_sistema = animacoes_do_sistema
        self._animar_central = self._ler_animar_central()
        eu = weakref.ref(self)
        shared.schema.connect("changed::cover-autoplay", lambda *_: (b := eu()) and b._religar_animar_central())
        self._modelo = modelo
        self._carrossel = regras.Carrossel([])
        self._jogos: list[dict[str, str]] = []
        self._agendado = False
        self._ocupada = False  # a fila de entrada e saída
        self._visivel = False
        self._saindo = False
        self._ja_saiu = False
        self._disponivel = True
        self._janela: QWindow | None = None
        self._estava_maximizada = False
        self._pendente = False
        self._centro_pendente = ""
        modelo.rowsInserted.connect(self._agendar)
        modelo.rowsRemoved.connect(self._agendar)
        modelo.modelReset.connect(self._agendar)
        modelo.dataChanged.connect(self._dados_mudaram)

    # --- propriedades ---
    @Property("QVariantList", notify=jogosMudaram)
    def jogos(self) -> list[dict[str, str]]:
        return self._jogos

    @Property(int, notify=alterado)
    def indice(self) -> int:
        return self._carrossel.indice

    def _central(self) -> dict[str, str] | None:
        return self._jogos[self._carrossel.indice] if self._jogos else None

    @Property(str, notify=alterado)
    def nome(self) -> str:
        return (self._central() or {}).get("nome", "")

    @Property(str, notify=alterado)
    def desenvolvedora(self) -> str:
        return (self._central() or {}).get("desenvolvedora", "")

    @Property(bool, notify=alterado)
    def vazia(self) -> bool:
        return not self._jogos

    @Property(bool, notify=alterado)
    def ocupada(self) -> bool:
        return self._ocupada

    @Property(int, constant=True)
    def jogosNaFila(self) -> int:  # noqa: N802
        return regras.JOGOS_NA_FILA

    @Property(bool, constant=True)
    def animacoes(self) -> bool:
        """As animações do Windows estão ativas: sem elas a fila e o passo vão direto ao fim."""
        return self._animacoes_do_sistema

    @Property(bool, notify=alterado)
    def visivel(self) -> bool:
        return self._visivel

    @Property(bool, notify=alterado)
    def disponivel(self) -> bool:
        return self._disponivel

    @Property(bool, notify=alterado)
    def jaSaiu(self) -> bool:  # noqa: N802
        """O usuário saiu do Big Picture nesta sessão: a entrada automática não volta."""
        return self._ja_saiu

    def _ler_animar_central(self) -> bool:
        return self._animacoes_do_sistema and shared.schema.get_boolean("cover-autoplay")

    def _religar_animar_central(self) -> None:
        animar = self._ler_animar_central()
        if animar != self._animar_central:
            self._animar_central = animar
            self.animarCentralMudou.emit()

    @Property(bool, notify=animarCentralMudou)
    def animarCentral(self) -> bool:  # noqa: N802
        """A capa animada do jogo central toca: `cover-autoplay` ligado e animações do Windows ativas."""
        return self._animar_central

    # --- a lista segue o modelo ---
    def _refazer(self, centro: str = "") -> None:
        linhas = regras.jogos_da_biblioteca(self._modelo.linhas())
        self._carrossel.trocar_lista([linha.jogo_id for linha in linhas], centro or None)
        self._jogos = [_dados(linha) for linha in linhas]
        self.jogosMudaram.emit()
        self.alterado.emit()

    @Slot()
    @Slot(str)
    def atualizar(self, centro: str = "") -> None:
        """Refaz a lista mantendo o jogo central (ou `centro`); se ele sumiu, fica o vizinho.

        Só vale visível e fora da saída; durante a fila fica pendente (só o centro mais recente) e
        roda no `filaTerminou`.
        """
        if not self._visivel or self._saindo:
            return
        if self._ocupada:
            self._pendente, self._centro_pendente = True, centro
            return
        self._refazer(centro)

    def _agendar(self, *_args: object) -> None:
        """Várias mudanças seguidas (uma importação) viram um só `atualizar` no próximo ciclo."""
        if self._visivel and not self._agendado:
            self._agendado = True
            QTimer.singleShot(0, self, self._rodar_agendado)

    def _rodar_agendado(self) -> None:
        self._agendado = False
        self.atualizar()

    def _dados_mudaram(self, topo: QModelIndex, base: QModelIndex, papeis: list[int]) -> None:
        if not papeis or not set(papeis) <= _SO_CAPA:
            self._agendar()
            return
        # O `soltar_copia` manda o `DeferredDelete` logo depois do sinal: a capa animada precisa
        # sair daqui já (D39), sem esperar o ciclo.
        por_id = {jogo["jogoId"]: jogo for jogo in self._jogos}
        for i in range(topo.row(), base.row() + 1):
            linha = self._modelo.linha(i)
            if (jogo := por_id.get(linha.jogo_id)) is not None:
                jogo.update(capa=linha.capa, capaAnimada=linha.capa_animada)
        self.jogosMudaram.emit()

    # --- navegação ---
    def _foi_para(self, mudou: bool) -> bool:  # noqa: FBT001
        if mudou:
            regras.tocar_tique()
            self.alterado.emit()
        return mudou

    @Slot(int, result=bool)
    def mover(self, delta: int) -> bool:
        return not self._ocupada and self._foi_para(self._carrossel.mover(delta))

    @Slot(int, result=bool)
    def irPara(self, indice: int) -> bool:  # noqa: N802
        return not self._ocupada and self._foi_para(self._carrossel.ir_para(indice))

    @Slot(result=bool)
    def inicio(self) -> bool:
        return not self._ocupada and self._foi_para(self._carrossel.inicio())

    @Slot(result=bool)
    def fim(self) -> bool:
        return not self._ocupada and self._foi_para(self._carrossel.fim())

    # --- entrar e sair ---
    def definir_janela(self, janela: QWindow) -> None:
        """A janela que vai à tela cheia; o Big Picture só fica disponível com renderizador 3D."""
        self._janela = janela
        self._rever_3d()
        sinal = getattr(janela, "sceneGraphInitialized", None)
        if sinal is not None:  # o renderizador só existe depois do primeiro quadro (na thread de render)
            sinal.connect(self._rever_3d, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _rever_3d(self) -> None:
        janela = self._janela
        if janela is None or janela.rendererInterface() is None:  # ainda sem renderizador: segue disponível
            return
        disponivel = tem_3d(janela)
        if disponivel != self._disponivel:
            self._disponivel = disponivel
            self.alterado.emit()

    @Slot()
    def entrar(self) -> None:
        if self._visivel or self._ocupada or not self._disponivel:
            return
        self._carrossel = regras.Carrossel([])  # sem centro a manter
        self._refazer()  # o jogado mais recentemente no centro
        self._visivel = True
        self._pendente = False
        if self._janela is not None:
            self._estava_maximizada = self._janela.visibility() == QWindow.Visibility.Maximized
            self._janela.showFullScreen()  # o Windows não devolve o estado maximizado sozinho (na saída)
        self._ocupada = bool(self._jogos)
        self.alterado.emit()
        if self._ocupada:
            self.filaPedida.emit(True)  # noqa: FBT003

    @Slot()
    def sair(self) -> None:
        if self._ocupada or not self._visivel:
            return
        self._saindo = True
        self._ocupada = bool(self._jogos)
        self.alterado.emit()
        if self._ocupada:
            self.filaPedida.emit(False)  # noqa: FBT003
        else:
            self._concluir_saida()

    @Slot()
    def filaTerminou(self) -> None:  # noqa: N802
        """O QML avisa que a fila (de entrada ou de saída) chegou ao fim."""
        if not self._ocupada:
            return
        if self._saindo:
            self._concluir_saida()
            return
        self._ocupada = False
        pendente, centro = self._pendente, self._centro_pendente
        self._pendente = False
        self.alterado.emit()
        if pendente:
            self.atualizar(centro)

    def _concluir_saida(self) -> None:
        jogo = (self._central() or {}).get("jogoId", "")
        self._saindo = self._ocupada = self._visivel = self._pendente = False
        self._ja_saiu = True
        self._carrossel, self._jogos = regras.Carrossel([]), []  # fora da tela nada decodifica capa (D39)
        if self._janela is not None:
            if self._estava_maximizada:
                self._janela.showMaximized()
            else:
                self._janela.showNormal()
        self.jogosMudaram.emit()
        self.alterado.emit()
        self.saiu.emit(jogo)
