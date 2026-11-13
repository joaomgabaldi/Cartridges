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
from typing import Any, Callable

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, SSLError, Timeout

from kyron.errors.friendly_error import FriendlyError
from kyron.jogo import Jogo
from kyron.store.managers.async_manager import AsyncManager
from kyron.store.managers.manager import Manager
from kyron.store.managers.steam_api_manager import SteamAPIManager
from kyron.utils.steamgriddb import (
    SgdbAuthError,
    SgdbGameNotFound,
    SgdbHelper,
    SgdbNoImageFound,
)

# Chave pela qual `process_game` entrega ao `main` o cancellable do lote.
_CANCELLABLE = "sgdb_cancellable"


class SgdbManager(AsyncManager):

    run_after = (SteamAPIManager,)
    retryable_on = (
        HTTPError,
        SSLError,
        RequestsConnectionError,
        ConnectionError,
        JSONDecodeError,
        Timeout,
    )
    continue_on = (SgdbGameNotFound, SgdbNoImageFound)

    def process_game(
        self, game: Jogo, additional_data: dict, callback: Callable[[Manager], Any]
    ) -> None:
        # Capturado ao enfileirar: um reset troca o cancellable, e uma tarefa que o lesse só ao rodar escreveria a capa depois da limpeza.
        super().process_game(
            game, {**additional_data, _CANCELLABLE: self.cancellable}, callback
        )

    def main(self, game: Jogo, additional_data: dict) -> None:
        cancellable = additional_data.get(_CANCELLABLE) or self.cancellable
        # O cancelamento é tratado aqui à mão: o AsyncManager só o confere antes de rodar e o SgdbHelper o ignora. Sem isto, uma chave errada numa biblioteca de 300 jogos gerava 300 erros 401 idênticos.
        if cancellable.is_set():
            return

        try:
            sgdb = SgdbHelper()
            sgdb.conditionaly_update_cover(game, additional_data)
        except SgdbAuthError as error:
            cancellable.set()
            raise FriendlyError(
                _("Não foi possível autenticar no SteamGridDB"),
                _("Verifique sua chave da API nas preferências."),
            ) from error
