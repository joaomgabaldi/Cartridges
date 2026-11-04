# news_feed.py
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

"""Lê o feed RSS do site de repacks como *novidades*: tudo o que não é um digest.

:mod:`cartridges.utils.updates_feed` quer os digests (aviso de patch por jogo); este módulo quer o resto e descarta os digests, que na página de Novidades seriam um muro de markup de spoiler (e uma novidade nunca vai ao casador de atualizações, que a confundiria com um patch). Só o que uma linha da lista mostra é guardado: título, link, data e um trecho do resumo.
"""

import logging
import re
from dataclasses import dataclass
from html.parser import HTMLParser

# pylint: disable=protected-access
# O leitor de digests é dono do transporte e das convenções de data e título do feed.
from cartridges.utils.updates_feed import (
    FEED_URL,
    _MAX_FEED_BYTES,
    _MAX_TITLE_CHARS,
    _parse_timestamp,
    _safe_url,
    fetch_feed_text,
    is_update_digest,
    parse_xml,
)

# O WordPress põe o resumo em <description> e o corpo inteiro neste elemento; o resumo é preferido.
_CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"

# Guarda contra um post que traga o corpo inteiro em <description>; as linhas mostram o texto todo.
_SUMMARY_MAX_CHARS = 4000

# O WordPress anexa um "leia o resto" ao resumo; sobrevive à remoção das tags como frase solta.
_TEASER_RE = re.compile(
    r"\s*(continue reading|read more|leia mais)\b.*$", re.IGNORECASE | re.DOTALL
)

_WHITESPACE_RE = re.compile(r"\s+")

_SKIPPED_TAGS = frozenset({"script", "style"})

# Teto de linhas por feed.
_MAX_POSTS = 500

# Teto da categoria, mostrada na mesma linha da data.
_MAX_CATEGORY_CHARS = 120


@dataclass(frozen=True)
class NewsPost:
    """Um post do feed, reduzido ao que uma linha da lista mostra."""

    identifier: str  # guid ou link; distingue os posts, não os ordena
    timestamp: int  # pubDate em segundos; a chave de ordenação
    title: str
    url: str  # "" sem link
    summary: str
    category: str  # primeira <category>, mostrada como etiqueta


class _TextExtractor(HTMLParser):
    """O texto visível de um fragmento HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.chunks.append(data)


def strip_html(fragment: str) -> str:
    """O texto puro de um fragmento HTML, com espaços colapsados. Fragmento malformado devolve o que foi lido, sem levantar."""
    parser = _TextExtractor()
    try:
        parser.feed(fragment or "")
        parser.close()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.debug("Failed to parse a news post summary", exc_info=True)

    return _WHITESPACE_RE.sub(" ", "".join(parser.chunks)).strip()


def summarize(fragment: str, max_chars: int = _SUMMARY_MAX_CHARS) -> str:
    """O resumo HTML de um post em texto puro, inteiro: o limite só pega corpo descontrolado, cortando em fim de palavra com reticências."""
    # Tirar o "leia o resto" deixa o travessão que o introduzia; o "…" final fica e o ponto final nunca sai.
    text = _TEASER_RE.sub("", strip_html(fragment)).strip(" \t–—-")
    if len(text) <= max_chars:
        return text

    head = text[: max_chars + 1]
    cut = head.rfind(" ")
    return (head[:cut] if cut > 0 else text[:max_chars]).rstrip(",;:.") + "…"


def parse_news(xml_text: str) -> list[NewsPost]:
    """Os posts legíveis do feed, do mais novo ao mais antigo; pula digests e itens sem título."""
    root = parse_xml(xml_text)
    if root is None:
        return []

    posts: list[NewsPost] = []
    seen: set[str] = set()
    for item in root.iter("item"):
        if len(posts) >= _MAX_POSTS:
            logging.warning("Repack feed carried more than %d posts", _MAX_POSTS)
            break

        title = _WHITESPACE_RE.sub(" ", (item.findtext("title") or "")).strip()
        if not title:
            continue
        if is_update_digest(title):
            continue
        title = title[:_MAX_TITLE_CHARS]

        # O link é aberto no navegador: passa pela mesma guarda de esquema da URL de um digest.
        link = _safe_url(item.findtext("link"))
        identifier = (item.findtext("guid") or link or title).strip()

        # Um guid repetido (republicação, documento concatenado) empilharia linhas iguais.
        if identifier in seen:
            continue
        seen.add(identifier)

        summary = summarize(
            item.findtext("description") or item.findtext(_CONTENT_NS) or ""
        )
        category = (item.findtext("category") or "").strip()[:_MAX_CATEGORY_CHARS]

        posts.append(
            NewsPost(
                identifier=identifier,
                timestamp=_parse_timestamp(item.findtext("pubDate") or ""),
                title=title,
                url=link,
                summary=summary,
                category=category,
            )
        )

    posts.sort(key=lambda post: post.timestamp, reverse=True)
    logging.debug("Repack feed yielded %d news posts", len(posts))
    return posts


def fetch_news(
    url: str = FEED_URL, timeout: float = 15, max_bytes: int = _MAX_FEED_BYTES
) -> list[NewsPost]:
    """Baixa e lê o feed. Levanta ``requests.RequestException`` em falha de rede; quem chama a trata como "nada novo"."""
    return parse_news(fetch_feed_text(url, timeout, max_bytes))
