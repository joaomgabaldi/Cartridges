"""O cartão de conquistas da tela de sessão: o progresso e os ícones de todas
as conquistas do jogo, para consultar de relance no outro monitor.

Passivo: nada é clicável. Passar o mouse num ícone mostra o nome, a descrição
e a porcentagem de jogadores.
"""

from typing import Any

from gi.repository import Gtk

from cartridges import shared
from cartridges.conquistas import icones, progresso

TAMANHO_ICONE = 48
# A área dos ícones cresce até aqui e depois rola: o "Já terminei de jogar"
# nunca sai da tela, nem num jogo com 150 conquistas.
ALTURA_MAXIMA = 220


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

        self.icones = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE,
            # Sem o destaque ao passar o mouse, como nas outras FlowBox: o
            # cartão é passivo e os ícones não parecem clicáveis.
            css_classes=["no-hover"],
            homogeneous=True,
            halign=Gtk.Align.CENTER,
            max_children_per_line=1000,
            row_spacing=6,
            column_spacing=6,
        )
        self.rolagem = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            # Sem isto o cartão pediria só a largura de um ícone, e a coluna
            # (centralizada) ficaria com a largura do título.
            propagate_natural_width=True,
            max_content_height=ALTURA_MAXIMA,
            child=self.icones,
        )
        self.append(self.rolagem)

    def limpar(self) -> None:
        self.icones.remove_all()
        self.set_visible(False)

    def mostrar(self, game: Any) -> None:
        """Preenche com o progresso do jogo; some se o jogo não tem cartão."""
        self.icones.remove_all()
        atual = progresso.do_jogo(game)
        self.set_visible(atual is not None)
        if atual is None:
            return
        # A primeira variável é quantas foram desbloqueadas; a segunda, o total
        self.contagem.set_label(_("{} de {}").format(atual.feitas, atual.total))
        self.porcentagem.set_label(f"{atual.porcentagem}%")
        self.barra.set_fraction(atual.fracao)
        mostrar_ocultas = shared.schema.get_boolean("conquistas-mostrar-ocultas")
        # A largura natural acompanha a quantidade real de ícones: o cartão
        # cresce para os lados até a janela e só então quebra a linha.
        self.icones.set_max_children_per_line(max(1, len(atual.todas)))
        for linha in atual.todas:
            # O wrapper explícito (não focável) tira os ícones da ordem do Tab.
            self.icones.append(
                Gtk.FlowBoxChild(child=self._icone(linha, mostrar_ocultas), focusable=False)
            )

    @staticmethod
    def _icone(linha: progresso.Linha, mostrar_ocultas: bool) -> Gtk.Widget:
        jeito = progresso.aparencia(linha, mostrar_ocultas)
        if jeito.oculta:
            imagem = Gtk.Image.new_from_icon_name("dialog-question-symbolic")
            imagem.set_pixel_size(TAMANHO_ICONE // 2)
            imagem.set_size_request(TAMANHO_ICONE, TAMANHO_ICONE)
        else:
            imagem = Gtk.Image(pixel_size=TAMANHO_ICONE, css_classes=["conquistas-icone"])
            if jeito.cinza:
                imagem.add_css_class("conquistas-icone-bloqueada")
            icones.carregar(jeito.origem, imagem.set_from_paintable)
        imagem.set_tooltip_markup(progresso.dica(linha, mostrar_ocultas))
        return imagem
