# caixa_redimensionavel.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A caixa do "Onde eu parei", que o usuário aumenta ou diminui pelo puxador.

O GTK não deixa redimensionar um balão: aqui um puxador no canto de baixo, à
direita, muda o tamanho pedido pela rolagem do texto, e o balão acompanha. As
duas caixas (a da tela do jogo e a da tela de sessão) dividem o mesmo tamanho,
guardado no estado do app e reaplicado sempre que uma delas aparece.
"""

from typing import Callable, Optional

from gi.repository import Gdk, GLib, Gtk

from cartridges import shared

# O tamanho de sempre da caixa, que é também o menor.
MINIMO = (320, 120)
# Quanto da janela a caixa pode ocupar: o balão sai preso ao botão, e maior
# que isso ele não cabe mais na tela.
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


def aplicar_tamanho(rolagem: Gtk.ScrolledWindow, tamanho: tuple[int, int]) -> None:
    """Muda o tamanho da caixa e o guarda para a próxima vez."""
    rolagem.set_size_request(*tamanho)
    shared.state_schema.set_int(_LARGURA, tamanho[0])
    shared.state_schema.set_int(_ALTURA, tamanho[1])


def _maximo(rolagem: Gtk.ScrolledWindow) -> Optional[tuple[int, int]]:
    """O maior tamanho que a janela comporta, ou ``None`` antes de ela existir."""
    raiz = rolagem.get_root()
    if raiz is None or not raiz.get_width():
        return None
    return (
        round(raiz.get_width() * FRACAO_MAXIMA[0]),
        round(raiz.get_height() * FRACAO_MAXIMA[1]),
    )


def restaurar(rolagem: Gtk.ScrolledWindow) -> None:
    """Põe a caixa no tamanho guardado, entre o mínimo e o que a janela de
    agora comporta: o tamanho deixado com a janela grande não pode passar da
    janela pequena, e um valor mexido à mão não encolhe a caixa a nada."""
    guardado = (
        shared.state_schema.get_int(_LARGURA),
        shared.state_schema.get_int(_ALTURA),
    )
    maximo = _maximo(rolagem) or (max(guardado[0], MINIMO[0]), max(guardado[1], MINIMO[1]))
    rolagem.set_size_request(*novo_tamanho(guardado, (0, 0), maximo))


# De quanto em quanto tempo, em ms, o arrasto lê o ponteiro (~60 por segundo).
INTERVALO_DO_ARRASTO = 16
# O balão fica centralizado no botão: a largura cresce dos dois lados, e o canto
# direito anda metade do que ela cresce. Com o dobro do deslocamento, o puxador
# acompanha o mouse (conferido no app em 18/10/2026). A altura cresce só para
# baixo, e vai um para um.
FATOR_DA_LARGURA = 2


def _ponteiro_na_janela(
    widget: Gtk.Widget, dispositivo: Optional[Gdk.Device]
) -> Optional[tuple[tuple[float, float], bool]]:
    """Onde o ponteiro está, medido na janela do app, e se o botão está apertado.

    Medido na janela, e não no balão: o balão muda de lugar enquanto cresce (o
    GTK o recentraliza no botão), e uma medida feita nele faria o puxador fugir
    do mouse.
    """
    raiz = widget.get_root()
    superficie = raiz.get_surface() if raiz is not None else None
    if superficie is None or dispositivo is None:
        return None
    achou, x, y, mascara = superficie.get_device_position(dispositivo)
    if not achou:
        return None
    return (x, y), bool(mascara & Gdk.ModifierType.BUTTON1_MASK)


class Arrasto:
    """Um arrasto do puxador, do aperto do botão até ele ser solto.

    Não segue os eventos de movimento do balão: no Windows, assim que o
    ponteiro sai de cima dele (e para aumentar a caixa ele precisa sair), o
    balão para de recebê-los, e a caixa ficava presa (conferido no app em
    18/10/2026). Quem chama lê a posição do ponteiro na janela em intervalos
    curtos e passa a ``passo`` enquanto o botão estiver apertado.
    """

    def __init__(
        self, rolagem: Gtk.ScrolledWindow, maximo: Callable[[], Optional[tuple[int, int]]]
    ) -> None:
        self.rolagem = rolagem
        self._maximo = maximo
        self._ponteiro: tuple[float, float] = (0.0, 0.0)
        self._tamanho: tuple[int, int] = MINIMO

    def comecar(self, ponteiro: tuple[float, float], tamanho: tuple[int, int]) -> None:
        self._ponteiro = ponteiro
        self._tamanho = tamanho

    def passo(self, ponteiro: tuple[float, float], apertado: bool) -> bool:
        """Acompanha o ponteiro; devolve se o arrasto continua."""
        if not apertado:
            aplicar_tamanho(self.rolagem, self.rolagem.get_size_request())
            return False
        maximo = self._maximo()
        if maximo is not None:
            deslocamento = (
                (ponteiro[0] - self._ponteiro[0]) * FATOR_DA_LARGURA,
                ponteiro[1] - self._ponteiro[1],
            )
            self.rolagem.set_size_request(*novo_tamanho(self._tamanho, deslocamento, maximo))
        return True


def ligar(rolagem: Gtk.ScrolledWindow) -> Gtk.Widget:
    """Põe o puxador no canto da caixa de ``rolagem`` e devolve o puxador.

    ``rolagem`` está numa caixa vertical (a do balão), e o puxador entra por
    último nela, alinhado à direita.
    """
    puxador = Gtk.Box(
        halign=Gtk.Align.END,
        width_request=16,
        height_request=16,
        tooltip_text=_("Arraste para mudar o tamanho"),
        cursor=Gdk.Cursor.new_from_name("se-resize", None),
    )
    puxador.add_css_class("puxador-de-tamanho")
    rolagem.get_parent().append(puxador)

    arrasto = Arrasto(rolagem, lambda: _maximo(rolagem))
    em_curso: dict[str, int] = {}
    clique = Gtk.GestureClick()

    def apertou(gesto: Gtk.GestureClick, _vezes: int, _x: float, _y: float) -> None:
        dispositivo = gesto.get_device()
        lido = _ponteiro_na_janela(rolagem, dispositivo)
        if lido is None or "fonte" in em_curso:
            return
        arrasto.comecar(lido[0], (rolagem.get_width(), rolagem.get_height()))

        def ler() -> bool:
            agora = _ponteiro_na_janela(rolagem, dispositivo)
            # Ponteiro fora da janela: a caixa espera onde está até ele voltar.
            continua = True if agora is None else arrasto.passo(*agora)
            if not continua or not rolagem.get_mapped():
                em_curso.pop("fonte", None)
                if continua:
                    aplicar_tamanho(rolagem, rolagem.get_size_request())
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE

        em_curso["fonte"] = GLib.timeout_add(INTERVALO_DO_ARRASTO, ler)

    clique.connect("pressed", apertou)
    puxador.add_controller(clique)

    # Ao aparecer, a caixa pega o tamanho guardado: o arrasto na outra caixa
    # (a da tela de sessão, ou a da tela do jogo) vale para esta também.
    rolagem.connect("map", restaurar)
    restaurar(rolagem)
    return puxador
