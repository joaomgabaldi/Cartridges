"""A janela da abertura enquanto um backup agendado é restaurado.

Sem ela, um backup grande deixava o app minutos sem nenhuma janela, parecendo
que não tinha aberto. Mostra o andamento e não fecha: a restauração foi pedida e
confirmada nas Preferências, e no fim o app abre sozinho (`main.py`).
"""

from typing import Any, Callable, Optional

from gi.repository import Adw, Gtk


def entregar_so_ao_mudar(entregar: Callable[[float], Any]) -> Callable[[float], None]:
    """Embrulha ``entregar`` (a entrega à tela, chamada pela thread de trabalho) para só
    passar adiante quando a porcentagem inteira muda: o trabalho avisa a cada pedaço de
    1 MB e a cada arquivo pequeno, e cada entrega agendada custa um `GLib.idle_add`."""
    ultima = -1

    def avancar(fracao: float) -> None:
        nonlocal ultima
        porcentagem = int(fracao * 100)
        if porcentagem != ultima:
            ultima = porcentagem
            entregar(fracao)

    return avancar


class JanelaRestaurando(Adw.Window):
    def __init__(self, application: Optional[Gtk.Application] = None) -> None:
        super().__init__(
            application=application,
            title="Cartridges",
            resizable=False,
            deletable=False,
            default_width=420,
        )
        self._pode_fechar = False
        self._porcentagem = 0
        self.connect("close-request", self._ao_fechar)

        caixa = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        self.titulo = Gtk.Label(label=_("Restaurando o backup"), css_classes=["title-2"])
        self.texto = Gtk.Label(
            label=_("O aplicativo será aberto quando a restauração terminar."),
            wrap=True,
            css_classes=["dim-label"],
        )
        # A porcentagem num rótulo próprio: o texto da própria barra fica colado nela.
        self.porcentagem = Gtk.Label(label="0%", css_classes=["caption", "numeric"])
        self.barra = Gtk.ProgressBar()
        andamento = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        andamento.append(self.porcentagem)
        andamento.append(self.barra)
        for filho in (self.titulo, self.texto, andamento):
            caixa.append(filho)

        # Para arrastar e minimizar durante a espera; fechar, não.
        self.cabecalho = Adw.HeaderBar(decoration_layout=":minimize")
        barra_de_titulo = Adw.ToolbarView()
        barra_de_titulo.add_top_bar(self.cabecalho)
        barra_de_titulo.set_content(caixa)
        self.set_content(barra_de_titulo)

    def _ao_fechar(self, *_args: Any) -> bool:
        return not self._pode_fechar

    def avancar(self, fracao: float) -> bool:
        """A fração restaurada (0 a 1). Só redesenha quando a porcentagem muda."""
        porcentagem = int(fracao * 100)
        if porcentagem != self._porcentagem:
            self._porcentagem = porcentagem
            self.barra.set_fraction(porcentagem / 100)
            self.porcentagem.set_label(f"{porcentagem}%")
        return False  # chamada por `GLib.idle_add`: uma vez só

    def terminar(self) -> None:
        self._pode_fechar = True
        self.destroy()
