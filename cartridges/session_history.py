# session_history.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tela do histórico de sessões de um jogo.

Montada em Python em vez de num .blp porque não há layout a descrever: é um
cabeçalho e uma lista de linhas iguais, cujo número só se sabe ao abrir. Um
template teria de declarar a lista vazia e ser preenchido daqui de qualquer
jeito, e custaria mais um arquivo e mais uma entrada no gresource.
"""

from datetime import datetime
from typing import Any

from gi.repository import Adw, Gtk

from cartridges.game import Game
from cartridges.utils import session_log
from cartridges.utils.create_dialog import create_dialog
from cartridges.utils.format_playtime import format_playtime
from cartridges.utils.relative_date import MONTHS


def format_session_date(timestamp: int) -> str:
    """"12 de agosto de 2026" — a data por extenso, em pt-BR.

    Datas absolutas, e não "Hoje"/"Ontem" como no resto do aplicativo: aqui a
    lista existe para ser lida de cima a baixo, e uma coluna que mistura
    "Terça-feira" com "3 de maio" não deixa comparar duas linhas de relance.
    """
    date = datetime.fromtimestamp(timestamp)
    return f"{date.day} de {MONTHS[date.month - 1].lower()} de {date.year}"


class SessionHistoryDialog(Adw.Dialog):
    """As sessões de um jogo, com a opção de apagar uma que contou errado."""

    def __init__(self, game: Game, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.game = game
        self.set_title(_("Histórico de sessões"))
        self.set_content_width(480)
        self.set_content_height(620)

        self.group = Adw.PreferencesGroup(title=game.name)
        self._rows: list[Gtk.Widget] = []

        page = Adw.PreferencesPage()
        page.add(self.group)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(page)
        self.set_child(toolbar)

        self.rebuild()

    def rebuild(self) -> None:
        """Relê o arquivo e redesenha a lista inteira.

        Redesenhar tudo em vez de tirar uma linha da tela: a remoção mexe no
        total dos resumos do cabeçalho também, e recarregar é a única forma de
        garantir que a tela mostra o que está gravado, e não o que ela acha que
        gravou.
        """
        for row in self._rows:
            self.group.remove(row)
        self._rows.clear()

        sessions = session_log.load(self.game.game_id)

        if not sessions:
            self.group.set_description(
                _(
                    "Nenhuma sessão registrada. O histórico começa a ser gravado "
                    "nas partidas a partir desta versão — o tempo de jogo somado "
                    "antes dela continua no total, mas sem as sessões que o "
                    "formaram."
                )
            )
            return

        self.group.set_description(
            # As variáveis são os tempos jogados nos últimos 7 e 30 dias
            _("Últimos 7 dias: {} · últimos 30 dias: {}").format(
                format_playtime(session_log.seconds_since(sessions, 7)),
                format_playtime(session_log.seconds_since(sessions, 30)),
            )
        )

        for session in sessions:
            self.group.add(row := self._build_row(session))
            self._rows.append(row)

    def _build_row(self, session: dict[str, Any]) -> Adw.ActionRow:
        ended = datetime.fromtimestamp(session["end"])
        row = Adw.ActionRow(
            title=format_session_date(session["end"]),
            # As variáveis são a hora em que a sessão terminou e sua duração
            subtitle=_("terminou às {} · {}").format(
                ended.strftime("%H:%M"), format_playtime(session["seconds"])
            ),
        )

        button = Gtk.Button(
            icon_name="user-trash-symbolic",
            valign=Gtk.Align.CENTER,
            tooltip_text=_("Apagar esta sessão"),
        )
        button.add_css_class("flat")
        button.connect("clicked", self.confirm_delete, session)
        row.add_suffix(button)
        return row

    def confirm_delete(self, _widget: Any, session: dict[str, Any]) -> None:
        """Pergunta antes de apagar: a linha não volta, e o total vai junto."""
        create_dialog(
            self,
            _("Apagar esta sessão?"),
            # As variáveis são a duração da sessão e a data em que ela terminou
            _(
                "{}, em {}. O tempo será descontado do total do jogo, e a "
                "sessão não poderá ser recuperada."
            ).format(
                format_playtime(session["seconds"]),
                format_session_date(session["end"]),
            ),
            "delete",
            _("Apagar"),
        ).connect("response", self.on_delete_response, session)

    def on_delete_response(
        self, _dialog: Any, response: str, session: dict[str, Any]
    ) -> None:
        if response != "delete":
            return

        if not session_log.delete(
            self.game.game_id, session["end"], session["seconds"]
        ):
            # A linha sumiu entre abrir a tela e confirmar (outra janela, o
            # arquivo editado à mão). Nada a descontar: o total continua
            # correspondendo ao que sobrou no histórico.
            self.rebuild()
            return

        # Nunca abaixo de zero: um total menor que a sessão só acontece com um
        # registro editado à mão, e o certo aí é zerar, não guardar um tempo
        # de jogo negativo que a ordenação levaria a sério.
        self.game.playtime = max(0, self.game.playtime - session["seconds"])
        self.game.save()
        self.game.update()
        self.rebuild()
