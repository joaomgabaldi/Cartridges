# game_cover.py
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

import threading
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
from PIL import Image, ImageFilter, ImageSequence, ImageStat

from cartridges import shared


def texture_from_pixbuf(pixbuf: GdkPixbuf.Pixbuf) -> Gdk.Texture:
    """O substituto documentado do Gdk.Texture.new_for_pixbuf, depreciado.

    Função de módulo porque três lugares constroem textura a partir de pixbuf
    (capas aqui, logos no game_logo e as prévias do logo_picker), e cada um
    reinventando a conversão é como a chamada depreciada sobreviveu a uma
    primeira limpeza.
    """
    return Gdk.MemoryTexture.new(
        pixbuf.get_width(),
        pixbuf.get_height(),
        Gdk.MemoryFormat.R8G8B8A8
        if pixbuf.get_has_alpha()
        else Gdk.MemoryFormat.R8G8B8,
        pixbuf.read_pixel_bytes(),
        pixbuf.get_rowstride(),
    )


class GameCover:
    texture: Optional[Gdk.Texture] = None
    blurred: Optional[Gdk.Texture] = None
    luminance: Optional[tuple[float, float]] = None
    path: Optional[Path] = None

    # Independent reasons to play the animation; it runs while either is set.
    # Hover (library grid) and the details page are tracked separately so that
    # leaving the grid cover does not stop an animation shown in the details view.
    _hover_active: bool = False
    _details_active: bool = False
    _anim_source_id: Optional[int] = None

    # The details page draws the cover 1.4x larger than the grid does, so the
    # texture decoded for the grid comes out visibly soft there. This is the
    # same image decoded at `shared.details_size`, and it exists only while
    # that page is showing this cover: `add_details_picture` decodes it and
    # `release_details_picture` drops it, so at most one is ever alive. Kept
    # off the shared `texture` for that reason — that one belongs to every
    # thumbnail in the library at once.
    _details_picture: Optional[Gtk.Picture] = None
    _details_texture: Optional[Gdk.Texture] = None

    # O desfoque do fundo dos detalhes é computado sob demanda e, na primeira
    # vez, fora do thread principal (decodificar o master 600x900 custa dezenas
    # de ms — era o engasgo da primeira abertura de cada jogo). A geração
    # invalida um cômputo em voo quando a capa troca no meio; o callback é um
    # só porque a página de detalhes só mostra um jogo por vez.
    _blur_generation: int = 0
    _blur_loading: bool = False
    _blur_callback: Optional[Callable] = None

    # An animated cover is shown as a still first frame until it actually needs
    # to play. The frames are then decoded with Pillow off the main thread (which
    # releases the GIL, unlike GdkPixbuf) into ready-to-draw textures.
    _animated_path: Optional[Path] = None
    _animation_loading: bool = False
    _frames: Optional[list[Gdk.Texture]] = None
    _frame_durations: Optional[list[int]] = None
    _frame_index: int = 0
    _release_source_id: Optional[int] = None

    # How long a paused animation keeps its decoded frames before they are
    # dropped. A full frame set is width × height × 4 bytes per frame and the
    # window's `game_covers` map never evicts, so without this every animated
    # cover the pointer has ever crossed stays resident — tens of megabytes on
    # a library with a handful of GIFs. The delay is what stops that from
    # turning into a re-decode every time the pointer sweeps across the grid.
    _FRAME_RELEASE_DELAY_SECONDS = 30

    placeholder = Gdk.Texture.new_from_resource(
        shared.PREFIX + "/library_placeholder.svg"
    )
    placeholder_small = Gdk.Texture.new_from_resource(
        shared.PREFIX + "/library_placeholder_small.svg"
    )

    def __init__(self, pictures: set[Gtk.Picture], path: Optional[Path] = None) -> None:
        self.pictures = pictures
        self.new_cover(path)

    def new_cover(self, path: Optional[Path] = None) -> None:
        # Cancel any timer still running for the previous cover
        if self._anim_source_id is not None:
            GLib.source_remove(self._anim_source_id)
            self._anim_source_id = None
        self._cancel_frame_release()
        self._animated_path = None
        self._animation_loading = False
        self._frames = None
        self._frame_durations = None
        self._frame_index = 0
        self.texture = None
        self.blurred = None
        self.luminance = None
        # Um desfoque ainda sendo computado é da imagem antiga: a geração nova
        # faz o resultado dele ser jogado fora quando aterrissar. O callback
        # fica de pé — quem o registrou (a página de detalhes) não deixou de
        # querer o fundo porque a imagem trocou; quer o da nova.
        self._blur_generation += 1
        self._blur_loading = False
        self.path = path
        # A different image: the sharp copy is of the old one. Re-decoded below
        # rather than just dropped, because the details page may be open on
        # this very game — editing its cover shows the result immediately.
        self._details_texture = None

        if path:
            if path.suffix.lower() in (".gif", ".webp"):
                # Decoding a whole animation is expensive (seconds for a large
                # WebP), so only show the first frame now and decode the rest
                # lazily, in the background, when it needs to play.
                self._animated_path = path
                self.texture = self._load_first_frame(path)
            else:
                self.texture = self._load_display_texture(path)
                if self._details_picture is not None:
                    self._details_texture = self._load_display_texture(
                        path, shared.details_size
                    )

        self.set_texture(self.texture)
        self._reconcile_animation()

        # Página de detalhes aberta neste jogo: recomeça o desfoque já. Toda
        # chamada do lado da janela roda ANTES deste new_cover (o save_cover o
        # adia por idle), então nenhum pedido novo viria — era o buraco que
        # deixava o fundo preto ao adicionar capa a um jogo que não tinha.
        if self._blur_callback is not None:
            self.ensure_blurred(self._blur_callback)

    def _load_first_frame(self, path: Path) -> Optional[Gdk.Texture]:
        """Quickly decode just the first frame of an animation for display."""
        width, height = shared.display_size
        try:
            with Image.open(path) as image:
                frame = image.convert("RGB").resize((int(width), int(height)))
                buffer = BytesIO()
                frame.save(buffer, "tiff", compression=None)
                return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buffer.getvalue()))
        except (OSError, GLib.Error):
            return self._load_display_texture(path)

    def _begin_loading_animation(self) -> None:
        """Decode every frame off the main thread.

        Pillow releases the GIL while decoding, so (unlike GdkPixbuf) this does
        not freeze the UI. Frames are downscaled to the on-screen size and the
        raw pixels handed back to the main thread to become textures.
        """
        self._animation_loading = True
        path = self._animated_path
        width, height = (int(value) for value in shared.display_size)

        def worker() -> None:
            frames: list[bytes] = []
            durations: list[int] = []
            try:
                with Image.open(path) as image:
                    for frame in ImageSequence.Iterator(image):
                        durations.append(int(frame.info.get("duration", 100)))
                        rgba = frame.convert("RGBA").resize((width, height))
                        frames.append(rgba.tobytes())
            except (OSError, ValueError):
                frames, durations = [], []
            GLib.idle_add(
                self._frames_decoded, path, frames, durations, width, height
            )

        threading.Thread(target=worker, daemon=True).start()

    def _frames_decoded(
        self,
        path: Path,
        frames: list[bytes],
        durations: list[int],
        width: int,
        height: int,
    ) -> bool:
        # The cover may have been replaced while the animation was decoding.
        # Clearing the flag unconditionally was a race: `new_cover` had already
        # cleared it and a decode for the *new* path could be running, so this
        # stale callback declared that second worker finished. The next hover
        # then saw "no frames, not loading" and started a third thread decoding
        # the same file.
        if path != self._animated_path:
            return False

        self._animation_loading = False
        if len(frames) < 2:
            self._animated_path = None  # Not actually animated; keep the still
            return False

        stride = width * 4
        self._frames = [
            Gdk.MemoryTexture.new(
                width,
                height,
                Gdk.MemoryFormat.R8G8B8A8,
                GLib.Bytes.new(raw),
                stride,
            )
            for raw in frames
        ]
        self._frame_durations = durations
        self._frame_index = 0
        if self.active and self._anim_source_id is None:
            self._schedule_frame()
        return False

    def _load_display_texture(
        self, path: Path, size: Optional[tuple] = None
    ) -> Optional[Gdk.Texture]:
        """Load a still cover downscaled to an on-screen render size.

        The cover files are stored at high resolution; rendering hundreds of
        them at full size is wasteful, so they are decoded straight to the
        display size to keep memory and drawing cost low. ``size`` overrides
        that for the one cover the details page is showing, which is drawn
        larger than the grid ever draws it.
        """
        width, height = size or shared.display_size
        try:
            return texture_from_pixbuf(
                GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(path), int(width), int(height), False
                )
            )
        except GLib.Error:
            pass
        try:
            return Gdk.Texture.new_from_filename(str(path))
        except GLib.Error:
            # Last resort (e.g. WebP without a GdkPixbuf loader): decode via PIL
            return self._pil_texture(path)

    def _pil_texture(self, path: Path) -> Optional[Gdk.Texture]:
        """Decode a still frame through PIL when GdkPixbuf has no loader"""
        try:
            with Image.open(path) as image:
                buffer = BytesIO()
                image.convert("RGBA").save(buffer, "tiff", compression=None)
                return Gdk.Texture.new_from_bytes(GLib.Bytes.new(buffer.getvalue()))
        except (OSError, GLib.Error):
            return None

    def get_texture(self) -> Gdk.Texture:
        if self._frames:
            return self._frames[self._frame_index]
        return self.texture

    @staticmethod
    def _compute_blur(
        path: Optional[Path],
    ) -> Optional[tuple[bytes, tuple[float, float]]]:
        """A metade PIL do desfoque: bytes de um TIFF 100x150 borrado + luminância.

        Separada para poder rodar num thread: só Pillow e bytes, nenhum objeto
        GTK — a textura é construída no thread principal por quem chamou.
        """
        try:
            if not path:
                raise OSError  # no cover: caller falls back to the placeholder
            with Image.open(path) as image:
                image = (
                    image.convert("RGB")
                    .resize((100, 150))
                    .filter(ImageFilter.GaussianBlur(20))
                )

                buffer = BytesIO()
                image.save(buffer, "tiff", compression=None)

                stat = ImageStat.Stat(image.convert("L"))

                # Luminance values for light and dark mode
                return buffer.getvalue(), (
                    min((stat.mean[0] + stat.extrema[0][0]) / 510, 0.7),
                    max((stat.mean[0] + stat.extrema[0][1]) / 510, 0.3),
                )
        except (OSError, ValueError):
            return None

    def _apply_blur(
        self, computed: Optional[tuple[bytes, tuple[float, float]]]
    ) -> None:
        """Turn a finished computation into the cached texture. Main thread."""
        if computed is not None:
            data, luminance = computed
            try:
                self.blurred = Gdk.Texture.new_from_bytes(GLib.Bytes.new(data))
                self.luminance = luminance
            except GLib.Error:
                self.blurred = None
        if self.blurred is None:
            # Missing/corrupt cover file: fall back to the placeholder
            # instead of crashing the details page
            self.blurred = self.placeholder_small
            self.luminance = (0.3, 0.5)

    def get_blurred(self) -> Gdk.Texture:
        if not self.blurred:
            self._apply_blur(self._compute_blur(self.path))
        return self.blurred

    def ensure_blurred(self, callback: Callable[["GameCover"], None]) -> None:
        """Hand the blurred texture to ``callback``, computing it off-thread.

        Já em cache, o callback sai na hora, no mesmo quadro — o caminho comum
        ao revisitar um jogo. Sem cache, o cômputo vai para um thread e volta
        por idle: é o que tira o engasgo da primeira abertura dos detalhes.

        O callback fica registrado como o consumidor vigente do fundo (só há
        um: a página de detalhes) e permanece depois de atendido — é assim que
        `new_cover` sabe a quem entregar o desfoque da capa nova quando ela
        troca com a página aberta. `release_details_picture` o desregistra.
        """
        self._blur_callback = callback

        # Sem capa não há nada para computar: o placeholder sai síncrono, sem
        # viagem por thread nem quadro preto no meio.
        if self.blurred is None and self.path is None:
            self._apply_blur(None)

        if self.blurred is not None:
            callback(self)
            return

        if self._blur_loading:
            return
        self._blur_loading = True
        generation = self._blur_generation
        path = self.path

        def worker() -> None:
            computed = self._compute_blur(path)
            GLib.idle_add(self._blur_ready, generation, computed)

        threading.Thread(target=worker, daemon=True).start()

    def _blur_ready(
        self,
        generation: int,
        computed: Optional[tuple[bytes, tuple[float, float]]],
    ) -> bool:
        # A capa trocou com o cômputo em voo: o resultado é da imagem antiga.
        # Se o new_cover que invalidou ainda não recomeçou o cômputo, recomeça
        # agora — quem registrou o callback segue esperando o fundo.
        if generation != self._blur_generation:
            if self._blur_callback is not None and not self._blur_loading:
                self.ensure_blurred(self._blur_callback)
            return False
        self._blur_loading = False
        self._apply_blur(computed)
        # O callback continua registrado: ver ensure_blurred.
        if self._blur_callback is not None:
            self._blur_callback(self)
        return False

    def add_picture(self, picture: Gtk.Picture) -> None:
        self.pictures.add(picture)
        picture.set_paintable(self._paintable_for(picture))
        picture.queue_draw()

    def add_details_picture(self, picture: Gtk.Picture) -> None:
        """Drive ``picture`` as the details page's cover, at its own size.

        Only still covers get their own texture. An animated one is about to
        start playing from frames decoded at the grid's size, so a sharper
        still would show for an instant and then be replaced — and decoding a
        whole second frame set at this size is the cost this design exists to
        avoid paying.
        """
        self._details_picture = picture
        if self._details_texture is None and self.path and not self._animated_path:
            self._details_texture = self._load_display_texture(
                self.path, shared.details_size
            )
        self.add_picture(picture)

    def release_details_picture(self, picture: Gtk.Picture) -> None:
        """Stop driving the details cover and drop its texture.

        Dropping it is the point: `shared.win.game_covers` never evicts, so a
        texture kept here would stay resident for every game the user has ever
        opened. One at a time is the whole bargain that makes decoding at this
        size affordable.
        """
        self.release_picture(picture)
        if self._details_picture is picture:
            self._details_picture = None
            self._details_texture = None
            # A página soltou esta capa; o pedido de fundo dela vai junto, ou
            # uma troca de capa futura acordaria um consumidor que já se foi.
            self._blur_callback = None

    def _paintable_for(self, picture: Gtk.Picture) -> Gdk.Paintable:
        """What ``picture`` should be showing right now.

        The details picture gets the sharper texture, but only while a still is
        on screen: once the animation frames exist they are what everything
        draws, so the two views stay on the same frame.
        """
        if (
            picture is self._details_picture
            and self._details_texture is not None
            and not self._frames
        ):
            return self._details_texture
        return self.get_texture() or self.placeholder

    def release_picture(self, picture: Gtk.Picture) -> None:
        """Stop driving ``picture``; another cover has taken it over.

        Handing a picture to a new cover is not enough on its own: this one goes
        on repainting every picture it still lists, and `_release_frames` does
        exactly that half a minute after it was paused — long after a cover swap
        looked finished, the library thumbnail would quietly revert to the old
        artwork's first frame.

        `discard`, because the caller cannot always know whether this cover ever
        held the picture (a game edited twice, a details page rebuilt in
        between), and "already gone" is the outcome being asked for anyway.
        """
        self.pictures.discard(picture)

    def set_texture(self, texture: Gdk.Texture) -> None:
        paintable = texture or self.placeholder
        for picture in self.pictures:
            # The details picture keeps its own, sharper texture whenever one
            # applies; everything else takes what it was handed.
            if picture is self._details_picture:
                picture.set_paintable(self._paintable_for(picture))
            else:
                picture.set_paintable(paintable)
            picture.queue_draw()

    @property
    def active(self) -> bool:
        """Whether the animation should currently be playing"""
        return self._hover_active or self._details_active

    def set_hover_animation(self, playing: bool) -> None:
        """Play while the pointer hovers the cover in the library grid"""
        self._hover_active = playing
        self._reconcile_animation()

    def set_details_animation(self, playing: bool) -> None:
        """Play while the cover is shown on the details page (ignores hover)"""
        self._details_active = playing
        self._reconcile_animation()

    def _reconcile_animation(self) -> None:
        """Start or pause playback to match the current active state"""
        if not self.active:
            self._pause_animation()
            return

        # Playing again: the frames are needed, so call off their release.
        self._cancel_frame_release()

        if self._frames is not None:
            if self._anim_source_id is None:
                self._schedule_frame()
        elif self._animated_path is not None and not self._animation_loading:
            # First time this cover needs to animate: decode it in the background
            self._begin_loading_animation()

    def _pause_animation(self) -> None:
        """Stop playback, leaving the current frame on screen."""
        if self._anim_source_id is not None:
            GLib.source_remove(self._anim_source_id)
            self._anim_source_id = None

        # Nothing is watching this cover any more, so its decoded frames are
        # dead weight — but only after a grace period, so sweeping the pointer
        # back over the same cover does not pay for a full re-decode.
        if self._frames is not None and self._release_source_id is None:
            self._release_source_id = GLib.timeout_add_seconds(
                self._FRAME_RELEASE_DELAY_SECONDS, self._release_frames
            )

    def _cancel_frame_release(self) -> None:
        if self._release_source_id is not None:
            GLib.source_remove(self._release_source_id)
            self._release_source_id = None

    def _release_frames(self) -> bool:
        """Drop the decoded frame set, leaving the still first frame on screen."""
        self._release_source_id = None
        if self.active:  # started playing again while the timer was pending
            return False

        self._frames = None
        self._frame_durations = None
        self._frame_index = 0
        # `texture` is the cheap first frame decoded in `new_cover`; putting it
        # back keeps the cover looking identical to how the animation left it
        # rather than blanking to the placeholder.
        self.set_texture(self.texture)
        return False

    def _schedule_frame(self) -> None:
        delay = 100
        if self._frame_durations:
            delay = self._frame_durations[self._frame_index]
        self._anim_source_id = GLib.timeout_add(max(20, delay), self._advance_frame)

    def _advance_frame(self) -> bool:
        self._anim_source_id = None
        if not (self._frames and self.active and self.pictures):
            # Playback can also stop here — a cover whose last Gtk.Picture was
            # taken away never goes through `_reconcile_animation`. Route it
            # through the same pause so its frames are released too.
            self._pause_animation()
            return False
        self._frame_index = (self._frame_index + 1) % len(self._frames)
        self.set_texture(self._frames[self._frame_index])
        self._schedule_frame()
        return False
