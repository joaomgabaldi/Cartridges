# elamigos_feed.py
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

"""Lê a página inicial do ElAmigos como *novidades* (só para a página de Novidades; o aviso de atualização por jogo segue só com a FitGirl).

O site não tem RSS. A página é uma lista por semana::

    <h1>07.11.2026</h1>
    <h3>Silica ElAmigos <a href="data/Silica.html">DOWNLOAD</a></h3>
    <hr>
    <h3>Forza Horizon 6 ElAmigos +[Update 479.874] <a href="data/Forza.html">DOWNLOAD</a></h3>

Cada ``<h3>`` vira uma linha: o nome antes de "ElAmigos", as marcas entre colchetes como resumo, o link e a data do bloco.
Depois das datas vem um ``<h4>`` e o arquivo alfabético de tudo, sem data, que é ignorado.

Limite: os blocos são semanais e sem hora. Um jogo somado a um bloco já visto aparece na lista, mas não acende o selo
de "não visto" (que compara datas) até sair um bloco com data mais nova.
"""

import logging
import re
from calendar import timegm
from html.parser import HTMLParser
from time import time
from typing import Optional
from urllib.parse import urljoin

# pylint: disable=protected-access
# O leitor de digests é dono do transporte e das guardas de URL e de data.
from kyron.utils.news_feed import NewsPost
from kyron.utils.updates_feed import (
    _MAX_CLOCK_SKEW_SECONDS,
    _MAX_TITLE_CHARS,
    _safe_url,
    fetch_feed_text,
)

PAGE_URL = "https://elamigos.site/"

_CATEGORY = "ElAmigos"

# A página traz semanas de lançamentos; a lista de Novidades mostra só o último mês.
_MAX_AGE_SECONDS = 30 * 24 * 3600

_MAX_POSTS = 500

_DATE_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{4})\s*$")
_MARK_RE = re.compile(r"\[([^\]]*)\]")
_GROUP_RE = re.compile(r"\s+ElAmigos\b.*$", re.IGNORECASE | re.DOTALL)
_WHITESPACE_RE = re.compile(r"\s+")


def _date_stamp(text: str) -> Optional[int]:
    """``dd.mm.aaaa`` em segundos, ou None. O site não dá a hora: meio-dia UTC cai no mesmo dia de UTC-11 a UTC+11 (meia-noite viraria "ontem" no Brasil)."""
    match = _DATE_RE.match(text)
    if not match:
        return None
    day, month, year = (int(part) for part in match.groups())
    try:
        return timegm((year, month, day, 12, 0, 0))
    except (ValueError, OverflowError):
        return None


class _PageParser(HTMLParser):
    """Junta ``(data, texto do h3, href)`` dos blocos datados, parando no arquivo alfabético."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.items: list[tuple[int, str, Optional[str]]] = []
        self._date: Optional[int] = None
        self._done = False
        self._in_h1 = False
        self._h1_buffer: list[str] = []
        self._h1_chars = 0
        self._in_h3 = False
        self._h3_date = 0
        self._h3_buffer: list[str] = []
        self._h3_chars = 0
        self._href: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if self._done:
            return
        if tag == "h1":
            self._in_h1 = True
            self._h1_buffer = []
            self._h1_chars = 0
        elif tag == "h4" and self._date is not None:
            # O arquivo alfabético começa depois do <h4> que fecha as datas.
            self._done = True
        elif tag == "h3" and self._date is not None:
            self._in_h3 = True
            # A data do bloco é fixada aqui: um <h1> quebrado dentro do <h3> não a troca por None.
            self._h3_date = self._date
            self._h3_buffer = []
            self._h3_chars = 0
            self._href = None
        elif tag == "a" and self._in_h3 and self._href is None:
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if self._done:
            return
        if tag == "h1" and self._in_h1:
            self._in_h1 = False
            self._date = _date_stamp("".join(self._h1_buffer))
        elif tag == "h3" and self._in_h3:
            self._in_h3 = False
            if len(self.items) < _MAX_POSTS:
                self.items.append((self._h3_date, "".join(self._h3_buffer), self._href))

    def handle_data(self, data: str) -> None:
        # Buffers limitados em caracteres: um <h1>/<h3> sem fechar acumularia o resto da página.
        if self._in_h1 and self._h1_chars < _MAX_TITLE_CHARS:
            self._h1_buffer.append(data[: _MAX_TITLE_CHARS - self._h1_chars])
            self._h1_chars += len(data)
        if self._in_h3 and self._h3_chars < _MAX_TITLE_CHARS:
            self._h3_buffer.append(data[: _MAX_TITLE_CHARS - self._h3_chars])
            self._h3_chars += len(data)


def _post(stamp: int, text: str, href: Optional[str]) -> Optional[NewsPost]:
    text = _WHITESPACE_RE.sub(" ", text).strip()
    # O texto do link ("DOWNLOAD") fica no fim do <h3>.
    text = re.sub(r"\s*DOWNLOAD$", "", text, flags=re.IGNORECASE)
    summary = ", ".join(mark.strip() for mark in _MARK_RE.findall(text) if mark.strip())
    title = _GROUP_RE.sub("", _MARK_RE.sub("", text)).strip(" +")
    if len(title) < 2:
        return None
    url = _safe_url(urljoin(PAGE_URL, href)) if href else ""
    return NewsPost(
        identifier=url or title,
        timestamp=stamp,
        title=title[:_MAX_TITLE_CHARS],
        url=url,
        summary=summary[:_MAX_TITLE_CHARS],
        category=_CATEGORY,
    )


def parse_page(html: str, now: Optional[float] = None) -> list[NewsPost]:
    """As linhas do último mês, do mais novo ao mais antigo; um jogo repetido vale pela primeira (mais nova) menção."""
    parser = _PageParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Failed to parse the ElAmigos page", exc_info=True)

    current = int(time() if now is None else now)
    posts: list[NewsPost] = []
    seen: set[str] = set()
    for stamp, text, href in parser.items:
        # Data no futuro é bloco quebrado: mesma guarda do feed da FitGirl, senão o selo ficaria aceso para sempre.
        if stamp > current + _MAX_CLOCK_SKEW_SECONDS or stamp < current - _MAX_AGE_SECONDS:
            continue
        post = _post(stamp, text, href)
        if post is None or post.identifier in seen:
            continue
        seen.add(post.identifier)
        posts.append(post)

    posts.sort(key=lambda post: post.timestamp, reverse=True)
    logging.debug("ElAmigos page yielded %d news posts", len(posts))
    return posts


def fetch_elamigos(url: str = PAGE_URL) -> list[NewsPost]:
    """Baixa e lê a página. Levanta ``requests.RequestException`` em falha de rede."""
    return parse_page(fetch_feed_text(url), now=time())
