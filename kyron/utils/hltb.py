# hltb.py
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

"""Fetch completion time estimates from HowLongToBeat.

No API: the search is ``POST /api/search/site``, guarded by a short-lived token from ``GET /api/search/site/init`` (sent as ``x-auth-token``). The token encodes IP and User-Agent, so credential and search must share one session; a 403 means "re-init and retry".

:func:`fetch_times` picks a route: ``resolve`` (search by title, needs the credential), ``get_times_by_id`` (the server-rendered ``/game/<id>`` page: no credential, used once the id is known) or ``resolve_chapters`` (games the site only catalogues by chapter). Times are in seconds.

The path is renamed every so often (``/api/bleed`` once answered 404 overnight; only the two constants moved). The symptom is ``HowLongToBeat init failed`` at DEBUG wrapping a 404 from the site itself: the new name is in the homepage's JS chunks as ``"/api/…"`` strings, the search one with an ``/init`` sibling. The old honeypot pair (``hpKey``/``hpVal``), if it returns, rejects every search with the init answering 200.
"""

import logging
import re
import json
import threading
import time
from typing import Any, Optional, TypedDict

import requests
from requests.exceptions import RequestException

from kyron.utils.download import MAX_RESPONSE_BYTES, read_capped
from kyron.utils.name_cleaner import clean_for_search
from kyron.utils.rate_limiter import RateLimiter
from kyron.utils.title_match import TitleMatch, rank_candidates, tokenize

BASE_URL = "https://howlongtobeat.com"
SEARCH_URL = f"{BASE_URL}/api/search/site"
INIT_URL = f"{BASE_URL}/api/search/site/init"
REQUEST_TIMEOUT_SECONDS = 15
# Os corpos são lidos em stream com o teto `MAX_RESPONSE_BYTES`; passar dele é RequestException, tratada como "o site não respondeu direito".

# O token embute o User-Agent que o pediu: toda requisição da sessão envia esta string exata, senão a credencial é recusada.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/",
}

# Tipos que não são o jogo base: os tempos são reais, mas de outra coisa.
_IGNORED_GAME_TYPES = frozenset({"dlc", "mod"})

# O mesmo filtro para a rota de capítulos, onde "dlc" precisa passar: o site tipa o primeiro capítulo como jogo e os demais como DLC
# (os capítulos 2 a 5 de Poppy Playtime são "dlc"). É seguro só aqui: esta rota lista cada entrada como capítulo, e o candidato
# precisa ter o título pedido como abertura exata seguido de um marcador de capítulo, o que trilha ou passe de temporada não passa.
_CHAPTER_IGNORED_GAME_TYPES = frozenset({"mod"})

# Jogos vendidos como um produto que o site só cataloga por capítulo. Lista escrita à mão e não regra: toda versão geral de "somar
# as entradas que estendem o título" erra caro ("Final Fantasy" juntaria a franquia, "The Last of Us" engoliria o "Part II"). Um caso novo é uma linha;
# até lá o jogo fica sem tempos, a falha que vale ter.
_CHAPTER_SERIES = frozenset({"poppy playtime"})

# A palavra que abre o que o candidato acrescenta ao título, seguida do número ("Poppy Playtime: Chapter 1 - ..."). Exigi-la nessa
# posição mantém "Poppy Playtime Forever: Chapter 9" de fora: estende outro título.
_CHAPTER_WORDS = frozenset({"chapter", "chapters", "episode", "capitulo"})

# Um IP bloqueado recebe 403 em tudo, e uma busca custa até quatro requisições (um 403 não se distingue de credencial expirada). O
# preenchimento da abertura percorre a biblioteca toda: mil jogos disparariam quatro mil requisições a um site que já recusou a primeira,
# o jeito mais certo de continuar bloqueado. Após tantas falhas seguidas o helper para de perguntar por um tempo e falha localmente.
_BREAKER_FAILURE_THRESHOLD = 3
_BREAKER_COOLDOWN_SECONDS = 15 * 60

# Os três campos no JSON embutido na página. A âncora aspas-e-dois-pontos importa: sem ela `"comp_main":` casaria com `"comp_main_count":` e afins.
_PAGE_FIELD_RES = {
    "hltb_main": re.compile(r'"comp_main":\s*(\d+)'),
    "hltb_main_extra": re.compile(r'"comp_plus":\s*(\d+)'),
    "hltb_completionist": re.compile(r'"comp_100":\s*(\d+)'),
}


class HLTBError(Exception):
    """Base class for every HowLongToBeat failure."""


class HLTBGameNotFoundError(HLTBError):
    """No entry on HowLongToBeat matches the title with enough confidence."""


class HLTBUnavailableError(HLTBError):
    """The endpoint could not be reached, or refused the credential twice."""


class HLTBTimes(TypedDict, total=False):
    """Completion times for a game, in seconds, in the shape :meth:`Game.update_values` expects."""

    hltb_id: Optional[int]
    hltb_main: int
    hltb_main_extra: int
    hltb_completionist: int
    # Por capítulo, para os jogos que só existem assim (``_CHAPTER_SERIES``). Vazio nos demais, para não sobrar um detalhamento velho.
    hltb_chapters: list[dict]


class HLTBRateLimiter(RateLimiter):
    """Rate limiter for HowLongToBeat: o site não publica limite e sofre com scrapers, então é gentil de propósito (~1 requisição a cada 1,5 s, com um pequeno surto)."""

    refill_period_seconds = 60
    refill_period_tokens = 40
    burst_tokens = 10


def format_hltb_time(seconds: Optional[int]) -> str:
    """Horas compactas ("16 h", "22,5 h"), com vírgula como :func:`format_playtime` e sem o ``,0``; travessão se não há dado, para a linha alinhar."""
    if not seconds or seconds <= 0:
        return "—"

    hours = round(seconds / 3600, 1)
    if hours < 0.1:
        # Menos de seis minutos é artefato de arredondamento; "0 h" leria como "sem dados".
        return _("< 0,1 h")

    text = str(int(hours)) if hours.is_integer() else str(hours).replace(".", ",")
    return _("{} h").format(text)


def _coerce_seconds(value: Any) -> Optional[int]:
    """``value`` como segundos positivos, ou None (o site manda 0 para "ninguém enviou este tempo", que não pode virar "0 h")."""
    try:
        seconds = int(float(value))
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def parse_entry(entry: dict) -> HLTBTimes:
    """Id e tempos de um resultado cru da busca; só chaves com dado real, para não apagar um tempo que o jogo já tinha."""
    times = HLTBTimes()

    if (game_id := _coerce_seconds(entry.get("game_id"))) is not None:
        times["hltb_id"] = game_id

    for key, field in (
        ("hltb_main", "comp_main"),
        ("hltb_main_extra", "comp_plus"),
        ("hltb_completionist", "comp_100"),
    ):
        if (seconds := _coerce_seconds(entry.get(field))) is not None:
            times[key] = seconds  # type: ignore[literal-required]

    return times


_TIME_KEYS = ("hltb_main", "hltb_main_extra", "hltb_completionist")


def _n_times(times: HLTBTimes) -> int:
    return sum(1 for key in _TIME_KEYS if times.get(key))


def is_chapter_series(name: str) -> bool:
    return " ".join(tokenize(name)) in _CHAPTER_SERIES


def chapter_times(chapters: dict[int, dict]) -> HLTBTimes:
    """Entradas por capítulo viram um detalhamento, na ordem dos capítulos.

    Sem total, de propósito: somar inventaria um número que não existe no site, e quem joga quer o tempo *do capítulo em que está*.
    Os três campos únicos e ``hltb_id`` são zerados: um jogo antes casado com a entrada errada não pode manter essas sobras, e um id None
    mantém os refreshes buscando por nome em vez de fixar o jogo na página de um capítulo.
    """
    times = HLTBTimes(
        hltb_id=None,
        hltb_chapters=[
            {
                "number": number,
                "name": chapters[number]["title"],
                "hltb_id": chapters[number]["times"].get("hltb_id"),
                **{key: chapters[number]["times"].get(key) for key in _TIME_KEYS},
            }
            for number in sorted(chapters)
        ],
    )
    for key in _TIME_KEYS:
        times[key] = None  # type: ignore[literal-required]
    return times


def has_times(times: HLTBTimes) -> bool:
    """True se a consulta produziu algo útil: uma das três estimativas ou um detalhamento por capítulo (um jogo por capítulos não tem estimativa única)."""
    return any(times.get(key) for key in _TIME_KEYS) or bool(
        times.get("hltb_chapters")
    )


class HLTBHelper:
    """Helper around the HowLongToBeat search and game pages."""

    rate_limiter: RateLimiter

    def __init__(self, rate_limiter: Optional[RateLimiter] = None) -> None:
        self.rate_limiter = rate_limiter or HLTBRateLimiter()
        self._session = requests.Session()
        self._session.headers.update(_BROWSER_HEADERS)
        # Uma credencial para todas as consultas; a trava impede os workers paralelos de buscar uma cada.
        self._credential: Optional[str] = None
        self._credential_lock = threading.Lock()
        # Estado do disjuntor, no helper (instância única do app, `shared_helper`): se um dos três chamadores (importação, preenchimento, edição) o abre, poupa os outros.
        self._breaker_lock = threading.Lock()
        self._failures = 0
        self._blocked_until = 0.0

    # region Circuit breaker

    def _breaker_check(self) -> None:
        """Falha a consulta localmente enquanto o disjuntor está aberto (``HLTBUnavailableError`` antes do fim do resfriamento)."""
        with self._breaker_lock:
            remaining = self._blocked_until - time.time()
        if remaining > 0:
            raise HLTBUnavailableError(
                "HowLongToBeat refused "
                f"{_BREAKER_FAILURE_THRESHOLD} lookups in a row, "
                f"waiting {int(remaining)}s"
            )

    def _breaker_record(self, ok: bool) -> None:
        """Conta um resultado e abre o disjuntor numa sequência de falhas. Qualquer resposta o fecha: só importa o site estar alcançável, não um jogo sem resultado."""
        with self._breaker_lock:
            if ok:
                self._failures = 0
                self._blocked_until = 0.0
                return
            self._failures += 1
            if self._failures < _BREAKER_FAILURE_THRESHOLD:
                return
            self._failures = 0
            self._blocked_until = time.time() + _BREAKER_COOLDOWN_SECONDS
        logging.info(
            "HowLongToBeat is not answering, pausing lookups for %d minutes",
            _BREAKER_COOLDOWN_SECONDS // 60,
        )

    # endregion

    # region Credential

    def _fetch_credential(self) -> Optional[str]:
        """Uma credencial nova, ou None se o site recusou."""
        # O site carrega a homepage antes de buscar: o mesmo aqui, para o cookie que o init espera já estar no jar.
        with self.rate_limiter:
            try:
                # stream + with: os cookies vêm dos headers e o corpo nunca é lido (sem stream baixaria a homepage inteira à toa).
                with self._session.get(
                    f"{BASE_URL}/", timeout=REQUEST_TIMEOUT_SECONDS, stream=True
                ):
                    pass
            except RequestException as error:
                logging.debug("HowLongToBeat homepage failed", exc_info=error)

        with self.rate_limiter:
            try:
                with self._session.get(
                    INIT_URL,
                    params={"t": int(time.time() * 1000)},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    stream=True,
                ) as response:
                    response.raise_for_status()
                    body = json.loads(read_capped(response, MAX_RESPONSE_BYTES))
            except (RequestException, ValueError) as error:
                logging.debug("HowLongToBeat init failed", exc_info=error)
                return None

        if not isinstance(body, dict):
            return None
        if not (token := body.get("token")):
            logging.debug("HowLongToBeat init returned no usable credential")
            return None
        return str(token)

    def _credential_or_fetch(self, force: bool = False) -> Optional[str]:
        with self._credential_lock:
            if self._credential is not None and not force:
                return self._credential
            self._credential = self._fetch_credential()
            return self._credential

    # endregion

    @staticmethod
    def _build_body(name: str) -> dict:
        return {
            "searchType": "games",
            "searchTerms": name.split(),
            "searchPage": 1,
            "size": 20,
            "searchOptions": {
                "games": {
                    "userId": 0,
                    "platform": "",
                    "sortCategory": "popular",
                    "rangeCategory": "main",
                    "rangeTime": {"min": None, "max": None},
                    "gameplay": {
                        "perspective": "",
                        "flow": "",
                        "genre": "",
                        "difficulty": "",
                    },
                    "rangeYear": {"min": "", "max": ""},
                    "modifier": "",
                },
                "users": {"sortCategory": "postcount"},
                "lists": {"sortCategory": "follows"},
                "filter": "",
                "sort": 0,
                "randomizer": 0,
            },
            "useCache": True,
        }

    def _post_search(
        self, name: str, credential: str
    ) -> tuple[Optional[list[dict]], bool]:
        """Uma tentativa de busca: ``(entries, stale)``. ``entries`` é None na falha; ``stale`` só se a credencial foi recusada, o único caso que vale repetir."""
        headers = {
            "Content-Type": "application/json",
            "x-auth-token": credential,
        }

        with self.rate_limiter:
            try:
                with self._session.post(
                    SEARCH_URL,
                    json=self._build_body(name),
                    headers=headers,
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    stream=True,
                ) as response:
                    if response.status_code in (401, 403):
                        logging.debug("HowLongToBeat credential rejected, refreshing")
                        return None, True
                    response.raise_for_status()
                    body = json.loads(read_capped(response, MAX_RESPONSE_BYTES))
            except (RequestException, ValueError) as error:
                logging.debug("HowLongToBeat search failed", exc_info=error)
                return None, False

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            return None, False
        return [entry for entry in data if isinstance(entry, dict)], False

    def search(self, name: str) -> list[dict]:
        """As entradas cruas do HowLongToBeat para ``name``. ``HLTBUnavailableError`` se o endpoint recusou duas vezes ou o disjuntor está aberto."""
        name = (name or "").strip()
        if not name:
            raise HLTBGameNotFoundError()

        self._breaker_check()
        try:
            entries = self._search(name)
        except HLTBUnavailableError:
            self._breaker_record(ok=False)
            raise
        self._breaker_record(ok=True)
        return entries

    def _search(self, name: str) -> list[dict]:
        credential = self._credential_or_fetch()
        if credential is not None:
            entries, stale = self._post_search(name, credential)
            if entries is not None:
                return entries
            if not stale:
                raise HLTBUnavailableError("HowLongToBeat search failed")

        # Sem credencial ou expirada: uma renovação forçada e uma repetição, como o front end do site; a segunda falha é queda real.
        credential = self._credential_or_fetch(force=True)
        if credential is None:
            raise HLTBUnavailableError("could not obtain a HowLongToBeat credential")

        entries, _stale = self._post_search(name, credential)
        if entries is None:
            raise HLTBUnavailableError("HowLongToBeat rejected a fresh credential")
        return entries

    def find_candidates(self, name: str) -> list[tuple[dict, TitleMatch]]:
        """Entradas plausíveis para ``name``, a melhor primeiro, pelo mesmo casador da Steam (a busca real devolve "The Outer Worlds", a edição Spacer's Choice, "The Outer Worlds 2" e dois DLCs juntos).

        Casa pelo título e, na falta, pelo alias, onde o site guarda nomes alternativos e regionais.
        """
        entries = [
            entry
            for entry in self.search(name)
            if str(entry.get("game_type", "")).lower() not in _IGNORED_GAME_TYPES
        ]

        ranked = rank_candidates(name, entries, name_key="game_name")
        if not any(match.confident for _, match in ranked):
            by_alias = [entry for entry in entries if entry.get("game_alias")]
            for candidate, match in rank_candidates(
                name, by_alias, name_key="game_alias"
            ):
                if match.confident:
                    ranked.insert(0, (candidate, match))
                    break

        if not ranked:
            logging.debug("No plausible HowLongToBeat candidate for %s", name)
            raise HLTBGameNotFoundError()
        return ranked

    def resolve(self, name: str) -> HLTBTimes:
        """Os tempos de ``name``. Só um casamento confiante e com tempo é adotado (uma entrada com os três campos zerados é esboço e trocaria "sem dados" por travessões enganosos).

        Levanta ``HLTBGameNotFoundError`` ou ``HLTBUnavailableError``.
        """
        for candidate, match in self.find_candidates(name):
            if not match.confident:
                break
            times = parse_entry(candidate)
            if not has_times(times):
                logging.debug(
                    "HowLongToBeat entry %s has no times", candidate.get("game_name")
                )
                continue
            logging.debug(
                "HowLongToBeat match for %s: %s (%s, score %d)",
                name,
                candidate.get("game_name"),
                match.reason,
                match.score,
            )
            return times
        raise HLTBGameNotFoundError()

    def resolve_chapters(self, name: str) -> HLTBTimes:
        """Os capítulos de um jogo por capítulos (só ``_CHAPTER_SERIES``), a melhor entrada por número.

        O candidato só vale se o título pedido é a abertura exata seguida de um marcador de capítulo e do número ("Poppy Playtime: Chapter 1 - ..." sim; "Poppy Playtime Forever: Chapter 9" não). São precisos dois capítulos, senão a rota comum tenta casar. Entradas tipadas como DLC contam (assim o site cataloga os capítulos após o primeiro), por isso percorre a busca crua e não :meth:`find_candidates`.
        Levanta ``HLTBGameNotFoundError`` ou ``HLTBUnavailableError``.
        """
        wanted = tokenize(name)
        chapters: dict[int, dict] = {}

        for entry in self.search(name):
            if str(entry.get("game_type", "")).lower() in _CHAPTER_IGNORED_GAME_TYPES:
                continue
            title = str(entry.get("game_name") or "")
            tokens = tokenize(title)
            if tokens[: len(wanted)] != wanted:
                continue
            # `tokenize` canoniza numerais: "Chapter III" chega como ["chapter", "3"].
            rest = tokens[len(wanted) :]
            if len(rest) < 2 or rest[0] not in _CHAPTER_WORDS or not rest[1].isdigit():
                continue
            times = parse_entry(entry)
            if not any(times.get(key) for key in _TIME_KEYS):
                continue

            number = int(rest[1])
            known = chapters.get(number)
            # Um capítulo pode aparecer duas vezes (relançamento, pacote): fica a entrada com mais das três estimativas.
            if known is None or _n_times(times) > _n_times(known["times"]):
                chapters[number] = {"title": title, "times": times}

        if len(chapters) < 2:
            logging.debug("No HowLongToBeat chapters for %s", name)
            raise HLTBGameNotFoundError()

        logging.debug(
            "HowLongToBeat chapters for %s: %s",
            name,
            ", ".join(chapters[number]["title"] for number in sorted(chapters)),
        )
        return chapter_times(chapters)

    def get_times_by_id(self, hltb_id: int) -> HLTBTimes:
        """Os tempos de um jogo conhecido, lidos da página pública (renderizada no servidor com o mesmo JSON, sem credencial):
        não toca o endpoint guardado nem refaz uma busca por título que poderia cair em outro jogo.

        Levanta ``HLTBGameNotFoundError`` (sem tempos) ou ``HLTBUnavailableError`` (falha ao buscar, ou disjuntor aberto).
        """
        self._breaker_check()
        with self.rate_limiter:
            try:
                with self._session.get(
                    f"{BASE_URL}/game/{int(hltb_id)}",
                    timeout=REQUEST_TIMEOUT_SECONDS,
                    stream=True,
                ) as response:
                    if response.status_code == 404:
                        raise HLTBGameNotFoundError()
                    response.raise_for_status()
                    page = read_capped(response, MAX_RESPONSE_BYTES).decode(
                        "utf-8", errors="replace"
                    )
            except RequestException as error:
                self._breaker_record(ok=False)
                raise HLTBUnavailableError("game page unreachable") from error

        # A página respondeu: um jogo sem tempos nada diz sobre o site estar alcançável.
        self._breaker_record(ok=True)

        times = HLTBTimes(hltb_id=int(hltb_id))
        for key, pattern in _PAGE_FIELD_RES.items():
            if match := pattern.search(page):
                if (seconds := _coerce_seconds(match.group(1))) is not None:
                    times[key] = seconds  # type: ignore[literal-required]

        if not has_times(times):
            logging.debug("No HowLongToBeat times on the page for %s", hltb_id)
            raise HLTBGameNotFoundError()
        return times


def fetch_times(
    helper: HLTBHelper, name: str, hltb_id: Optional[int] = None
) -> HLTBTimes:
    """Os tempos de um jogo pela rota mais barata: um id conhecido vai direto à página pública (sem credencial e sem nova busca que poderia cair em outro jogo); a busca é o recurso, para jogos não identificados e ids que deixaram de resolver.

    Todo chamador passa por aqui, então nunca divergem sobre qual rota vence. Levanta ``HLTBGameNotFoundError`` ou ``HLTBUnavailableError``.
    """
    cleaned = clean_for_search(name or "")
    if not cleaned:
        raise HLTBGameNotFoundError()

    # Jogos por capítulos primeiro, id inclusive: não há página única, então um id nele é sobra de um casamento errado.
    if is_chapter_series(cleaned):
        try:
            return helper.resolve_chapters(cleaned)
        except HLTBGameNotFoundError:
            # A listagem mudou de forma (capítulos unidos numa entrada, por exemplo): segue e casa como qualquer jogo.
            logging.debug("Falling back to a plain lookup for %s", cleaned)

    if hltb_id:
        try:
            return _plain(helper.get_times_by_id(int(hltb_id)))
        except HLTBGameNotFoundError:
            logging.debug("HowLongToBeat id %s is gone, searching by name", hltb_id)

    return _plain(helper.resolve(cleaned))


def _plain(times: HLTBTimes) -> HLTBTimes:
    """Marca o resultado como de uma entrada única, não de capítulos, para um jogo antes por capítulos não manter um detalhamento velho."""
    times.setdefault("hltb_chapters", [])
    return times
