# steam_picker.py
#
# Copyright 2026 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pick which Steam entry a game corresponds to.

Some titles cannot be resolved automatically. "The Outer Worlds" is the plain
case: Steam's own search returns the sequel and a re-release but not the
original, so there is no correct answer to pick from the results — only a
person who knows which game they own can settle it.

This dialog puts that decision in their hands, and the appid they choose is
saved so the question is asked once rather than on every refresh.
"""

import logging
import threading
from typing import Any, Callable, Optional

import requests
from gi.repository import Adw, GLib, Gtk

from cartridges import shared
from cartridges.utils.name_cleaner import clean_for_search, clean_game_name
from cartridges.utils.steam import (
    SteamAPIData,
    SteamAPIHelper,
    SteamError,
    SteamGameNotFoundError,
    SteamNotAGameError,
)
from cartridges.utils.title_match import TitleMatch


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/steam-picker.ui")
class SteamPicker(Adw.Dialog):
    __gtype_name__ = "SteamPicker"

    search_bar: Gtk.SearchBar = Gtk.Template.Child()
    search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    stack: Gtk.Stack = Gtk.Template.Child()
    status_page: Adw.StatusPage = Gtk.Template.Child()
    listbox: Gtk.ListBox = Gtk.Template.Child()

    def __init__(
        self,
        name: str,
        helper: SteamAPIHelper,
        on_selected: Callable[[str, SteamAPIData], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.helper = helper
        self.on_selected = on_selected

        # A generation counter invalidates in-flight searches when a new one
        # starts or the dialog is closed.
        self._generation = 0
        self._debounce_id = 0
        self._closed = False
        self._rows: dict[Gtk.ListBoxRow, str] = {}
        # A mesma proteção dos outros pickers contra a busca dupla que o
        # search-changed atrasado do set_text programático dispara na abertura.
        self._last_query: Optional[str] = None

        self.search_entry.set_text(clean_game_name(name))

        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", lambda *_: self.search())
        self.listbox.connect("row-activated", self._on_row_activated)
        self.connect("closed", self._on_closed)

        self.search()

    # region Search

    def _on_search_changed(self, *_args: Any) -> None:
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
        # Longer than the cover picker's delay: every pause in typing is a
        # request to the Steam store, which rate limits.
        self._debounce_id = GLib.timeout_add(700, self._debounce_fire)

    def _debounce_fire(self) -> bool:
        self._debounce_id = 0
        if self.search_entry.get_text().strip() == self._last_query:
            return False
        self.search()
        return False

    def search(self) -> None:
        self._generation += 1
        generation = self._generation
        self._clear_results()

        query = self.search_entry.get_text().strip()
        self._last_query = query
        if not query:
            self._show_empty(_("Digite o nome de um jogo"))
            return

        self.stack.set_visible_child_name("loading")
        threading.Thread(
            target=self._search_thread, args=(query, generation), daemon=True
        ).start()

    def _search_thread(self, query: str, generation: int) -> None:
        try:
            candidates = self.helper.find_candidates(clean_for_search(query))
        except SteamGameNotFoundError:
            GLib.idle_add(
                self._show_empty,
                _("Nenhum jogo encontrado"),
                _("Tente buscar por outro nome."),
                generation,
            )
            return
        except (SteamError, requests.RequestException) as error:
            logging.warning("Steam picker search failed: %s", error)
            GLib.idle_add(
                self._show_empty,
                _("Não foi possível concluir a busca"),
                _("Verifique a conexão e tente novamente."),
                generation,
            )
            return

        GLib.idle_add(self._show_results, candidates, generation)

    # endregion
    # region Results

    def _show_results(
        self, candidates: list[tuple[dict, TitleMatch]], generation: int
    ) -> bool:
        if generation != self._generation or self._closed:
            return False

        self._clear_results()
        for candidate, match in candidates:
            appid = str(candidate.get("id", ""))
            if not appid:
                continue
            row = Adw.ActionRow(
                title=GLib.markup_escape_text(str(candidate.get("name", ""))),
                subtitle=self._describe(appid, match),
                activatable=True,
            )
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
            self.listbox.append(row)
            # Adw.ActionRow is itself a Gtk.ListBoxRow, so it is not wrapped on
            # append and "row-activated" hands back this very widget.
            self._rows[row] = appid

        if not self._rows:
            return self._show_empty(
                _("Nenhum jogo encontrado"),
                _("Tente buscar por outro nome."),
                generation,
            )

        self.stack.set_visible_child_name("results")
        return False

    @staticmethod
    def _describe(appid: str, match: TitleMatch) -> str:
        """Explain, in one line, how well a candidate fits the searched title."""
        if match.confident:
            return _("ID na Steam: {} · corresponde ao título").format(appid)
        return _("ID na Steam: {} · parece ser outro produto").format(appid)

    def _clear_results(self) -> None:
        self._rows.clear()
        self.listbox.remove_all()

    def _show_empty(
        self, titulo: str, descricao: str = "", generation: Optional[int] = None
    ) -> bool:
        if generation is not None and generation != self._generation:
            return False
        # Título e descrição juntos: com o título fixo, uma busca que falhou
        # dizia "Nenhum … encontrado".
        self.status_page.set_title(titulo)
        self.status_page.set_description(descricao)
        self.stack.set_visible_child_name("empty")
        return False

    # endregion
    # region Selection

    def _on_row_activated(self, _listbox: Gtk.ListBox, row: Gtk.ListBoxRow) -> None:
        if not (appid := self._rows.get(row)):
            return
        self.stack.set_visible_child_name("loading")
        threading.Thread(
            target=self._select_thread, args=(appid,), daemon=True
        ).start()

    def _select_thread(self, appid: str) -> None:
        try:
            data = self.helper.get_api_data(appid)
        except SteamNotAGameError:
            GLib.idle_add(
                self._show_empty,
                _("Este item não é um jogo"),
                _("Escolha outro resultado."),
            )
            return
        except (SteamError, requests.RequestException) as error:
            logging.warning("Steam picker fetch failed: %s", error)
            GLib.idle_add(
                self._show_empty,
                _("Não foi possível obter os dados"),
                _("Verifique a conexão e tente novamente."),
            )
            return
        GLib.idle_add(self._select_done, appid, data)

    def _select_done(self, appid: str, data: SteamAPIData) -> bool:
        if not self._closed:
            self.on_selected(appid, data)
            self.close()
        return False

    # endregion

    def _on_closed(self, *_args: Any) -> None:
        self._closed = True
        # A pending debounce would fire after the dialog is gone and run
        # `search()` against disposed widgets. Bumping the generation only
        # invalidates the *results* of a search, never the search itself.
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = 0
        self._generation += 1
        self._clear_results()
