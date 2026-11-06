# logo_arquivos.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os arquivos do logo de um jogo: o que a store precisa para mover e apagar."""

from pathlib import Path
from typing import Optional

from kyron import shared

IMAGE_SUFFIXES = (".png", ".webp", ".jpg", ".jpeg")


def sidecar_path(game_id: str) -> Path:
    return shared.logos_dir / f"{game_id}.json"


def remove_logo(game_id: str, keep: Optional[str] = None) -> None:
    for suffix in IMAGE_SUFFIXES:
        path = shared.logos_dir / f"{game_id}{suffix}"
        if path.name != keep:
            path.unlink(missing_ok=True)

    if keep is None:
        sidecar_path(game_id).unlink(missing_ok=True)
