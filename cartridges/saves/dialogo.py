# dialogo.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O diálogo com as versões guardadas dos saves de um jogo.

Montado em Python, como o histórico de sessões: é uma lista de linhas iguais cujo
número só se sabe ao abrir. Escolher uma versão pede confirmação e só então chama
`backup_de_saves.restaurar`.
"""

from datetime import datetime
from typing import Any

from gi.repository import Adw, Gtk

from cartridges.game import Game
from cartridges.saves import backup_de_saves
from cartridges.saves.ludusavi import Versao
from cartridges.utils.create_dialog import create_dialog


def _data_e_hora(quando: datetime) -> tuple[str, str]:
    """A data e a hora locais de uma versão (o Ludusavi as guarda em UTC)."""
    local = quando.astimezone()
    return f"{local:%d/%m/%Y}", f"{local:%H:%M}"


def formatar(quando: datetime) -> str:
    """"09/10/2026 às 21:14", no horário local."""
    data, hora = _data_e_hora(quando)
    return f"{data} às {hora}"


def confirmar(janela: Any, game: Game, versao: Versao) -> None:
    """Pergunta se o usuário quer mesmo trocar os saves atuais por esta versão."""

    def ao_responder(_dialogo: Any, resposta: str) -> None:
        if resposta == "restaurar":
            backup_de_saves.restaurar(game, versao.id)
            if janela is not None:
                janela.close()

    data, hora = _data_e_hora(versao.quando)
    create_dialog(
        janela,
        _("Restaurar este save?"),
        _(
            "Tem certeza que deseja restaurar o save de {data} às {hora}? "
            "Os saves atuais deste jogo serão substituídos."
        ).format(data=data, hora=hora),
        "restaurar",
        _("Restaurar"),
        destructive=True,
    ).connect("response", ao_responder)


class DialogoDeVersoes(Adw.Dialog):
    """Uma linha por versão, da mais recente para a mais antiga."""

    def __init__(self, game: Game, **kwargs: Any) -> None:
        super().__init__(title=_("Restaurar save"), content_width=420, **kwargs)
        self.game = game

        self.lista = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.lista.add_css_class("boxed-list")
        self.linhas: list[Adw.ActionRow] = []

        versoes = sorted(
            backup_de_saves.versoes_do_jogo(game), key=lambda v: v.quando, reverse=True
        )
        for versao in versoes:
            linha = Adw.ActionRow(title=formatar(versao.quando), activatable=True)
            linha.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            linha.connect("activated", lambda _linha, v=versao: confirmar(self, game, v))
            self.lista.append(linha)
            self.linhas.append(linha)

        rolagem = Gtk.ScrolledWindow(
            child=self.lista,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=420,
            margin_top=12,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        vista = Adw.ToolbarView(content=rolagem)
        vista.add_top_bar(Adw.HeaderBar())
        self.set_child(vista)
