# file_manager.py
#
# Copyright 2023 Geoffrey Coulaud
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

import json

from kyron import shared

# Reexportado: os testes e o gravador abaixo usam um só nome; a tupla mora junto de `Jogo` porque também é a lista do que `Jogo.update_values` aceita.
from kyron.jogo import PERSISTED_ATTRS, Jogo
from kyron.store.managers.async_manager import AsyncManager
from kyron.store.managers.hltb_manager import HLTBManager
from kyron.store.managers.steam_api_manager import SteamAPIManager
from kyron.utils.gravar_atomico import gravar_atomico


class FileManager(AsyncManager):

    # Grava por último: antes das consultas online o jogo seria salvo sem os metadados que estão para chegar.
    run_after = (SteamAPIManager, HLTBManager)
    signals = {"salvar"}
    executor = "gravacao"

    def main(self, game: Jogo, additional_data: dict) -> None:
        if additional_data.get("skip_save"):  # Skip saving when loading games from disk
            return

        gravar_atomico(
            shared.games_dir / f"{game.game_id}.json",
            json.dumps({attr: getattr(game, attr) for attr in PERSISTED_ATTRS}, indent=4, sort_keys=True),
        )
