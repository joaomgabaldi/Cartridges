# steam_api_manager.py
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

import logging
from typing import Optional

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, SSLError, Timeout

from cartridges import shared
from cartridges.game import Game
from cartridges.store.managers.async_manager import AsyncManager
from cartridges.utils.name_cleaner import clean_for_search
from cartridges.utils.steam import (
    STEAM_METADATA_VERSION,
    SteamAPIHelper,
    SteamError,
    SteamGameNotFoundError,
    SteamNotAGameError,
    SteamRateLimiter,
)


# Os campos que a tela de edição grava de volta — os únicos em que um valor
# vindo da Steam pode atropelar algo que o usuário digitou. Metacritic,
# avaliações, suporte a controle e afins não são editáveis à mão e continuam
# sempre atualizados.
_USER_EDITED_KEYS = ("name", "developer", "publisher", "release_date", "genre")


def _keep_user_edits(game: Game, online_data: dict, additional_data: dict) -> dict:
    """No modo "só o que falta", um campo editável só preenche o que está vazio.

    O modo escolhia quais *jogos* entravam na fila, mas aplicava o dict
    inteiro: um jogo renomeado à mão que entrasse pela lacuna do gênero saía
    com o nome e a desenvolvedora revertidos para os da Steam — em silêncio, e
    na biblioteca inteira de uma vez a cada bump de STEAM_METADATA_VERSION,
    que re-enfileira tudo. A regra é a mesma da restauração de backup: o que
    está preenchido na biblioteca é mais recente do que o que veio de fora.
    """
    if not additional_data.get("only_missing"):
        return online_data
    return {
        key: value
        for key, value in online_data.items()
        if key not in _USER_EDITED_KEYS or not getattr(game, key, None)
    }


class SteamAPIManager(AsyncManager):
    """Manager in charge of completing a game's data from the Steam API.

    For games with a known Steam appid the appdetails endpoint is queried
    directly, and the appid is remembered so later refreshes never go back to
    guessing from the title. For everything else (e.g. imported shortcuts) the
    name is resolved first, and only adopted when the match is unambiguous —
    a title like "The Outer Worlds" ranks below its own sequel in Steam's
    search, so a best-effort guess would attach the wrong game's data. Lookups
    that fail simply leave the game untouched; they never hide it.
    """

    retryable_on = (HTTPError, SSLError, RequestsConnectionError, Timeout)

    steam_api_helper: SteamAPIHelper = None
    steam_rate_limiter: SteamRateLimiter = None

    def __init__(self) -> None:
        super().__init__()
        self.steam_rate_limiter = SteamRateLimiter()
        self.steam_api_helper = SteamAPIHelper(self.steam_rate_limiter)

    @staticmethod
    def resolve_tags(
        appid: str, additional_data: dict
    ) -> tuple[Optional[list[int]], bool]:
        """Work out where this game's user tags come from.

        The library refresh fetches the tags of every game up front, hundreds
        per request, and hands the result over as ``steam_tags``. A game absent
        from that mapping is one the bulk call did not answer for, and its
        genre must be left exactly as it is — recomputing it without tags would
        quietly downgrade it to the coarse store genre.

        :return: an ``(tag_ids, skip_genre)`` tuple
        """
        bulk = additional_data.get("steam_tags")
        if not isinstance(bulk, dict):
            return None, False  # ordinary import: fetch them per game
        tag_ids = bulk.get(appid)
        return tag_ids, tag_ids is None

    def main(self, game: Game, additional_data: dict) -> None:
        # Tumba não é processada, exceto o zerado adicionado à mão
        # (`zerado_manual`), que só existe como tumba e precisa dos dados.
        if game.blacklisted or (
            game.removed and not additional_data.get("zerado_manual")
        ):
            return

        # Only fetch metadata when enabled
        if not shared.schema.get_boolean("steam-metadata"):
            return

        # Guardado para saber, depois de gravar, se o appID mudou — e então
        # agendar a ligação com um zerado do mesmo appID (Q2).
        anterior = game.steam_appid

        # A known appid is authoritative: it comes either from a steam:// URL
        # or from an earlier resolution the user may have corrected by hand.
        # Searching by name again would risk overwriting that with whatever
        # the store currently ranks first.
        appid = additional_data.get("steam_appid") or game.steam_appid

        if appid is not None:
            tag_ids, skip_genre = self.resolve_tags(str(appid), additional_data)
            try:
                online_data = self.steam_api_helper.get_api_data(
                    appid=str(appid), tag_ids=tag_ids, skip_genre=skip_genre
                )
            except (SteamNotAGameError, SteamGameNotFoundError):
                return
            except SteamError as error:
                logging.debug("Steam lookup failed for %s", game.name, exc_info=error)
                return
            game.steam_appid = str(appid)
            game.update_values(_keep_user_edits(game, online_data, additional_data))
            # Stamped only on the paths that actually answered. A lookup that
            # failed or found nothing must leave the game looking unchecked, or
            # a network blip would mark it as up to date with fields it never
            # received and "only what is missing" would never come back for it.
            game.steam_checked = STEAM_METADATA_VERSION
            self._marcar_ligacao(game, anterior, additional_data)
            return

        # Otherwise resolve the name, which only succeeds when the matcher is
        # sure the title is the same game — a merely related one (a sequel, an
        # expansion) would attach another game's developer, publisher and
        # scores to this one, so the game is left untouched instead.
        try:
            appid, online_data = self.steam_api_helper.resolve(
                clean_for_search(game.name)
            )
        except SteamGameNotFoundError:
            logging.debug("No confident Steam match for %s", game.name)
            return
        except SteamError as error:
            logging.debug("Steam search failed for %s", game.name, exc_info=error)
            return

        # Remember it so later refreshes skip the search entirely.
        game.steam_appid = appid
        game.update_values(_keep_user_edits(game, online_data, additional_data))
        game.steam_checked = STEAM_METADATA_VERSION
        self._marcar_ligacao(game, anterior, additional_data)

    @staticmethod
    def _marcar_ligacao(game: Game, anterior: Optional[str], additional_data: dict) -> None:
        """Se o appID mudou, marca que ``game`` pode ligar com um zerado (Q2).

        Só marca — não liga na hora. Rodando dentro de um pipeline (import,
        carga inicial), o SGDB corre logo depois do Steam no mesmo grupo de
        managers (``run_after``) para buscar uma capa; se a ligação copiasse a
        capa do zerado aqui, o download do SGDB a sobrescreveria assim que
        terminasse, ainda que depois. Por isso quem liga de fato é
        `Store._ao_avancar_pipeline`, só depois que o pipeline inteiro (SGDB
        incluído) termina. Fora de um pipeline (ex.: atualização de metadados
        em lote), quem chama `main` decide sozinho o que fazer com a marca.

        ``sem_ligacao`` é usado pela restauração de backup, que já casa
        zerados com jogos vivos por identidade e não pode ter uma fusão
        acontecendo no meio dela.
        """
        if str(game.steam_appid) != str(anterior) and not additional_data.get("sem_ligacao"):
            additional_data["ligar_zerado"] = True
