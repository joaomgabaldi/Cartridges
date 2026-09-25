# hltb_manager.py
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

import logging

from cartridges import shared
from cartridges.game import Game
from cartridges.store.managers.async_manager import AsyncManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils.hltb import (
    HLTBError,
    HLTBHelper,
    HLTBRateLimiter,
    HLTBTimes,
    fetch_times,
)


class HLTBManager(AsyncManager):
    """Manager in charge of completing a game's HowLongToBeat estimates.

    Runs after the Steam lookup on purpose: that step is what turns a shortcut
    named ``Play Cyberpunk 2077 - Atalho`` into the real title, and searching
    HowLongToBeat with the corrected name is the difference between a match and
    a miss. Failures are never fatal — the game simply keeps whatever times it
    already had (usually none) and the rest of the import carries on.
    """

    run_after = (SteamAPIManager,)
    # No retryable_on: the helper handles its own recovery — it refreshes an
    # expired credential and retries once — and converts every transport
    # failure into an HLTBError, so nothing from requests ever reaches the
    # retry machinery. Listing those exceptions here would only look like
    # protection that isn't there.

    hltb_helper: HLTBHelper

    def __init__(self) -> None:
        super().__init__()
        self.hltb_helper = HLTBHelper(HLTBRateLimiter())

    def main(self, game: Game, additional_data: dict) -> None:
        # Tumba não é processada, exceto o zerado adicionado à mão
        # (`zerado_manual`), que só existe como tumba e precisa dos dados.
        if game.blacklisted or (
            game.removed and not additional_data.get("zerado_manual")
        ):
            return

        if not shared.schema.get_boolean("hltb-metadata"):
            return

        # Completion estimates barely move once a game is out, so a game that
        # already has them is left alone. Only an explicit refresh (the button
        # in the details dialog) asks again, which keeps a re-import of a large
        # library from replaying hundreds of requests for unchanged numbers.
        refresh = bool(additional_data.get("refresh_hltb"))
        if game.has_hltb_times and not refresh:
            return

        try:
            times = self._fetch(game)
        except HLTBError as error:
            logging.debug(
                "HowLongToBeat lookup failed for %s", game.name, exc_info=error
            )
            return

        game.update_values(times)

    def _fetch(self, game: Game) -> HLTBTimes:
        """Get ``game``'s times, id first and title search as the fallback."""
        return fetch_times(self.hltb_helper, game.name, game.hltb_id)


def shared_helper() -> HLTBHelper:
    """The app-wide helper, or a throwaway one if the manager isn't up yet.

    Everything outside the pipeline (the backfill, the details dialog) has to
    borrow the manager's instance rather than build its own: a fresh
    :class:`HLTBHelper` would rediscover the endpoint, start a second refill
    thread that never exits, and — worse — hand out request budget the shared
    rate limiter has no idea it spent.
    """
    # `is not None`, not a truth test: Store defines __len__, so an empty
    # library would read as falsy and send every caller to a throwaway helper.
    store = getattr(shared, "store", None)
    manager = store.managers.get(HLTBManager) if store is not None else None
    if isinstance(manager, HLTBManager):
        return manager.hltb_helper
    return HLTBHelper(HLTBRateLimiter())
