# save_cover.py
#
# Copyright 2022-2023 kramo
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


import logging
import os
import tempfile
from pathlib import Path
from shutil import copyfile
from typing import Optional
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from cartridges import shared
from cartridges.jogo import ANIMATED_SUFFIXES  # reexportado: mora ao lado de get_cover_path
from cartridges.utils import copias_animadas
from cartridges.utils.enquadramento import escala_sobre_fundo
from cartridges.utils.na_tela import entregar_na_tela
from cartridges.utils.thread_principal import na_thread_principal


# Formato do Pillow -> sufixo com que a capa animada é guardada.
_SUFIXO_ANIMADO = {"GIF": ".gif", "WEBP": ".webp", "PNG": ".apng"}


def _temporario(sufixo: str) -> Path:
    """Um arquivo temporário novo e vazio, que quem chama apaga."""
    descritor, caminho = tempfile.mkstemp(suffix=sufixo)
    os.close(descritor)
    return Path(caminho)


def convert_cover(cover_path: Optional[Path] = None, resize: bool = True) -> Optional[Path]:
    if not cover_path:
        return None

    if not resize and cover_path.suffix.lower() in Image.registered_extensions():
        return cover_path

    return _convert_readable_cover(cover_path, resize)


def _convert_readable_cover(cover_path: Path, resize: bool) -> Optional[Path]:
    tmp_path: Optional[Path] = None
    try:
        with Image.open(cover_path) as image:
            # A cover can come straight off the network (SteamGridDB) or from a
            # file the user picked. Pillow refuses absurd pixel counts with a
            # DecompressionBombError, which is neither UnidentifiedImageError
            # nor OSError — it escaped this handler entirely and took the
            # importer's worker thread with it. Treat it as "unreadable cover",
            # which is what it is.
            animated = getattr(image, "is_animated", False)
            fmt = (image.format or "").upper()

            # GIF, animated WebP and APNG are stored verbatim at their original
            # resolution: the library plays reduced copies made by Pillow
            # (``copias_animadas``), never the original. Re-encoding an animated
            # cover into a 256-colour GIF caused banding, washed-out colours
            # and, for APNG, outright save failures.
            if animated and (suffix := _SUFIXO_ANIMADO.get(fmt)):
                tmp_path = _temporario(suffix)
                copyfile(cover_path, tmp_path)
                return tmp_path

            # Any other animated format has no copy pipeline, so fall back to a
            # clean full-colour still of the first frame.
            if animated:
                image.seek(0)

            # This might not be necessary in the future
            # https://github.com/python-pillow/Pillow/issues/2663
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")

            tmp_path = _temporario(".tiff")
            # Covers are always stored losslessly at high resolution
            (image.resize(shared.image_size) if resize else image).save(
                tmp_path,
                compression="tiff_adobe_deflate",
            )
    except Image.DecompressionBombError:
        # Fora do fallback abaixo: ele regrava a mesma imagem gigante num TIFF
        # e chama `convert_cover` de novo, que a recusa de novo — recursão sem
        # fim, com um TIFF enorme a mais em %TEMP% a cada nível.
        logging.warning("Cover refused, image too large: %s", Path(cover_path).name)
        return None
    except (UnidentifiedImageError, OSError, ValueError) as error:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        logging.warning("Could not convert cover %s: %s", Path(cover_path).name, error)
        return None
    except BaseException:
        # Qualquer outra falha: sem o temporário que ficou pela metade, e quem chamou decide.
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise

    return tmp_path


class UnreadableCoverError(Exception):
    """The candidate cover could not be decoded by Pillow."""


def composite_cover(image_path: Path) -> Image.Image:
    """``image_path`` shaped as a cover, for a cover picked from a file.

    An image taller than a cover, or wider by at most
    `enquadramento.MAX_STRETCH`, is just stretched later; anything wider is
    fitted in the middle over a blurred, stretched copy of itself.
    """
    # `convert_cover` returns None for anything Pillow cannot read; `str(None)`
    # used to turn that into a literal "None" filename.
    converted = convert_cover(image_path, resize=False)
    if converted is None:
        raise UnreadableCoverError(image_path)
    try:
        with Image.open(converted) as aberta:
            source = aberta.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise UnreadableCoverError(image_path) from error
    finally:
        # `convert_cover` may hand back the input untouched; only a temp it
        # made is ours to remove.
        if converted != image_path:
            converted.unlink(missing_ok=True)

    width, height = source.size
    cover_width, cover_height = shared.image_size
    scale = escala_sobre_fundo(width, height, shared.image_size)
    if scale is None:
        return source

    interp = Image.Resampling.BILINEAR
    cover = source.resize((2, 2), interp).resize((cover_width, cover_height), interp)
    x, y = (cover_width - width * scale) / 2, (cover_height - height * scale) / 2
    cover.alpha_composite(source.resize((int(width * scale), int(height * scale)), interp), (int(x), int(y)))
    return cover


def save_cover(game_id: str, cover_path: Path) -> None:
    shared.covers_dir.mkdir(parents=True, exist_ok=True)

    # As cópias reduzidas são apagadas só com a capa nova já no lugar (aqui e
    # no fim): até lá a tela ainda mostra a velha e pode pedir a cópia dela. O
    # ``apagar`` invalida todo pedido que já existe, então o que leu a velha
    # não sobrevive, e o que vier depois só acha a nova.

    if not cover_path:
        # Remoção explícita: aqui sim toda forma anterior cai, e não há nada
        # novo para proteger.
        for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
            (shared.covers_dir / f"{game_id}{suffix}").unlink(missing_ok=True)
        copias_animadas.apagar(game_id)
        return

    # Animated covers keep their own extension; everything else is a TIFF still
    if cover_path.suffix.lower() in ANIMATED_SUFFIXES:
        dest = shared.covers_dir / f"{game_id}{cover_path.suffix.lower()}"
    else:
        dest = shared.covers_dir / f"{game_id}.tiff"

    # Copia para um tmp no próprio diretório e só então assume o nome final.
    # A ordem antiga — apagar tudo e depois copiar — deixava a capa ausente ou
    # truncada num disco cheio ou numa queda, e uma truncada passa no
    # `is_file()` do SGDB, que então nunca mais re-busca. O `replace` é atômico
    # no mesmo volume; uma cópia que falha custa o tmp e preserva a capa atual.
    tmp_dest = dest.with_name(f"{dest.name}.{uuid4().hex}.tmp")
    try:
        copyfile(cover_path, tmp_dest)
        tmp_dest.replace(dest)
    finally:
        tmp_dest.unlink(missing_ok=True)

    # As formas de OUTRO sufixo só caem depois que a nova está no lugar.
    for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
        if suffix != dest.suffix:
            (shared.covers_dir / f"{game_id}{suffix}").unlink(missing_ok=True)

    copias_animadas.apagar(game_id)
    if dest.suffix in ANIMATED_SUFFIXES:
        # A prévia da edição pode já ter as cópias desta capa: o ``preparar``
        # abaixo só gera as que faltarem.
        copias_animadas.adotar(cover_path, dest)

    # Capa animada nova: as cópias reduzidas dela são geradas em segundo plano,
    # com o autoplay ligado ou não.
    # Pela mesma entrega do ``apagar`` logo acima (que avisa a tarefa para não
    # esperar as cópias da capa velha): as duas chegam à thread principal na
    # ordem das chamadas, e a tarefa é dela.
    if dest.suffix in ANIMATED_SUFFIXES:
        entregar_na_tela(copias_animadas.preparar, [(game_id, dest)])

    # save_cover can be called from a worker thread (e.g. the async SgdbManager),
    # but the grid is refreshed by the game's `update()`, which belongs to the main
    # thread. A URL com `?v=<mtime_ns>` da grade troca a capa sozinha.
    na_thread_principal(_atualizar_jogo, game_id)


def _atualizar_jogo(game_id: str) -> None:
    store = getattr(shared, "store", None)
    if store is not None and (jogo := store.get(game_id)) is not None:
        jogo.update()
