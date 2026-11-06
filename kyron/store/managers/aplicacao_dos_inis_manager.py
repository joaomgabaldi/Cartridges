# aplicacao_dos_inis_manager.py
#
# Copyright 2026 joaomgabaldi
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

import logging

from kyron.emuladores import aplicacao
from kyron.jogo import Jogo
from kyron.store.managers.async_manager import AsyncManager
from kyron.store.managers.steam_api_manager import SteamAPIManager


class AplicacaoDosInisManager(AsyncManager):
    """Grava o idioma e o nome do jogador nos .ini, depois que a Steam confirmou os idiomas do jogo."""

    run_after = (SteamAPIManager,)

    def main(self, game: Jogo, additional_data: dict) -> None:
        if game.blacklisted or (game.removed and not additional_data.get("zerado_manual")):
            return
        try:
            aplicacao.aplicar_no_jogo(game)
        except OSError as erro:
            logging.warning("Falha ao gravar os .ini de %s: %s", game.name, erro)
