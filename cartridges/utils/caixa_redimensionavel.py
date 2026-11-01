# caixa_redimensionavel.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A caixa do "Onde eu parei", que o usuário aumenta ou diminui pelo puxador.

As duas caixas (a da tela do jogo e a da tela de sessão) dividem o mesmo tamanho,
guardado no estado do app e reaplicado sempre que uma delas aparece. A regra é pura;
o ``CaixaDaAnotacao`` a entrega ao QML.
"""

from PySide6.QtCore import Property, QObject, Signal, Slot

from cartridges import shared

# O tamanho de sempre da caixa, que é também o menor.
MINIMO = (320, 120)
# Quanto da janela a caixa pode ocupar: maior que isso ela não cabe mais na tela.
FRACAO_MAXIMA = (0.9, 0.8)
_LARGURA = "notas-largura"
_ALTURA = "notas-altura"


def novo_tamanho(
    inicio: tuple[int, int], deslocamento: tuple[float, float], maximo: tuple[int, int]
) -> tuple[int, int]:
    """O tamanho depois de arrastar o puxador por ``deslocamento``, nos limites."""
    largura, altura = (
        round(min(max(valor + delta, menor), max(maior, menor)))
        for valor, delta, menor, maior in zip(inicio, deslocamento, MINIMO, maximo)
    )
    return largura, altura


def maximo_da_janela(largura: float, altura: float, livre_largura: float, livre_altura: float) -> tuple[int, int]:
    """O maior tamanho da caixa: a fração da janela, e nunca além do espaço livre à direita e abaixo do balão.

    O balão do Qt não é empurrado para dentro da janela; sem o limite do espaço livre, o puxador sairia da janela.
    """
    return (
        round(min(largura * FRACAO_MAXIMA[0], livre_largura)),
        round(min(altura * FRACAO_MAXIMA[1], livre_altura)),
    )


class CaixaDaAnotacao(QObject):
    """O tamanho compartilhado das duas caixas; contexto ``caixaDaAnotacao``."""

    mudou = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._tamanho = MINIMO

    @Property(int, notify=mudou)
    def largura(self) -> int:
        return self._tamanho[0]

    @Property(int, notify=mudou)
    def altura(self) -> int:
        return self._tamanho[1]

    def _por(self, tamanho: tuple[int, int]) -> None:
        if tamanho != self._tamanho:
            self._tamanho = tamanho
            self.mudou.emit()

    @Slot(float, float, float, float)
    def restaurar(self, janela_largura: float, janela_altura: float, livre_largura: float, livre_altura: float) -> None:
        """Põe a caixa no tamanho guardado, entre o mínimo e o que a janela de agora comporta: o tamanho deixado com a
        janela grande não passa da janela pequena, e um valor mexido à mão não encolhe a caixa a nada. Não regrava o
        tamanho: o guardado fica para quando a janela voltar a ser grande."""
        guardado = (shared.state_schema.get_int(_LARGURA), shared.state_schema.get_int(_ALTURA))
        maximo = maximo_da_janela(janela_largura, janela_altura, livre_largura, livre_altura) if janela_largura > 0 else guardado
        self._por(novo_tamanho(guardado, (0, 0), maximo))

    @Slot(int, int, float, float, float, float, float, float)
    def arrastar(  # noqa: PLR0913
        self, inicio_largura: int, inicio_altura: int, dx: float, dy: float,
        janela_largura: float, janela_altura: float, livre_largura: float, livre_altura: float,
    ) -> None:  # fmt: skip
        """Acompanha o puxador (sem gravar; ``gravar`` vem ao soltar)."""
        maximo = maximo_da_janela(janela_largura, janela_altura, livre_largura, livre_altura)
        self._por(novo_tamanho((inicio_largura, inicio_altura), (dx, dy), maximo))

    @Slot()
    def gravar(self) -> None:
        shared.state_schema.set_int(_LARGURA, self._tamanho[0])
        shared.state_schema.set_int(_ALTURA, self._tamanho[1])
