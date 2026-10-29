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

from PySide6.QtCore import Property, QModelIndex, QObject, QSize, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage
from PySide6.QtQuick import QQuickImageProvider

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
        self._ocupada = False  # a fila de entrada e saída (Task 3) liga isto
        modelo.rowsInserted.connect(self._agendar)
        modelo.rowsRemoved.connect(self._agendar)
        modelo.modelReset.connect(self._agendar)
        modelo.dataChanged.connect(self._dados_mudaram)
        self.atualizar()

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
    @Slot()
    @Slot(str)
    def atualizar(self, centro: str = "") -> None:
        """Refaz a lista mantendo o jogo central (ou `centro`); se ele sumiu, fica o vizinho."""
        linhas = regras.jogos_da_biblioteca(self._modelo.linhas())
        self._carrossel.trocar_lista([linha.jogo_id for linha in linhas], centro or None)
        self._jogos = [_dados(linha) for linha in linhas]
        self.jogosMudaram.emit()
        self.alterado.emit()

    def _agendar(self, *_args: object) -> None:
        """Várias mudanças seguidas (uma importação) viram um só `atualizar` no próximo ciclo."""
        if not self._agendado:
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
