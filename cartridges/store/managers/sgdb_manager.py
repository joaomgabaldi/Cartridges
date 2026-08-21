# sgdb_manager.py
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

from json import JSONDecodeError

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, SSLError, Timeout

from cartridges.errors.friendly_error import FriendlyError
from cartridges.game import Game
from cartridges.store.managers.async_manager import AsyncManager
from cartridges.store.managers.cover_manager import CoverManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils.steamgriddb import (
    SgdbAuthError,
    SgdbGameNotFound,
    SgdbHelper,
    SgdbNoImageFound,
)


class SgdbManager(AsyncManager):
    """Manager in charge of downloading a game's cover from SteamGridDB"""

    run_after = (SteamAPIManager, CoverManager)
    retryable_on = (
        HTTPError,
        SSLError,
        RequestsConnectionError,
        ConnectionError,
        JSONDecodeError,
        Timeout,
    )
    # A missing game or image is an expected outcome, not a user-facing error
    continue_on = (SgdbGameNotFound, SgdbNoImageFound)

    def main(self, game: Game, additional_data: dict) -> None:
        # The cancellation has to be honoured here, by hand, because nothing
        # else will honour it: AsyncManager.process_game builds its Gio.Task
        # with return_on_cancel left at FALSE, so cancelling a task still lets
        # its thread function run to the end, and SgdbHelper never looks at a
        # cancellable of any kind. Cancelling therefore only ever stopped tasks
        # that had not been created yet — of which, in an import, there are
        # none: they are all queued up front. So a wrong API key in a 300-game
        # library meant 300 identical 401s, 300 identical FriendlyErrors queued
        # for the user and 300 pointless round trips to steamgriddb.com.
        # Checking on the way in is what turns that into one error and stops.
        if self.cancellable.is_cancelled():
            return

        try:
            sgdb = SgdbHelper()
            sgdb.conditionaly_update_cover(game, additional_data)
        except SgdbAuthError as error:
            # If invalid auth, cancel all SGDBManager tasks
            self.cancellable.cancel()
            raise FriendlyError(
                _("Não foi possível autenticar no SteamGridDB"),
                _("Verifique sua chave da API nas preferências"),
            ) from error
