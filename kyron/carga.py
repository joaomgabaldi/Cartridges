# carga.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A carga da biblioteca do disco (`games/*.json`) na abertura."""

import json
import logging
import re
from typing import Any

from kyron import shared
from kyron.jogo import Jogo, capas_do_disco

# O tipo de cada campo que um game_id.json persiste, fora os de identidade (conferidos em `carregar_jogos_do_disco`).
_NUMBER = (int, float)
# Todo id que o app gera: `imported_12`, `shortcuts_<hash>`.
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
            "aviso_dos_inis_ligado",
            "conquistas",
            "saves_local_desconhecido_avisado",
            "backup_dos_saves_desligado",
            "comando_a_conferir",
            "appid_manual",
        ),
        bool,
    ),
    "hltb_chapters": list,
}

# Campos cujo default é None: só neles `null` é "não informado" (`"version": null` virava `None > 1.6`).
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
    """Descarta campos de tipo errado num registro editado à mão: cai o campo, não o jogo. Muta e devolve ``data``."""
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
    """Lê cada arquivo de ``shared.games_dir`` e o entrega a ``store.add_game``; devolve quantos chegaram sem erro."""
    games: list[tuple[Jogo, str]] = []
    if shared.games_dir.is_dir():
        for game_file in shared.games_dir.iterdir():
            # Ignora sobras como .json.tmp de uma gravação interrompida.
            if game_file.suffix != ".json":
                continue
            try:
                with game_file.open(encoding="utf-8") as open_file:
                    data = json.load(open_file)
            except (OSError, json.decoder.JSONDecodeError) as error:
                logging.warning("Skipping unreadable game record %s: %s", game_file.name, error)
                continue
            # `Jogo.__init__` lê `source` fora do guarda do JSON: sem ele a abertura inteira cairia. O executável vazio só vale
            # num jogo zerado recriado por backup. O game_id vira nome de arquivo: um "..\x" de backup alheio saía da pasta.
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
            # Um arquivo por vez: o que escapar da limpeza acima custa esse jogo, não a janela inteira.
            try:
                games.append((Jogo(sanitize_game_fields(data, game_file.name)), game_file.name))
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Skipping unloadable game record %s", game_file.name)

    carregados = 0
    with capas_do_disco():
        for game, name in games:
            try:
                store.add_game(game, {"skip_save": True})
            except Exception:  # pylint: disable=broad-exception-caught
                logging.exception("Skipping unloadable game record %s", name)
            else:
                carregados += 1
    return carregados
