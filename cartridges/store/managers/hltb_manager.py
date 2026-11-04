# hltb_manager.py
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
from cartridges.jogo import Jogo
from cartridges.store.managers.async_manager import AsyncManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils.hltb import (
    HLTBError,
    HLTBGameNotFoundError,
    HLTBHelper,
    HLTBRateLimiter,
    HLTBTimes,
    fetch_times,
)


class HLTBManager(AsyncManager):
    """Completa as estimativas do HowLongToBeat do jogo.

    Roda depois da consulta à Steam de propósito: ela corrige o nome de um atalho ("Play Cyberpunk 2077 - Atalho"), e
    buscar com o nome certo decide entre achar e não achar. Falhas nunca são fatais.
    """

    run_after = (SteamAPIManager,)
    # Sem retryable_on: o helper renova a credencial expirada e tenta de novo, e converte falhas de transporte em HLTBError.

    hltb_helper: HLTBHelper

    def __init__(self) -> None:
        super().__init__()
        self.hltb_helper = HLTBHelper(HLTBRateLimiter())

    def main(self, game: Jogo, additional_data: dict) -> None:
        # Jogo apagado não é processado, exceto o zerado manual (`zerado_manual`), que só existe assim e precisa dos dados.
        if game.blacklisted or (
            game.removed and not additional_data.get("zerado_manual")
        ):
            return

        if not shared.schema.get_boolean("hltb-metadata"):
            return

        # As estimativas quase não mudam: só o botão de atualizar nos detalhes pede de novo, e reimportar uma biblioteca grande não repete centenas de requisições.
        refresh = bool(additional_data.get("refresh_hltb"))
        if game.has_hltb_times and not refresh:
            return

        try:
            times = self._fetch(game)
        except HLTBGameNotFoundError:
            # Resposta, não erro: sem traceback no log.
            logging.debug("HowLongToBeat lookup failed for %s", game.name)
            return
        except HLTBError as error:
            logging.debug(
                "HowLongToBeat lookup failed for %s", game.name, exc_info=error
            )
            return

        game.update_values(times)

    def _fetch(self, game: Jogo) -> HLTBTimes:
        return fetch_times(self.hltb_helper, game.name, game.hltb_id)


def shared_helper() -> HLTBHelper:
    """O helper do app, ou um descartável se o manager ainda não subiu.

    Fora do pipeline é preciso usar a instância do manager: um helper novo redescobriria o endpoint e gastaria cota que o limitador compartilhado não conhece.
    """
    # `is not None`, não verdade: Store define __len__, e uma biblioteca vazia mandaria todos a um helper descartável.
    store = getattr(shared, "store", None)
    manager = store.managers.get(HLTBManager) if store is not None else None
    if isinstance(manager, HLTBManager):
        return manager.hltb_helper
    return HLTBHelper(HLTBRateLimiter())
