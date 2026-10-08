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

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from gi.repository import Gdk, GdkPixbuf, GLib, Gtk
from PIL import Image, ImageFilter, ImageStat

from cartridges import shared
from cartridges.utils import copias_animadas, tocador_capas
from cartridges.utils.copias_animadas import Resultado
from cartridges.utils.na_tela import entregar_na_tela


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

    # Independent reasons to play the animation; it runs while any is set.
    # Hover (library grid), the details page and being in view (autoplay) are
    # tracked separately so that leaving the grid cover does not stop an
    # animation shown in the details view.
    _hover_active: bool = False
    _details_active: bool = False
    _visible_active: bool = False

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
    # invalida um cômputo em voo quando a capa troca no meio — o do desfoque e
    # os avisos da animação (cópia pronta, quadro, cópia corrompida); o
    # callback do desfoque é um só porque a página de detalhes só mostra um
    # jogo por vez.
    _blur_generation: int = 0
    _blur_loading: bool = False
    _blur_callback: Optional[Callable] = None

    # Uma capa animada aparece como o primeiro quadro parado até precisar
    # tocar. Aí toca pela cópia reduzida em disco (`copias_animadas`), no
    # tocador único (`tocador_capas`), que entrega um quadro por vez: nenhuma
    # capa guarda a animação inteira na memória. `_frame_texture` é só o
    # último quadro recebido.
    _animated_path: Optional[Path] = None
    _frame_texture: Optional[Gdk.Texture] = None
    # Uma cópia desta capa terminou em "falhou" (disco cheio, falta de
    # memória): não se pede outra até a capa mudar, ou cada reconcile
    # refaria de 10 a 25 s de geração para falhar de novo.
    _gravacao_falhou: bool = False

    # Capas da abertura já decodificadas no tamanho da grade; ver
    # `pre_decodificadas`. Cada uma é usada uma vez.
    _pre_decodificadas: dict[Path, GdkPixbuf.Pixbuf] = {}

    placeholder = Gdk.Texture.new_from_resource(
        shared.PREFIX + "/library_placeholder.svg"
    )
    placeholder_small = Gdk.Texture.new_from_resource(
        shared.PREFIX + "/library_placeholder_small.svg"
    )

    @classmethod
    @contextmanager
    def pre_decodificadas(cls, caminhos: Iterable[Optional[Path]]) -> Iterator[None]:
        """Decodifica as capas estáticas em threads, antes de a grade pedir.

        Uma por vez na thread principal, as 107 capas de uma biblioteca real
        levavam 0,67 s antes de a janela aparecer (medido em 28/09/2026); em
        threads, ~0,1 s: o GdkPixbuf solta o GIL enquanto decodifica. Só o
        pixbuf sai das threads, e a textura continua sendo feita na thread
        principal, em `_load_display_texture`. A capa que falhar aqui fica de
        fora e segue o caminho normal de lá, com os mesmos substitutos. Ao sair
        do bloco, as que a grade não usou são descartadas.
        """
        width, height = (int(value) for value in shared.display_size)

        def decodificar(path: Path) -> Optional[GdkPixbuf.Pixbuf]:
            try:
                return GdkPixbuf.Pixbuf.new_from_file_at_scale(
                    str(path), width, height, False
                )
            except GLib.Error:
                return None

        estaticas = [
            path for path in caminhos
            if path and path.suffix.lower() not in (".gif", ".webp")
        ]
        with ThreadPoolExecutor() as executor:
            prontas = zip(estaticas, executor.map(decodificar, estaticas))
            cls._pre_decodificadas = {
                path: pixbuf for path, pixbuf in prontas if pixbuf is not None
            }
        try:
            yield
        finally:
            cls._pre_decodificadas = {}

    def __init__(self, pictures: set[Gtk.Picture], path: Optional[Path] = None) -> None:
        self.pictures = pictures
        self.new_cover(path)

    def new_cover(self, path: Optional[Path] = None) -> None:
        # A animação da imagem antiga para aqui; os quadros e avisos dela ainda
        # a caminho são descartados pela geração, logo abaixo.
        tocador_capas.tocador.parar(self)
        self._animated_path = None
        self._frame_texture = None
        self._gravacao_falhou = False
        self.texture = None
        self.blurred = None
        self.luminance = None
        # Um desfoque ainda sendo computado é da imagem antiga: a geração nova
        # faz o resultado dele ser jogado fora quando aterrissar (e o mesmo
        # vale para os avisos da animação). O callback fica de pé — quem o
        # registrou (a página de detalhes) não deixou de querer o fundo porque
        # a imagem trocou; quer o da nova.
        self._blur_generation += 1
        self._blur_loading = False
        self.path = path
        # A different image: the sharp copy is of the old one. Re-decoded below
        # rather than just dropped, because the details page may be open on
        # this very game — editing its cover shows the result immediately.
        self._details_texture = None

        if path:
            if path.suffix.lower() in (".gif", ".webp"):
                # Só o primeiro quadro agora; a animação toca pela cópia
                # reduzida quando algum motivo pedir (`_reconcile_animation`).
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

        # Uma capa animada nova (ou trocada) pode estar à vista: a janela
        # reavalia. As prévias do seletor e os testes não têm janela.
        if self._animated_path is not None and hasattr(shared.win, "agendar_autoplay"):
            shared.win.agendar_autoplay()

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
        if size is None and (
            pixbuf := GameCover._pre_decodificadas.pop(path, None)
        ) is not None:
            return texture_from_pixbuf(pixbuf)
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
        except (OSError, GLib.Error) as error:
            # Last decoder in the chain: the cover file itself is unreadable.
            logging.warning("Unreadable cover %s: %s", Path(path).name, error)
            return None

    def get_texture(self) -> Gdk.Texture:
        return self._frame_texture or self.texture

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
            entregar_na_tela(self._blur_ready, generation, computed)

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
        # Sem picture a animação para sozinha (`_quadro`); com uma de volta,
        # retoma se algum motivo segue ligado.
        self._reconcile_animation()

    def add_details_picture(self, picture: Gtk.Picture) -> None:
        """Drive ``picture`` as the details page's cover, at its own size.

        Only still covers get their own texture. An animated one is about to
        start playing, and the copy it plays already comes at this size (or,
        while that copy is being made, the grid's one stretched), so a sharper
        still would only show for an instant before being replaced.
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

        The details picture gets the sharper texture. Only still covers have
        one, so an animated cover draws the same frame in every picture.
        """
        if picture is self._details_picture and self._details_texture is not None:
            return self._details_texture
        return self.get_texture() or self.placeholder

    def release_picture(self, picture: Gtk.Picture) -> None:
        """Stop driving ``picture``; another cover has taken it over.

        Handing a picture to a new cover is not enough on its own: this one goes
        on repainting every picture it still lists whenever a frame of its
        animation arrives (one already on its way when it was paused, or any
        after it plays again) — long after a cover swap looked finished, the
        library thumbnail would quietly revert to the old artwork.

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
        return self._hover_active or self._details_active or self._visible_active

    @property
    def animada(self) -> bool:
        """Se a capa é animada (GIF/WebP de mais de um quadro, até onde se sabe)."""
        return self._animated_path is not None

    def set_hover_animation(self, playing: bool) -> None:
        """Play while the pointer hovers the cover in the library grid"""
        self._hover_active = playing
        self._reconcile_animation()

    def set_details_animation(self, playing: bool) -> None:
        """Play while the cover is shown on the details page (ignores hover)"""
        self._details_active = playing
        self._reconcile_animation()

    def set_visible_animation(self, playing: bool) -> None:
        """Toca enquanto a capa está à vista na grade (reprodução automática).

        A janela chama isto em toda parada de rolagem, para cada capa animada:
        sem mudança, não faz nada.
        """
        if playing == self._visible_active:
            return
        self._visible_active = playing
        self._reconcile_animation()

    def desligar_animacao(self) -> None:
        """Desliga todos os motivos de uma vez. Para quem solta a capa de vez:
        o tocador a seguraria tocando sem ninguém ver por qualquer motivo
        esquecido ligado."""
        self._hover_active = self._details_active = self._visible_active = False
        self._reconcile_animation()

    def _reconcile_animation(self) -> None:
        """Toca ou pausa conforme os motivos.

        Com algum motivo ligado, toca a cópia do tamanho em que a capa aparece
        (a dos detalhes com a página de detalhes, senão a da grade). A troca de
        uma cópia para a outra segue do mesmo instante: as duas têm a mesma
        duração total, mas não necessariamente os mesmos quadros. A cópia que
        falta é pedida a cada reconcile: a fila junta os pedidos repetidos, e um
        pedido cancelado não avisa ninguém, então um "pedido em andamento"
        guardado aqui poderia nunca mais deixar pedir.
        """
        tocador = tocador_capas.tocador
        if not (self.active and self._animated_path):
            tocador.parar(self)
            return

        origem = self._animated_path
        geracao = self._blur_generation
        grade, detalhes = copias_animadas.tamanhos()
        tamanho = detalhes if self._details_active else grade
        copia = copias_animadas.caminho_para(origem, tamanho)
        if not copia.is_file():
            if not self._gravacao_falhou:
                copias_animadas.pedir(
                    origem, copia, tamanho, partial(self._copia_pronta, geracao)
                )
            # Os detalhes tocam a cópia da grade, ampliada, até a deles sair.
            copia = copias_animadas.caminho_para(origem, grade)
            if not copia.is_file():
                tocador.parar(self)
                self._frame_texture = None
                self.set_texture(self.texture)
                return

        tocador.tocar(
            self,
            copia,
            ao_quadro=partial(self._quadro, geracao),
            ao_falhar=partial(self._copia_falhou, geracao, copia),
            posicao_inicial_ms=tocador.posicao_ms(self),
        )

    def _copia_pronta(self, geracao: int, resultado: Resultado) -> None:
        """O fim de um pedido de cópia. Thread principal."""
        if geracao != self._blur_generation:
            return  # pedido da imagem anterior
        if resultado == "pronta":
            self._reconcile_animation()
        elif resultado in ("estatica", "ilegivel"):
            # Um quadro só, ou nem abre: deixa de ser animada. A ilegível
            # mostra a capa padrão, como um jogo sem capa.
            self._animated_path = None
            tocador_capas.tocador.parar(self)
            self._frame_texture = None
            if resultado == "ilegivel":
                self.texture = None
            self.set_texture(self.texture)
        elif resultado == "falhou":
            # Disco cheio, sem permissão, sem memória: fica como está (a
            # cópia da grade, se houver, ou o quadro parado) e não pede mais
            # até a capa mudar.
            self._gravacao_falhou = True

    def _quadro(self, geracao: int, dados: bytes, largura: int, altura: int) -> None:
        """Um quadro do tocador, em RGBA. Thread principal."""
        if geracao != self._blur_generation or self._animated_path is None:
            return  # quadro da imagem anterior, já a caminho quando ela trocou
        if not self.pictures:
            # Ninguém mostra mais esta capa: quem a soltou não precisa lembrar
            # de desligar cada motivo. `add_picture` retoma.
            tocador_capas.tocador.parar(self)
            return
        self._frame_texture = Gdk.MemoryTexture.new(
            largura,
            altura,
            Gdk.MemoryFormat.R8G8B8A8,
            GLib.Bytes.new(dados),
            largura * 4,
        )
        self.set_texture(self._frame_texture)

    def _copia_falhou(self, geracao: int, copia: Path) -> None:
        """O tocador desistiu da cópia (três leituras seguidas falharam).

        A cópia está corrompida: apaga e reconcilia, que a pede de novo. Se já
        não existe (a capa acabou de trocar e as cópias foram apagadas), não é
        corrupção, e o reconcile basta.
        """
        if geracao == self._blur_generation:
            try:
                copia.unlink(missing_ok=True)
            except OSError as erro:
                # Presa: reconciliar tocaria a mesma cópia e falharia de novo,
                # em loop. Fica no último quadro até o próximo motivo.
                logging.warning("Cópia animada %s não apagada: %s", copia.name, erro)
                return
        self._reconcile_animation()
