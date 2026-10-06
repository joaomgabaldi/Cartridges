"""A lista completa de conquistas de um jogo.

Uma lista só, em duas seções: primeiro as desbloqueadas, da mais recente para a
mais antiga, depois as que faltam, apagadas. As raras (menos de 10% dos
jogadores) levam a porcentagem em dourado. Oculta ainda bloqueada não mostra
nome nem descrição, a menos que a preferência peça.
"""

import logging
from typing import Any, Optional

from gi.repository import Adw, Gtk

from cartridges import shared
from cartridges.conquistas import icones, progresso
from cartridges.conquistas.progresso import Linha, aparencia
from cartridges.utils.relative_date import relative_date

_TAMANHO_ICONE = 36


def _data(quando: int) -> Optional[str]:
    """A data por extenso; ``None`` se o carimbo não couber num calendário.

    O histórico aceita qualquer inteiro de 64 bits, e ``datetime.fromtimestamp``
    levanta OverflowError, OSError ou ValueError para os absurdos (ou, no
    Windows, para qualquer carimbo negativo). Sem data a fileira continua boa.
    """
    try:
        texto = str(relative_date(quando))
    except (OverflowError, OSError, ValueError):
        logging.getLogger(__name__).debug("Carimbo fora do calendário: %r", quando)
        return None
    # `relative_date` devolve minúsculas, para seguir um rótulo com dois-pontos;
    # aqui a data aparece sozinha, então a primeira letra sobe.
    return texto[:1].upper() + texto[1:]


class ConquistasDialog(Adw.Dialog):
    def __init__(self, game: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_title(_("Conquistas"))
        self.set_content_width(520)
        self.set_content_height(640)

        self.linhas_desbloqueadas: list[Adw.ActionRow] = []
        self.linhas_bloqueadas: list[Adw.ActionRow] = []
        atual = progresso.do_jogo(game)
        mostrar_ocultas = shared.schema.get_boolean("conquistas-mostrar-ocultas")

        titulo = Adw.WindowTitle(title=_("Conquistas"))
        if atual is not None:
            # A primeira variável é o nome do jogo; as outras, desbloqueadas e total
            titulo.set_subtitle(
                _("{} · {} de {}").format(game.name, atual.feitas, atual.total)
            )
        cabecalho = Adw.HeaderBar(title_widget=titulo)

        pagina = Adw.PreferencesPage()
        if atual is not None:
            topo = Adw.PreferencesGroup()
            topo.add(Gtk.ProgressBar(fraction=atual.fracao))
            pagina.add(topo)

            desbloqueadas = Adw.PreferencesGroup(title=_("Desbloqueadas"))
            for linha in atual.desbloqueadas:
                fileira = self._fileira(linha, mostrar_ocultas)
                self.linhas_desbloqueadas.append(fileira)
                desbloqueadas.add(fileira)
            desbloqueadas.set_visible(bool(atual.desbloqueadas))
            pagina.add(desbloqueadas)

            bloqueadas = Adw.PreferencesGroup(title=_("Bloqueadas"))
            for linha in atual.bloqueadas:
                fileira = self._fileira(linha, mostrar_ocultas)
                self.linhas_bloqueadas.append(fileira)
                bloqueadas.add(fileira)
            bloqueadas.set_visible(bool(atual.bloqueadas))
            pagina.add(bloqueadas)

        vista = Adw.ToolbarView()
        vista.add_top_bar(cabecalho)
        vista.set_content(pagina)
        self.set_child(vista)

    @staticmethod
    def _fileira(linha: Linha, mostrar_ocultas: bool) -> Adw.ActionRow:
        info = linha.info
        visual = aparencia(linha, mostrar_ocultas)

        fileira = Adw.ActionRow(use_markup=False)
        if visual.oculta:
            fileira.set_title(_("Conquista oculta"))
            fileira.set_subtitle(_("Os detalhes aparecem depois do desbloqueio."))
            simbolo = Gtk.Image.new_from_icon_name("dialog-question-symbolic")
            simbolo.set_pixel_size(24)
            simbolo.set_size_request(_TAMANHO_ICONE, _TAMANHO_ICONE)
            fileira.add_prefix(simbolo)
        else:
            fileira.set_title(info.titulo)
            fileira.set_subtitle(info.descricao)
            imagem = Gtk.Image(pixel_size=_TAMANHO_ICONE)
            imagem.add_css_class("conquistas-icone")
            if visual.cinza:
                # O Xbox manda um ícone só: a bloqueada usa o mesmo, em cinza.
                imagem.add_css_class("conquistas-icone-bloqueada")
            icones.carregar(visual.origem, imagem.set_from_paintable)
            fileira.add_prefix(imagem)

        lado = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        if linha.quando and (data := _data(linha.quando)):
            lado.append(Gtk.Label(label=data, xalign=1, css_classes=["dim-label"]))
        if info.porcentagem is not None:
            texto = progresso.porcentagem_em_texto(info.porcentagem)
            rotulo = Gtk.Label(label=f"★ {texto}" if info.rara else texto, xalign=1)
            rotulo.add_css_class("conquista-rara" if info.rara else "dim-label")
            lado.append(rotulo)
        fileira.add_suffix(lado)

        if not linha.desbloqueada:
            fileira.add_css_class("dim-label")
        return fileira
