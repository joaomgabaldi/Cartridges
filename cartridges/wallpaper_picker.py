# wallpaper_picker.py
#
# Copyright 2026 kramo
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

"""A escolha à mão do papel de parede da sessão.

A busca automática acerta o tema e erra o enquadramento: medido numa página de
resultados de verdade, um em cada doze cortes parte alguém ao meio, porque a
arte é larga e o monitor é estreito. Nenhuma ordenação conserta isso — o site
não diz onde está o assunto da imagem —, então esta tela é a régua: a grade
mostra os candidatos JÁ CORTADOS, no formato do monitor, e a barrinha desliza
a faixa antes de gravar.

Toda a fidelidade vem de uma coisa só: a miniatura e o arquivo final passam
pela mesma :func:`~cartridges.utils.session_wallpaper.enquadrar`. Como ela
corta em proporção, o quadro de 146px da grade e o de 1080px do monitor são o
mesmo quadro. O que se vê aqui é o que vai para a parede, não uma ideia dele.
"""

import logging
import shutil
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests
from gi.repository import Adw, Gdk, Gio, GLib, Gtk
from PIL import Image, UnidentifiedImageError

from cartridges import shared
from cartridges.utils.download import download_bytes
from cartridges.utils.name_cleaner import clean_game_name
from cartridges.utils.session_wallpaper import (
    alvo,
    eixo_do_corte,
    enquadrar,
    imagem_para_textura_bytes,
)
from cartridges.utils.wallhaven import IMAGE_SUFFIXES, WallhavenError, buscar

# Uma página do site. A grade de quatro colunas mostra seis linhas com isso.
MAX_RESULTS = 24

# Altura da célula da grade, em pixels lógicos. A largura sai da proporção do
# monitor: com uma tela 9:16 dá 146, com uma 3:4 dá 195 — e nos dois casos a
# célula é a tela em miniatura.
CELL_HEIGHT = 260

# Altura da prévia grande, onde a faixa é escolhida.
PREVIEW_HEIGHT = 440


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/wallpaper-picker.ui")
class WallpaperPicker(Adw.Dialog):
    __gtype_name__ = "WallpaperPicker"

    header_bar: Adw.HeaderBar = Gtk.Template.Child()
    none_button: Gtk.Button = Gtk.Template.Child()
    search_bar: Gtk.SearchBar = Gtk.Template.Child()
    search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    stack: Gtk.Stack = Gtk.Template.Child()
    status_page: Adw.StatusPage = Gtk.Template.Child()
    flowbox: Gtk.FlowBox = Gtk.Template.Child()
    adjust_picture: Gtk.Picture = Gtk.Template.Child()
    adjust_hint: Gtk.Label = Gtk.Template.Child()
    adjust_scale: Gtk.Scale = Gtk.Template.Child()
    adjust_adjustment: Gtk.Adjustment = Gtk.Template.Child()
    adjust_back: Gtk.Button = Gtk.Template.Child()
    adjust_apply: Gtk.Button = Gtk.Template.Child()

    def __init__(
        self,
        name: str,
        on_selected: Callable[[Path, float], None],
        on_cleared: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)

        self.on_selected = on_selected
        self.on_cleared = on_cleared

        self.largura, self.altura = alvo()
        self.cell_width = max(1, round(CELL_HEIGHT * self.largura / self.altura))

        # A mesma guarda de geração das outras duas telas de escolha: uma
        # busca em voo quando outra começa (ou quando a janela fecha) não pode
        # despejar os resultados dela na grade.
        self._generation = 0
        self._debounce_id = 0
        self._closed = False
        self._results: dict[Gtk.FlowBoxChild, dict[str, Any]] = {}
        self._added = 0
        self._last_query: Optional[str] = None
        self._temp_dir = Path(tempfile.mkdtemp(prefix="cartridges_wallpaper_"))

        # O que está aberto na tela de ajuste: o original inteiro (que é o que
        # vai ser gravado) e uma cópia pequena, que é de onde cada arrastada da
        # barrinha recorta. Recortar o 4K a cada pixel de arrasto travaria.
        self._bytes: bytes = b""
        self._suffix = ".jpg"
        self._previa: Optional[Image.Image] = None

        self.search_entry.set_text(clean_game_name(name))

        self.search_entry.connect("search-changed", self._on_search_changed)
        self.search_entry.connect("activate", lambda *_: self.search())
        self.flowbox.connect("child-activated", self._on_child_activated)
        self.none_button.connect("clicked", self._on_none_clicked)
        self.adjust_adjustment.connect("value-changed", self._on_position_changed)
        self.adjust_back.connect("clicked", lambda *_: self._show_results())
        self.adjust_apply.connect("clicked", self._on_apply_clicked)
        self.connect("closed", self._on_closed)

        self.search()

    # region Search

    def _on_search_changed(self, *_args: Any) -> None:
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(500, self._debounce_fire)

    def _debounce_fire(self) -> bool:
        self._debounce_id = 0
        # O set_text do __init__ emite um search-changed atrasado; sem este
        # guard, abrir a janela buscava duas vezes a mesma coisa.
        if self.search_entry.get_text().strip() == self._last_query:
            return False
        self.search()
        return False

    def search(self) -> None:
        self._generation += 1
        generation = self._generation
        self._clear_results()

        query = self.search_entry.get_text().strip()
        self._last_query = query
        if not query:
            self._show_empty(_("Digite o nome de um jogo"))
            return

        self.stack.set_visible_child_name("loading")
        threading.Thread(
            target=self._search_thread, args=(query, generation), daemon=True
        ).start()

    def _search_thread(self, query: str, generation: int) -> None:
        try:
            # Retrato primeiro e paisagem depois, na mesma grade: o que não
            # precisa de corte aparece na frente, e o que precisa continua à
            # mão logo abaixo — em quatro de cada cinco jogos ele é tudo o que
            # existe.
            achados = buscar(query, self.largura, self.altura, retrato=True)
            vistos = {item["id"] for item in achados}
            achados += [
                item
                for item in buscar(query, self.largura, self.altura, retrato=False)
                if item["id"] not in vistos
            ]
        except WallhavenError as error:
            logging.warning("Busca de papel de parede falhou: %s", error)
            GLib.idle_add(self._show_empty, _("Não foi possível buscar"), generation)
            return

        if not achados:
            GLib.idle_add(
                self._show_empty, _("Nenhum papel de parede encontrado"), generation
            )
            return

        # Seis de cada vez, na ordem da busca. Uma por vez, com 15s de limite
        # cada, uma rede ruim segurava a grade por minutos — e a janela fechada
        # só era notada entre uma miniatura e a seguinte.
        candidatos = achados[:MAX_RESULTS]
        with ThreadPoolExecutor(max_workers=6) as executor:
            miniaturas = executor.map(
                lambda item: self._miniatura(item, generation), candidatos
            )
            for item, dados in zip(candidatos, miniaturas):
                if generation != self._generation:
                    return
                if dados is not None:
                    GLib.idle_add(self._add_result, dados, item, generation)

        GLib.idle_add(self._finish_results, generation)

    def _miniatura(self, item: dict[str, Any], generation: int) -> Optional[bytes]:
        """A miniatura de ``item`` já cortada, em PNG. None quando não deu."""
        if generation != self._generation:
            return None  # busca trocada ou janela fechada: nem baixa
        try:
            miniatura = download_bytes(str(item["thumb"]), timeout=15)
        except requests.RequestException as error:
            logging.info("Miniatura não baixou (%s)", error)
            return None
        caminho = self._temp_dir / f"{item['id']}.img"
        try:
            caminho.write_bytes(miniatura)
            with Image.open(caminho) as arquivo:
                quadro = enquadrar(arquivo.convert("RGB"), *self._cell_pixels())
            return imagem_para_textura_bytes(quadro)
        except (OSError, UnidentifiedImageError, ValueError):
            return None

    def _cell_pixels(self) -> tuple[int, int]:
        """A célula em pixels de verdade, para não sair borrada num monitor HiDPI."""
        escala = max(1, int(shared.scale_factor))
        return self.cell_width * escala, CELL_HEIGHT * escala

    def _finish_results(self, generation: int) -> bool:
        if generation != self._generation or self._closed:
            return False
        if not self._added:
            self._show_empty(_("Não foi possível carregar as pré-visualizações"))
        return False

    # endregion
    # region Results

    def _add_result(
        self, dados: bytes, item: dict[str, Any], generation: int
    ) -> bool:
        if generation != self._generation or self._closed:
            return False

        try:
            textura = Gdk.Texture.new_from_bytes(GLib.Bytes.new(dados))
        except GLib.Error:
            return False

        picture = Gtk.Picture(
            paintable=textura,
            content_fit=Gtk.ContentFit.COVER,
            width_request=self.cell_width,
            height_request=CELL_HEIGHT,
            can_shrink=True,
        )
        picture.add_css_class("wallpaper-preview")

        self.flowbox.append(picture)
        if child := picture.get_parent():
            child.set_focusable(True)
            self._results[child] = item
        self._added += 1
        self.stack.set_visible_child_name("results")
        return False

    def _clear_results(self) -> None:
        self._results.clear()
        self._added = 0
        self.flowbox.remove_all()

    def _show_empty(self, message: str, generation: Optional[int] = None) -> bool:
        if generation is not None and generation != self._generation:
            return False
        self.status_page.set_description(message)
        self.stack.set_visible_child_name("empty")
        return False

    def _show_results(self) -> None:
        # A imagem aberta some junto com a tela de ajuste: são dezenas de MB
        # de bitmap, e voltar para a grade quer dizer que ela foi descartada.
        self._previa = None
        self._bytes = b""
        self.stack.set_visible_child_name("results" if self._added else "empty")

    # endregion
    # region Adjust

    def _on_child_activated(
        self, _flowbox: Gtk.FlowBox, child: Gtk.FlowBoxChild
    ) -> None:
        if not (item := self._results.get(child)):
            return
        self.stack.set_visible_child_name("loading")
        threading.Thread(
            target=self._open_thread, args=(item, self._generation), daemon=True
        ).start()

    def _open_thread(self, item: dict[str, Any], generation: int) -> None:
        url = str(item["path"])
        try:
            conteudo = download_bytes(url, timeout=45)
        except requests.RequestException as error:
            logging.warning("Não foi possível baixar o papel de parede: %s", error)
            GLib.idle_add(self._show_empty, _("Não foi possível baixar"), generation)
            return

        try:
            with Image.open(Path(self._salvar_temporario(conteudo, url))) as arquivo:
                imagem = arquivo.convert("RGB")
                escala = min(
                    1.0,
                    PREVIEW_HEIGHT
                    * max(1, int(shared.scale_factor))
                    * 2
                    / max(1, imagem.height),
                )
                previa = (
                    imagem.resize(
                        (
                            max(1, round(imagem.width * escala)),
                            max(1, round(imagem.height * escala)),
                        ),
                        Image.LANCZOS,
                    )
                    if escala < 1
                    else imagem.copy()
                )
        except (OSError, UnidentifiedImageError, ValueError) as error:
            logging.warning("Imagem baixada não pôde ser lida: %s", error)
            GLib.idle_add(self._show_empty, _("Não foi possível abrir a imagem"), generation)
            return

        GLib.idle_add(self._open_done, conteudo, url, previa, generation)

    def _salvar_temporario(self, conteudo: bytes, url: str) -> str:
        caminho = self._temp_dir / f"escolhida{Path(urlparse(url).path).suffix or '.jpg'}"
        caminho.write_bytes(conteudo)
        return str(caminho)

    def _open_done(
        self, conteudo: bytes, url: str, previa: Image.Image, generation: int
    ) -> bool:
        if generation != self._generation or self._closed:
            return False

        self._bytes = conteudo
        sufixo = Path(urlparse(url).path).suffix.lower()
        self._suffix = sufixo if sufixo in IMAGE_SUFFIXES else ".jpg"
        self._previa = previa

        # Qual eixo a barrinha move depende das duas proporções: arte larga é
        # cortada nas laterais, arte alta demais é cortada em cima e embaixo.
        # Dizer isso poupa o usuário de descobrir arrastando.
        lateral = eixo_do_corte(previa.width, previa.height, self.largura, self.altura)
        self.adjust_hint.set_label(
            _("Arraste para escolher a faixa da imagem")
            if lateral
            else _("Arraste para escolher a altura da imagem")
        )

        self.adjust_adjustment.set_value(50)
        self._redesenhar_previa()
        self.stack.set_visible_child_name("adjust")
        return False

    def _on_position_changed(self, *_args: Any) -> None:
        self._redesenhar_previa()

    def _redesenhar_previa(self) -> None:
        if self._previa is None:
            return
        escala = max(1, int(shared.scale_factor))
        largura = max(1, round(PREVIEW_HEIGHT * self.largura / self.altura))
        quadro = enquadrar(
            self._previa,
            largura * escala,
            PREVIEW_HEIGHT * escala,
            self.adjust_adjustment.get_value() / 100,
        )
        try:
            textura = Gdk.Texture.new_from_bytes(
                GLib.Bytes.new(imagem_para_textura_bytes(quadro))
            )
        except GLib.Error:
            return
        self.adjust_picture.set_size_request(largura, PREVIEW_HEIGHT)
        self.adjust_picture.set_paintable(textura)

    def _on_apply_clicked(self, *_args: Any) -> None:
        if not self._bytes:
            return
        # Entregue fora da pasta temporária desta janela, que é apagada ao
        # fechar: quem chamou segura o arquivo até o Aplicar da edição — ou
        # até o Cancelar, que continua cancelando.
        try:
            modelo = f"cartridges_wallpaper_XXXXXX{self._suffix}"
            arquivo, fluxo = Gio.File.new_tmp(modelo)
            # Fechado antes da escrita: aberto, o fluxo que `new_tmp` devolve
            # segura o arquivo até o coletor de lixo passar.
            fluxo.close()
            caminho = Path(arquivo.get_path())
            caminho.write_bytes(self._bytes)
        except (GLib.Error, OSError) as error:
            logging.warning("Não foi possível guardar a escolha: %s", error)
            self._show_empty(_("Não foi possível guardar a imagem"))
            return

        self.on_selected(caminho, self.adjust_adjustment.get_value() / 100)
        self.close()

    # endregion

    def _on_none_clicked(self, *_args: Any) -> None:
        self.on_cleared()
        self.close()

    def _on_closed(self, *_args: Any) -> None:
        self._closed = True
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
            self._debounce_id = 0
        self._generation += 1
        self._clear_results()
        self._previa = None
        self._bytes = b""
        shutil.rmtree(self._temp_dir, ignore_errors=True)
