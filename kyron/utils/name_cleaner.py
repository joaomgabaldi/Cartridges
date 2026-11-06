# name_cleaner.py
#
# Copyright 2024 kramo
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

"""Normaliza nomes de jogo vindos de atalhos e arquivos (``Game (DX12)``, ``Game™``, ``Game - Shortcut``).

``clean_game_name`` tira esse ruído com cautela e nunca devolve texto vazio.
"""

import re

_NOISE_TOKENS = {
    "windows",
    "win32",
    "win64",
    "dx9",
    "dx10",
    "dx11",
    "dx12",
    "directx",
    "directx9",
    "directx10",
    "directx11",
    "directx12",
    "vulkan",
    "opengl",
    "x64",
    "x86",
    "32bit",
    "64bit",
}

# Ruído só entre colchetes: "Hades (PC)" é Hades, mas "PC Building Simulator" é um título.
_BRACKET_NOISE_TOKENS = _NOISE_TOKENS | {
    "pc",
    "steam",
    "epic",
    "gog",
    "uwp",
    "origin",
    "battlenet",
}

_TRADEMARK_RE = re.compile("[™®©]")  # ™ ® ©
_BRACKETS_RE = re.compile(r"\s*[\(\[\{][^)\]}]*[\)\]\}]")  # (...), [...], {...}
_SHORTCUT_SUFFIX_RE = re.compile(
    r"\s*[-–—]\s*"
    r"(shortcut|atalho|acceso\s+directo|raccourci|verkn[üu]pfung)\s*$",
    re.IGNORECASE,
)
_LAUNCH_PREFIX_RE = re.compile(
    r"^\s*(play|launch|start|jogar|iniciar)\s+", re.IGNORECASE
)
_DIRECTX_PHRASE_RE = re.compile(r"\bdirectx\s*1?[0-2]\b", re.IGNORECASE)
_WS_RE = re.compile(r"\s{2,}")
_SEARCH_SEPARATORS_RE = re.compile(r"[-–—:;,./]+")
# Apóstrofos tipográficos viram o ASCII nas buscas: as lojas indexam a forma reta ("Assassin’s" não achava nada).
_APOSTROPHE_RE = re.compile("[’ʼ‘‛´`]")


def _normalize(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def _is_noise(token: str) -> bool:
    return _normalize(token) in _NOISE_TOKENS


def _strip_noise_brackets(match: re.Match) -> str:
    """Tira o grupo entre colchetes só de ruído, ou vazio ("(DirectX 12)" já foi esvaziado antes)."""
    inner = _normalize(match.group(0))
    return " " if not inner or inner in _BRACKET_NOISE_TOKENS else match.group(0)


def clean_game_name(name: str) -> str:
    if not name:
        return name

    cleaned = name.strip()

    for ext in (".lnk", ".url"):
        if cleaned.lower().endswith(ext):
            cleaned = cleaned[: -len(ext)]

    cleaned = cleaned.replace("_", " ")

    cleaned = _TRADEMARK_RE.sub("", cleaned)
    cleaned = _SHORTCUT_SUFFIX_RE.sub("", cleaned)
    cleaned = _LAUNCH_PREFIX_RE.sub("", cleaned)
    cleaned = _DIRECTX_PHRASE_RE.sub(" ", cleaned)
    cleaned = _BRACKETS_RE.sub(_strip_noise_brackets, cleaned)

    tokens = cleaned.split()
    kept = [token for token in tokens if not _is_noise(token)]
    cleaned = " ".join(kept if kept else tokens)

    cleaned = _WS_RE.sub(" ", cleaned).strip(" -–—")
    return cleaned or name.strip()


def clean_for_search(name: str) -> str:
    """``clean_game_name`` para buscas online: separadores viram espaço e apóstrofos viram ASCII.

    Steam e SteamGridDB erram "Black Myth - Wukong" mas acham "Black Myth Wukong". Só para a consulta, nunca para exibir.
    """
    display = clean_game_name(name)
    cleaned = _SEARCH_SEPARATORS_RE.sub(" ", _APOSTROPHE_RE.sub("'", display))
    return re.sub(r"\s+", " ", cleaned).strip() or display
