# game_logo.py
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

"""The official horizontal logo shown as the details page header.

It replaces the game's title, so everything stays inside the space a title occupies; nothing is invented locally. Every lookup is remembered on disk: a hit for good (only renaming the game or picking another by hand replaces it), a miss for a week.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

lazy import requests
from PIL import Image

from kyron import shared
from kyron.jogo import Jogo as Game
from kyron.utils.download import download_bytes
from kyron.utils.gravar_atomico import gravar_atomico
from kyron.utils.ler_json import ler_json
from kyron.utils.logo_arquivos import IMAGE_SUFFIXES, remove_logo  # noqa: F401  (reexportados)
from kyron.utils.logo_arquivos import sidecar_path as _sidecar_path
from kyron.utils.steamgriddb import SgdbAuthError, SgdbError, SgdbHelper

# Limites do cabeçalho. A altura é o controle principal (varia bem menos que a largura entre jogos); a largura é a rede de
# segurança contra um wordmark muito largo. 360px fica um pouco além do cartão do HowLongToBeat abaixo.
LOGO_MAX_HEIGHT = 72
LOGO_MAX_WIDTH = 360
# Assets pequenos só são ampliados até ficarem legíveis, nunca para encher a caixa.
LOGO_MIN_HEIGHT = 44

# Um logo precisa ser horizontal para servir de cabeçalho; os quase quadrados (ícones, selos) são o que a categoria "logo" do SteamGridDB traz quando não há wordmark.
MIN_ASPECT_RATIO = 1.3

# Teto de DIMENSÃO, além do de bytes: o loader de PNG decodifica a imagem inteira na thread principal a cada visita, e um
# upload de 15000x8000 px cabe em 25 MiB. O ranking desempata para o maior, então sem isto o desmedido ganha.
MAX_SOURCE_DIMENSION = 4096

# A página é desenhada sobre uma capa escura e borrada: o logo preto fica invisível, então vem por último.
STYLE_RANK = {"official": 3, "white": 2, "custom": 1, "black": -2}

# Formatos com transparência: um JPEG traz um retângulo de fundo embutido e perde para qualquer alternativa.
# `.webp` é recusado em `_usable`, então não entra aqui.
TRANSPARENT_SUFFIXES = (".png",)

# Quanto vale a resposta "este jogo não tem logo".
MISS_TTL_SECONDS = 7 * 24 * 60 * 60


def logo_display_size(
    width: int,
    height: int,
    max_width: int = LOGO_MAX_WIDTH,
    max_height: int = LOGO_MAX_HEIGHT,
) -> tuple[int, int]:
    """Clamp an intrinsic logo size to the header box (default: the details page's), keeping its ratio.

    Returned as an exact pair, given verbatim to the picture, so the ratio is preserved by construction.
    """
    if width <= 0 or height <= 0:
        return (0, 0)

    scale = min(max_height / height, max_width / width)
    if scale > 1:
        # Ampliar é último recurso e para assim que o logo tem altura de título.
        scale = min(scale, max(1.0, LOGO_MIN_HEIGHT / height))

    return (max(1, round(width * scale)), max(1, round(height * scale)))


def _intrinsic_size(path: Path) -> Optional[tuple[int, int]]:
    try:
        with Image.open(path) as image:
            return image.size
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def load_logo(
    path: Path, max_width: int = LOGO_MAX_WIDTH, max_height: int = LOGO_MAX_HEIGHT
) -> Optional[tuple[Path, int]]:
    """Check a cached logo and size it for the header.

    Returns the path and the width in logical pixels; the height is left to the page, derived from the image's own proportions, so the logo is never stretched.
    """
    size = _intrinsic_size(path)
    if not size:
        return None
    # O mesmo teto do fetch, para o arquivo escolhido à mão: as dimensões vêm do cabeçalho, sem decodificar.
    if max(size) > MAX_SOURCE_DIMENSION:
        logging.debug("Logo %s excede %d px, ignorado", path, MAX_SOURCE_DIMENSION)
        return None

    width, height = logo_display_size(*size, max_width, max_height)
    if not (width and height):
        return None
    return (path, width)


def _read_sidecar(game_id: str) -> Optional[dict[str, Any]]:
    try:
        data = ler_json(_sidecar_path(game_id))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        logging.warning("Unreadable logo sidecar %s: %s", _sidecar_path(game_id).name, error)
        return None
    return data if isinstance(data, dict) else None


def _write_sidecar(
    game_id: str, name: str, filename: Optional[str], locked: bool = False
) -> None:
    data = {
        "name": name,
        "file": filename,
        "timestamp": int(time.time()),
        # Travado: decidido pelo usuário, nunca rebuscado nem recasado com o título.
        "locked": locked,
    }
    # Temporário + replace: um sidecar truncado lê como "nunca buscado", e a busca seguinte apagava o logo escolhido.
    # Nome único porque buscas de jogos diferentes (e a do seletor) gravam em paralelo.
    try:
        gravar_atomico(_sidecar_path(game_id), json.dumps(data))
    except OSError as error:
        logging.debug("Could not record logo lookup for %s: %s", game_id, error)


def _cached_file(sidecar: Optional[dict[str, Any]]) -> Optional[Path]:
    if not sidecar:
        return None

    filename = str(sidecar.get("file") or "")
    # Só um nome solto: um caminho absoluto ou de rede vindo de um backup abriria arquivos fora da pasta.
    if not filename or Path(filename).name != filename:
        return None

    path = shared.logos_dir / filename
    return path if path.is_file() else None


def cached_logo_path(game: Game) -> Optional[Path]:
    """The logo on disk for ``game``, if one applies to it right now.

    An automatically fetched logo cached under a different name does not count (a header with the previous
    game's branding is worse than the plain title); a logo the user picked is exempt. Age never disqualifies
    a logo on disk: only "no logo" ages (see `_miss_expired`).
    """
    sidecar = _read_sidecar(game.game_id)
    if not sidecar:
        return None
    # Um jogo zerado nunca busca de novo (`logo_lookup_needed`): nem o nome nem a validade podem descartar o logo dele.
    if sidecar.get("locked") or getattr(game, "removed", False):
        return _cached_file(sidecar)
    if sidecar.get("name") != game.name:
        return None
    return _cached_file(sidecar)


def _miss_expired(sidecar: dict[str, Any]) -> bool:
    """Whether an automatic "no logo" answer is old enough to ask again.

    Um logo em disco nunca vence; um acerto cujo arquivo sumiu conta como "sem logo" (o cache foi esvaziado).
    """
    if _cached_file(sidecar):
        return False
    try:
        age = time.time() - float(sidecar.get("timestamp", 0))
    except (TypeError, ValueError):
        return True
    return age > MISS_TTL_SECONDS


def logo_choice(game: Game) -> str:
    """How ``game``'s header is currently decided: automatic, manual or title."""
    sidecar = _read_sidecar(game.game_id)
    if not sidecar or not sidecar.get("locked"):
        return "auto"
    return "manual" if _cached_file(sidecar) else "title"


def save_manual_logo(game_id: str, name: str, source: Path) -> Optional[Path]:
    """Adopt ``source`` as ``game_id``'s logo, chosen by hand. Locks it."""
    suffix = source.suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        suffix = ".png"

    filename = f"{game_id}{suffix}"
    destination = shared.logos_dir / filename
    try:
        shared.logos_dir.mkdir(parents=True, exist_ok=True)
        remove_logo(game_id, keep=filename)
        destination.write_bytes(source.read_bytes())
    except OSError as error:
        logging.warning("Could not save the chosen logo for %s: %s", game_id, error)
        return None

    _write_sidecar(game_id, name, filename, locked=True)
    return destination


def use_title_instead(game_id: str, name: str) -> None:
    """Record that ``game_id`` should show its title, not a logo.

    Stored as a locked lookup with no image, not as a deletion, so the automatic fetch does not put a logo back.
    """
    remove_logo(game_id)
    _write_sidecar(game_id, name, None, locked=True)


def reset_logo(game_id: str) -> None:
    """Forget every decision about ``game_id``'s logo, manual ones included; the ordinary lookup runs again."""
    remove_logo(game_id)


def logo_lookup_needed(game: Game) -> bool:
    """Whether ``game`` is worth asking SteamGridDB about right now.

    No for a game with a logo, one whose miss is still fresh, and without an API key. A renamed game always
    needs a new lookup: the cached asset matched the old title, and a wrong logo is worse than none.
    """
    if not shared.schema.get_string("sgdb-key"):
        return False

    if game.blacklisted or game.removed:
        return False

    sidecar = _read_sidecar(game.game_id)
    if not sidecar:
        return True

    if sidecar.get("locked"):
        return False

    if sidecar.get("name") != game.name:
        return True

    # Só o "sem logo" é perguntado de novo; um logo em disco fica para sempre.
    return _miss_expired(sidecar)


def _candidate_key(logo: dict[str, Any]) -> tuple:
    """Rank one candidate; larger sorts better: style first (visibility), then transparency, then the community score, and only then size."""
    style = str(logo.get("style", "")).lower()
    suffix = Path(urlparse(str(logo.get("url", ""))).path).suffix.lower()

    try:
        score = float(logo.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0

    return (
        STYLE_RANK.get(style, 0),
        suffix in TRANSPARENT_SUFFIXES,
        score,
        int(logo.get("width", 0) or 0),
    )


def _usable(logo: dict[str, Any]) -> bool:
    url = str(logo.get("url", "") or "")
    if not url:
        return False

    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        return False

    # A versão anterior (GTK) não lia WebP: continua recusado para não mudar quais logos os jogos recebem.
    if suffix == ".webp":
        return False

    try:
        width = int(logo.get("width", 0) or 0)
        height = int(logo.get("height", 0) or 0)
    except (TypeError, ValueError):
        return False

    # Tamanho ausente não descarta (a API o omite em alguns); um quadrado conhecido, sim.
    if width and height and width / height < MIN_ASPECT_RATIO:
        return False

    # O desmedido é pulado aqui para o pick escolher o próximo, em vez de baixar o que seria descartado.
    if width > MAX_SOURCE_DIMENSION or height > MAX_SOURCE_DIMENSION:
        return False

    return True


def pick_logo(logos: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    usable = [logo for logo in logos if _usable(logo)]
    if not usable:
        return None
    return max(usable, key=_candidate_key)


def _keep_existing_logo(game: Game) -> Optional[Path]:
    """Renew the logo ``game`` already has, for a lookup that found nothing.

    A lookup that failed says nothing about the logo on disk: otherwise an unreachable SteamGridDB would replace a good logo with a miss.
    """
    sidecar = _read_sidecar(game.game_id)
    # Jogo renomeado: o logo antigo foi casado com o título anterior.
    if not sidecar or sidecar.get("name") != game.name:
        return None

    path = _cached_file(sidecar)
    if path is None:
        return None

    _write_sidecar(
        game.game_id, game.name, path.name, locked=bool(sidecar.get("locked"))
    )
    return path


def fetch_logo(game: Game) -> Optional[Path]:
    """Look ``game``'s logo up on SteamGridDB and cache it. Blocking: call off the main thread.

    Returns the cached path, or None when there is no usable logo (an ordinary outcome: the caller keeps the
    text title). Errors are logged and swallowed; a decorative asset never interrupts the page.
    """
    sgdb = SgdbHelper()

    try:
        sgdb_id = sgdb.get_game_id(game)
        logos = sgdb.get_logos(sgdb_id)
    except SgdbAuthError:
        # Sem registrar miss: a chave está errada, não o jogo (esconderia todo logo por uma semana após corrigi-la).
        logging.info("Could not authenticate to SteamGridDB while fetching a logo")
        return _keep_existing_logo(game)
    except (SgdbError, requests.RequestException) as error:
        logging.debug("No logo for %s: %s", game.name, error)
        if kept := _keep_existing_logo(game):
            return kept
        # Jogo desconhecido do SteamGridDB é uma resposta real e vale cache; falha de rede não, e repete na visita seguinte.
        if isinstance(error, SgdbError):
            _write_sidecar(game.game_id, game.name, None)
        return None

    logo = pick_logo(logos)
    if not logo:
        if kept := _keep_existing_logo(game):
            return kept
        _write_sidecar(game.game_id, game.name, None)
        return None

    url = str(logo["url"])
    try:
        content = download_bytes(url, timeout=15)
    except requests.RequestException as error:
        logging.debug("Could not download logo for %s: %s", game.name, error)
        return _keep_existing_logo(game)

    # O usuário pode ter escolhido à mão enquanto a requisição estava no ar; sobrescrever apagaria o arquivo dele
    # (`remove_logo` abaixo) e destravaria o sidecar, e a visita seguinte o trocaria de novo.
    if (existing := _read_sidecar(game.game_id)) and existing.get("locked"):
        logging.debug("Keeping the chosen logo for %s", game.name)
        return _cached_file(existing)

    suffix = Path(urlparse(url).path).suffix.lower() or ".png"
    filename = f"{game.game_id}{suffix}"
    path = shared.logos_dir / filename
    try:
        shared.logos_dir.mkdir(parents=True, exist_ok=True)
        # Tira o logo em outro formato, para não deixar o arquivo antigo para sempre.
        remove_logo(game.game_id, keep=filename)
        path.write_bytes(content)
    except OSError as error:
        logging.debug("Could not save logo for %s: %s", game.name, error)
        return None

    # Confere que os bytes são uma imagem: uma página de erro ou download truncado viraria um *acerto*, confiado para sempre.
    fetched_size = _intrinsic_size(path)
    # Desmedido é inutilizável (o metadado da API pode mentir): descartar aqui registra "sem logo" e não deixa o arquivo gigante no disco.
    if fetched_size is None or max(fetched_size) > MAX_SOURCE_DIMENSION:
        logging.debug("Discarding an unusable logo for %s", game.name)
        path.unlink(missing_ok=True)
        _write_sidecar(game.game_id, game.name, None)
        return None

    _write_sidecar(game.game_id, game.name, filename)
    return path
