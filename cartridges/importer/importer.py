# importer.py
#
# Copyright 2022-2023 kramo
# Copyright 2023 Geoffrey Coulaud
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
from time import time
from typing import Any, Optional

from gi.repository import Adw, Gio, GLib, Gtk

from cartridges import shared
from cartridges.errors.error_producer import ErrorProducer
from cartridges.errors.friendly_error import FriendlyError
from cartridges.game import Game
from cartridges.importer.location import UnresolvableLocationError
from cartridges.importer.source import Source, SourceScanError
from cartridges.store.managers.async_manager import AsyncManager
from cartridges.store.pipeline import Pipeline


# pylint: disable=too-many-instance-attributes
class Importer(ErrorProducer):
    """A class in charge of scanning sources for games"""

    progress_toast: Optional[Adw.Toast] = None
    summary_toast: Optional[Adw.Toast] = None

    sources: set[Source]

    n_source_tasks_created: int = 0
    n_source_tasks_done: int = 0
    n_pipelines_done: int = 0
    game_pipelines: set[Pipeline]

    removed_game_ids: set[str]
    imported_game_ids: set[str]
    scanned_source_ids: set[str]

    def __init__(self) -> None:
        super().__init__()

        shared.import_time = int(time())

        # TODO: make this stateful
        shared.store.new_game_ids = set()
        shared.store.duplicate_game_ids = set()

        self.removed_game_ids = set()
        self.imported_game_ids = set()
        self.scanned_source_ids = set()

        self.game_pipelines = set()
        self.sources = set()

        # game_pipelines is added to from source worker threads but read on the
        # main thread (progress polling, summary). Guard it so a concurrent add
        # can't raise "Set changed size during iteration".
        self._pipelines_lock = threading.Lock()
        # Pipelines already counted as done. The "advanced" signal fires from
        # worker and main threads alike; without this dedup two emissions could
        # both see is_done (double count) or interleave a lost `+= 1` — either
        # way the done/created equality never holds and the import never ends.
        self._counted_done_pipelines: set[Pipeline] = set()

    @property
    def pipelines_progress(self) -> float:
        with self._pipelines_lock:
            pipelines = list(self.game_pipelines)
        progress = sum(pipeline.progress for pipeline in pipelines)
        try:
            progress = progress / len(pipelines)
        except ZeroDivisionError:
            progress = 0
        return progress  # type: ignore

    @property
    def sources_progress(self) -> float:
        try:
            progress = self.n_source_tasks_done / self.n_source_tasks_created
        except ZeroDivisionError:
            progress = 0
        return progress

    @property
    def finished(self) -> bool:
        with self._pipelines_lock:
            n_pipelines = len(self.game_pipelines)
            n_pipelines_done = self.n_pipelines_done
        return (
            self.n_source_tasks_created == self.n_source_tasks_done
            and n_pipelines == n_pipelines_done
        )

    def add_source(self, source: Source) -> None:
        self.sources.add(source)

    def run(self, mostrar_progresso: bool = True) -> None:
        """Use several Gio.Task to import games from added sources"""
        shared.win.get_application().state = shared.AppState.IMPORT

        if self.__class__.summary_toast:
            shared.win.toast_queue.dismiss(self.__class__.summary_toast)
        if self.__class__.progress_toast:
            shared.win.toast_queue.dismiss(self.__class__.progress_toast)

        shared.win.get_application().lookup_action("import").set_enabled(False)
        shared.win.get_application().lookup_action("add_game").set_enabled(False)
        shared.win.get_application().lookup_action("preferences").set_enabled(False)

        self.n_pipelines_done = 0
        self.n_source_tasks_done = 0
        with self._pipelines_lock:
            self._counted_done_pipelines.clear()

        if mostrar_progresso:
            self.create_progress_toast()
        GLib.timeout_add(100, self.monitor_import)

        # Collect all errors and reset the cancellables for the managers
        # - Only one importer exists at any given time
        # - Every import starts fresh
        self.collect_errors()
        for manager in shared.store.managers.values():
            manager.collect_errors()
            if isinstance(manager, AsyncManager):
                manager.reset_cancellable()

        for source in self.sources:
            logging.debug("Importing games from source %s", source.source_id)
            task = Gio.Task.new(None, None, self.source_callback, (source,))
            self.n_source_tasks_created += 1
            task.run_in_thread(
                lambda _task,
                _obj,
                _data,
                _cancellable,
                src=source: self.source_task_thread_func((src,))
            )

    def monitor_import(self) -> bool:
        """Monitor import progress to update the progress toast and to trigger
        import cleanup once the work has finished"""
        if not self.finished:
            self.update_progress_toast()
            return True

        self.finish_import()
        return False

    def finish_import(self) -> None:
        """Callback called when importing has finished"""
        logging.info("Import done")
        self.remove_games()
        self.imported_game_ids = shared.store.new_game_ids
        shared.store.new_game_ids = set()
        shared.store.duplicate_game_ids = set()
        if self.__class__.progress_toast:
            shared.win.toast_queue.dismiss(self.__class__.progress_toast)
            self.__class__.progress_toast = None
        self.__class__.summary_toast = self.create_summary_toast()
        self.create_error_dialog()
        shared.win.get_application().lookup_action("import").set_enabled(True)
        shared.win.get_application().lookup_action("add_game").set_enabled(True)
        shared.win.get_application().lookup_action("preferences").set_enabled(True)
        shared.win.get_application().state = shared.AppState.DEFAULT
        # Re-apply the current sort so freshly imported games land in order
        shared.win.library.invalidate_sort()
        shared.win.zerados_library.invalidate_sort()

    def remove_games(self) -> None:
        """Set removed to True for missing games"""
        if not shared.schema.get_boolean("remove-missing"):
            return

        keys = shared.schema.list_keys()

        for game in shared.store:
            if game.removed:
                continue
            if game.source == "imported":
                continue
            # Only remove games whose source was actually scanned this run.
            # A missing/unset folder (e.g. a disconnected drive) must not be
            # mistaken for "every game was uninstalled"
            if game.base_source not in self.scanned_source_ids:
                continue
            if (game.base_source in keys) and (
                not shared.schema.get_boolean(game.base_source)
            ):
                continue
            if game.game_id in shared.store.duplicate_game_ids:
                continue
            if game.game_id in shared.store.new_game_ids:
                continue

            logging.debug("Removing missing game %s (%s)", game.name, game.game_id)

            game.removed = True
            game.save()
            game.update()
            self.removed_game_ids.add(game.game_id)

    """Import Actions — Threaded; None of this should touch GUI"""

    def source_task_thread_func(self, data: tuple) -> None:
        """Source import task code"""

        source: Source
        source, *_rest = data

        # Early exit if not available or not installed
        if not source.is_available:
            logging.info("Source %s skipped, not available", source.source_id)
            return
        try:
            iterator = iter(source)
        except UnresolvableLocationError:
            logging.info("Source %s skipped, bad location", source.source_id)
            return

        # Get games from source
        logging.info("Scanning source %s", source.source_id)
        # Whether the scan ran to the end. Anything that interrupts it leaves
        # this False, which is what keeps `remove_games` off this source's
        # games: an incomplete scan cannot tell a missing game from an unseen
        # one, and guessing wrong deletes a library.
        scan_complete = False
        scan_failed = False
        while True:
            # Handle exceptions raised when iterating
            try:
                iteration_result = next(iterator)
            except StopIteration:
                scan_complete = True
                break
            except SourceScanError as error:
                # The source knows its own scan failed and said so. Reported
                # like any other error, not just logged: a scan that quietly
                # produces half a library is worse than one that says it broke.
                logging.warning("Scan of %s incomplete: %s", source.source_id, error)
                self.report_error(error)
                break
            except Exception as error:  # pylint: disable=broad-exception-caught
                # A generator that raised is closed, so this `continue` cannot
                # resume it: the next `next()` raises StopIteration and the loop
                # ends there, with however many games were yielded before the
                # error and no way to know what came after. That is an
                # incomplete scan — and it reaches the same StopIteration that a
                # clean finish does, which is why it needs its own flag rather
                # than being inferred from how the loop ended.
                logging.exception("%s in %s", type(error).__name__, source.source_id)
                self.report_error(error)
                scan_failed = True
                continue

            # Handle the result depending on its type
            if isinstance(iteration_result, Game):
                game = iteration_result
                additional_data = {}
            elif isinstance(iteration_result, tuple):
                game, additional_data = iteration_result
            elif iteration_result is None:
                continue
            else:
                # Warn source implementers that an invalid type was produced
                # Should not happen on production code
                logging.warning(
                    "%s produced an invalid iteration return type %s",
                    source.source_id,
                    type(iteration_result),
                )
                continue

            # Register game
            pipeline: Optional[Pipeline] = shared.store.add_game(
                game, additional_data
            )
            if pipeline is not None:
                logging.info("Imported %s (%s)", game.name, game.game_id)
                pipeline.connect(
                    "advanced",
                    self.pipeline_advanced_callback,
                )
                with self._pipelines_lock:
                    self.game_pipelines.add(pipeline)

        # Only a scan that ran to the end licenses removing that source's
        # missing games
        if scan_complete and not scan_failed:
            self.scanned_source_ids.add(source.source_id)
        else:
            logging.info(
                "Keeping %s games: the scan did not finish", source.source_id
            )

    def source_callback(self, _obj: Any, _result: Any, data: tuple) -> None:
        """Callback executed when a source is fully scanned"""
        source, *_rest = data
        logging.debug("Import done for source %s", source.source_id)
        self.n_source_tasks_done += 1

    def pipeline_advanced_callback(self, pipeline: Pipeline) -> None:
        """Callback called when a pipeline for a game has advanced.

        May run on any thread. Counting is idempotent per pipeline so
        concurrent or repeated "advanced" emissions cannot skew the counter.
        """
        if pipeline.is_done:
            with self._pipelines_lock:
                if pipeline not in self._counted_done_pipelines:
                    self._counted_done_pipelines.add(pipeline)
                    self.n_pipelines_done += 1

    """GUI Actions"""

    def create_progress_toast(self) -> None:
        """Show a persistent toast while games are imported in the background"""
        toast = Adw.Toast(title=_("Importando jogos…"), timeout=0)
        self.__class__.progress_toast = toast
        shared.win.toast_queue.add(toast)

    def update_progress_toast(self) -> None:
        """Update the toast title with the overall import progress"""
        if not self.__class__.progress_toast:
            return

        # Reserve 10% for the sources discovery, the rest is the pipelines
        progress = (0.1 * self.sources_progress) + (0.9 * self.pipelines_progress)
        self.__class__.progress_toast.set_title(
            _("Importando jogos… {}%").format(int(progress * 100))
        )

    def create_error_dialog(self) -> None:
        """Dialog containing all errors raised by importers"""

        # Collect all errors that happened in the importer and the managers
        errors = []
        errors.extend(self.collect_errors())
        for manager in shared.store.managers.values():
            errors.extend(manager.collect_errors())

        # Filter out non friendly errors
        errors = set(
            tuple(
                (error.title, error.subtitle)
                for error in (
                    filter(lambda error: isinstance(error, FriendlyError), errors)
                )
            )
        )

        # No error to display
        if not errors:
            self.timeout_toast()
            return

        # Create error dialog
        dialog = Adw.AlertDialog()
        dialog.set_heading(_("Aviso"))
        dialog.add_response("close", _("Dispensar"))
        dialog.add_response("open_preferences_import", _("Preferências"))
        dialog.set_default_response("open_preferences_import")
        dialog.connect("response", self.dialog_response_callback)

        if len(errors) == 1:
            dialog.set_heading((error := next(iter(errors)))[0])
            dialog.set_body(error[1])
        else:
            # Display the errors in a list
            list_box = Gtk.ListBox()
            list_box.set_selection_mode(Gtk.SelectionMode.NONE)
            list_box.set_css_classes(["boxed-list"])
            list_box.set_margin_top(9)
            for error in errors:
                row = Adw.ActionRow.new()
                # Adw.PreferencesRow parses title and subtitle as Pango markup
                # by default, and these carry file paths and API messages: a
                # single "&" (D:\Games & Emulators) makes Pango reject the
                # string and the row renders blank — losing the error text at
                # the one moment the user needs to read it.
                row.set_title(GLib.markup_escape_text(error[0]))
                row.set_subtitle(GLib.markup_escape_text(error[1]))
                list_box.append(row)
            dialog.set_body(_("Os seguintes erros ocorreram durante a importação:"))
            dialog.set_extra_child(list_box)

        dialog.present(shared.win)

    def undo_import(self, *_args: Any) -> None:
        # Games may have vanished since the import (e.g. the app was reset),
        # so missing ids are skipped instead of crashing the undo
        for game_id in self.imported_game_ids:
            if game := shared.store.get(game_id):
                game.removed = True
                game.update()
                game.save()

        for game_id in self.removed_game_ids:
            if game := shared.store.get(game_id):
                game.removed = False
                game.update()
                game.save()

        self.imported_game_ids = set()
        self.removed_game_ids = set()
        if self.__class__.summary_toast:
            shared.win.toast_queue.dismiss(self.__class__.summary_toast)

        logging.info("Import undone")

    @staticmethod
    def summarize_names(names: list[str], singular: str, plural: str) -> str:
        """Human-friendly summary: names when few, a count when many"""
        if len(names) <= 3:
            return (singular if len(names) == 1 else plural).format(
                ", ".join(sorted(names, key=str.casefold))
            )
        return plural.format(
            # The variable is the number of games.
            ngettext("{} jogo", "{} jogos", len(names)).format(len(names))
        )

    def create_summary_toast(self) -> Adw.Toast:
        """Toast summarizing which games were imported and removed"""

        # Timeout 0: how long the summary stays is decided by `timeout_toast`,
        # once the warnings dialog (if any) is out of the way.
        toast = Adw.Toast(timeout=0)

        with self._pipelines_lock:
            pipelines = list(self.game_pipelines)
        added_names = [
            pipeline.game.name
            for pipeline in pipelines
            if not (pipeline.game.blacklisted or pipeline.game.removed)
        ]
        removed_names = [
            game.name
            for game_id in self.removed_game_ids
            if (game := shared.store.get(game_id))
        ]

        parts = []
        if added_names:
            # The variable is the game name(s) or the number of games.
            parts.append(
                self.summarize_names(
                    added_names, _("Importado: {}"), _("Importados: {}")
                )
            )
        if removed_names:
            # The variable is the game name(s) or the number of games.
            parts.append(
                self.summarize_names(
                    removed_names, _("Removido: {}"), _("Removidos: {}")
                )
            )

        if parts:
            toast_title = " · ".join(parts)
            toast.set_button_label(_("Desfazer"))
            toast.connect("button-clicked", self.undo_import)
        else:
            toast_title = _("Nenhum jogo novo encontrado")
            toast.set_button_label(_("Preferências"))
            toast.connect(
                "button-clicked",
                self.dialog_response_callback,
                "open_preferences",
                "import",
            )

        toast.set_title(toast_title)

        if parts or not shared.schema.get_boolean("auto-import"):
            shared.win.toast_queue.add(toast)

        return toast

    def open_preferences(
        self,
        page_name: Optional[str] = None,
        expander_row: Optional[Adw.ExpanderRow] = None,
    ) -> Adw.PreferencesDialog:
        return shared.win.get_application().on_preferences_action(
            page_name=page_name, expander_row=expander_row
        )

    def timeout_toast(self, *_args: Any) -> None:
        """Manually timeout the toast after the user has dismissed all warnings.

        Handed to the queue rather than timed here: the summary may still be
        waiting behind another toast, and a countdown started now would run out
        before it ever reached the screen.
        """
        if self.__class__.summary_toast:
            shared.win.toast_queue.dismiss_after(self.__class__.summary_toast, 5)

    def dialog_response_callback(self, _widget: Any, response: str, *args: Any) -> None:
        """Handle after-import dialogs callback"""
        logging.debug("After-import dialog response: %s (%s)", response, str(args))
        if response == "open_preferences":
            self.open_preferences(*args)
        elif response == "open_preferences_import":
            # May return None if the preferences dialog is already open, and
            # Adw.Dialog emits "closed" (there is no "close-request" signal)
            if preferences := self.open_preferences(*args):
                preferences.connect("closed", self.timeout_toast)
            else:
                self.timeout_toast()
        else:
            self.timeout_toast()
