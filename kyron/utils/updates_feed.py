# updates_feed.py
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

"""Read the repack site's RSS feed and pull the patched-game lists out of it.

The site blocks HTML scraping behind Cloudflare; the RSS feed is served straight through. Only the periodic *Updates Digest* matters: each patched game is a collapsible spoiler shaped like this::

    <div class="su-spoiler ...">
      <div class="su-spoiler-title"><span class="su-spoiler-icon"></span>Game</div>
      <div class="su-spoiler-content ...">
        <a href="https://fitgirl-repacks.site/game/">Repack page</a>
        ... download links ...
      </div>
    </div>

From each spoiler the *title* (bare game name, for matching) and the *Repack page* link are kept; file-host anchors and ``.rar`` items are ignored (read as a title they yield noise or a numeric signature).
"""

import logging
import re
from datetime import timezone
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from time import time
from typing import Optional
from xml.etree import ElementTree

lazy import requests

# O TLS importa: tudo o que este módulo devolve é confiado adiante (nomes guiam o casador, URLs vão ao JSON do jogo e ao
# navegador, corpos são exibidos). Em texto claro um proxy poderia reescrever os três, então o feed só é lido por https.
FEED_URL = "https://fitgirl-repacks.site/feed/"

# Comparado sem diferenciar maiúsculas com o título sem espaços nas pontas.
_DIGEST_TITLE_PREFIX = "updates digest"

_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"

# O contêiner tem só o token ``su-spoiler``; o cabeçalho e o corpo acrescentam um sufixo.
_SPOILER_CLASS = "su-spoiler"
_SPOILER_TITLE_CLASS = "su-spoiler-title"
_SPOILER_CONTENT_CLASS = "su-spoiler-content"

# O link da página de repack do jogo (não os de download), achado pelo texto da âncora.
_REPACK_LINK_TEXT = "repack page"

# O feed é pequeno, mas o teto limita uma resposta hostil.
_MAX_FEED_BYTES = 8 * 1024 * 1024

# Alguns hosts devolvem uma página de bot a um user agent vazio.
_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Cartridges/updates-feed"

_WHITESPACE_RE = re.compile(r"\s+")

# Tetos para um documento hostil ou quebrado não virar alocação; um digest real tem dezenas de jogos, e estes limites
# ficam uma ordem de grandeza acima, aplicados em silêncio.
_MAX_ENTRIES = 2000  # spoilers taken from a single digest body
_MAX_TITLE_CHARS = 300  # characters kept from one spoiler header
_MAX_URL_CHARS = 2048  # characters kept from one href

# Só estes dois esquemas sobrevivem: a URL é gravada no JSON do jogo e chega ao navegador (`abrir_url` também guarda), e um `javascript:`/`file:` não deve chegar ao disco.
_ALLOWED_URL_SCHEMES = ("http://", "https://")

# Uma pubDate muito à frente do relógio é post quebrado ou tentativa de envenenar a dispensa: `Game.dismiss_update` grava o
# timestamp em `update_dismissed_ts`, e um post do ano 3000 silenciaria o jogo para sempre.
_MAX_CLOCK_SKEW_SECONDS = 7 * 24 * 3600

# XML com DTD é recusado: o `xml.etree` expande entidades sem limite ("billion laughs"), e um feed não tem motivo para
# doctype, o que fecha a classe de ataques sem um parser de terceiros.
_DOCTYPE_RE = re.compile(r"<!DOCTYPE", re.IGNORECASE)

_ELEMENT_START_RE = re.compile(r"<[A-Za-z_]")


def _prolog_end(xml_text: str) -> int:
    """O índice onde o prólogo termina: o primeiro `<` que abre um elemento.

    Comentários e instruções de processamento são pulados por inteiro: um regex solto achava o `<a` dentro de um
    comentário e deixava um DOCTYPE real fora da busca. Um comentário ou PI sem fechamento estende o prólogo até o
    fim, o que só erra para o lado de recusar o feed.
    """
    position = 0
    length = len(xml_text)
    while position < length:
        start = xml_text.find("<", position)
        if start == -1:
            return length
        if xml_text.startswith("<?", start):
            end = xml_text.find("?>", start + 2)
            if end == -1:
                return length
            position = end + 2
        elif xml_text.startswith("<!--", start):
            end = xml_text.find("-->", start + 4)
            if end == -1:
                return length
            position = end + 3
        elif _ELEMENT_START_RE.match(xml_text, start):
            return start
        else:
            # `<!DOCTYPE`, `<!` de subset interno ou lixo: segue dentro do prólogo.
            position = start + 1
    return length


@dataclass(frozen=True)
class DigestEntry:
    """One patched game named in a digest: its title and its repack page."""

    name: str
    url: str  # "" sem link


@dataclass(frozen=True)
class UpdatePost:
    """One *Updates Digest* post reduced to what the checker needs."""

    identifier: str  # guid ou link, só para logs
    timestamp: int  # pubDate em segundos; a chave de ordenação
    title: str
    entries: tuple[DigestEntry, ...]

class _DigestParser(HTMLParser):
    """Extract ``(title, repack url)`` for every spoiler in a digest body.

    ``su-spoiler`` bounds one game, ``su-spoiler-title`` holds the name and the first "Repack page" anchor in
    ``su-spoiler-content`` the link. An entry is emitted when the container closes, so a spoiler without a link still yields its name.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[DigestEntry] = []
        self._div_depth = 0

        self._in_spoiler = False
        self._spoiler_depth = 0
        self._name: Optional[str] = None
        self._url: Optional[str] = None

        self._capturing_title = False
        self._title_depth = 0
        self._title_buffer: list[str] = []

        self._in_content = False
        self._content_depth = 0

        self._in_anchor = False
        self._anchor_href: Optional[str] = None
        self._anchor_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "div":
            classes = (dict(attrs).get("class") or "").split()
            if _SPOILER_CLASS in classes and not self._in_spoiler:
                self._in_spoiler = True
                self._spoiler_depth = self._div_depth
                self._name = None
                self._url = None
            if _SPOILER_TITLE_CLASS in classes and not self._capturing_title:
                self._capturing_title = True
                self._title_depth = self._div_depth
                self._title_buffer = []
            if _SPOILER_CONTENT_CLASS in classes and not self._in_content:
                self._in_content = True
                self._content_depth = self._div_depth
            self._div_depth += 1
        elif tag == "a" and not self._in_anchor:
            # Âncoras não aninham em HTML válido; num corpo mutilado, ignorar a segunda preserva a primeira.
            self._in_anchor = True
            self._anchor_href = dict(attrs).get("href")
            self._anchor_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "div":
            # Com piso, e as seções fecham em `<=`, não `==`: um `</div>` solto (comum em posts escritos à mão) levava o contador a negativos.
            self._div_depth = max(0, self._div_depth - 1)
            if self._capturing_title and self._div_depth <= self._title_depth:
                self._capturing_title = False
                self._name = "".join(self._title_buffer).strip() or self._name
                self._title_buffer = []
            if self._in_content and self._div_depth <= self._content_depth:
                self._in_content = False
            if self._in_spoiler and self._div_depth <= self._spoiler_depth:
                self._in_spoiler = False
                if self._name and len(self.entries) < _MAX_ENTRIES:
                    self.entries.append(
                        DigestEntry(self._name, _safe_url(self._url))
                    )
                self._name = None
                self._url = None
        elif tag == "a" and self._in_anchor:
            self._in_anchor = False
            text = "".join(self._anchor_buffer).strip()
            self._anchor_buffer = []
            # Vale o primeiro link "Repack page"; as âncoras de download seguintes são ignoradas.
            if (
                self._in_content
                and self._url is None
                and text.casefold() == _REPACK_LINK_TEXT
            ):
                self._url = self._anchor_href or ""

    def handle_data(self, data: str) -> None:
        # Os dois buffers são limitados: um `su-spoiler-title` sem fechar acumularia o resto do documento.
        if self._capturing_title and len(self._title_buffer) < _MAX_TITLE_CHARS:
            self._title_buffer.append(data)
        if self._in_anchor and len(self._anchor_buffer) < _MAX_TITLE_CHARS:
            self._anchor_buffer.append(data)


def _safe_url(raw: Optional[str]) -> str:
    """``raw`` se for uma URL web simples que aceitamos guardar, senão "". Vem de um documento de terceiros e é gravada no JSON do jogo, então o esquema é checado na entrada."""
    url = (raw or "").strip()
    if not url:
        return ""
    if len(url) > _MAX_URL_CHARS:
        logging.warning("Dropping over-long URL from the repack feed")
        return ""
    if not url.lower().startswith(_ALLOWED_URL_SCHEMES):
        logging.warning("Dropping feed URL with unexpected scheme: %r", url[:120])
        return ""
    return url


def parse_xml(xml_text: str) -> Optional[ElementTree.Element]:
    """Parse a feed document, refusing anything that declares a DTD (shared by both readers, so the guard cannot be forgotten in one).

    :returns: the root element, or None when unusable; callers treat that like an empty feed.
    """
    if not xml_text:
        return None

    # Só o prólogo pode ter doctype: varrer só esse trecho evita que um "<!DOCTYPE" literal num corpo de post (inofensivo) recuse o feed.
    if _DOCTYPE_RE.search(xml_text, 0, _prolog_end(xml_text)):
        logging.warning("Refusing repack feed: document declares a DTD")
        return None

    try:
        return ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        logging.warning("Repack feed was not valid XML")
        return None


def _normalize_title(raw: str) -> Optional[str]:
    """Whitespace-normalise a spoiler title (already bare: no build note or version), or None if it is not a real name."""
    text = _WHITESPACE_RE.sub(" ", raw or "").strip()
    if len(text) < 2:
        return None
    # Além do teto não é um nome que o casador confirmaria, e seguiria para o aviso e para toda comparação.
    return text[:_MAX_TITLE_CHARS]


def extract_entries(content_html: str) -> list[DigestEntry]:
    """The de-duplicated ``(name, url)`` entries of a digest body, in order (first mention wins)."""
    parser = _DigestParser()
    try:
        parser.feed(content_html or "")
        parser.close()
    except Exception:  # pylint: disable=broad-exception-caught
        # Um corpo malformado não derruba a leitura do feed: este post não rende nada.
        logging.warning("Failed to parse an update digest body", exc_info=True)
        return []

    entries: list[DigestEntry] = []
    seen: set[str] = set()
    for entry in parser.entries:
        name = _normalize_title(entry.name)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        entries.append(DigestEntry(name, entry.url))
    return entries


def is_update_digest(title: Optional[str]) -> bool:
    return bool(title) and title.strip().casefold().startswith(_DIGEST_TITLE_PREFIX)


def _parse_timestamp(pubdate: Optional[str]) -> int:
    """Convert an RSS ``pubDate`` to epoch seconds, 0 when unusable.

    Two corrections, since the number is compared with values persisted on disk: a date without a usable
    timezone is read as UTC (RFC 5322), not in the machine's zone (up to fourteen hours off); and a date far in
    the future is rejected, since ``Game.dismiss_update`` stores it as the floor for every future notice.
    """
    if not pubdate:
        return 0
    try:
        parsed = parsedate_to_datetime(pubdate)
    except (TypeError, ValueError, OverflowError):
        return 0

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    try:
        stamp = int(parsed.timestamp())
    except (OSError, OverflowError, ValueError):
        return 0

    if stamp < 0:
        return 0
    if stamp > int(time()) + _MAX_CLOCK_SKEW_SECONDS:
        logging.warning("Ignoring implausible feed date %r", pubdate[:120])
        return 0
    return stamp


def parse_feed(xml_text: str) -> list[UpdatePost]:
    """Parse a feed document into digest posts, newest first.

    Non-digest posts and digests with no extractable game are skipped; the latter is logged, the fingerprint of the site changing its markup.
    """
    root = parse_xml(xml_text)
    if root is None:
        return []

    posts: list[UpdatePost] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()[:_MAX_TITLE_CHARS]
        if not is_update_digest(title):
            continue

        content = item.findtext(_CONTENT_NS) or item.findtext("description") or ""
        entries = extract_entries(content)
        if not entries:
            logging.warning("Update digest %r yielded no game names", title)
            continue

        identifier = (item.findtext("guid") or item.findtext("link") or title).strip()[
            :_MAX_URL_CHARS
        ]
        timestamp = _parse_timestamp(item.findtext("pubDate"))
        logging.debug(
            "Digest %r (%d): %s",
            title,
            timestamp,
            ", ".join(entry.name for entry in entries),
        )

        posts.append(
            UpdatePost(
                identifier=identifier,
                timestamp=timestamp,
                title=title,
                entries=tuple(entries),
            )
        )

    posts.sort(key=lambda post: post.timestamp, reverse=True)
    return posts


def fetch_feed_text(
    url: str = FEED_URL, timeout: float = 15, max_bytes: int = _MAX_FEED_BYTES
) -> str:
    """Download the feed document as text, capping the response size.

    Shared by the digest parser here and :mod:`kyron.utils.news_feed`, so the transport (cap, user agent,
    encoding fallback) exists once. Raises ``requests.RequestException``; callers treat a failed poll as "no news".
    """
    with requests.get(
        url,
        timeout=timeout,
        stream=True,
        headers={"User-Agent": _USER_AGENT, "Accept": "application/rss+xml, */*"},
    ) as response:
        response.raise_for_status()

        buffer = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                logging.warning("Repack feed exceeded %d bytes; truncating", max_bytes)
                break

        # `response.encoding` é palpite do requests: sem charset explícito devolve ISO-8859-1 (RFC 2616) e estraga um feed UTF-8,
        # e um título com mojibake não casa mais com o da biblioteca. Só vale o cabeçalho que declara charset.
        content_type = response.headers.get("Content-Type", "")
        declared = response.encoding if "charset=" in content_type.lower() else None

    return _decode(bytes(buffer), declared)


def _decode(raw: bytes, declared: Optional[str]) -> str:
    for encoding in (declared, _declared_xml_encoding(raw), "utf-8"):
        if not encoding:
            continue
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    # Nada decodificou limpo: guarda o legível em vez de perder a consulta por um byte.
    return raw.decode("utf-8", errors="replace")


def _declared_xml_encoding(raw: bytes) -> Optional[str]:
    match = re.match(
        rb"""\s*<\?xml[^>]*?encoding\s*=\s*["']([A-Za-z0-9._\-]+)["']""", raw[:512]
    )
    return match.group(1).decode("ascii", errors="replace") if match else None


def fetch_feed(
    url: str = FEED_URL, timeout: float = 15, max_bytes: int = _MAX_FEED_BYTES
) -> list[UpdatePost]:
    """Download and parse the feed into digest posts. Raises as :func:`fetch_feed_text`."""
    return parse_feed(fetch_feed_text(url, timeout, max_bytes))
