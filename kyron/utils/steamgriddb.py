# steamgriddb.py
#
# Copyright 2022-2023 kramo
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

import contextlib
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests
from requests.exceptions import HTTPError, RequestException

from kyron import shared
from kyron.jogo import Jogo
from kyron.utils.download import (
    MAX_ANIMATED_IMAGE_BYTES,
    MAX_IMAGE_BYTES,
    download_bytes,
    get_capped,
)
from kyron.utils.name_cleaner import clean_for_search
from kyron.utils.save_cover import ANIMATED_SUFFIXES, convert_cover, save_cover
from kyron.utils.title_match import rank_candidates


_downloads_animados = threading.BoundedSemaphore(2)


class SgdbError(Exception):
    pass


class SgdbAuthError(SgdbError):
    pass


class SgdbGameNotFound(SgdbError):
    pass


class SgdbBadRequest(SgdbError):
    pass


class SgdbNoImageFound(SgdbError):
    pass


def auth_error(res: requests.Response) -> SgdbAuthError:
    """O erro de um 401, qualquer que seja o corpo.

    Uma chave ruim costuma receber 401 do Cloudflare, em HTML: lido como JSON dava JSONDecodeError, que está em
    `SgdbManager.retryable_on`, e o caso era repetido três vezes e virava falha genérica, sem o diálogo que diria o que corrigir.
    """
    try:
        message = str(res.json()["errors"][0])
    except (ValueError, LookupError, TypeError):
        message = "SteamGridDB rejected the API key"
    return SgdbAuthError(message)


def _data_list(res: requests.Response) -> list:
    """O ``data`` de um 200 do SGDB, exigindo o formato documentado.

    Um 200 de outro formato (``{"success": false}`` de um proxy) levantava ``KeyError``, que os pickers não tratam:
    a thread morria e o diálogo ficava no spinner. Agora é ``SgdbBadRequest``.
    """
    try:
        payload = res.json()
    except ValueError as error:
        raise SgdbBadRequest(res.status_code) from error
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise SgdbBadRequest(res.status_code)
    return payload["data"]


class SgdbHelper:
    """Consultas ao SteamGridDB."""

    base_url = "https://www.steamgriddb.com/api/v2/"

    @property
    def auth_headers(self) -> dict[str, str]:
        key = shared.schema.get_string("sgdb-key")
        headers = {"Authorization": f"Bearer {key}"}
        return headers

    def get_game_id(self, game: Jogo) -> Any:
        """O id SGDB que melhor casa com o jogo. Pode levantar."""
        # A consulta é um segmento de caminho: precisa de URL-encode (espaços, ':', '&', acentos).
        query = clean_for_search(game.name)
        uri = f"{self.base_url}search/autocomplete/{quote(query, safe='')}"
        res = get_capped(uri, headers=self.auth_headers, timeout=10)
        match res.status_code:
            case 200:
                results = [r for r in _data_list(res) if isinstance(r, dict)]
                if not results:
                    raise SgdbGameNotFound(query)
                with_ids = [r for r in results if r.get("id") is not None]
                if not with_ids:
                    raise SgdbBadRequest(res.status_code)
                # Pelo mesmo casamento de títulos da Steam, não por igualdade: a consulta é o nome *limpo* e os
                # resultados são crus. Um casamento confiante vence; senão o melhor plausível; sequência ou título alheio nunca.
                ranked = rank_candidates(query, with_ids)
                if not ranked:
                    raise SgdbGameNotFound(query)
                return ranked[0][0]["id"]
            case 401:
                raise auth_error(res)
            case 404:
                raise SgdbGameNotFound(res.status_code)
            case _:
                # raise_for_status() só levanta em 4xx/5xx; guarda contra um 2xx/3xx inesperado devolver None.
                res.raise_for_status()
                raise SgdbBadRequest(res.status_code)

    def _lista(self, uri: str, jogo: bool = True) -> list[dict]:
        """O ``data`` de uma resposta em lista. Levanta na chave recusada e, com ``jogo``, no 404 (`SgdbGameNotFound`);
        um 2xx/3xx inesperado vira lista vazia."""
        res = get_capped(uri, headers=self.auth_headers, timeout=10)
        match res.status_code:
            case 200:
                return _data_list(res)
            case 401:
                raise auth_error(res)
            case 404 if jogo:
                raise SgdbGameNotFound(res.status_code)
            case _:
                res.raise_for_status()
                return []

    def search_games(self, query: str) -> list[dict]:
        # Busca sem resultado é lista vazia, não "jogo não encontrado": o 404 cai no `raise_for_status`.
        return self._lista(
            f"{self.base_url}search/autocomplete/{quote(query, safe='')}", jogo=False
        )

    def get_grids(
        self, game_id: str, animated: bool = False, dimensions: Optional[str] = None
    ) -> list[dict]:
        """Os grids (capas) de um jogo SGDB, com ao menos ``url`` e ``thumb``.

        ``dimensions`` (ex.: ``"600x900"``) é opcional: restringi-lo descarta a maioria das animadas, que raramente têm o tamanho exato.
        """
        params = []
        if dimensions:
            params.append(f"dimensions={dimensions}")
        if animated:
            params.append("types=animated")
        uri = f"{self.base_url}grids/game/{game_id}"
        if params:
            uri += "?" + "&".join(params)
        return self._lista(uri)

    def get_logos(self, game_id: str) -> list[dict]:
        """Os logos horizontais de um jogo SGDB, com ``url``, ``style`` e ``width``/``height``; escolher é com quem chama.

        Pede só estáticos, sem NSFW nem piada: o cabeçalho dos detalhes é marca, não lugar para animação.
        """
        return self._lista(
            f"{self.base_url}logos/game/{game_id}?types=static&nsfw=false&humor=false"
        )

    def get_image_uri(self, game_id: str, animated: bool = False) -> Any:
        uri = f"{self.base_url}grids/game/{game_id}?dimensions=600x900"
        if animated:
            uri += "&types=animated"
        res = get_capped(uri, headers=self.auth_headers, timeout=10)
        match res.status_code:
            case 200:
                data = _data_list(res)
                if len(data) == 0:
                    raise SgdbNoImageFound()
                first = data[0]
                if not isinstance(first, dict) or not first.get("url"):
                    raise SgdbBadRequest(res.status_code)
                return first["url"]
            case 401:
                raise auth_error(res)
            case 404:
                raise SgdbGameNotFound(res.status_code)
            case _:
                # raise_for_status() só levanta em 4xx/5xx; guarda contra um 2xx/3xx inesperado devolver None.
                res.raise_for_status()
                raise SgdbBadRequest(res.status_code)

    def conditionaly_update_cover(
        self, game: Jogo, additional_data: Optional[dict] = None
    ) -> None:
        use_sgdb = shared.schema.get_boolean("sgdb")
        if not use_sgdb or game.blacklisted:
            return

        prefer_sgdb = shared.schema.get_boolean("sgdb-prefer")

        # Sem efeito se já há capa e não se prefere o SGDB. Confere todo sufixo que `save_cover` grava: só .tiff/.gif
        # deixava um .webp animado escolhido à mão passar por "sem capa", e o download o apagava.
        if not prefer_sgdb and any(
            (shared.covers_dir / f"{game.game_id}{suffix}").is_file()
            for suffix in (*ANIMATED_SUFFIXES, ".tiff")
        ):
            return

        try:
            sgdb_id = self.get_game_id(game)
        except (HTTPError, SgdbError) as error:
            logging.warning(
                "%s while getting SGDB ID for %s", type(error).__name__, game.name
            )
            raise error

        image_uri_kwargs_sets = [{"animated": False}]
        if shared.schema.get_boolean("sgdb-animated"):
            image_uri_kwargs_sets.insert(0, {"animated": True})

        for uri_kwargs in image_uri_kwargs_sets:
            try:
                uri = self.get_image_uri(sgdb_id, **uri_kwargs)
                # Só duas capas animadas por vez: cada jogo busca numa thread própria e uma animada pode ter 200 MB (o dobro na RAM).
                with (
                    _downloads_animados
                    if uri_kwargs["animated"]
                    else contextlib.nullcontext()
                ):
                    # download_bytes limita o tamanho e levanta em erro HTTP: uma página de erro nunca vira capa.
                    content = download_bytes(
                        uri,
                        timeout=10,
                        max_bytes=MAX_ANIMATED_IMAGE_BYTES
                        if uri_kwargs["animated"]
                        else MAX_IMAGE_BYTES,
                    )
                    descritor, nome = tempfile.mkstemp()
                    os.close(descritor)
                    tmp_file_path = Path(nome)
                    converted = None
                    try:
                        tmp_file_path.write_bytes(content)
                        # `convert_cover` recebe um Path (lê `.suffix`).
                        converted = convert_cover(tmp_file_path)
                        # A conversão que falha devolve None, e `save_cover` apaga as capas existentes *antes* de checar o
                        # argumento (None é como a edição limpa a capa): passar a falha adiante destruía a capa que o jogo já tinha.
                        if converted is None:
                            raise SgdbNoImageFound()
                        save_cover(game.game_id, converted)
                    finally:
                        # Remove o download e o temporário da conversão: `save_cover` copia, e ficariam no %TEMP% para sempre.
                        tmp_file_path.unlink(missing_ok=True)
                        if converted is not None and converted != tmp_file_path:
                            converted.unlink(missing_ok=True)
            except SgdbAuthError as error:
                raise error
            except (HTTPError, SgdbError, RequestException) as error:
                logging.warning(
                    "%s while getting image for %s kwargs=%s",
                    type(error).__name__,
                    game.name,
                    str(uri_kwargs),
                )
                continue
            else:
                return

        logging.warning(
            'No matching image found for game "%s" (SGDB ID %s)',
            game.name,
            sgdb_id,
        )
        raise SgdbNoImageFound()
