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

lazy from requests.exceptions import ConnectionError as RequestsConnectionError
lazy from requests.exceptions import HTTPError, SSLError, Timeout

from kyron import shared
from kyron.jogo import Jogo
from kyron.store.managers.async_manager import AsyncManager
from kyron.store.managers.emulador_manager import EmuladorManager
from kyron.utils.name_cleaner import clean_for_search
from kyron.utils.steam import (
    STEAM_METADATA_VERSION,
    SteamAPIHelper,
    SteamError,
    SteamGameNotFoundError,
    SteamNotAGameError,
    SteamRateLimiter,
)


# Os campos que a tela de edição grava de volta: os únicos em que um valor da Steam pode atropelar o que a pessoa digitou.
_USER_EDITED_KEYS = ("name", "developer", "publisher", "release_date", "genre")


def _keep_user_edits(game: Jogo, online_data: dict, additional_data: dict) -> dict:
    """No modo "só o que falta", um campo editável só preenche o que está vazio.

    O modo escolhia os *jogos* da fila mas aplicava o dict inteiro: um jogo renomeado à mão voltava ao nome da Steam, na biblioteca toda a cada bump de STEAM_METADATA_VERSION. O que está na biblioteca é mais recente que o de fora (a mesma regra da restauração de backup).
    """
    if not additional_data.get("only_missing"):
        return online_data
    return {
        key: value
        for key, value in online_data.items()
        if key not in _USER_EDITED_KEYS or not getattr(game, key, None)
    }


class SteamAPIManager(AsyncManager):
    """Completa os dados do jogo pela API da Steam.

    Com appid conhecido consulta o appdetails direto e o guarda; sem ele (atalhos) resolve o nome e só adota um resultado inequívoco: "The Outer Worlds" fica abaixo da sequência na busca da Steam. Falhas deixam o jogo intacto.
    """

    run_after = (EmuladorManager,)

    # Propriedade: as classes do ``requests`` só são resolvidas na primeira falha, não na abertura.
    @property
    def retryable_on(self):
        return (HTTPError, SSLError, RequestsConnectionError, Timeout)

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
        """Define de onde vêm as tags do jogo: ``(tag_ids, skip_genre)``.

        A atualização da biblioteca busca as tags de todos os jogos de uma vez (``steam_tags``); um jogo fora desse mapa não foi respondido, e seu gênero não pode ser recalculado sem tags (cairia para o gênero genérico da loja).
        """
        bulk = additional_data.get("steam_tags")
        if not isinstance(bulk, dict):
            return None, False  # ordinary import: fetch them per game
        tag_ids = bulk.get(appid)
        return tag_ids, tag_ids is None

    def main(self, game: Jogo, additional_data: dict) -> None:
        # Jogo apagado não é processado, exceto o zerado manual (`zerado_manual`), que só existe assim e precisa dos dados.
        if game.blacklisted or (
            game.removed and not additional_data.get("zerado_manual")
        ):
            return

        if not shared.schema.get_boolean("steam-metadata"):
            return

        # Para saber, depois de gravar, se o appID mudou e então agendar a ligação com um zerado do mesmo appID.
        anterior = game.steam_appid

        # Um appid conhecido (URL steam:// ou resolução anterior corrigida à mão) é a verdade: buscar o nome de novo poderia sobrescrevê-lo.
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
            # Só nos caminhos que responderam: uma falha de rede não pode deixar o jogo "em dia" com campos que nunca recebeu.
            game.steam_checked = STEAM_METADATA_VERSION
            self._marcar_ligacao(game, anterior, additional_data)
            return

        # Senão resolve o nome, só quando o matcher tem certeza de ser o mesmo jogo; um parente (sequência, expansão) traria dados de outro jogo.
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

        game.steam_appid = appid
        game.update_values(_keep_user_edits(game, online_data, additional_data))
        game.steam_checked = STEAM_METADATA_VERSION
        self._marcar_ligacao(game, anterior, additional_data)

    @staticmethod
    def _marcar_ligacao(game: Jogo, anterior: Optional[str], additional_data: dict) -> None:
        """Se o appID mudou, marca que ``game`` pode ligar com um zerado; só marca, não liga na hora.

        O SGDB corre depois do Steam no mesmo pipeline e sobrescreveria a capa copiada do zerado; quem liga é `Store._ao_avancar_pipeline`, com o pipeline terminado. Fora de um pipeline, quem chama `main` decide. ``sem_ligacao`` vem do zerado manual (`zerado_manual`), cujo seletor já impede appID de jogo da biblioteca.
        """
        if str(game.steam_appid) != str(anterior) and not additional_data.get("sem_ligacao"):
            additional_data["ligar_zerado"] = True
