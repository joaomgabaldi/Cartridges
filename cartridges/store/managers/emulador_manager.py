# emulador_manager.py
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

from cartridges import shared
from cartridges.emuladores import aplicacao
from cartridges.jogo import Jogo
from cartridges.store.managers.async_manager import AsyncManager


class EmuladorManager(AsyncManager):
    """Procura os .ini dos emuladores do jogo e adota o AppID que eles dizem (antes da Steam, que o trata como verdade)."""

    def main(self, game: Jogo, additional_data: dict) -> None:
        if game.blacklisted or (game.removed and not additional_data.get("zerado_manual")):
            return
        outros = []
        if shared.store is not None:
            outros = [
                o.executable
                for o in shared.store
                if o.game_id != game.game_id and not o.removed and o.executable
            ]
        try:
            appid = aplicacao.atualizar_inis(game, outros)
        except OSError as erro:
            logging.warning("Falha ao procurar os .ini de %s: %s", game.name, erro)
            return
        # Um steam:// do atalho é a verdade: os .ini são achados, mas o AppID deles não é adotado.
        if not additional_data.get("steam_appid") and aplicacao.adotar_appid(game, appid):
            additional_data["steam_appid"] = appid
            # Já adotado aqui, o Steam não veria mudança; a ligação com o zerado do mesmo AppID é marcada agora.
            if not additional_data.get("sem_ligacao"):
                additional_data["ligar_zerado"] = True
