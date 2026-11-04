# carga.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A carga da biblioteca do disco (`games/*.json`) na abertura."""

import json
import logging
import re
from typing import Any

from cartridges import shared
from cartridges.jogo import Jogo

_NUMBER = (int, float)
_GAME_ID_RE = re.compile(r"[A-Za-z0-9_-]+")

_GAME_FIELD_TYPES: dict[str, Any] = {
    **dict.fromkeys(
        (
            "added",
            "last_played",
            "playtime",
            "rating",
            "metacritic",
            "steam_checked",
            "hltb_id",
            "hltb_main",
            "hltb_main_extra",
            "hltb_completionist",
            "install_size",
            "install_size_ts",
            "version",
            "shortcut_mtime",
            "update_available_ts",
            "update_dismissed_ts",
        ),
        _NUMBER,
    ),
    **dict.fromkeys(
        (
            "status",
            "notes",
            "developer",
            "publisher",
            "release_date",
            "steam_review",
            "genre",
            "controller_support",
            "description",
            "steam_appid",
            "shortcut_path",
            "process_executable",
            "update_url",
            "ludusavi_nome",
        ),
        str,
    ),
    **dict.fromkeys(
        (
            "gamepad_recommended",
            "removed",
            "blacklisted",
            "run_as_admin",
            "track_process",
            "track_updates",
            "conquistas",
            "saves_local_desconhecido_avisado",
            "backup_dos_saves_desligado",
            "comando_a_conferir",
        ),
        bool,
    ),
    "hltb_chapters": list,
}

_NULLABLE_GAME_KEYS = frozenset(
    {
        "metacritic",
        "hltb_id",
        "hltb_main",
        "hltb_main_extra",
        "hltb_completionist",
        "developer",
        "publisher",
        "release_date",
        "steam_review",
        "genre",
        "controller_support",
        "description",
        "steam_appid",
        "hltb_chapters",
    }
)


def sanitize_game_fields(data: dict, record_name: str) -> dict:
    for key, expected in _GAME_FIELD_TYPES.items():
        if key not in data:
            continue
        value = data[key]
        if value is None and key in _NULLABLE_GAME_KEYS:
            continue
        valid = isinstance(value, expected) and not (
            key == "hltb_chapters"
            and not all(isinstance(chapter, dict) for chapter in value)
        )
        if not valid:
            logging.warning("Campo %s inválido em %s, ignorado", key, record_name)
            del data[key]
    return data


def carregar_jogos_do_disco(store: Any) -> int:
    """Lê cada ficha de ``shared.games_dir`` e a entrega a ``store.add_game``; devolve quantas chegaram sem erro."""
    games: list[tuple[Jogo, str]] = []
    if shared.games_dir.is_dir():
        for game_file in shared.games_dir.iterdir():
            if game_file.suffix != ".json":
                continue
            try:
                with game_file.open(encoding="utf-8") as open_file:
                    data = json.load(open_file)
            except (OSError, json.decoder.JSONDecodeError) as error:
                logging.warning("Skipping unreadable game record %s: %s", game_file.name, error)
                continue
            # Um registro sem um dos campos sem default não é carregável: o `Jogo.__init__` lê `source` fora do guarda
            # do JSON, e um arquivo corrompido derrubaria a abertura inteira.
            if (
                not isinstance(data, dict)
                or not all(
                    isinstance(data.get(key), str) and data[key]
                    for key in ("source", "game_id", "name")
                )
                or not _GAME_ID_RE.fullmatch(data["game_id"])
                or not isinstance(data.get("executable"), str)
                or not (data["executable"] or data.get("removed") is True)
            ):
                logging.warning("Skipping malformed game record %s", game_file.name)
                continue
            try:
                games.append((Jogo(sanitize_game_fields(data, game_file.name)), game_file.name))
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Skipping unloadable game record %s", game_file.name)

    carregados = 0
    for game, name in games:
        try:
            store.add_game(game, {"skip_save": True})
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Skipping unloadable game record %s", name)
        else:
            carregados += 1
    return carregados
