# preferences.py
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

# pyright: reportAssignmentType=none

import json
import logging
from pathlib import Path
from shutil import rmtree
from typing import Any, Callable, Optional

from gi.repository import Adw, Gio, GLib, Gtk

from cartridges import shared
from cartridges.errors.friendly_error import FriendlyError
from cartridges.metadata_refresh import get_metadata_refresh
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.utils.create_dialog import create_dialog


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/preferences.ui")
class CartridgesPreferences(Adw.PreferencesDialog):
    __gtype_name__ = "CartridgesPreferences"

    general_page: Adw.PreferencesPage = Gtk.Template.Child()
    import_page: Adw.PreferencesPage = Gtk.Template.Child()
    sgdb_page: Adw.PreferencesPage = Gtk.Template.Child()

    minimize_after_launch_switch: Adw.SwitchRow = Gtk.Template.Child()
    cover_launches_game_switch: Adw.SwitchRow = Gtk.Template.Child()
    playtime_tracking_switch: Adw.SwitchRow = Gtk.Template.Child()
    gamepad_switch: Adw.SwitchRow = Gtk.Template.Child()
    gamepad_rumble_switch: Adw.SwitchRow = Gtk.Template.Child()
    process_grace_spin_row: Adw.SpinRow = Gtk.Template.Child()

    auto_import_switch: Adw.SwitchRow = Gtk.Template.Child()
    remove_missing_switch: Adw.SwitchRow = Gtk.Template.Child()
    steam_metadata_switch: Adw.SwitchRow = Gtk.Template.Child()
    hltb_metadata_switch: Adw.SwitchRow = Gtk.Template.Child()

    metadata_update_row: Adw.ActionRow = Gtk.Template.Child()
    metadata_stack: Gtk.Stack = Gtk.Template.Child()
    metadata_fetch_button: Gtk.Button = Gtk.Template.Child()
    metadata_cancel_button: Gtk.Button = Gtk.Template.Child()
    metadata_progress_bar: Gtk.ProgressBar = Gtk.Template.Child()

    shortcuts_expander_row: Adw.ExpanderRow = Gtk.Template.Child()
    shortcuts_location_action_row: Adw.ActionRow = Gtk.Template.Child()
    shortcuts_location_button: Gtk.Button = Gtk.Template.Child()
    shortcuts_recursive_switch: Adw.SwitchRow = Gtk.Template.Child()

    sgdb_key_group: Adw.PreferencesGroup = Gtk.Template.Child()
    sgdb_key_entry_row: Adw.EntryRow = Gtk.Template.Child()
    sgdb_switch: Adw.SwitchRow = Gtk.Template.Child()
    sgdb_prefer_switch: Adw.SwitchRow = Gtk.Template.Child()
    sgdb_animated_switch: Adw.SwitchRow = Gtk.Template.Child()
    sgdb_fetch_button: Gtk.Button = Gtk.Template.Child()
    sgdb_stack: Gtk.Stack = Gtk.Template.Child()
    sgdb_spinner: Adw.Spinner = Gtk.Template.Child()

    export_playtime_button_row = Gtk.Template.Child()
    import_playtime_button_row = Gtk.Template.Child()

    danger_zone_group = Gtk.Template.Child()
    remove_all_games_button_row = Gtk.Template.Child()
    reset_button_row = Gtk.Template.Child()

    is_open = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        # Make it so only one dialog can be open at a time
        self.__class__.is_open = True
        self.connect("closed", lambda *_: self.set_is_open(False))

        self.file_chooser = Gtk.FileDialog()

        # General
        self.remove_all_games_button_row.connect("activated", self.remove_all_games)
        self.export_playtime_button_row.connect("activated", self.export_playtime)
        self.import_playtime_button_row.connect("activated", self.import_playtime)

        # Debug
        if shared.PROFILE == "development":
            self.reset_button_row.set_visible(True)
            self.reset_button_row.connect("activated", self.reset_app)

        # Shortcuts source settings
        shared.schema.bind(
            "shortcuts",
            self.shortcuts_expander_row,
            "enable-expansion",
            Gio.SettingsBindFlags.DEFAULT,
        )
        self.update_shortcuts_location_subtitle()
        self.shortcuts_location_button.connect(
            "clicked", self.choose_folder, self.set_shortcuts_location
        )

        # SteamGridDB
        def sgdb_key_changed(*_args: Any) -> None:
            shared.schema.set_string("sgdb-key", self.sgdb_key_entry_row.get_text())

        self.sgdb_key_entry_row.set_text(shared.schema.get_string("sgdb-key"))
        self.sgdb_key_entry_row.connect("changed", sgdb_key_changed)

        self.sgdb_key_group.set_description(
            _(
                "É necessária uma chave de API para usar o SteamGridDB. Você pode gerar uma {}aqui{}."
            ).format(
                '<a href="https://www.steamgriddb.com/profile/preferences/api">', "</a>"
            )
        )

        def update_sgdb(*_args: Any) -> None:
            counter = 0
            # Skip removed games (kept in the store as tombstones)
            games = [game for game in shared.store if not game.removed]
            games_len = len(games)
            if not games_len:
                return
            sgdb_manager = shared.store.managers[SgdbManager]
            sgdb_manager.reset_cancellable()

            self.sgdb_spinner.set_visible(True)
            self.sgdb_stack.set_visible_child(self.sgdb_spinner)

            self.add_toast(download_toast := Adw.Toast.new(_("Baixando capas…")))

            def update_cover_callback(manager: SgdbManager) -> None:
                nonlocal counter
                nonlocal games_len
                nonlocal download_toast

                counter += 1
                if counter != games_len:
                    return

                for error in manager.collect_errors():
                    if isinstance(error, FriendlyError):
                        create_dialog(self, error.title, error.subtitle)
                        break

                for game in games:
                    game.update()

                # No HIGH priority: it is what made a toast cut another one off
                # mid-life and then reappear, and it buys nothing here — the
                # toast it would have jumped is dismissed on the line below.
                toast = Adw.Toast.new(_("Capas atualizadas"))
                download_toast.dismiss()
                self.add_toast(toast)

                self.sgdb_spinner.set_visible(False)
                self.sgdb_stack.set_visible_child(self.sgdb_fetch_button)

            for game in games:
                sgdb_manager.process_game(game, {}, update_cover_callback)

        self.sgdb_fetch_button.connect("clicked", update_sgdb)

        self.setup_metadata_row()

        # Switches
        self.bind_switches(
            {
                "minimize-after-launch",
                "cover-launches-game",
                "playtime-tracking",
                "gamepad",
                "gamepad-rumble",
                "auto-import",
                "remove-missing",
                "steam-metadata",
                "hltb-metadata",
                "shortcuts-recursive",
                "sgdb",
                "sgdb-prefer",
                "sgdb-animated",
            }
        )

        def set_sgdb_sensitive(widget: Adw.EntryRow) -> None:
            if not widget.get_text():
                shared.schema.set_boolean("sgdb", False)

            self.sgdb_switch.set_sensitive(widget.get_text())

        self.sgdb_key_entry_row.connect("changed", set_sgdb_sensitive)
        set_sgdb_sensitive(self.sgdb_key_entry_row)

        # Playtime tracking always minimises the main window (the session window
        # takes over), so while it's on, "minimise on launch" is forced on and
        # locked. It becomes editable again only when tracking is off.
        def sync_minimize_lock(*_args: Any) -> None:
            tracking = self.playtime_tracking_switch.get_active()
            if tracking:
                self.minimize_after_launch_switch.set_active(True)
            self.minimize_after_launch_switch.set_sensitive(not tracking)

        self.playtime_tracking_switch.connect("notify::active", sync_minimize_lock)
        sync_minimize_lock()

        # Rumble is meaningless with the controller turned off, so the row
        # greys out along with it rather than sitting there doing nothing
        def sync_rumble_sensitive(*_args: Any) -> None:
            self.gamepad_rumble_switch.set_sensitive(self.gamepad_switch.get_active())

        self.gamepad_switch.connect("notify::active", sync_rumble_sensitive)
        sync_rumble_sensitive()

        # Grace period for process tracking. The row's value is a double while
        # the setting is an int, so map it by hand rather than using bind().
        self.process_grace_spin_row.set_value(
            shared.schema.get_int("process-tracking-grace")
        )
        self.process_grace_spin_row.connect(
            "notify::value",
            lambda row, *_: shared.schema.set_int(
                "process-tracking-grace", int(row.get_value())
            ),
        )

    def set_is_open(self, is_open: bool) -> None:
        self.__class__.is_open = is_open

    # region Metadata refresh

    def setup_metadata_row(self) -> None:
        """Wire the row up as a view onto the refresh.

        The run itself outlives this dialog, so nothing about it is owned here.
        The progress handler is dropped on close for two reasons: it would keep
        a closed dialog alive until the run ended, and a stale dialog would go
        on writing to widgets the user has already dismissed.
        """
        self.metadata_fetch_button.connect("clicked", self.ask_metadata_scope)
        self.metadata_cancel_button.connect("clicked", self.cancel_metadata_update)
        for switch in (self.steam_metadata_switch, self.hltb_metadata_switch):
            switch.connect("notify::active", self.update_metadata_sensitive)
        self.update_metadata_sensitive()

        refresh = get_metadata_refresh()
        handler = refresh.connect("progress", self.sync_metadata_ui)
        self.connect("closed", lambda *_: refresh.disconnect(handler))
        self.sync_metadata_ui()

    def update_metadata_sensitive(self, *_args: Any) -> None:
        """Grey the row out when neither metadata source is enabled.

        Both managers check their own setting and return immediately when it is
        off, so with both switches down the button would run through the whole
        library and change nothing.
        """
        self.metadata_update_row.set_sensitive(
            self.steam_metadata_switch.get_active()
            or self.hltb_metadata_switch.get_active()
        )

    def sync_metadata_ui(self, *_args: Any) -> None:
        """Show whatever the refresh is doing right now.

        Called both when the dialog opens and on every step of a run, so a
        dialog that was closed halfway through comes back showing the bar at
        the position the refresh has actually reached.
        """
        refresh = get_metadata_refresh()
        self.metadata_stack.set_visible_child(
            self.metadata_cancel_button if refresh.running else self.metadata_fetch_button
        )
        self.metadata_cancel_button.set_sensitive(not refresh.cancelled)
        self.metadata_progress_bar.set_visible(refresh.running)
        self.metadata_progress_bar.set_fraction(refresh.fraction)
        # The variables are how many games are done and how many there are
        self.metadata_progress_bar.set_text(
            _("{} de {}").format(refresh.done, refresh.total)
        )

    def ask_metadata_scope(self, *_args: Any) -> None:
        """Ask what to refresh, then start.

        Offered as a question rather than two buttons in the preferences
        because the answer depends on the moment, not on a preference: filling
        in a newly added field is the common case, and re-reading the whole
        library is the rare one.
        """
        refresh = get_metadata_refresh()
        games = refresh.library()
        incomplete = [game for game in games if refresh.is_incomplete(game)]

        if not games:
            self.add_toast(Adw.Toast.new(_("Nenhum jogo na biblioteca")))
            return

        dialog = Adw.AlertDialog.new(
            _("Atualizar metadados"),
            _(
                "Buscar apenas o que falta trata {} de {} jogos, consultando de cada "
                "um só a fonte que lhe deve algo. É o suficiente para preencher "
                "campos novos. Buscar tudo relê a biblioteca inteira na Steam e no "
                "HowLongToBeat, e leva bem mais tempo."
            ).format(len(incomplete), len(games)),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("missing", _("Só o que falta"))
        dialog.add_response("all", _("Buscar tudo"))
        dialog.set_default_response("missing")
        dialog.set_close_response("cancel")

        def on_response(_dialog: Adw.AlertDialog, response: str) -> None:
            if response not in ("missing", "all"):
                return
            only_missing = response == "missing"
            wanted = incomplete if only_missing else games
            if get_metadata_refresh().start(wanted, only_missing=only_missing):
                return
            # `start` refuses for two different reasons, and telling the user
            # there is nothing to fetch when a run is already under way would
            # be plainly wrong.
            self.add_toast(
                Adw.Toast.new(
                    _("Nada a atualizar")
                    if not wanted
                    else _("Uma atualização já está em andamento")
                )
            )

        dialog.connect("response", on_response)
        dialog.choose(self)

    def cancel_metadata_update(self, *_args: Any) -> None:
        get_metadata_refresh().cancel()
        self.metadata_cancel_button.set_sensitive(False)

    # endregion

    def get_switch(self, setting: str) -> Any:
        return getattr(self, f'{setting.replace("-", "_")}_switch')

    def bind_switches(self, settings: set[str]) -> None:
        for setting in settings:
            shared.schema.bind(
                setting,
                self.get_switch(setting),
                "active",
                Gio.SettingsBindFlags.DEFAULT,
            )

    def choose_folder(
        self, _widget: Any, callback: Callable, callback_data: Optional[str] = None
    ) -> None:
        self.file_chooser.select_folder(shared.win, None, callback, callback_data)

    def remove_all_games(self, *_args: Any) -> None:
        """Ask for confirmation, then wipe the whole library (irreversible)."""
        dialog = Adw.AlertDialog.new(
            _("Resetar o aplicativo?"),
            _(
                "Isso apaga todos os jogos e capas e esquece a pasta de atalhos "
                "configurada. Não é possível desfazer."
            ),
        )
        dialog.add_response("cancel", _("Cancelar"))
        dialog.add_response("reset", _("Resetar"))
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.reset_response)
        dialog.present(self)

    def reset_response(self, _dialog: Any, response: str) -> None:
        if response == "reset":
            self.reset_app_data()

    def reset_app_data(self) -> None:
        """Delete every stored game and cover and forget the shortcuts folder."""
        # End any play session first: its periodic save would otherwise
        # re-create the game's JSON right after the wipe
        # (avoid import cycles)
        from cartridges.process_session import ProcessSession
        from cartridges.session_window import SessionWindow

        if SessionWindow.active is not None:
            SessionWindow.active.close()
        if ProcessSession.active is not None:
            # Don't record: the game is about to be wiped, and saving it would
            # write its JSON back to disk after the reset
            ProcessSession.active.stop(record=False)

        # Same reason, and the refresh is the longest-running of the three: it
        # walks its own list of games for minutes and saves each one as it
        # finishes. The queue stops here; the game already in flight is caught
        # by the store check in `MetadataRefresh._run_queue`.
        get_metadata_refresh().cancel()

        # Drop pending undo toasts; their games are about to be deleted and
        # clicking "Desfazer" later would resurrect one on disk
        for toast in list(shared.win.toasts.values()):
            shared.win.toast_queue.dismiss(toast)
        shared.win.toasts = {}

        # Forget the last import's undo data for the same reason (Ctrl+Z
        # would otherwise look up games that no longer exist)
        if shared.importer:
            shared.importer.imported_game_ids = set()
            shared.importer.removed_game_ids = set()

        if shared.win.navigation_view.get_visible_page() == shared.win.details_page:
            shared.win.navigation_view.pop()

        # Clear the UI and in-memory store
        shared.win.library.remove_all()
        shared.win.hidden_library.remove_all()
        shared.store.clear()
        shared.win.game_covers = {}

        # Delete the files on disk (games + covers)
        if shared.games_dir.is_dir():
            for path in shared.games_dir.glob("*.json"):
                path.unlink(missing_ok=True)
        if shared.covers_dir.is_dir():
            for path in shared.covers_dir.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)
        if shared.logos_dir.is_dir():
            for path in shared.logos_dir.iterdir():
                if path.is_file():
                    path.unlink(missing_ok=True)

        # Forget the configured shortcuts folder
        shared.schema.set_string("shortcuts-location", "")
        self.update_shortcuts_location_subtitle()

        shared.win.set_library_child()

        # Plain priority, like every other toast now: HIGH is what interrupted
        # whatever was on screen and pushed it back into the queue to replay.
        self.add_toast(Adw.Toast.new(_("Aplicativo resetado")))

    def _json_filters(self) -> Gio.ListStore:
        json_filter = Gtk.FileFilter(name=_("Backup do Cartridges"))
        json_filter.add_suffix("json")
        json_filter.add_mime_type("application/json")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(json_filter)
        return filters

    def export_playtime(self, *_args: Any) -> None:
        """Save each played game's stable id and playtime to a JSON file."""
        # Tombstones (removed games) stay out of the backup
        playtimes = {
            game.game_id: {"name": game.name, "playtime": game.playtime}
            for game in shared.store
            if game.playtime and not game.removed
        }
        if not playtimes:
            self.add_toast(Adw.Toast.new(_("Nenhum tempo de jogo para exportar")))
            return

        dialog = Gtk.FileDialog()
        dialog.set_initial_name("cartridges-tempos-de-jogo.json")
        dialog.set_filters(self._json_filters())

        def finish(file_dialog: Gtk.FileDialog, result: Gio.Task) -> None:
            try:
                path = Path(file_dialog.save_finish(result).get_path())
            except GLib.Error:
                return
            try:
                path.write_text(
                    json.dumps(
                        {"version": 1, "playtimes": playtimes},
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            except OSError as error:
                create_dialog(self, _("Não foi possível exportar"), str(error))
                return
            self.add_toast(Adw.Toast.new(_("Tempos de jogo exportados")))

        dialog.save(shared.win, None, finish)

    def import_playtime(self, *_args: Any) -> None:
        """Add playtimes from a backup to the current ones, matching by stable id."""
        dialog = Gtk.FileDialog()
        dialog.set_filters(self._json_filters())

        def finish(file_dialog: Gtk.FileDialog, result: Gio.Task) -> None:
            try:
                path = Path(file_dialog.open_finish(result).get_path())
            except GLib.Error:
                return
            try:
                playtimes = json.loads(path.read_text(encoding="utf-8"))["playtimes"]
                if not isinstance(playtimes, dict):
                    raise ValueError
            except (OSError, ValueError, KeyError, TypeError):
                create_dialog(
                    self,
                    _("Backup inválido"),
                    _("O arquivo não é um backup de tempos de jogo válido."),
                )
                return

            restored = 0
            for game in shared.store:
                entry = playtimes.get(game.game_id)
                if not isinstance(entry, dict):
                    continue
                try:
                    backup_time = int(entry.get("playtime", 0))
                except (TypeError, ValueError):
                    continue
                # Add the backup's time on top of the current one so multiple
                # backups accumulate. Note: importing the same file twice will
                # count its time twice.
                if backup_time > 0:
                    game.playtime += backup_time
                    game.save()
                    restored += 1

            if restored:
                shared.win.library.invalidate_sort()
                shared.win.hidden_library.invalidate_sort()

            self.add_toast(
                Adw.Toast.new(
                    ngettext(
                        "{} jogo restaurado", "{} jogos restaurados", restored
                    ).format(restored)
                    if restored
                    else _("Nenhum jogo correspondente no backup")
                )
            )

        dialog.open(shared.win, None, finish)

    def reset_app(self, *_args: Any) -> None:
        # `app_dir` now holds the cache and the logs as well, so the first line
        # already covers what the third used to. Kept explicit anyway: it states
        # what is deleted rather than relying on one path containing another,
        # and it keeps working if either is ever moved.
        rmtree(shared.app_dir, True)
        rmtree(shared.config_dir / shared.APP_DIR_NAME, True)
        rmtree(shared.cache_dir, True)
        rmtree(shared.log_dir, True)

        for key in (
            (settings_schema_source := Gio.SettingsSchemaSource.get_default())
            .lookup(shared.APP_ID, True)
            .list_keys()
        ):
            shared.schema.reset(key)
        for key in settings_schema_source.lookup(
            shared.APP_ID + ".State", True
        ).list_keys():
            shared.state_schema.reset(key)

        shared.win.get_application().quit()

    def update_shortcuts_location_subtitle(self) -> None:
        """Show the currently selected shortcuts folder as the row subtitle"""
        location = shared.schema.get_string("shortcuts-location")
        # AdwPreferencesRow parses its subtitle as Pango markup by default, and a
        # Windows folder is free to contain an ampersand: "D:\Games & Emulators"
        # fails the parse outright, which leaves the row blank and logs a GTK
        # warning. Escaped the same way the Steam picker escapes third-party
        # titles. Purely a rendering matter — "<" and ">" cannot occur in a
        # Windows path, so there is nothing here to inject with.
        self.shortcuts_location_action_row.set_subtitle(
            # Not `str(Path(location))`: that renders with `os.sep`, which on
            # the interpreter this ships with is a forward slash, so the folder
            # the user had just picked came back looking nothing like what the
            # file chooser showed them. The stored string is already in the
            # shape Windows writes.
            GLib.markup_escape_text(location.replace("/", "\\"))
            if location
            else _("Nenhuma pasta selecionada")
        )

    def set_shortcuts_location(
        self, _widget: Any, result: Gio.Task, *_args: Any
    ) -> None:
        """Callback called when the shortcuts folder picker returns"""
        try:
            path = Path(self.file_chooser.select_folder_finish(result).get_path())
        except GLib.Error:
            return

        shared.schema.set_string("shortcuts-location", str(path))
        self.update_shortcuts_location_subtitle()
        logging.debug("User-set shortcuts location is %s", path)
