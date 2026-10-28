# carga.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A carga da biblioteca do disco (`games/*.json`) na abertura.

Copiado de `main.py` da versão GTK (`sanitize_game_fields` e
`load_games_from_disk`), sem a pré-decodificação das capas, que era do widget.
"""

import json
import logging
import re
from typing import Any

from cartridges import shared
from cartridges.jogo import Jogo

# O tipo de cada campo que um game_id.json persiste, fora os quatro de
# identidade (conferidos em `carregar_jogos_do_disco`). `rating` e `status` têm
# guarda própria na exibição; os demais eram aplicados por setattr sem checagem.
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
            "conquistas",
            "saves_local_desconhecido_avisado",
            "backup_dos_saves_desligado",
            "comando_a_conferir",
        ),
        bool,
    ),
    "hltb_chapters": list,
}

# Os campos cujo default na classe é None: só neles `null` quer dizer "não
# informado". Nos outros, `"version": null` virava `None > 1.6` na carga.
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
    """Descarta campos de tipo errado num registro editado à mão.

    ``"playtime": "5h"`` estourava TypeError na tela de detalhes e na
    ordenação; ``"removed": "false"`` contava como verdadeiro e o jogo sumia;
    ``"notes": 5`` derrubava os detalhes. Cai o campo, não o jogo — o default
    da classe vale como "não informado". Muta e devolve ``data``.
    """
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
    """Lê cada ficha de ``shared.games_dir`` e a entrega a ``store.add_game``.

    Devolve quantas chegaram à store sem erro. Uma ficha ruim custa só aquele
    jogo, nunca a abertura.
    """
    games: list[tuple[Jogo, str]] = []
    if shared.games_dir.is_dir():
        for game_file in shared.games_dir.iterdir():
            # Skip leftovers such as .json.tmp from an interrupted save
            if game_file.suffix != ".json":
                continue
            try:
                with game_file.open(encoding="utf-8") as open_file:
                    data = json.load(open_file)
            except (OSError, json.decoder.JSONDecodeError) as error:
                logging.warning("Skipping unreadable game record %s: %s", game_file.name, error)
                continue
            # A record missing one of the fields that has no default is not
            # loadable: `Jogo.__init__` reads `source` to derive
            # `base_source` and would raise here, outside the JSON guard
            # above, so a single corrupt file stopped the app from opening
            # at all rather than costing one game. O executável pode ser
            # vazio só numa tumba: um zerado recriado pelo backup nunca
            # teve instalação neste PC. O game_id vira nome de arquivo (capa,
            # logo, exclusão): um "..\x" de um backup alheio apontava para fora
            # da pasta do app.
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
            # Um arquivo por vez: o que escapar da limpeza acima custa esse
            # jogo, e não a janela inteira, que abre depois desta carga.
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
