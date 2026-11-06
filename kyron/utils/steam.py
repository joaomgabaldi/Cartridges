# steam.py
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

import json
import logging
import re
from datetime import date
from typing import Callable, Optional, TypedDict

from requests.exceptions import HTTPError, RequestException

from kyron import shared
from kyron.emuladores import idiomas
from kyron.utils.download import get_capped
from kyron.utils.rate_limiter import RateLimiter
from kyron.utils.steam_genre import pick_genre
from kyron.utils.title_match import TitleMatch, rank_candidates


# Sobe quando a consulta passa a produzir um campo novo. O jogo guarda a versão da última consulta, o que distingue "anterior
# ao campo" de "a Steam não tem nada a dizer" (campo vazio não distingue: 29 de 30 jogos não têm recomendação de controle, e é resposta correta).
#
# 1: genre, controller_support, gamepad_recommended
# 2: description
STEAM_METADATA_VERSION = 2

# Ids de categoria do appdetails para controle. Não há "sem suporte": o jogo simplesmente não traz nenhum.
CONTROLLER_FULL_CATEGORY = 28
CONTROLLER_PARTIAL_CATEGORY = 18
# "Gamepad Recommended"; a ausência significa "não declarado", não "não".
GAMEPAD_RECOMMENDED_CATEGORY = 60

# Quantas tags pedir: só a primeira de gênero vale, mas ela pode estar bem abaixo (Spider-Man chega a "Ação / Aventura" na 8ª).
TAG_COUNT = 20

# Appids por requisição de tags: 200 em menos de um segundo, um token em vez de 200 ao atualizar a biblioteca. É perto do teto:
# os appids vão na URL, e um lote cheio mede 6647 bytes, dentro dos 8 kB de a maioria dos servidores, com pouca folga. Subir exige medir de novo.
TAG_BATCH_SIZE = 200


class SteamError(Exception):
    pass


class SteamGameNotFoundError(SteamError):
    pass


class SteamNotAGameError(SteamError):
    pass


class SteamAPIData(TypedDict, total=False):
    """Dict returned by SteamAPIHelper.get_api_data"""

    name: str
    developer: str
    publisher: str
    release_date: str
    metacritic: int
    steam_review: str
    genre: str
    # "full" ou "partial"; ausente se a Steam não declara.
    controller_support: str
    gamepad_recommended: bool
    description: str
    # Códigos Steam dos idiomas do jogo (`kyron.emuladores.idiomas`); ausente se a resposta não os traz.
    idiomas_steam: list[str]


class SteamRateLimiter(RateLimiter):
    """Rate limiter for the Steam web API"""

    # O limite parece ser 200 requisições em 5 min
    # https://stackoverflow.com/questions/76047820/how-am-i-exceeding-steam-apis-rate-limit
    # https://stackoverflow.com/questions/51795457/avoiding-error-429-too-many-requests-steam-web-api
    refill_period_seconds = 5 * 60
    refill_period_tokens = 200
    burst_tokens = 100

    def _init_pick_history(self) -> None:
        """Carrega o histórico do schema, para lembrar o limite entre execuções: `seed_history` drena o balde pelo que é restaurado."""
        super()._init_pick_history()
        timestamps_str = shared.state_schema.get_string("steam-limiter-tokens-history")
        # Entrada de estado corrompida nunca pode derrubar a abertura: recomeça com histórico novo.
        try:
            timestamps = json.loads(timestamps_str)
        except ValueError:
            timestamps = []
        if isinstance(timestamps, list):
            restored = [t for t in timestamps if isinstance(t, (int, float))]
            # `add()` sem argumentos registra uma retirada agora: sem a guarda, uma primeira abertura inventaria uma requisição (e gastaria um token).
            if restored:
                self.pick_history.add(*restored)
        self.pick_history.remove_old_entries()

    def acquire(self) -> None:
        super().acquire()
        timestamps_str = json.dumps(self.pick_history.copy_timestamps())
        shared.state_schema.set_string("steam-limiter-tokens-history", timestamps_str)


# Tabela própria para o parse não depender do locale (`strptime("%b")` falharia em silêncio). Só português: o appdetails é pedido assim (`l=brazilian`).
_MONTH_NUMBERS = {
    "jan": 1, "janeiro": 1,
    "fev": 2, "fevereiro": 2,
    "mar": 3, "marco": 3, "março": 3,
    "abr": 4, "abril": 4,
    "mai": 5, "maio": 5,
    "jun": 6, "junho": 6,
    "jul": 7, "julho": 7,
    "ago": 8, "agosto": 8,
    "set": 9, "setembro": 9,
    "out": 10, "outubro": 10,
    "nov": 11, "novembro": 11,
    "dez": 12, "dezembro": 12,
}  # fmt: skip
_MONTH_ABBR = (
    "", "jan.", "fev.", "mar.", "abr.", "mai.", "jun.",
    "jul.", "ago.", "set.", "out.", "nov.", "dez.",
)  # fmt: skip


# Textos da Steam para jogo sem data, na grafia que o app mostra.
_UNDATED_TEXTS = {"em breve": "Em breve", "a ser anunciado": "A ser anunciado"}


def parse_release_date(raw: Optional[str]) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Lê uma data de lançamento como ``(ano, mês, dia)``; mês e dia podem faltar.

    Só estes formatos: "17/set./2020" (Steam), "02/09/2020" (à mão), "set. 2020" ou "set./2020" e "2020".
    Dia e mês só passam se formarem uma data que existe: "31/fev./2026" dá ``(None, None, None)``, como "Em breve".
    """
    text = (raw or "").strip().lower()
    day = month = None
    if m := re.fullmatch(r"(\d{1,2})/([a-zç]+)\.?/(\d{4})", text):
        day, month, year = int(m[1]), _MONTH_NUMBERS.get(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", text):
        day, month, year = int(m[1]), int(m[2]), int(m[3])
    elif m := re.fullmatch(r"([a-zç]+)\.?[ /](?:de )?(\d{4})", text):
        month, year = _MONTH_NUMBERS.get(m[1]), int(m[2])
    elif m := re.fullmatch(r"\d{4}", text):
        year = int(m[0])
    else:
        return None, None, None
    try:
        date(year, 1 if month is None else month, 1 if day is None else day)
    except (TypeError, ValueError):
        return None, None, None
    return year, month, day


def format_release_date(raw: Optional[str]) -> Optional[str]:
    """A data no formato da Steam ("2/set./2026", "set./2026", "2026"); "Em breve" e "A ser anunciado" passam na grafia do app.

    O resto é descartado (``None``): o texto mostrado é sempre montado aqui, nunca o que veio de fora.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if undated := _UNDATED_TEXTS.get(text.lower()):
        return undated
    year, month, day = parse_release_date(text)
    if year is None:
        logging.debug("Data de lançamento descartada: %r", text)
        return None
    if month is None:
        return str(year)
    if day is None:
        return f"{_MONTH_ABBR[month]}/{year}"
    return f"{day}/{_MONTH_ABBR[month]}/{year}"


class SteamAPIHelper:
    """Helper around the Steam API"""

    base_url = "https://store.steampowered.com/api"
    search_url = "https://store.steampowered.com/api/storesearch/"
    reviews_url = "https://store.steampowered.com/appreviews"
    store_items_url = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/"
    rate_limiter: RateLimiter

    def __init__(self, rate_limiter: RateLimiter) -> None:
        self.rate_limiter = rate_limiter

    def search_store(self, name: str) -> list[dict]:
        """Os resultados crus da busca da loja. Levanta ``SteamGameNotFoundError`` se nada for utilizável."""
        with self.rate_limiter:
            try:
                with get_capped(
                    self.search_url,
                    params={"term": name, "l": "english", "cc": "us"},
                    timeout=10,
                ) as response:
                    response.raise_for_status()
                    payload = response.json()
                    # JSON válido que não é objeto (proxy) estourava AttributeError fora de todo except: a thread do seletor morria
                    # e o spinner ficava eterno. Formato errado vale o mesmo "não encontrado" do JSON inválido.
                    items = payload.get("items") if isinstance(payload, dict) else None
                    if not isinstance(items, list):
                        items = []
                    # Só entradas com appid numérico: `"id": null` passava e estourava TypeError/KeyError adiante, fora de todo except.
                    items = [
                        item
                        for item in items
                        if isinstance(item, dict) and isinstance(item.get("id"), int)
                    ]
            except HTTPError as error:
                logging.warning("Steam search HTTP error for %s", name, exc_info=error)
                raise error
            except ValueError as error:
                # 200 com corpo JSON inválido (proxy, captive portal): vale "não encontrado", o jogo fica como está
                logging.warning("Steam search invalid response for %s", name)
                raise SteamGameNotFoundError() from error

        if not items:
            raise SteamGameNotFoundError()
        return items

    def search_candidates(self, name: str) -> list[tuple[dict, TitleMatch]]:
        """As entradas plausíveis da loja para ``name``, a melhor primeiro; sequência, trilha ou título alheio são descartados. Levanta ``SteamGameNotFoundError``."""
        ranked = rank_candidates(name, self.search_store(name))
        if not ranked:
            logging.debug("No plausible Steam candidate for %s", name)
            raise SteamGameNotFoundError()
        return ranked

    def find_candidates(self, name: str) -> list[tuple[dict, TitleMatch]]:
        """Tudo o que pode ser ``name``, o melhor primeiro. Só a busca da loja: a Steam aposentou o ``ISteamApps/GetAppList`` (404) e o substituto exige chave de Web API."""
        return self.search_candidates(name)

    def resolve(self, name: str, max_attempts: int = 4) -> tuple[str, SteamAPIData]:
        """O appid de ``name`` com seus metadados, ``(appid, data)``. Levanta ``SteamGameNotFoundError``.

        Candidatos confiantes são tentados em ordem até um ser um jogo: servidores dedicados, builds de teste e trailers
        dividem o nome e só se distinguem quando o appdetails responde.
        """
        attempts = 0
        for candidate, match in self.find_candidates(name):
            if not match.confident or attempts >= max_attempts:
                break
            attempts += 1
            appid = str(candidate["id"])
            logging.debug(
                "Trying %s for %s (%s, score %d)",
                appid,
                name,
                match.reason,
                match.score,
            )
            try:
                return appid, self.get_api_data(appid)
            except (SteamNotAGameError, SteamGameNotFoundError):
                continue
        raise SteamGameNotFoundError()

    def get_api_data(
        self,
        appid: str,
        tag_ids: Optional[list[int]] = None,
        skip_genre: bool = False,
    ) -> SteamAPIData:
        """Dados online de um jogo pelo appid; pode bloquear pelo limite da API.

        https://wiki.teamfortress.com/wiki/User:RJackson/StorefrontAPI#appdetails
        """
        with self.rate_limiter:
            try:
                with get_capped(
                    # Português para a descrição, o único campo em prosa; o resto sobrevive (ids iguais, e a data só muda de forma, que o parser já lê).
                    f"{self.base_url}/appdetails?appids={appid}&l=brazilian",
                    timeout=10,
                ) as response:
                    response.raise_for_status()
                    payload = response.json()
            except HTTPError as error:
                logging.warning("Steam API HTTP error for %s", appid, exc_info=error)
                raise error
            except ValueError as error:
                logging.warning("Steam API invalid response for %s", appid)
                raise SteamGameNotFoundError() from error

        # Um pedido leva um appID só, então a resposta tem uma entrada só. A chave não serve: a Steam passou a devolvê-la sob o ID de um
        # DLC (o 391220 veio como "541750"), com o appID certo em `data`. Outro formato vale "não encontrado".
        entry = (
            next(iter(payload.values()))
            if isinstance(payload, dict) and len(payload) == 1
            else None
        )
        if not isinstance(entry, dict) or not entry.get("success"):
            logging.debug("Appid %s not found", appid)
            raise SteamGameNotFoundError()

        app_data = entry.get("data")
        if not isinstance(app_data, dict):
            logging.debug("Appid %s has no data", appid)
            raise SteamGameNotFoundError()

        if app_data.get("type") not in {"game", "demo", "mod"}:
            logging.debug("Appid %s is not a game", appid)
            raise SteamNotAGameError()

        values = self.parse_app_data(app_data)
        if isinstance(app_data.get("supported_languages"), str) and (
            (codigos := idiomas.do_appdetails(app_data["supported_languages"])) is not None
        ):
            values["idiomas_steam"] = codigos

        # `skip_genre` deixa a chave de fora para o `update_values` não tocar no campo: cair no gênero amplo trocaria um "Metroidvania" por "Ação" quando a requisição de tags falhou.
        if not skip_genre and (genre := self.get_genre(appid, app_data, tag_ids)):
            values["genre"] = genre

        # As duas notas aparecem lado a lado: o resumo de avaliações é sempre buscado, com ou sem Metacritic.
        review = self.get_review_summary(appid)
        if review:
            values["steam_review"] = review
        return values

    @staticmethod
    def parse_app_data(app_data: dict) -> SteamAPIData:
        """Os campos que guardamos de um appdetails. Todos opcionais: o nome só entra não vazio e o resto fica de fora se ausente, para o `update_values` não sobrescrever."""
        values = SteamAPIData()
        if name := app_data.get("name"):
            values["name"] = name
        # `short_description` e não `about_the_game`: o longo é HTML com imagens e vídeo, e às vezes só isso (o do Cyberpunk 2077 tem 3665 caracteres sem texto algum).
        if description := app_data.get("short_description"):
            values["description"] = description.strip()
        if developers := app_data.get("developers"):
            values["developer"] = ", ".join(developers)
        if publishers := app_data.get("publishers"):
            values["publisher"] = ", ".join(publishers)
        release_info = app_data.get("release_date")
        if isinstance(release_info, dict) and (
            release_date := format_release_date(release_info.get("date"))
        ):
            values["release_date"] = release_date
        metacritic_info = app_data.get("metacritic")
        if isinstance(metacritic_info, dict) and isinstance(
            (score := metacritic_info.get("score")), int
        ):
            values["metacritic"] = score
        if controller := SteamAPIHelper.parse_controller_support(app_data):
            values["controller_support"] = controller
        # Sempre gravado, ao contrário dos acima: aqui o payload é a resposta inteira, e um jogo que perde a recomendação perde a linha.
        values["gamepad_recommended"] = SteamAPIHelper.parse_gamepad_recommended(app_data)
        return values

    def get_genre(
        self, appid: str, app_data: dict, tag_ids: Optional[list[int]] = None
    ) -> Optional[str]:
        """O gênero a mostrar, ou None. ``tag_ids`` evita uma requisição por jogo quando quem chama já as tem (a atualização da biblioteca); senão são buscadas aqui, pois o appdetails só traz os gêneros amplos. Ver :mod:`kyron.utils.steam_genre`."""
        genres = app_data.get("genres")
        genre_ids = (
            [str(entry.get("id")) for entry in genres if isinstance(entry, dict)]
            if isinstance(genres, list)
            else []
        )
        if tag_ids is None:
            tag_ids = self.get_store_tags(appid)
        return pick_genre(genre_ids, tag_ids)

    @staticmethod
    def category_ids(app_data: dict) -> set:
        categories = app_data.get("categories")
        if not isinstance(categories, list):
            return set()
        return {entry.get("id") for entry in categories if isinstance(entry, dict)}

    @staticmethod
    def parse_controller_support(app_data: dict) -> Optional[str]:
        """"full", "partial" ou None. Pelo id da categoria e não pela descrição: treze categorias têm "Controller", "Gamepad" ou "Input" no nome e nenhuma diz se o jogo se joga com controle."""
        ids = SteamAPIHelper.category_ids(app_data)
        if CONTROLLER_FULL_CATEGORY in ids:
            return "full"
        if CONTROLLER_PARTIAL_CATEGORY in ids:
            return "partial"
        # Nenhuma categoria: "desconhecido" e não "nenhum" (muitos jogos antigos aceitam controle sem rótulo); a interface omite a linha.
        return None

    @staticmethod
    def parse_gamepad_recommended(app_data: dict) -> bool:
        """Se os desenvolvedores recomendam controle: afirmação à parte e mais rara que `parse_controller_support` (suporte diz que *funciona*; isto, que é como se deve jogar)."""
        return GAMEPAD_RECOMMENDED_CATEGORY in SteamAPIHelper.category_ids(app_data)

    def get_store_tags(self, appid: str) -> list[int]:
        """Os ids das tags de um jogo, a mais votada primeiro (as da página da loja, que o appdetails não traz; :mod:`kyron.utils.steam_genre` dá os nomes).

        Lista vazia em qualquer falha: o gênero cai no `genres`, que já está em mãos, e não vale falhar a consulta toda por isso.
        """
        return self.get_store_tags_bulk([appid]).get(appid, [])

    def get_store_tags_bulk(
        self, appids: list[str], should_stop: Optional[Callable[[], bool]] = None
    ) -> dict[str, list[int]]:
        """Os ids de tag de vários jogos de uma vez, por appid (uma requisição cobre :data:`TAG_BATCH_SIZE` jogos).

        Appid que falha, é desconhecido ou sem tags fica ausente, não lista vazia: quem chama distingue "não vieram tags" de "o jogo não tem" (o primeiro não pode sobrescrever um gênero gravado). ``should_stop`` é consultado entre lotes (cada um pode ficar 30 s em timeout).
        """
        # O endpoint quer números, e `steam_appid` é uma string que pode ter sido editada à mão.
        numeric: dict[int, str] = {}
        for appid in appids:
            try:
                numeric[int(appid)] = appid
            except (TypeError, ValueError):
                continue
        if not numeric:
            return {}

        wanted = list(numeric)
        result: dict[str, list[int]] = {}
        for start in range(0, len(wanted), TAG_BATCH_SIZE):
            if should_stop is not None and should_stop():
                break
            batch = wanted[start : start + TAG_BATCH_SIZE]
            payload = {
                "ids": [{"appid": appid} for appid in batch],
                "context": {"language": "english", "country_code": "US"},
                "data_request": {"include_tag_count": TAG_COUNT},
            }
            with self.rate_limiter:
                try:
                    with get_capped(
                        self.store_items_url,
                        params={"input_json": json.dumps(payload)},
                        timeout=30,
                    ) as response:
                        response.raise_for_status()
                        items = response.json()["response"].get("store_items", [])
                # AttributeError de propósito: um proxy respondendo 200 com `{"response": null}` chega ao `.get` num não-dict, e
                # matava a thread de pré-busca da atualização, que agenda a fila: a rodada ficava "em andamento" para sempre.
                except (
                    RequestException,
                    ValueError,
                    KeyError,
                    TypeError,
                    AttributeError,
                ) as error:
                    logging.debug("Steam tags error for %d apps", len(batch), exc_info=error)
                    continue

            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                key = numeric.get(item.get("appid"))
                tags = item.get("tags")
                if key is None or not isinstance(tags, list):
                    continue
                result[key] = [
                    tag["tagid"]
                    for tag in tags
                    if isinstance(tag, dict) and isinstance(tag.get("tagid"), int)
                ]
        return result

    def get_review_summary(self, appid: str) -> Optional[str]:
        """O resumo de avaliações da Steam (ex.: "Muito positivas"), do endpoint público appreviews. None sem avaliações ou em qualquer erro: nunca bloqueia a importação."""
        with self.rate_limiter:
            try:
                with get_capped(
                    f"{self.reviews_url}/{appid}",
                    params={
                        "json": 1,
                        "language": "all",
                        "purchase_type": "all",
                        "num_per_page": 0,
                        "l": "brazilian",
                    },
                    timeout=10,
                ) as response:
                    response.raise_for_status()
                    payload = response.json()
                    # isinstance antes do .get(): corpo não-objeto estourava AttributeError depois de o appdetails responder (a perda descrita abaixo).
                    summary = (
                        payload.get("query_summary")
                        if isinstance(payload, dict)
                        else None
                    )
            except (RequestException, ValueError) as error:
                # Toda falha de transporte, não só HTTPError: um timeout aqui escapava *depois* de o appdetails responder, perdia nome,
                # desenvolvedora e Metacritic e fazia o manager repetir o appdetails três vezes. O resumo é o campo menos importante.
                logging.debug("Steam reviews error for %s", appid, exc_info=error)
                return None

        if not isinstance(summary, dict) or not summary.get("total_reviews"):
            return None
        desc = summary.get("review_score_desc")
        return desc if isinstance(desc, str) and desc else None
