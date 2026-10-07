"""O cartão de conquistas da tela de sessão: o progresso e os ícones de todas
as conquistas do jogo, para consultar de relance no outro monitor.

Passivo: nada é clicável. Passar o mouse num ícone mostra o nome, a descrição
e a porcentagem de jogadores.
"""

from typing import Any

from gi.repository import Gtk

from cartridges import shared
from cartridges.conquistas import icones, progresso
from cartridges.conquistas.progresso import Aparencia
from cartridges.utils.spring_scroll import attach as attach_spring_scroll

TAMANHO_ICONE = 48


def _ladrilho(tamanho: int, conteudo: Gtk.Widget) -> Gtk.Widget:
    """O quadrado cinza, do tamanho e com o canto dos ícones de verdade, que
    ocupa o lugar de um ícone que não há (oculta) ou que ainda não chegou."""
    conteudo.set_halign(Gtk.Align.CENTER)
    conteudo.set_valign(Gtk.Align.CENTER)
    conteudo.set_hexpand(True)
    caixa = Gtk.Box(css_classes=["conquistas-ladrilho"])
    caixa.set_size_request(tamanho, tamanho)
    caixa.append(conteudo)
    return caixa


def imagem(visual: Aparencia, tamanho: int, interrogacao: int) -> Gtk.Widget:
    """O ícone de uma conquista, na lista e na tela de sessão.

    A oculta é um quadrado com uma interrogação (``interrogacao`` px); as
    outras mostram um troféu genérico até a imagem chegar (`icones.carregar`) —
    e para sempre, se ela não chegar. A bloqueada vai em cinza quando a loja
    não tem a versão bloqueada.
    """
    if visual.oculta:
        sinal = Gtk.Label(css_classes=["conquistas-interrogacao"])
        sinal.set_markup(f'<span size="{interrogacao * 750}">?</span>')
        return _ladrilho(tamanho, sinal)

    generico = Gtk.Image.new_from_icon_name("starred-symbolic")
    generico.set_pixel_size(tamanho // 2)
    figura = Gtk.Image(pixel_size=tamanho, css_classes=["conquistas-icone"])
    if visual.cinza:
        # O Xbox manda um ícone só: a bloqueada usa o mesmo, em cinza.
        figura.add_css_class("conquistas-icone-bloqueada")
    pilha = Gtk.Stack()
    pilha.add_child(_ladrilho(tamanho, generico))
    pilha.add_child(figura)

    def entregar(textura: Any) -> None:
        figura.set_from_paintable(textura)
        pilha.set_visible_child(figura)

    icones.carregar(visual.origem, entregar)
    return pilha


class CartaoDaSessao(Gtk.Box):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12, **kwargs)
        self.add_css_class("card")
        self.add_css_class("conquistas-sessao")
        self.set_visible(False)

        topo = Gtk.Box(spacing=12)
        self.contagem = Gtk.Label(xalign=0, hexpand=True, css_classes=["heading"])
        self.porcentagem = Gtk.Label(xalign=1, css_classes=["dim-label", "numeric"])
        topo.append(self.contagem)
        topo.append(self.porcentagem)
        self.append(topo)

        self.barra = Gtk.ProgressBar()
        self.append(self.barra)

        # Uma linha só, rolando para os lados: em grade, um jogo com muitas
        # conquistas virava um paredão de ícones que empurrava o resto da tela.
        self.icones = Gtk.Box(
            spacing=6,
            # Espaço para a barra de rolagem, que flutua sobre a borda de baixo
            # e cobriria os ícones.
            margin_bottom=14,
            # Sem foco na lista nem na rolagem: o cartão é só para olhar.
            can_focus=False,
        )
        self.rolagem = Gtk.ScrolledWindow(
            vscrollbar_policy=Gtk.PolicyType.NEVER,
            # Com poucos ícones o cartão fica do tamanho deles, centralizado;
            # com muitos, cresce até a janela e passa a rolar.
            propagate_natural_width=True,
            propagate_natural_height=True,
            can_focus=False,
            child=self.icones,
        )
        attach_spring_scroll(self.rolagem, horizontal=True)
        self.append(self.rolagem)

    def limpar(self) -> None:
        self._esvaziar()
        # A próxima sessão começa do início da lista; a atualização ao vivo
        # (`mostrar` de novo) não, para não arrancar a lista de quem está lendo.
        self.rolagem.get_hadjustment().set_value(0)
        self.set_visible(False)

    def mostrar(self, game: Any) -> None:
        """Preenche com o progresso do jogo; some se o jogo não tem cartão."""
        self._esvaziar()
        atual = progresso.do_jogo(game)
        self.set_visible(atual is not None)
        if atual is None:
            return
        # A primeira variável é quantas foram desbloqueadas; a segunda, o total
        self.contagem.set_label(_("{} de {}").format(atual.feitas, atual.total))
        self.porcentagem.set_label(f"{atual.porcentagem}%")
        self.barra.set_fraction(atual.fracao)
        mostrar_ocultas = shared.schema.get_boolean("conquistas-mostrar-ocultas")
        for linha in atual.em_ordem_da_sessao:
            self.icones.append(self._icone(linha, mostrar_ocultas))

    def _esvaziar(self) -> None:
        while filho := self.icones.get_first_child():
            self.icones.remove(filho)

    @staticmethod
    def _icone(linha: progresso.Linha, mostrar_ocultas: bool) -> Gtk.Widget:
        figura = imagem(progresso.aparencia(linha, mostrar_ocultas), TAMANHO_ICONE, TAMANHO_ICONE // 2)
        figura.set_tooltip_markup(progresso.dica(linha, mostrar_ocultas))
        return figura
