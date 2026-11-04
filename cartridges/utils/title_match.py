# title_match.py
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

"""Compare a local game title against a store title.

String equality is too brittle (``Game™``, ``Game: Definitive Edition``, ``VI`` vs ``6``), but loosening it also matches ``The Outer Worlds`` with ``The Outer Worlds 2``, a different game. So: (1) normalization drops signs, punctuation, case, accents and articles and canonicalizes numerals; (2) the ordered numbers of a title are a hard gate (``[]`` vs ``[2]``), rejected before any scoring; (3) the remaining words are scored (edition fluff still matches, words naming separate content do not).
"""

import re
import unicodedata
from dataclasses import dataclass

SCORE_EXACT = 100  # same game, same edition
SCORE_EDITION = 90  # same game, a repackaged edition of it
SCORE_RELATED = 40  # same franchise/base title, but a distinct product
SCORE_MISMATCH = 0  # not the same game

# O menor score adotável sem perguntar ao usuário.
CONFIDENT_SCORE = SCORE_EDITION

# Palavras sem identidade própria, descartadas dos dois lados ("Witcher 3" vs "The Witcher 3").
_STOPWORDS = frozenset({"the", "a", "an", "of", "and"})

_EDITION_WORDS = frozenset(
    {
        "edition",
        "editions",
        "goty",
        "year",
        "game",
        "definitive",
        "complete",
        "collection",
        "deluxe",
        "ultimate",
        "premium",
        "anniversary",
        "enhanced",
        "extended",
        "remastered",
        "remaster",
        "hd",
        "4k",
        "redux",
        "director",
        "directors",
        "cut",
        "standard",
        "gold",
        "platinum",
        "legacy",
        "classic",
        "original",
        "special",
        "digital",
        "full",
        "version",
        "pc",
        "steam",
    }
)

# Palavras de um *produto diferente* com o mesmo título (trilha, DLC, demo, ferramenta): desqualificam o candidato, pois dão metadados errados.
_DISQUALIFYING_WORDS = frozenset(
    {
        "soundtrack",
        "soundtracks",
        "ost",
        "score",
        "album",
        "dlc",
        "expansion",
        "season",
        "pass",
        "pack",
        "bundle",
        "upgrade",
        "demo",
        "beta",
        "playtest",
        "prologue",
        "trial",
        "artbook",
        "art",
        "book",
        "comic",
        "wallpaper",
        "avatar",
        "avatars",
        "emote",
        "sdk",
        "editor",
        "server",
        "dedicated",
        "tool",
        "tools",
        "benchmark",
        "vr",
    }
)

# Lista branca, não parser geral: "MIX" e "DIC" são romanos válidos mas quase sempre palavras, e lê-los como número bloquearia um casamento correto.
_ROMAN_NUMERALS = {
    "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
}  # fmt: skip

# "one" fica de fora de propósito: é quase sempre pronome ("No One Lives Forever").
_NUMBER_WORDS = {
    "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip

_TRADEMARK_RE = re.compile("[™®©]")  # ™ ® ©
_APOSTROPHE_RE = re.compile("['’ʼ´`]")
# Separa em tudo que não é caractere de palavra (unicode) e no underscore, que serve de separador em nomes de arquivo.
# Uma classe [^a-z0-9] apagaria scripts não-latinos: "ペルソナ5" viraria ["5"] e casaria com qualquer título japonês com um 5.
_NON_ALNUM_RE = re.compile(r"[\W_]+")

# Crédito possessivo de autor no início ("Sid Meier's Civilization VI"): as lojas o trazem, os atalhos em geral não.
_POSSESSIVE_PREFIX_RE = re.compile(r"^[^:\-–—]{1,30}['’]s\s")

# Quantas palavras iniciais podem ser marca ("Disney Epic Mickey", "LEGO Star Wars") antes de parecerem outro jogo.
_MAX_BRANDING_PREFIX_WORDS = 2


def _strip_accents(text: str) -> str:
    """Acentos viram a base ASCII (``Pokémon`` → ``Pokemon``)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def tokenize(title: str) -> list[str]:
    """Tokens comparáveis de ``title``, com todo numeral canonizado. Apóstrofos são apagados (``Spacer's`` → ``spacers``), não trocados por espaço."""
    text = _strip_accents(_TRADEMARK_RE.sub("", title or ""))
    text = _APOSTROPHE_RE.sub("", text).casefold()
    text = text.replace("&", " and ")
    tokens = [token for token in _NON_ALNUM_RE.split(text) if token]

    canonical = []
    for index, token in enumerate(tokens):
        is_last = index == len(tokens) - 1
        if token.isdigit():
            # Sem zeros à esquerda ("07" = "7"), mantendo o "0".
            canonical.append(str(int(token)))
        elif token in _ROMAN_NUMERALS:
            canonical.append(str(_ROMAN_NUMERALS[token]))
        elif token in _NUMBER_WORDS:
            canonical.append(str(_NUMBER_WORDS[token]))
        elif token == "i" and is_last and index > 0:
            # Um "I" só é numeral no fim de um título maior ("The Last of Us Part I"); fora disso é o pronome.
            canonical.append("1")
        else:
            canonical.append(token)
    return canonical


def numeric_signature(tokens: list[str]) -> list[str]:
    """Os tokens numéricos em ordem, o que identifica uma sequência (``Left 4 Dead`` é ``["4"]``, ``Left 4 Dead 2`` é ``["4", "2"]``)."""
    return [token for token in tokens if token.isdigit()]


def core_words(tokens: list[str]) -> list[str]:
    return [
        token
        for token in tokens
        if not token.isdigit() and token not in _STOPWORDS
    ]


@dataclass(frozen=True)
class TitleMatch:
    """Outcome of comparing a wanted title against a store title."""

    score: int
    reason: str

    @property
    def confident(self) -> bool:
        return self.score >= CONFIDENT_SCORE


def compare_titles(wanted: str, candidate: str) -> TitleMatch:
    """Quão bem ``candidate`` identifica o mesmo jogo que ``wanted``: um :class:`TitleMatch` com ``score`` (um ``SCORE_*``) e ``reason`` para o log."""
    wanted_tokens = tokenize(wanted)
    candidate_tokens = tokenize(candidate)

    if not wanted_tokens or not candidate_tokens:
        return TitleMatch(SCORE_MISMATCH, "empty title")

    # O portão da sequência, checado primeiro: diferença aqui é outro jogo, por mais parecidas que sejam as palavras.
    wanted_numbers = numeric_signature(wanted_tokens)
    candidate_numbers = numeric_signature(candidate_tokens)
    if wanted_numbers != candidate_numbers:
        return TitleMatch(
            SCORE_MISMATCH,
            f"numeric signature {candidate_numbers} != {wanted_numbers}",
        )

    wanted_core = core_words(wanted_tokens)
    candidate_core = core_words(candidate_tokens)

    if wanted_core == candidate_core:
        return TitleMatch(SCORE_EXACT, "titles match")

    # Um título só de números e stopwords ("7", "1917", "The") passou pelo portão numérico, e um conjunto vazio é subconjunto
    # de tudo: não há veredicto honesto, e "7" não é "7 Days to Die".
    if not wanted_core:
        return TitleMatch(SCORE_MISMATCH, "no core words")

    # Tudo o que o título pedido diz precisa estar presente, senão é outro jogo com palavras em comum.
    wanted_set = set(wanted_core)
    candidate_set = set(candidate_core)
    if not wanted_set.issubset(candidate_set):
        missing = sorted(wanted_set - candidate_set)
        return TitleMatch(SCORE_MISMATCH, f"missing words {missing}")

    extras = [word for word in candidate_core if word not in wanted_set]

    # Uma trilha ou demo tem o título inteiro do jogo: só esta lista as distingue.
    if disqualifying := [w for w in extras if w in _DISQUALIFYING_WORDS]:
        return TitleMatch(SCORE_MISMATCH, f"separate product: {disqualifying}")

    # A posição das palavras extras importa: *antes* do título é crédito de editora ou autor; *depois* costuma ser a
    # edição ou um produto à parte. A busca sempre acha uma palavra (`wanted_set` não é vazio e está todo no candidato).
    first_wanted = next(
        index for index, word in enumerate(candidate_core) if word in wanted_set
    )
    prefix_extras = candidate_core[:first_wanted]
    suffix_extras = [
        word for word in candidate_core[first_wanted:] if word not in wanted_set
    ]

    if prefix_extras and not _is_branding_prefix(
        prefix_extras, candidate, len(wanted_core)
    ):
        return TitleMatch(SCORE_RELATED, f"unexpected prefix: {prefix_extras}")

    if all(word in _EDITION_WORDS for word in suffix_extras):
        return TitleMatch(SCORE_EDITION, f"edition of the same game: {extras}")

    # Palavras que nomeiam conteúdo ("Trauma", "Spacer's Choice") são outro produto: reportado, não aceito, para quem chama sugerir.
    return TitleMatch(SCORE_RELATED, f"related title: {suffix_extras}")


def _is_branding_prefix(
    prefix_extras: list[str], raw_candidate: str, wanted_word_count: int
) -> bool:
    """True se as palavras iniciais parecem crédito de editora/autor: o possessivo é inequívoco; senão um prefixo curto só é perdoado se o título pedido for específico o bastante."""
    if _POSSESSIVE_PREFIX_RE.match(raw_candidate):
        return True
    return (
        len(prefix_extras) <= _MAX_BRANDING_PREFIX_WORDS and wanted_word_count >= 2
    )


def rank_candidates(
    wanted: str,
    candidates: list[dict],
    name_key: str = "name",
) -> list[tuple[dict, TitleMatch]]:
    """Ordena os resultados da loja do melhor para o pior, descartando os que não casam.

    Empates: um Metacritic e um appid menor apontam a entrada original, a que carrega as avaliações esperadas.
    """
    scored = []
    for candidate in candidates:
        match = compare_titles(wanted, str(candidate.get(name_key, "")))
        if match.score > SCORE_MISMATCH:
            scored.append((candidate, match))

    def sort_key(entry: tuple[dict, TitleMatch]) -> tuple:
        candidate, match = entry
        has_metascore = bool(str(candidate.get("metascore") or "").strip())
        try:
            appid = int(candidate.get("id") or candidate.get("appid") or 0)
        except (TypeError, ValueError):
            appid = 0
        return (-match.score, not has_metascore, appid)

    return sorted(scored, key=sort_key)
