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


from pathlib import Path
from shutil import copyfile
from typing import Optional

from gi.repository import Gdk, GdkPixbuf, Gio, GLib
from PIL import Image, UnidentifiedImageError

from cartridges import shared

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

    if pixbuf:
        cover_path = Path(Gio.File.new_tmp("XXXXXX.tiff")[0].get_path())
        pixbuf.savev(str(cover_path), "tiff")

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
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError):
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
        except (GLib.Error, OSError):
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


def save_cover(game_id: str, cover_path: Path) -> None:
    shared.covers_dir.mkdir(parents=True, exist_ok=True)

    # Remove every previous cover for this game, whatever its format
    for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
        (shared.covers_dir / f"{game_id}{suffix}").unlink(missing_ok=True)

    if not cover_path:
        return

    # Animated covers keep their own extension; everything else is a TIFF still
    if cover_path.suffix.lower() in ANIMATED_SUFFIXES:
        dest = shared.covers_dir / f"{game_id}{cover_path.suffix.lower()}"
    else:
        dest = shared.covers_dir / f"{game_id}.tiff"

    copyfile(cover_path, dest)

    # save_cover can be called from a worker thread (e.g. the async SgdbManager),
    # but refreshing the on-screen cover touches GTK widgets, which must happen
    # on the main thread. Marshal it there; .get() avoids a check-then-index race
    # if the entry is removed concurrently.
    if (game_cover := shared.win.game_covers.get(game_id)) is not None:
        GLib.idle_add(game_cover.new_cover, dest)
