# zerados_picker.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O "Adicionar" da página Jogos Zerados: marcar como Zerado um jogo que já
foi desinstalado.

A tela de detalhes só abre para o que está em alguma grade, e um desinstalado
sem a marca não está em nenhuma — sem isto, um jogo desinstalado antes de ser
marcado nunca mais teria como entrar na página. Montado em Python, como o
histórico de sessões: é uma lista cujo tamanho só se sabe ao abrir.
"""

from typing import Any

from gi.repository import Adw, Gtk

from cartridges import shared
from cartridges.game import Game
from cartridges.utils.format_playtime import format_playtime
from cartridges.utils.relative_date import relative_date
from cartridges.utils.spring_scroll import attach as attach_spring_scroll


def candidatos() -> list[Game]:
    """Os desinstalados que ainda não são zerados, em ordem de nome."""
    return sorted(
        (
            game
            for game in shared.store
            if game.removed and not game.blacklisted and not game.zerado
        ),
        key=lambda game: game.name.casefold(),
    )


def descricao(jogo: Game) -> str:
    """Tempo e última vez jogado: o que separa duas fichas de mesmo nome."""
    if not jogo.last_played:
        return _("Nunca jogado")
    # As variáveis são o tempo de jogo e a data da última vez jogado
    return _("{} · Jogado por último: {}").format(
        format_playtime(jogo.playtime), relative_date(jogo.last_played)
    )


class ZeradosPicker(Adw.Dialog):
    """A lista dos candidatos; clicar num deles o marca e o tira da lista."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_title(_("Adicionar a Jogos Zerados"))
        self.set_content_width(460)
        self.set_content_height(520)

        self.lista = Gtk.ListBox(
            selection_mode=Gtk.SelectionMode.NONE, valign=Gtk.Align.START
        )
        self.lista.add_css_class("boxed-list")
        for jogo in candidatos():
            # Sem markup: um "&" no nome de um jogo não é marcação.
            linha = Adw.ActionRow(
                title=jogo.name,
                subtitle=descricao(jogo),
                activatable=True,
                use_markup=False,
            )
            linha.add_suffix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
            linha.connect("activated", self.on_escolhido, jogo)
            self.lista.append(linha)

        rolagem = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True
        )
        rolagem.set_child(
            Adw.Clamp(
                child=self.lista,
                margin_top=12,
                margin_bottom=12,
                margin_start=12,
                margin_end=12,
            )
        )
        # A mesma mola das grades: a lista também rola com inércia.
        attach_spring_scroll(rolagem)

        vazio = Adw.StatusPage(
            icon_name="object-select-symbolic",
            title=_("Nenhum jogo desinstalado"),
            description=_("Todos os jogos desinstalados já estão em Jogos Zerados."),
        )

        self.pilha = Gtk.Stack()
        self.pilha.add_named(rolagem, "lista")
        self.pilha.add_named(vazio, "vazio")
        self._mostrar()

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(self.pilha)
        self.set_child(toolbar)

    def _mostrar(self) -> None:
        self.pilha.set_visible_child_name(
            "lista" if self.lista.get_row_at_index(0) else "vazio"
        )

    def on_escolhido(self, linha: Adw.ActionRow, jogo: Game) -> None:
        # Fica aberto: quem veio marcar os jogos antigos costuma ter vários.
        # Linha velha (o jogo foi reinstalado, ou a ficha trocada na store
        # desde que a lista abriu): só sai da lista, sem mexer no jogo.
        if shared.store.get(jogo.game_id) is jogo and jogo.removed:
            jogo.definir_status("beaten")
            jogo.save()
            jogo.update()
        self.lista.remove(linha)
        self._mostrar()
