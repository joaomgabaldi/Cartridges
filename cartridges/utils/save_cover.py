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
from pathlib import Path
from shutil import copyfile
from typing import Optional
from uuid import uuid4

from gi.repository import Gdk, GdkPixbuf, Gio, GLib
from PIL import Image, UnidentifiedImageError

from cartridges import shared
from cartridges.utils import copias_animadas
from cartridges.utils.na_tela import entregar_na_tela

# Cover formats that hold an animation and are stored in their original form
ANIMATED_SUFFIXES = (".gif", ".webp")


def convert_cover(
    cover_path: Optional[Path] = None,
    pixbuf: Optional[GdkPixbuf.Pixbuf] = None,
    resize: bool = True,
) -> Optional[Path]:
    if not cover_path and not pixbuf:
        return None

    pixbuf_extensions = set()
    for pixbuf_format in GdkPixbuf.Pixbuf.get_formats():
        for pixbuf_extension in pixbuf_format.get_extensions():
            pixbuf_extensions.add(pixbuf_extension)

    if not resize and cover_path and cover_path.suffix.lower()[1:] in pixbuf_extensions:
        return cover_path

    pixbuf_temp: Optional[Path] = None
    if pixbuf:
        # Este TIFF é só a entrada do bloco Pillow abaixo, que grava um temp
        # próprio e devolve esse — o intermediário nunca é o retorno. Sem o
        # unlink no finally lá embaixo, cada capa escolhida à mão deixava este
        # arquivo órfão em %TEMP% para sempre: o mesmo vazamento que o ramo de
        # fallback já conserta, com o mesmo comentário, no finally dele.
        pixbuf_temp = Path(Gio.File.new_tmp("XXXXXX.tiff")[0].get_path())
        pixbuf.savev(str(pixbuf_temp), "tiff")
        cover_path = pixbuf_temp

    try:
        return _convert_readable_cover(cover_path, resize)
    finally:
        if pixbuf_temp is not None:
            pixbuf_temp.unlink(missing_ok=True)


def _convert_readable_cover(cover_path: Path, resize: bool) -> Optional[Path]:
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

            # GIF and animated WebP animate natively and are stored verbatim at
            # their original resolution. Re-encoding an animated cover into a
            # 256-colour GIF caused banding, washed-out colours and, for some
            # formats (e.g. APNG), outright save failures.
            if animated and fmt in ("GIF", "WEBP"):
                suffix = ".gif" if fmt == "GIF" else ".webp"
                tmp_path = Path(Gio.File.new_tmp(f"XXXXXX{suffix}")[0].get_path())
                copyfile(cover_path, tmp_path)
                return tmp_path

            # Any other animated format (e.g. APNG) cannot be animated by
            # GdkPixbuf anyway, so fall back to a clean full-colour still of the
            # first frame instead of a fragile, lossy GIF.
            if animated:
                image.seek(0)

            # This might not be necessary in the future
            # https://github.com/python-pillow/Pillow/issues/2663
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")

            tmp_path = Path(Gio.File.new_tmp("XXXXXX.tiff")[0].get_path())
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
    except (UnidentifiedImageError, OSError, ValueError):
        intermediate: Optional[Path] = None
        result: Optional[Path] = None
        try:
            Gdk.Texture.new_from_filename(str(cover_path)).save_to_tiff(
                tmp_path := Gio.File.new_tmp("XXXXXX.tiff")[0].get_path()
            )
            # Gio.File.get_path() returns a str; convert_cover indexes
            # cover_path.suffix, so it must be handed a Path or the fallback
            # raises AttributeError instead of producing the still cover.
            intermediate = Path(tmp_path)
            result = convert_cover(intermediate)
            return result
        except (GLib.Error, OSError) as error:
            logging.warning("Could not convert cover %s: %s", Path(cover_path).name, error)
            return None
        finally:
            # The re-encoded scratch file is only an input to the recursive
            # call, which writes a temp of its own. Leaving it behind put a
            # second stray TIFF in %TEMP% for every cover taking this path.
            # Guarded by identity because `convert_cover` is allowed to hand
            # its input straight back — deleting it then would return the
            # caller a path to a file that no longer exists.
            if intermediate is not None and result is not intermediate:
                intermediate.unlink(missing_ok=True)

    return tmp_path


class UnreadableCoverError(Exception):
    """The candidate cover could not be decoded by Pillow or GdkPixbuf."""


# How much a stretch may distort an image before it gets blurred bars instead.
_MAX_STRETCH = 0.12


def composite_cover(image_path: Path) -> GdkPixbuf.Pixbuf:
    """``image_path`` shaped as a cover, for a cover picked from a file.

    An image taller than a cover, or wider by at most `_MAX_STRETCH`, is just
    stretched later; anything wider is fitted in the middle over a blurred,
    stretched copy of itself.
    """
    # `convert_cover` returns None for anything neither Pillow nor GdkPixbuf
    # can read; `str(None)` used to turn that into a literal "None" filename.
    converted = convert_cover(image_path, resize=False)
    if converted is None:
        raise UnreadableCoverError(image_path)
    try:
        source = GdkPixbuf.Pixbuf.new_from_file(str(converted))
    except GLib.Error as error:
        raise UnreadableCoverError(image_path) from error
    finally:
        # `convert_cover` may hand back the input untouched; only a temp it
        # made is ours to remove.
        if converted != image_path:
            converted.unlink(missing_ok=True)

    width, height = source.get_width(), source.get_height()
    cover_width, cover_height = shared.image_size
    taller = width / height < cover_width / cover_height
    if taller or 1 - (height / width * cover_width) / cover_height <= _MAX_STRETCH:
        return source

    interp = GdkPixbuf.InterpType.BILINEAR
    cover = source.scale_simple(2, 2, interp).scale_simple(cover_width, cover_height, interp)
    scale = min(cover_width / width, cover_height / height)
    x, y = (cover_width - width * scale) / 2, (cover_height - height * scale) / 2
    source.composite(
        cover, int(x), int(y), int(width * scale), int(height * scale),
        x, y, scale, scale, interp, 255,
    )  # fmt: skip
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

    # Capa animada nova: as cópias reduzidas dela são geradas em segundo plano,
    # com o autoplay ligado ou não.
    # Pela mesma entrega do ``apagar`` logo acima (que avisa a tarefa para não
    # esperar as cópias da capa velha): as duas chegam à thread principal na
    # ordem das chamadas, e a tarefa é dela.
    if dest.suffix in ANIMATED_SUFFIXES:
        entregar_na_tela(copias_animadas.preparar, [(game_id, dest)])

    # save_cover can be called from a worker thread (e.g. the async SgdbManager),
    # but refreshing the on-screen cover touches GTK widgets, which must happen
    # on the main thread. Marshal it there; .get() avoids a check-then-index race
    # if the entry is removed concurrently.
    if (game_cover := shared.win.game_covers.get(game_id)) is not None:
        GLib.idle_add(game_cover.new_cover, dest)
