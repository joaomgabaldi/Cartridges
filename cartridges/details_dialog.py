# details_dialog.py
#
# Copyright 2022-2024 kramo
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

# pyright: reportAssignmentType=none

import logging
import re
import threading
from pathlib import Path
from time import time
from typing import Any, Optional

from gi.repository import Adw, Gio, GLib, Gtk
from PIL import Image, UnidentifiedImageError

from cartridges import shared
from cartridges.errors.friendly_error import FriendlyError
from cartridges.game import Game, STATUS_LABELS
from cartridges.game_cover import GameCover
from cartridges.logo_picker import LogoPicker
from cartridges.wallpaper_picker import WallpaperPicker
from cartridges.sgdb_picker import SgdbPicker
from cartridges.steam_picker import SteamPicker
from cartridges.store.managers.cover_manager import CoverManager
from cartridges.store.managers.hltb_manager import shared_helper as shared_hltb_helper
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils import session_fita, window_geometry
from cartridges.utils.create_dialog import create_dialog
from cartridges.utils.game_folder import game_folder, open_folder
from cartridges.utils.game_logo import (
    IMAGE_SUFFIXES,
    logo_choice,
    reset_logo,
    save_manual_logo,
    use_title_instead,
)
from cartridges.utils.hltb import HLTBTimes, fetch_times, has_times
from cartridges.utils.session_wallpaper import (
    Posicoes,
    escolha as wallpaper_choice,
    nao_trocar,
    redefinir as reset_wallpaper,
    salvar_escolha,
)
from cartridges.utils.name_cleaner import clean_for_search, clean_game_name
from cartridges.utils.run_executable import aumid_from_command
from cartridges.utils.save_cover import convert_cover, save_cover
from cartridges.utils.steam import (
    STEAM_METADATA_VERSION,
    SteamAPIHelper,
    SteamGameNotFoundError,
    SteamRateLimiter,
)


# Folga do arredondamento da caixa de cores, que fala RGB: a cor escolhida ali
# passa pelo campo hexadecimal, de 8 bits por canal, e volta com um ou dois
# graus de matiz a menos. Sem a folga, `aplicar_fita` leria isso como escolha
# de gente e marcaria a cor como "escolhida à mão" sem que ninguém a tivesse
# trocado. Medido: `set_rgba` seguido de `get_rgba`, sem a caixa no meio,
# devolve matiz e saturação idênticos — um teste que só faça essa ida e volta
# não reproduz a deriva, e não é motivo para tirar a folga daqui.
FOLGA_MATIZ = 2
FOLGA_SATURACAO = 10


def _mesma_cor(uma: session_fita.Cor, outra: session_fita.Cor) -> bool:
    """Se duas cores são a mesma cor aos olhos — não ao bit.

    A distância de matiz é circular: 359 e 0 são vizinhos, e um vermelho de
    capa cai bem em cima dessa emenda.
    """
    distancia = abs(uma.matiz - outra.matiz) % 360
    return (
        min(distancia, 360 - distancia) <= FOLGA_MATIZ
        and abs(uma.saturacao - outra.saturacao) <= FOLGA_SATURACAO
        and uma.brilho == outra.brilho
    )


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/details-dialog.ui")
class DetailsDialog(Adw.Dialog):
    __gtype_name__ = "DetailsDialog"

    cover_overlay: Gtk.Overlay = Gtk.Template.Child()
    cover: Gtk.Picture = Gtk.Template.Child()
    cover_button_browse: Gtk.Button = Gtk.Template.Child()
    cover_button_edit: Gtk.Button = Gtk.Template.Child()
    cover_button_delete_revealer: Gtk.Revealer = Gtk.Template.Child()
    cover_button_delete: Gtk.Button = Gtk.Template.Child()
    spinner: Adw.Spinner = Gtk.Template.Child()

    logo_row: Adw.ActionRow = Gtk.Template.Child()
    logo_button_browse: Gtk.Button = Gtk.Template.Child()
    logo_button_file: Gtk.Button = Gtk.Template.Child()
    logo_button_reset: Gtk.Button = Gtk.Template.Child()

    wallpaper_row: Adw.ActionRow = Gtk.Template.Child()
    wallpaper_button_browse: Gtk.Button = Gtk.Template.Child()
    wallpaper_button_file: Gtk.Button = Gtk.Template.Child()
    wallpaper_button_reset: Gtk.Button = Gtk.Template.Child()

    fita_row: Adw.ActionRow = Gtk.Template.Child()
    fita_button_reset: Gtk.Button = Gtk.Template.Child()
    fita_color_button: Gtk.ColorDialogButton = Gtk.Template.Child()
    fita_brilho_row: Adw.SpinRow = Gtk.Template.Child()

    name: Adw.EntryRow = Gtk.Template.Child()
    steam_fetch_stack: Gtk.Stack = Gtk.Template.Child()
    steam_fetch_button: Gtk.Button = Gtk.Template.Child()
    steam_fetch_spinner: Adw.Spinner = Gtk.Template.Child()
    developer: Adw.EntryRow = Gtk.Template.Child()
    publisher: Adw.EntryRow = Gtk.Template.Child()
    release_date: Adw.EntryRow = Gtk.Template.Child()
    genre: Adw.EntryRow = Gtk.Template.Child()
    controller_support: Adw.ComboRow = Gtk.Template.Child()
    status: Adw.ComboRow = Gtk.Template.Child()
    rating_row: Adw.ActionRow = Gtk.Template.Child()
    rating_box: Gtk.Box = Gtk.Template.Child()
    executable: Adw.EntryRow = Gtk.Template.Child()
    run_as_admin_switch: Adw.SwitchRow = Gtk.Template.Child()
    track_process_switch: Adw.SwitchRow = Gtk.Template.Child()
    process_executable: Adw.EntryRow = Gtk.Template.Child()
    track_updates_switch: Adw.SwitchRow = Gtk.Template.Child()

    file_chooser_button: Gtk.Button = Gtk.Template.Child()
    open_folder_button: Gtk.Button = Gtk.Template.Child()

    apply_button: Gtk.Button = Gtk.Template.Child()

    cover_changed: bool = False

    # How many background operations are in flight. Apply is sensitive exactly
    # when this is 0 (see `begin_loading`).
    _loading_ops: int = 0

    # Metacritic score and Steam review summary from the last Steam fetch. There
    # are no editable rows for them, so they're stashed here and written to the
    # game on apply (None = leave whatever the game already has).
    fetched_metacritic: Optional[int] = None
    fetched_steam_review: Optional[str] = None
    # Same treatment for the gamepad recommendation: it is a claim Steam either
    # makes or does not, with nothing for the user to correct, so it gets no
    # row of its own and rides along on the fetch.
    fetched_gamepad_recommended: Optional[bool] = None
    # And for the description: prose from Steam, not a field to type into.
    fetched_description: Optional[str] = None

    # Appid the last fetch resolved to. Written to the game on apply so future
    # refreshes reuse it instead of searching the title again.
    fetched_steam_appid: Optional[str] = None

    # HowLongToBeat estimates from the last fetch. Like the scores above there
    # is no editable row for them (they are a read-only reference), so they
    # ride along here until apply.
    fetched_hltb: Optional[HLTBTimes] = None

    is_open: bool = False

    # What the user asked for the details page header, staged until apply so
    # Cancel really cancels. None means "untouched"; otherwise a pair of
    # (choice, file), where choice is "manual" (use the file), "title" (no logo
    # at all) or "auto" (forget the decision and let the lookup run again).
    _logo_choice: Optional[tuple[str, Optional[Path]]] = None
    _wallpaper_choice: Optional[tuple[str, Optional[Path], Posicoes]] = None
    # O arquivo temporário que a tela de escolha entregou, e que é desta tela
    # apagar. None quando a escolha veio do disco do usuário, que não se apaga.
    _wallpaper_tmp: Optional[Path] = None

    # A nota escolhida nas estrelas, de 0 a 5. Guardada aqui até o Aplicar,
    # como todo o resto do diálogo: clicar numa estrela e depois cancelar não
    # pode ter mudado a nota do jogo.
    _rating: int = 0

    # The folder behind `open_folder_button`, kept in step with the executable
    # field. None means the command names no folder we can find.
    _game_folder: Optional[str] = None

    # A cor da fita como a linha a mostrou por último. É contra ela que o
    # Aplicar decide se houve escolha de gente — ver `aplicar_fita`.
    _fita_mostrada: Optional[session_fita.Cor] = None

    # "Voltar a tirar a cor da capa" foi pedido, mas ainda não aconteceu: como
    # toda escolha desta tela, ela fica em memória até o Aplicar, e fechar no X
    # a desfaz.
    _fita_redefinir: bool = False

    # Se a prévia ao vivo chegou a pintar alguma fita nesta abertura da tela.
    _fita_previa_usada: bool = False

    def __init__(self, game: Optional[Game] = None, **kwargs: Any):
        super().__init__(**kwargs)

        # Make it so only one dialog can be open at a time
        self.__class__.is_open = True
        self.connect("closed", lambda *_: self.set_is_open(False))

        # Editing a game must not move the library. Snapshot the scroll
        # position before the dialog takes focus and put it back once it's
        # closed, however it was closed.
        shared.win.store_library_scroll()
        self.connect("closed", lambda *_: shared.win.restore_library_scroll())
        self.connect("closed", lambda *_: self.discard_wallpaper_tmp())

        self.game: Optional[Game] = game
        self.game_cover: GameCover = GameCover({self.cover})

        # "Sem status" e depois os status na ordem de STATUS_LABELS. Montado
        # aqui, e não no .blp, para que a posição de cada opção e o valor que
        # ela grava saiam da mesma lista — ver STATUS_VALUES.
        self.status.set_model(
            Gtk.StringList.new([_("Sem status"), *STATUS_LABELS.values()])
        )

        self.rating_buttons: list[Gtk.Button] = []
        for value in range(1, 6):
            button = Gtk.Button(
                valign=Gtk.Align.CENTER,
                # A variável é o número de estrelas
                tooltip_text=ngettext("{} estrela", "{} estrelas", value).format(
                    value
                ),
            )
            button.add_css_class("flat")
            button.connect("clicked", self.on_star_clicked, value)
            self.rating_box.append(button)
            self.rating_buttons.append(button)

        if self.game:
            self.set_title(_("Detalhes do jogo"))
            self.name.set_text(self.game.name)
            if self.game.developer:
                self.developer.set_text(self.game.developer)
            if self.game.publisher:
                self.publisher.set_text(self.game.publisher)
            if self.game.release_date:
                self.release_date.set_text(self.game.release_date)
            if self.game.genre:
                self.genre.set_text(self.game.genre)
            self.set_controller_support(self.game.controller_support)
            self.set_status(self.game.status)
            self._rating = self.game.stars
            self.executable.set_text(self.game.executable)
            self.run_as_admin_switch.set_active(self.game.run_as_admin)

            self.track_process_switch.set_active(self.game.track_process)

            self.track_updates_switch.set_active(self.game.track_updates)
            # Pre-fill the process name: use the saved value, else derive it from
            # the launch command when that points to an .exe (blank otherwise).
            process_exe = self.game.process_executable or self.exe_name_from_command(
                self.game.executable
            )
            if process_exe:
                self.process_executable.set_text(process_exe)

            self.apply_button.set_label(_("Aplicar"))

            self.game_cover.new_cover(self.game.get_cover_path())
            self.game_cover.set_details_animation(True)
            if self.game_cover.get_texture():
                self.cover_button_delete_revealer.set_reveal_child(True)
        else:
            self.set_title(_("Adicionar novo jogo"))
            self.apply_button.set_label(_("Adicionar"))

        # Lido uma vez, ao abrir: é hardware, e a linha do papel de parede só
        # tem o que escolher com algum monitor além do principal.
        self._has_secondary_monitor = window_geometry.has_secondary_monitor()

        self.update_rating_stars()
        self.update_process_rows()
        self.update_open_folder_button()
        self.update_logo_row()
        self.update_wallpaper_row()
        self.atualizar_fita()

        image_filter = Gtk.FileFilter(name=_("Imagens"))

        # .palm and .pdf are write-only
        for extension in set(Image.registered_extensions()) - {".palm", ".pdf"}:
            image_filter.add_suffix(extension[1:])

        image_filter.add_suffix("svg")  # Gdk.Texture supports .svg but PIL doesn't

        image_filters = Gio.ListStore.new(Gtk.FileFilter)
        image_filters.append(image_filter)

        # Windows executables and launchable files. The old filter used the
        # freedesktop MIME type "application/x-executable", which does not
        # match .exe files on Windows and left the chooser empty.
        exec_filter = Gtk.FileFilter(name=_("Executáveis"))
        for suffix in ("exe", "bat", "cmd", "lnk", "url"):
            exec_filter.add_suffix(suffix)

        exec_filters = Gio.ListStore.new(Gtk.FileFilter)
        exec_filters.append(exec_filter)

        self.image_file_dialog = Gtk.FileDialog()
        self.image_file_dialog.set_filters(image_filters)
        self.image_file_dialog.set_default_filter(image_filter)

        self.exec_file_dialog = Gtk.FileDialog()
        self.exec_file_dialog.set_filters(exec_filters)
        self.exec_file_dialog.set_default_filter(exec_filter)

        # Um seletor próprio para o logo, mais estreito que o das capas: o
        # arquivo escolhido é copiado como está por save_manual_logo, sem
        # conversão no meio, então a lista é o que o cabeçalho sabe desenhar
        # (GdkPixbuf) — não a lista larga do Pillow que vale para capas.
        logo_filter = Gtk.FileFilter(name=_("Imagens de logo"))
        for suffix in IMAGE_SUFFIXES:
            logo_filter.add_suffix(suffix[1:])
        logo_filters = Gio.ListStore.new(Gtk.FileFilter)
        logo_filters.append(logo_filter)

        self.logo_file_dialog = Gtk.FileDialog()
        self.logo_file_dialog.set_filters(logo_filters)
        self.logo_file_dialog.set_default_filter(logo_filter)

        self.cover_button_delete.connect("clicked", self.delete_pixbuf)
        self.cover_button_edit.connect("clicked", self.choose_cover)
        self.cover_button_browse.connect("clicked", self.browse_covers)
        self.logo_button_browse.connect("clicked", self.browse_logos)
        self.logo_button_file.connect("clicked", self.choose_logo_file)
        self.logo_button_reset.connect("clicked", self.reset_logo_choice)
        self.wallpaper_button_browse.connect("clicked", self.browse_wallpapers)
        self.wallpaper_button_file.connect("clicked", self.choose_wallpaper_file)
        self.wallpaper_button_reset.connect("clicked", self.reset_wallpaper_choice)
        self.fita_button_reset.connect("clicked", self.redefinir_fita)
        # Cor e brilho aparecem na parede enquanto se mexe neles: escolher cor
        # de fita olhando só para o quadradinho da tela não diz nada sobre como
        # ela fica atrás do monitor.
        self.fita_color_button.connect("notify::rgba", self.previa_da_fita)
        self.fita_brilho_row.connect("notify::value", self.previa_da_fita)
        # Fechar sem aplicar desfaz a prévia: o que vale fora desta tela é o
        # roxo do app.
        self.connect("closed", lambda *_: self.encerrar_previa())
        self.steam_fetch_button.connect("clicked", self.fetch_metadata)
        self.file_chooser_button.connect("clicked", self.choose_executable)
        self.open_folder_button.connect("clicked", self.open_game_folder)
        self.apply_button.connect("clicked", self.apply_preferences)

        self.name.connect("entry-activated", self.focus_executable)
        # Editing the title invalidates the scores of the last Steam fetch, so
        # values from a previously fetched (different) game are never applied
        self.name.connect("changed", self.invalidate_fetched_scores)
        self.developer.connect("entry-activated", self.focus_executable)
        self.publisher.connect("entry-activated", self.focus_executable)
        self.release_date.connect("entry-activated", self.focus_executable)
        self.genre.connect("entry-activated", self.focus_executable)
        self.executable.connect("entry-activated", self.apply_preferences)
        # Whether the game is packaged is a property of the command being typed,
        # so the rows that depend on it follow the field rather than the value it
        # happened to hold when the dialog opened
        self.executable.connect("changed", self.update_process_rows)
        # Same reasoning for the folder button: pointing the command somewhere
        # else points it at another folder, or at none.
        self.executable.connect("changed", self.update_open_folder_button)
        self.process_executable.connect("entry-activated", self.apply_preferences)

        self.track_process_switch.connect(
            "notify::active", self.on_track_process_toggled
        )

        self.set_focus(self.name)

    def is_packaged(self) -> bool:
        """Microsoft Store / Game Pass game, judged by the command in the field.

        Read live instead of latched in ``__init__``, because the answer changes
        while the dialog is open. "Adicionar novo jogo" starts with no game at
        all, so the latched value was always False: pasting a
        ``shell:AppsFolder\\…`` command and flipping the switch saved
        ``track_process=True`` and a process name for a game whose playtime comes
        from its package identity, where neither is ever read. Editing an
        existing classic game into a packaged one had the same effect from the
        other direction.
        """
        return bool(aumid_from_command(self.executable.get_text()))

    def update_process_rows(self, *_args: Any) -> None:
        """Match the process-tracking rows to the command currently entered.

        A packaged game tracks its playtime from the package identity, so the
        manual process-watching rows have nothing to offer it and are hidden.
        """
        packaged = self.is_packaged()
        self.track_process_switch.set_visible(not packaged)
        self.process_executable.set_visible(
            self.track_process_switch.get_active() and not packaged
        )

    def update_open_folder_button(self, *_args: Any) -> None:
        """Offer the game's folder only when the command actually names one.

        Resolved here rather than on the click so the button can be honest about
        itself: a Steam or Epic command, or a game whose folder is gone, has
        nothing to open and shows no button at all.

        The resolution stats the disk on the main thread, on every keystroke in
        the field. Deliberate: on a local disk the stat costs microseconds, and
        no library here lives on a network drive — where a dead SMB mount would
        hang this for its reconnect timeout, freezing the whole window. If
        games on network paths ever become a case to support, this resolution
        has to move off the main thread first.
        """
        self._game_folder = game_folder(self.executable.get_text())
        self.open_folder_button.set_visible(bool(self._game_folder))

    def open_game_folder(self, *_args: Any) -> None:
        open_folder(self._game_folder or "")

    def on_track_process_toggled(self, *_args: Any) -> None:
        active = self.track_process_switch.get_active()
        self.update_process_rows()
        if not active:
            return

        # Pre-fill the field from the current executable if it's still empty
        if not self.process_executable.get_text().strip():
            prefill = self.exe_name_from_command(self.executable.get_text())
            if prefill:
                self.process_executable.set_text(prefill)
        self.set_focus(self.process_executable)

    @staticmethod
    def exe_name_from_command(command: str) -> str:
        """Best-effort extraction of the game's .exe filename from a command.

        Prefers an .exe inside a quoted path (the classic-shortcut and manual-add
        form), then falls back to a bare .exe token, ignoring the launcher stubs
        commands are wrapped in. Returns "" when nothing usable is found (e.g. a
        Steam/Epic/UWP launcher), so the field stays blank in that case.
        """
        if not command:
            return ""

        candidates = re.findall(r'"([^"]*\.exe)"', command, re.IGNORECASE)
        if not candidates:
            ignored = {"explorer.exe", "cmd.exe", "start.exe"}
            candidates = [
                token
                for token in re.findall(r"\S+\.exe", command, re.IGNORECASE)
                if Path(token.strip('"')).name.casefold() not in ignored
            ]
        if not candidates:
            return ""
        return Path(candidates[-1].strip('"')).name

    def delete_pixbuf(self, *_args: Any) -> None:
        self.game_cover.new_cover()

        self.cover_button_delete_revealer.set_reveal_child(False)
        self.cover_changed = True

    def apply_preferences(self, *_args: Any) -> None:
        # Enter nas linhas de executável/processo chega aqui direto, sem passar
        # pelo botão que `begin_loading` desabilita. Aplicar com uma operação em
        # voo salvava o jogo sem os dados ainda na rede — e, com uma capa em
        # conversão, instalava a capa na sessão sem nunca gravá-la no disco.
        # O mesmo portão do botão, na porta que faltava.
        if self._loading_ops:
            return
        final_name = self.name.get_text()
        final_developer = self.developer.get_text()
        final_publisher = self.publisher.get_text()
        final_release_date = self.release_date.get_text()
        final_genre = self.genre.get_text().strip()
        final_controller_support = self.get_controller_support()
        final_status = self.get_status()
        final_executable = self.executable.get_text()

        if not self.game:
            if final_name == "":
                create_dialog(
                    self, _("Não foi possível adicionar o jogo"), _("O título do jogo não pode ficar vazio.")
                )
                return

            if final_executable == "":
                create_dialog(
                    self, _("Não foi possível adicionar o jogo"), _("O executável não pode ficar vazio.")
                )
                return

            # Increment the number after the game id (eg. imported_1, imported_2)
            source_id = "imported"
            numbers = [0]
            game_id: str
            for game_id in shared.store.source_games.get(source_id, set()):
                prefix = "imported_"
                if not game_id.startswith(prefix):
                    continue
                # Ignore ids whose suffix isn't a number (hand-edited/corrupted
                # JSON) instead of crashing the whole "add game" flow
                try:
                    numbers.append(int(game_id.replace(prefix, "", 1)))
                except ValueError:
                    continue

            game_number = max(numbers) + 1

            self.game = Game(
                {
                    "game_id": f"imported_{game_number}",
                    "hidden": False,
                    "source": source_id,
                    "added": int(time()),
                }
            )

        else:
            if final_name == "":
                create_dialog(
                    self,
                    _("Não foi possível aplicar as alterações"),
                    _("O título do jogo não pode ficar vazio."),
                )
                return

            if final_executable == "":
                create_dialog(
                    self,
                    _("Não foi possível aplicar as alterações"),
                    _("O executável não pode ficar vazio."),
                )
                return

        # Forced off for a packaged game: its rows are hidden, so an old value
        # left over from before must not trip the validation below over a switch
        # the user can no longer see.
        track_process = (
            self.track_process_switch.get_active() and not self.is_packaged()
        )
        final_process_executable = self.process_executable.get_text().strip()

        # Tracking a process needs a name to watch for; refuse to save otherwise
        if track_process and not final_process_executable:
            create_dialog(
                self,
                _("Não foi possível salvar"),
                _(
                    "Informe o nome do executável para rastrear o processo, ou "
                    "desative essa opção."
                ),
            )
            return

        self.game.name = final_name
        self.game.developer = final_developer or None
        self.game.publisher = final_publisher or None
        self.game.release_date = final_release_date or None
        self.game.genre = final_genre or None
        self.game.controller_support = final_controller_support
        self.game.status = final_status
        self.game.rating = self._rating
        # Only touch these when a fetch actually returned them, so manual edits
        # without a Steam lookup keep any existing values.
        if self.fetched_metacritic is not None:
            self.game.metacritic = self.fetched_metacritic
        if self.fetched_gamepad_recommended is not None:
            self.game.gamepad_recommended = self.fetched_gamepad_recommended
        if self.fetched_description is not None:
            self.game.description = self.fetched_description
        if self.fetched_steam_review is not None:
            self.game.steam_review = self.fetched_steam_review
        if self.fetched_steam_appid is not None:
            self.game.steam_appid = self.fetched_steam_appid
            # The fetch here goes through the same lookup the importer uses, so
            # it leaves the game as up to date as a refresh would. Without the
            # stamp, a game the user fixed by hand would keep coming back in
            # "only what is missing" to be told the same thing again.
            self.game.steam_checked = STEAM_METADATA_VERSION
        if self.fetched_hltb:
            # update_values only carries the keys the lookup actually returned,
            # so a game with only a main-story estimate keeps whatever the
            # other two already held instead of having them blanked.
            self.game.update_values(dict(self.fetched_hltb))
        self.game.executable = final_executable
        self.game.run_as_admin = self.run_as_admin_switch.get_active()
        self.game.track_process = track_process
        self.game.process_executable = final_process_executable

        # Turning tracking off clears any pending notice so re-enabling later
        # starts clean and never resurrects a stale patch from a feed that has
        # since moved on. Whether it was just switched on decides if we poll
        # right away instead of making the user wait for the next timer tick.
        track_updates = self.track_updates_switch.get_active()
        just_enabled = track_updates and not self.game.track_updates
        if not track_updates:
            self.game.update_available_ts = 0
            self.game.update_url = ""
        self.game.track_updates = track_updates

        if self.game.game_id in shared.win.game_covers.keys():
            # Fully stop the cover being replaced
            old_cover = shared.win.game_covers[self.game.game_id]
            old_cover.set_hover_animation(False)
            old_cover.set_details_animation(False)
            # Pausing it is not enough: the grid's Gtk.Picture is about to be
            # driven by the new cover, but the old one still lists it and
            # `_release_frames` repaints everything it lists half a minute after
            # being paused. The library thumbnail would flip back to the previous
            # artwork's first frame long after the edit looked applied.
            old_cover.release_picture(self.game.cover)

            # Capa inalterada: o desfoque já computado vale para o objeto novo.
            # Sem herdá-lo, um Aplicar sem mudança nenhuma recomeçava o fundo
            # do zero e a página de detalhes piscava preto por um quadro.
            if not self.cover_changed and old_cover.path == self.game_cover.path:
                self.game_cover.blurred = old_cover.blurred
                self.game_cover.luminance = old_cover.luminance

        shared.win.game_covers[self.game.game_id] = self.game_cover

        if self.cover_changed:
            save_cover(
                self.game.game_id,
                self.game_cover.path,
            )

        self.apply_logo_choice(self.game)
        self.apply_wallpaper_choice(self.game)
        self.aplicar_fita(self.game)

        shared.store.add_game(self.game, {}, run_pipeline=False)
        self.game.save()
        self.game.update()

        # Newly opted in: poll the feed now rather than at the next scheduled
        # tick, so the notice can appear on this session instead of a later one.
        if just_enabled:
            app = shared.win.get_application()
            checker = getattr(app, "updates_checker", None)
            if checker is not None:
                checker.check_async()

        # TODO: this is fucked up (less than before)
        # Get a cover from SGDB if none is present
        if not self.game_cover.get_texture():
            self.game.set_loading(1)
            sgdb_manager = shared.store.managers[SgdbManager]
            sgdb_manager.reset_cancellable()
            sgdb_manager.process_game(self.game, {}, self.update_cover_callback)

        # discard (not remove): a double activation (Enter + click racing the
        # dialog close) must not raise KeyError on the second pass
        self.game_cover.pictures.discard(self.cover)

        # Only jump to the game's details page if that's where the edit was
        # opened from; otherwise stay on the current screen (e.g. the library).
        on_details_page = (
            shared.win.navigation_view.get_visible_page() == shared.win.details_page
        )
        self.close()
        if on_details_page:
            shared.win.show_details_page(self.game)

    def update_cover_callback(self, manager: SgdbManager) -> None:
        # Set the game as not loading
        self.game.set_loading(-1)
        self.game.update()

        # Handle errors that occured
        for error in manager.collect_errors():
            # On auth error, inform the user
            if isinstance(error, FriendlyError):
                create_dialog(
                    shared.win,
                    error.title,
                    error.subtitle,
                    "open_preferences",
                    _("Preferências"),
                ).connect("response", self.update_cover_error_response)

    def update_cover_error_response(self, _widget: Any, response: str) -> None:
        if response == "open_preferences":
            shared.win.get_application().on_preferences_action(page_name="sgdb")

    def focus_executable(self, *_args: Any) -> None:
        self.set_focus(self.executable)

    # The combo row's positions, in the order the model lists them. Kept as a
    # pair of lookups rather than an index arithmetic trick so reordering the
    # rows in the .blp cannot silently turn "full" into "partial" in every
    # record the user saves afterwards.
    CONTROLLER_POSITIONS = {None: 0, "full": 1, "partial": 2}
    CONTROLLER_VALUES = {0: None, 1: "full", 2: "partial"}

    def set_controller_support(self, value: Optional[str]) -> None:
        """Select the row matching a stored value.

        Anything unrecognised — a hand-edited record, a value Steam invents
        later — selects "not stated", which is what the details page already
        does with it.
        """
        self.controller_support.set_selected(self.CONTROLLER_POSITIONS.get(value, 0))

    def get_controller_support(self) -> Optional[str]:
        """The stored value for the selected row, or None for "not stated"."""
        return self.CONTROLLER_VALUES.get(self.controller_support.get_selected())

    # Os valores gravados, na mesma ordem em que o modelo do seletor foi
    # montado no __init__: "" primeiro, depois as chaves de STATUS_LABELS.
    # Derivado da mesma lista de propósito — um status novo entra numa linha só
    # e as duas pontas continuam de acordo.
    STATUS_VALUES = ("", *STATUS_LABELS)

    def set_status(self, value: str) -> None:
        """Seleciona a linha de um status guardado.

        Um valor que ninguém reconhece — um registro editado à mão — cai em
        "Sem status", que é o que a tela de detalhes também faz com ele.
        """
        try:
            self.status.set_selected(self.STATUS_VALUES.index(value or ""))
        except ValueError:
            self.status.set_selected(0)

    def get_status(self) -> str:
        """O valor da linha selecionada, ou "" para sem status."""
        selected = self.status.get_selected()
        if selected >= len(self.STATUS_VALUES):
            return ""
        return self.STATUS_VALUES[selected]

    def on_star_clicked(self, _widget: Any, value: int) -> None:
        """Marca a nota, ou a tira ao clicar de novo na estrela já marcada.

        Sem esse segundo clique não haveria como voltar a "sem nota": cinco
        botões que só sobem deixariam 1 estrela como piso, e 1 estrela é uma
        opinião, não a ausência de uma.
        """
        self._rating = 0 if self._rating == value else value
        self.update_rating_stars()

    def update_rating_stars(self) -> None:
        """Preenche as estrelas até a nota atual e esvazia as demais."""
        for index, button in enumerate(self.rating_buttons, start=1):
            button.set_icon_name(
                "starred-symbolic" if index <= self._rating else "non-starred-symbolic"
            )

    def invalidate_fetched_scores(self, *_args: Any) -> None:
        """Drop the last Steam fetch (called when the title changes).

        The appid goes too: a retyped title is the user saying this is a
        different game, so keeping the old one would pin the next fetch to what
        they just corrected away from.
        """
        self.fetched_metacritic = None
        self.fetched_steam_review = None
        self.fetched_gamepad_recommended = None
        self.fetched_description = None
        self.fetched_steam_appid = None
        self.fetched_hltb = None

    def begin_loading(self, cover: bool = False) -> None:
        """Take Apply away for the duration of one background operation.

        Counted rather than toggled. The cover conversion and the metadata fetch
        both lock Apply and they overlap freely — pick a cover, then press fetch
        before the conversion lands — and with a toggle each one undid the
        other: the first to finish handed Apply back while the second was still
        running, and the second then switched it off and left it off, with
        Cancel (and losing the edits) the only way out.

        ``cover`` marks the operations that also dim the artwork and spin over
        it; the fetch has its own spinner in the button and leaves the cover
        alone.
        """
        self._loading_ops += 1
        self.apply_button.set_sensitive(False)
        if cover:
            self.spinner.set_visible(True)
            self.cover_overlay.set_opacity(0)

    def end_loading(self, cover: bool = False) -> None:
        """Give one operation back; Apply returns once the last one is done."""
        self._loading_ops = max(0, self._loading_ops - 1)
        self.apply_button.set_sensitive(self._loading_ops == 0)
        if cover:
            self.spinner.set_visible(False)
            self.cover_overlay.set_opacity(1)

    def set_cover(self, _source: Any, result: Gio.Task, *_args: Any) -> None:
        try:
            path = self.image_file_dialog.open_finish(result).get_path()
        except GLib.Error:
            return

        def finish(new_path: Optional[Path]) -> bool:
            # Runs on the main thread: GTK widgets are not thread-safe
            if new_path:
                self.game_cover.new_cover(new_path)
                self.cover_button_delete_revealer.set_reveal_child(True)
                self.cover_changed = True

            self.end_loading(cover=True)
            return False

        def thread_func() -> None:
            new_path = None

            try:
                try:
                    with Image.open(path) as image:
                        if getattr(image, "is_animated", False):
                            new_path = convert_cover(path)
                except UnidentifiedImageError:
                    pass

                if not new_path:
                    new_path = convert_cover(
                        pixbuf=shared.store.managers[CoverManager].composite_cover(
                            Path(path)
                        )
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                # `composite_cover` raises UnreadableCoverError for a truncated
                # file or an SVG nothing here can rasterise — and the file
                # filter offers SVG. Whatever the reason, this thread is the
                # only thing that can balance the loading counter: dying here
                # left the spinner turning and Apply disabled for good, which is
                # the exact failure the counter exists to prevent.
                logging.exception("Could not prepare the chosen cover")
                new_path = None

            GLib.idle_add(finish, new_path)

        self.begin_loading(cover=True)
        threading.Thread(target=thread_func, daemon=True).start()

    def set_executable(self, _source: Any, result: Gio.Task, *_args: Any) -> None:
        try:
            path = self.exec_file_dialog.open_finish(result).get_path()
        except GLib.Error:
            return

        # Windows quoting: cmd.exe only understands double quotes. shlex.quote
        # produced POSIX single quotes here, which broke every launch command
        # created through the file chooser. Windows paths cannot contain '"',
        # so wrapping is always safe.
        self.executable.set_text(f'"{path}"')

    def choose_executable(self, *_args: Any) -> None:
        self.exec_file_dialog.open(self.get_root(), None, self.set_executable)

    def choose_cover(self, *_args: Any) -> None:
        self.image_file_dialog.open(self.get_root(), None, self.set_cover)

    def browse_covers(self, *_args: Any) -> None:
        SgdbPicker(self.name.get_text(), self.set_cover_from_path).present(self)

    def browse_logos(self, *_args: Any) -> None:
        LogoPicker(
            self.name.get_text(), self.set_logo_from_path, self.set_logo_to_title
        ).present(self)

    def choose_logo_file(self, *_args: Any) -> None:
        self.logo_file_dialog.open(self.get_root(), None, self.set_logo_file)

    def set_logo_file(self, _source: Any, result: Gio.Task, *_args: Any) -> None:
        try:
            path = Path(self.logo_file_dialog.open_finish(result).get_path())
        except GLib.Error:
            return
        # O mesmo caminho em espera da escolha no SteamGridDB: nada é gravado
        # até o Aplicar, então Cancelar continua cancelando.
        self.set_logo_from_path(path)

    def set_logo_from_path(self, path: Path) -> None:
        self._logo_choice = ("manual", path)
        self.update_logo_row()

    def set_logo_to_title(self) -> None:
        self._logo_choice = ("title", None)
        self.update_logo_row()

    def reset_logo_choice(self, *_args: Any) -> None:
        self._logo_choice = ("auto", None)
        self.update_logo_row()

    def update_logo_row(self) -> None:
        """Say which of the three states the header is in, staged or saved."""
        if self._logo_choice:
            choice = self._logo_choice[0]
        elif self.game:
            choice = logo_choice(self.game)
        else:
            choice = "auto"

        self.logo_row.set_subtitle(
            {
                "manual": _("Escolhido manualmente"),
                "title": _("Sem logo, usando o título"),
            }.get(choice, _("Automático (SteamGridDB)"))
        )
        # Nothing to undo while the header is already being decided for you.
        self.logo_button_reset.set_visible(choice != "auto")

    def apply_logo_choice(self, game: Game) -> bool:
        """Write the staged header decision to disk. True when it changed.

        Deliberately last in the apply path and keyed to the final name: a
        rename applied in the same pass has to be the name the choice is
        recorded against, or the very next lookup would call it stale.
        """
        if not self._logo_choice:
            return False

        choice, path = self._logo_choice
        if choice == "manual" and path:
            save_manual_logo(game.game_id, game.name, path)
        elif choice == "title":
            use_title_instead(game.game_id, game.name)
        else:
            reset_logo(game.game_id)

        self._logo_choice = None
        return True

    # region Papel de parede da sessão

    def browse_wallpapers(self, *_args: Any) -> None:
        WallpaperPicker(
            self.name.get_text(), self.set_wallpaper_from_picker, self.set_wallpaper_none
        ).present(self)

    def choose_wallpaper_file(self, *_args: Any) -> None:
        self.image_file_dialog.open(self.get_root(), None, self.set_wallpaper_file)

    def set_wallpaper_file(self, _source: Any, result: Gio.Task, *_args: Any) -> None:
        try:
            chosen = self.image_file_dialog.open_finish(result).get_path()
        except GLib.Error:
            return
        if chosen:
            self.open_wallpaper_file(Path(chosen))

    def open_wallpaper_file(self, path: Path) -> None:
        """Leva o arquivo do disco à tela de ajuste, como uma imagem da busca.

        Nenhum arquivo serve inteiro a um arranjo com monitor em pé e deitado,
        e mesmo com uma orientação só a faixa é escolha de quem vê a imagem.
        """
        WallpaperPicker(
            self.name.get_text(),
            self.set_wallpaper_from_picker,
            self.set_wallpaper_none,
            arquivo=path,
        ).present(self)

    def set_wallpaper_from_picker(self, path: Path, posicoes: Posicoes) -> None:
        """Adota o arquivo que a tela de escolha entregou.

        Ela o entrega numa pasta temporária e o esquece — venha ele da busca ou
        do disco, é sempre uma cópia. Daqui em diante quem o apaga é esta tela:
        ao trocar de escolha, ao aplicar (a imagem já foi copiada para a pasta
        das paredes) ou ao fechar sem aplicar.
        """
        self.discard_wallpaper_tmp()
        self._wallpaper_choice = ("manual", path, posicoes)
        self._wallpaper_tmp = path
        self.update_wallpaper_row()

    def discard_wallpaper_tmp(self) -> None:
        if self._wallpaper_tmp is None:
            return
        try:
            self._wallpaper_tmp.unlink(missing_ok=True)
        except OSError as error:
            logging.info("Could not remove the staged wallpaper: %s", error)
        self._wallpaper_tmp = None

    def set_wallpaper_none(self) -> None:
        self.discard_wallpaper_tmp()
        self._wallpaper_choice = ("none", None, Posicoes())
        self.update_wallpaper_row()

    def reset_wallpaper_choice(self, *_args: Any) -> None:
        self.discard_wallpaper_tmp()
        self._wallpaper_choice = ("auto", None, Posicoes())
        self.update_wallpaper_row()

    def update_wallpaper_row(self) -> None:
        if not self._has_secondary_monitor:
            self.wallpaper_row.set_sensitive(False)
            self.wallpaper_row.set_subtitle(_("Precisa de um segundo monitor"))
            return

        if self._wallpaper_choice:
            choice = self._wallpaper_choice[0]
        elif self.game:
            choice = wallpaper_choice(self.game)
        else:
            choice = "auto"

        self.wallpaper_row.set_subtitle(
            {
                "manual": _("Escolhido manualmente"),
                "none": _("Não trocar o papel de parede"),
            }.get(choice, _("Automático (wallhaven)"))
        )
        self.wallpaper_button_reset.set_visible(choice != "auto")

    def apply_wallpaper_choice(self, game: Game) -> bool:
        """Grava a decisão em disco. True quando ela mudou.

        Como a do logo, presa ao nome final: a escolha automática é reaberta
        quando o jogo é renomeado, e o nome que vale é o desta mesma gravação.
        """
        if not self._wallpaper_choice:
            return False

        choice, path, posicoes = self._wallpaper_choice
        if choice == "manual" and path:
            salvar_escolha(game.game_id, game.name, path, posicoes)
        elif choice == "none":
            nao_trocar(game.game_id, game.name)
        else:
            reset_wallpaper(game.game_id)

        self.discard_wallpaper_tmp()
        self._wallpaper_choice = None
        return True

    # endregion
    # region Fita de LED

    def cor_automatica(self) -> session_fita.Cor:
        """A cor que a linha deve mostrar agora.

        Com a redefinição pedida, é o automático mesmo havendo escolha em
        disco: a escolha só será apagada no Aplicar, mas a tela já tem de
        mostrar o que o Aplicar vai deixar valendo.

        Jogo novo ainda não existe em disco nem tem capa de onde tirar cor: o
        que sobra é o roxo do app, que é o mesmo que ele receberia depois de
        criado e sem capa.
        """
        if self.game:
            return session_fita.cor_do_jogo(self.game, self._fita_redefinir)
        return session_fita.roxo()

    def atualizar_fita(self) -> None:
        """Mostra a cor que vale hoje: a escolhida ou a que sai da capa."""
        # Sem fita configurada não há cor para escolher, como a linha do papel
        # de parede sem um segundo monitor. Sai antes de `cor_automatica`: tirar
        # a dominante da capa custa milissegundos de thread de UI em toda
        # abertura da tela, e aqui seriam gastos para uma fita que não existe.
        if not session_fita.fitas():
            self._fita_mostrada = None
            self.fita_row.set_sensitive(False)
            self.fita_row.set_subtitle(_("Nenhuma fita configurada"))
            self.fita_brilho_row.set_sensitive(False)
            self.fita_brilho_row.set_subtitle(_("Nenhuma fita configurada"))
            self.fita_button_reset.set_visible(False)
            return

        cor = self.cor_automatica()
        self._fita_mostrada = cor
        self.fita_color_button.set_rgba(session_fita.cor_para_rgba(cor))
        self.fita_brilho_row.set_value(session_fita.por_cento(cor.brilho))

        manual = (
            bool(self.game)
            and not self._fita_redefinir
            and session_fita.escolhida(self.game.game_id)
        )
        self.fita_button_reset.set_visible(manual)
        self.fita_row.set_subtitle(
            _("Escolhida por você") if manual else _("Tirada da capa")
        )

    def previa_da_fita(self, *_args: Any) -> None:
        """Mostra nas fitas a cor e o brilho que estão na tela agora."""
        if self._fita_mostrada is None:
            return
        self._fita_previa_usada = True
        session_fita.previa(
            session_fita.rgba_para_cor(
                self.fita_color_button.get_rgba(),
                session_fita.de_por_cento(self.fita_brilho_row.get_value()),
            )
        )

    def encerrar_previa(self) -> None:
        """Devolve as fitas ao roxo do app depois de a tela sumir.

        Só quando houve prévia: sem isso, abrir e fechar a tela de um jogo
        qualquer repintaria as fitas à toa.
        """
        if self._fita_previa_usada:
            self._fita_previa_usada = False
            session_fita.previa(session_fita.roxo())

    def redefinir_fita(self, *_args: Any) -> None:
        """Marca a intenção de voltar ao automático. Quem apaga é o Aplicar."""
        if not self.game:
            return
        self._fita_redefinir = True
        self.atualizar_fita()

    def aplicar_fita(self, game: Game) -> None:
        """Grava a cor da fita, mas só quando ela é escolha de verdade.

        Quem abriu a tela para renomear um jogo não pediu cor nenhuma, e gravar
        aqui marcaria esse jogo como "cor escolhida à mão" para sempre — ele
        nunca mais acompanharia a capa. Por isso a comparação antes de gravar.
        """
        # Sem fita configurada a linha nem chega a ser preenchida, e o que está
        # nos widgets é o padrão do .blp, não escolha de ninguém: gravar dali
        # apagaria a cor que o jogo já tem em disco. A redefinição pedida passa,
        # porque apagar é justamente o que ela quer.
        if self._fita_mostrada is None and not self._fita_redefinir:
            return

        na_tela = session_fita.rgba_para_cor(
            self.fita_color_button.get_rgba(),
            session_fita.de_por_cento(self.fita_brilho_row.get_value()),
        )
        # Contra o que a linha mostrou, e não contra o automático de agora: um
        # jogo novo ganha a capa neste mesmo Aplicar, e o automático mudaria
        # debaixo da comparação sem que ninguém tivesse mexido na cor.
        mostrada = self._fita_mostrada
        escolha_nova = mostrada is not None and not _mesma_cor(na_tela, mostrada)

        if escolha_nova:
            # Uma cor escolhida depois do clique em "voltar ao automático"
            # cancela a redefinição: vale o que está na tela.
            session_fita.salvar_cor(game.game_id, game.name, na_tela)
        elif self._fita_redefinir:
            session_fita.redefinir(game.game_id)
        elif session_fita.escolhida(game.game_id):
            # Nada mudou, mas a escolha é regravada: como a do papel de parede,
            # ela guarda o nome do jogo, e o que vale é o nome deste Aplicar.
            session_fita.salvar_cor(game.game_id, game.name, na_tela)

        self._fita_redefinir = False

    # endregion

    def fetch_metadata(self, *_args: Any) -> None:
        """Look up the current title online and fill the fields for review.

        Two lookups run back to back behind one button: Steam for the
        identity of the game, then HowLongToBeat for its completion times.
        They are chained rather than parallel because the Steam step is what
        turns a messy shortcut name into the real title, and searching
        HowLongToBeat with that corrected title is what makes it match.

        Nothing is saved here: the fetched values just populate the editable
        fields so the user can check them before applying. This makes fixing a
        badly-named import easy (correct the name, fetch, review, apply)
        without ever overwriting manual edits behind the user's back.
        """
        name = self.name.get_text().strip()
        if not name:
            return
        self.steam_fetch_stack.set_visible_child(self.steam_fetch_spinner)
        # Applying mid-fetch would save the game before the lookups land and
        # silently drop everything still in flight — the estimates especially,
        # since they arrive last. The spinner already says "working"; this
        # makes the dialog actually behave that way.
        self.begin_loading()
        threading.Thread(
            target=self._fetch_metadata_thread, args=(name,), daemon=True
        ).start()

    def _fetch_metadata_thread(self, name: str) -> None:
        # Reuse the app-wide helper: creating a SteamRateLimiter per fetch would
        # leak its refill thread (it never exits) and race the shared token
        # history stored in the schema.
        manager = shared.store.managers.get(SteamAPIManager)
        helper = (
            manager.steam_api_helper
            if manager
            else SteamAPIHelper(SteamRateLimiter())
        )
        # An appid already tied to this game wins over searching the name
        # again: it is either what a previous fetch resolved or what the user
        # picked by hand, and a fresh search could quietly undo that. The saved
        # one only applies while the title is untouched — editing it means the
        # user is telling us the game is not what we had recorded.
        saved_appid = (
            self.game.steam_appid
            if self.game and name.strip() == (self.game.name or "").strip()
            else None
        )
        appid = self.fetched_steam_appid or saved_appid
        try:
            if appid:
                data = helper.get_api_data(str(appid))
            else:
                appid, data = helper.resolve(clean_for_search(name))
        except SteamGameNotFoundError:
            # Nothing the matcher trusts. Rather than adopt the closest hit —
            # which for "The Outer Worlds" is its own sequel — let the user say
            # which game this is.
            GLib.idle_add(self._fetch_metadata_choose, helper, name)
            return
        except Exception as error:  # pylint: disable=broad-exception-caught
            GLib.idle_add(self._fetch_metadata_done, None, error, str(appid or ""))
            return
        GLib.idle_add(self._fetch_metadata_done, data, None, str(appid))

    def _fetch_metadata_choose(self, helper: SteamAPIHelper, name: str) -> bool:
        """Open the picker so the user can identify the game themselves."""
        self.steam_fetch_stack.set_visible_child(self.steam_fetch_button)
        # The fetch ends here as far as the dialog is concerned: dismissing the
        # picker with Esc or a click outside never calls back, so holding Apply
        # for a callback that may never come left the user with no way to keep
        # their edits but Cancel. The picker is modal over this dialog, so an
        # enabled Apply underneath is unreachable until it is gone — which is
        # what every other exit from the fetch already does.
        self.end_loading()
        SteamPicker(name, helper, self._on_steam_picked).present(self)
        return False

    def _on_steam_picked(self, appid: str, data: dict) -> None:
        # Picking resumes the fetch `_fetch_metadata_choose` let go of, so it
        # takes the counter back for the HowLongToBeat leg that follows.
        self.begin_loading()
        self._fetch_metadata_done(data, None, appid)

    def _fetch_metadata_done(
        self, data: Optional[dict], error: Optional[Exception], appid: str = ""
    ) -> bool:
        if error is not None or not data:
            self.steam_fetch_stack.set_visible_child(self.steam_fetch_button)
            self.end_loading()
            create_dialog(
                self,
                _("Nada encontrado na Steam"),
                _("Confira o título e a conexão e tente novamente."),
            )
            return False

        if data.get("name"):
            # set_text fires "changed", which clears the fetched values; the
            # fresh ones are assigned right below, so the order matters here
            self.name.set_text(clean_game_name(data["name"]))
        if appid:
            self.fetched_steam_appid = appid
        if data.get("developer"):
            self.developer.set_text(data["developer"])
        if data.get("publisher"):
            self.publisher.set_text(data["publisher"])
        if data.get("release_date"):
            self.release_date.set_text(data["release_date"])
        if data.get("metacritic") is not None:
            self.fetched_metacritic = data["metacritic"]
        if data.get("steam_review"):
            self.fetched_steam_review = data["steam_review"]
        # Straight into the rows, like the developer and publisher above: both
        # have an editable field, so the fetch fills it in for the user to
        # check rather than deciding for them behind the dialog.
        if data.get("genre"):
            self.genre.set_text(data["genre"])
        if data.get("controller_support"):
            self.set_controller_support(data["controller_support"])
        if data.get("gamepad_recommended") is not None:
            self.fetched_gamepad_recommended = data["gamepad_recommended"]
        if data.get("description"):
            self.fetched_description = data["description"]

        # Chain straight into HowLongToBeat with the title Steam just
        # confirmed. The spinner stays up so the button reflects that the
        # fetch as a whole is still running.
        threading.Thread(
            target=self._fetch_hltb_thread,
            args=(self.name.get_text().strip(),),
            daemon=True,
        ).start()
        return False

    def _fetch_hltb_thread(self, name: str) -> None:
        """Look up ``name`` on HowLongToBeat off the main thread.

        This is the correction path: the background lookups (import pipeline and
        startup backfill) fill everything in on their own, so the only reason to
        come through here is that they got the game wrong — the user fixes the
        title and presses fetch, and the edited name is what gets searched.
        """
        # Share the manager's helper so its rate limiter (and its discovered
        # endpoint) are the ones the whole app uses; a throwaway instance would
        # rediscover the endpoint and spawn a second refill thread per fetch.
        helper = shared_hltb_helper()

        # Same rule as the Steam appid above: a saved id is authoritative only
        # while the title is untouched. Editing the name is the user saying
        # this is a different game, and then it has to be searched afresh.
        saved_id = (
            self.game.hltb_id
            if self.game and name == (self.game.name or "").strip()
            else None
        )

        times: Optional[HLTBTimes] = None
        if name:
            try:
                times = fetch_times(helper, name, saved_id)
            except Exception:  # pylint: disable=broad-exception-caught
                # Broader than HLTBError on purpose: `fetch_times` also does
                # `int(hltb_id)` on a value read from the game's own JSON, so a
                # hand-edited record raises ValueError here. Any escape from
                # this thread means `_fetch_hltb_done` never runs and Apply
                # stays disabled with nothing loading.
                logging.exception("Could not fetch HowLongToBeat times")
                times = None
        GLib.idle_add(self._fetch_hltb_done, times, name)

    def _fetch_hltb_done(self, times: Optional[HLTBTimes], name: str) -> bool:
        """Stash the fetched estimates; silence is fine when there are none.

        A miss here is not worth a dialog: the Steam metadata the user asked
        for did arrive, and plenty of games simply have no HowLongToBeat entry.

        The times are dropped if the title changed while the request was in
        flight — that is the user saying this is a different game, and the
        answer in hand is for the old one.
        """
        self.steam_fetch_stack.set_visible_child(self.steam_fetch_button)
        self.end_loading()
        if name != self.name.get_text().strip():
            return False
        if times and has_times(times):
            self.fetched_hltb = times
            logging.debug("HowLongToBeat fetch for %s: %s", name, times)
        else:
            logging.info("No HowLongToBeat times found for %s", name)
        return False

    def set_cover_from_path(self, new_path: Path) -> None:
        self.game_cover.new_cover(new_path)
        self.game_cover.set_details_animation(True)
        self.cover_button_delete_revealer.set_reveal_child(True)
        self.cover_changed = True

    def set_is_open(self, is_open: bool) -> None:
        self.__class__.is_open = is_open
