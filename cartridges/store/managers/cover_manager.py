# local_cover_manager.py
#
# Copyright 2023 Geoffrey Coulaud
# Copyright 2023 kramo
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
from typing import NamedTuple

from gi.repository import GdkPixbuf, Gio
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import HTTPError, SSLError, Timeout

from cartridges import shared
from cartridges.game import Game
from cartridges.store.managers.manager import Manager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils.download import download_bytes
from cartridges.utils.save_cover import convert_cover, save_cover


class UnreadableCoverError(Exception):
    """The candidate cover could not be decoded by Pillow or GdkPixbuf."""


class ImageSize(NamedTuple):
    width: float = 0
    height: float = 0

    @property
    def aspect_ratio(self) -> float:
        return self.width / self.height

    def __str__(self):
        return f"{self.width}x{self.height}"

    def __mul__(self, scale: float | int) -> "ImageSize":
        return ImageSize(
            self.width * scale,
            self.height * scale,
        )

    def __truediv__(self, divisor: float | int) -> "ImageSize":
        return self * (1 / divisor)

    def __add__(self, other_size: "ImageSize") -> "ImageSize":
        return ImageSize(
            self.width + other_size.width,
            self.height + other_size.height,
        )

    def __sub__(self, other_size: "ImageSize") -> "ImageSize":
        return self + (other_size * -1)

    def element_wise_div(self, other_size: "ImageSize") -> "ImageSize":
        """Divide every element of self by the equivalent in the other size"""
        return ImageSize(
            self.width / other_size.width,
            self.height / other_size.height,
        )

    def element_wise_mul(self, other_size: "ImageSize") -> "ImageSize":
        """Multiply every element of self by the equivalent in the other size"""
        return ImageSize(
            self.width * other_size.width,
            self.height * other_size.height,
        )

    def invert(self) -> "ImageSize":
        """Invert the element of self"""
        return ImageSize(1, 1).element_wise_div(self)


class CoverManager(Manager):
    """
    Manager in charge of adding the cover image of the game

    Order of priority is:
    1. local cover
    2. online cover

    Shortcut/executable icons are deliberately not used: they are tiny and look
    bad stretched into a cover. Games without art simply stay uncovered.
    """

    run_after = (SteamAPIManager,)
    retryable_on = (
        HTTPError,
        SSLError,
        RequestsConnectionError,
        ConnectionError,
        Timeout,
    )

    # ponytail: este manager é `blocking` atrás de um async, então o retry com
    # sleep(3) do handle_error roda na main thread — até ~21 s congelado por
    # capa que falha. Hoje o caminho é morto (nenhuma fonte deste fork produz
    # online_cover_url/local_image_path); se uma fonte nova reviver o manager,
    # o upgrade é torná-lo AsyncManager ou zerar retry_delay para ele.

    def download_image(self, url: str) -> Path:
        # O download vem ANTES do temp: criado primeiro, cada URL que falhasse
        # vazava um arquivo vazio em %TEMP% por tentativa — três por URL, com o
        # retry — porque o raise acontecia antes do try/finally do chamador.
        content = download_bytes(url, timeout=5)
        path = Path(Gio.File.new_tmp()[0].get_path())
        path.write_bytes(content)
        return path

    def is_stretchable(self, source_size: ImageSize, cover_size: ImageSize) -> bool:
        is_taller = source_size.aspect_ratio < cover_size.aspect_ratio
        if is_taller:
            return True
        max_stretch = 0.12
        resized_height = (1 / source_size.aspect_ratio) * cover_size.width
        stretch = 1 - (resized_height / cover_size.height)
        return stretch <= max_stretch

    def composite_cover(
        self,
        image_path: Path,
        scale: float = 1,
        blur_size: ImageSize = ImageSize(2, 2),
    ) -> GdkPixbuf.Pixbuf:
        """
        Return the image composited with a background blur.
        If the image is stretchable, just stretch it.

        :param path: Path where the source image is located
        :param scale:
            Scale of the smalled image side
            compared to the corresponding side in the cover
        :param blur_size: Size of the downscaled image used for the blur
        """

        # Load source image. `convert_cover` returns None for anything neither
        # Pillow nor GdkPixbuf can read; `str(None)` used to turn that into a
        # literal "None" filename and a confusing GLib.Error from deep inside
        # the pixbuf loader, several frames away from the real cause.
        converted = convert_cover(image_path, resize=False)
        if converted is None:
            raise UnreadableCoverError(image_path)
        try:
            source = GdkPixbuf.Pixbuf.new_from_file(str(converted))
        finally:
            # `convert_cover` may hand back the input untouched (when it is
            # already in a format GdkPixbuf reads) or a fresh temp file. Only
            # the temp is ours to remove — the input is the caller's.
            if converted != image_path:
                converted.unlink(missing_ok=True)
        source_size = ImageSize(source.get_width(), source.get_height())
        cover_size = ImageSize._make(shared.image_size)

        # Stretch if possible
        if scale == 1 and self.is_stretchable(source_size, cover_size):
            return source

        # Create the blurred cover background
        # fmt: off
        cover = (
            source
            .scale_simple(*blur_size, GdkPixbuf.InterpType.BILINEAR)
            .scale_simple(*cover_size, GdkPixbuf.InterpType.BILINEAR)
        )
        # fmt: on

        # Scale to fit, apply scaling, then center
        uniform_scale = scale * min(cover_size.element_wise_div(source_size))
        source_in_cover_size = source_size * uniform_scale
        source_in_cover_position = (cover_size - source_in_cover_size) / 2

        # Center the scaled source image in the cover
        source.composite(
            cover,
            *source_in_cover_position,
            *source_in_cover_size,
            *source_in_cover_position,
            uniform_scale,
            uniform_scale,
            GdkPixbuf.InterpType.BILINEAR,
            255,
        )
        return cover

    def main(self, game: Game, additional_data: dict) -> None:
        if game.blacklisted:
            return
        for key in (
            "local_image_path",
            "online_cover_url",
        ):
            # Get an image path
            if not (value := additional_data.get(key)):
                continue
            if key == "online_cover_url":
                image_path = self.download_image(value)
            else:
                image_path = Path(value)

            composited = None
            try:
                if not image_path.is_file():
                    continue

                composited = convert_cover(pixbuf=self.composite_cover(image_path))
                # `save_cover` unlinks the game's existing covers before it
                # inspects its argument (None is the documented way the details
                # dialog clears one), so passing a conversion failure through
                # would delete a perfectly good cover. Skip instead.
                if composited is None:
                    logging.warning(
                        "Could not build a cover for %s from %s",
                        game.game_id,
                        image_path,
                    )
                    continue

                save_cover(game.game_id, composited)
                # First source that produces a usable cover wins, and the keys
                # above are in the priority order this class documents: local
                # first, online second. Without stopping here the loop carried
                # on and `save_cover` ran a second time, so the online art
                # overwrote the local one every single time both existed —
                # exactly the opposite of what the docstring promises, and
                # invisible to anyone who only had one of the two.
                break
            except UnreadableCoverError:
                logging.warning("Unreadable cover candidate for %s", game.game_id)
                continue
            finally:
                # The composited temp is copied by `save_cover`, never adopted,
                # so nothing else would ever remove it from %TEMP%.
                if composited is not None:
                    composited.unlink(missing_ok=True)
                # The online path is a temp download we own; local paths are the
                # user's own files and must never be removed.
                if key == "online_cover_url":
                    image_path.unlink(missing_ok=True)
