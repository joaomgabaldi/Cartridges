# metadata_refresh.py
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

"""Refresh the metadata of games already in the library.

Deliberately *not* owned by the preferences dialog. A whole-library refresh
runs for minutes, and the dialog is a transient the user is free to close in
the meantime — if it owned the queue, closing it would either abandon work
halfway through or leave it running with no way to see or stop it. So the run
lives here, for the lifetime of the process, and the dialog is only a view onto
it: it reads the counters when it opens and follows the ``progress`` signal
while it stays open.
"""

import logging
from threading import Thread
from typing import Any, Optional

from gi.repository import Adw, GLib, GObject

from cartridges import shared
from cartridges.errors.friendly_error import FriendlyError
from cartridges.game import Game
from cartridges.store.managers.hltb_manager import HLTBManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils.steam import STEAM_METADATA_VERSION


class MetadataRefresh(GObject.Object):
    """A whole-library metadata refresh, running or idle."""

    __gtype_name__ = "MetadataRefresh"

    running: bool = False
    cancelled: bool = False
    done: int = 0
    total: int = 0

    def __init__(self) -> None:
        super().__init__()
        self._queue: list[Game] = []
        self._managers: list[Any] = []
        self._only_missing: bool = False

    @GObject.Signal(name="progress")
    def progress(self):  # type: ignore
        """Emitted when a game finishes, and when the run starts or ends."""

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0

    @staticmethod
    def needs_steam(game: Game) -> bool:
        """Whether the Steam lookup has anything left to give this game.

        Judged on two things, because neither works alone.

        The *always-produced* fields — developer, release date, genre — come
        back from every successful lookup, so one of them missing means the
        game never had one. The rest cannot be read this way: fresh from the
        API, 29 of 30 games carry no gamepad recommendation and 5 no controller
        support, and those are answers, not gaps. Treating an empty field as
        work to do would put the whole library back in the queue on every run.

        `steam_checked` covers what emptiness cannot: a game looked up before a
        field existed is stamped with an older version, so it comes back
        exactly once for the fields it never had the chance to receive.
        """
        if not game.steam_appid:
            return True
        # Coerced rather than compared directly. The value is read straight out
        # of the game's JSON, and a hand-edited record can hold `null` or a
        # string there — `None < 2` raises TypeError, and this runs inside a
        # comprehension over the whole library on the main thread, so one bad
        # record stopped the scope dialog from opening at all. Anything that is
        # not a usable number reads as "never checked", which is the safe
        # answer: the game is looked up again.
        try:
            checked = int(game.steam_checked)
        except (TypeError, ValueError):
            return True
        if checked < STEAM_METADATA_VERSION:
            return True
        return not (game.developer and game.release_date and game.genre)

    @staticmethod
    def needs_hltb(game: Game) -> bool:
        """Whether HowLongToBeat has anything left to give this game.

        The same rule the manager applies to itself, so asking here can never
        queue a game the lookup would then decline to work on.
        """
        return not game.has_hltb_times

    @classmethod
    def is_incomplete(cls, game: Game) -> bool:
        """Whether any source still has something for this game."""
        return cls.needs_steam(game) or cls.needs_hltb(game)

    @staticmethod
    def library() -> list[Game]:
        """The games a refresh would consider: everything the user can see."""
        return [game for game in shared.store if not (game.removed or game.blacklisted)]

    @staticmethod
    def _in_library(game: Game) -> bool:
        """Whether the store still holds this exact game under its id.

        Identity, not just the id: a game removed and re-imported while the
        refresh was walking its queue is a different record, and writing this
        one over it would undo the import.
        """
        store = getattr(shared, "store", None)
        if store is None:
            return False
        return store.get(game.game_id) is game

    def start(self, games: list[Game], only_missing: bool = False) -> bool:
        """Begin refreshing ``games``. Returns False when there is nothing to do.

        With ``only_missing`` each game is asked which sources still owe it
        something, and only those run for it. A game that has everything but
        its completion times costs one HowLongToBeat lookup instead of the
        three Steam requests it would otherwise sit through.
        """
        if self.running or not games:
            return False

        self._managers = [
            shared.store.managers[SteamAPIManager],
            shared.store.managers[HLTBManager],
        ]
        for manager in self._managers:
            manager.reset_cancellable()

        self._only_missing = only_missing
        self._queue = list(games)
        self.running = True
        self.cancelled = False
        self.done = 0
        self.total = len(games)
        self.emit("progress")

        # The tags of every game in one or two requests instead of one each.
        # Off the main thread because it is network work, and before anything
        # else because the per-game lookups are what consume it.
        def prefetch() -> None:
            tags: dict[str, list[int]] = {}
            try:
                # Only the games whose Steam lookup will actually run: asking
                # for the tags of a game that is queued for HowLongToBeat alone
                # would be paying for an answer nobody reads.
                wanted = [
                    game
                    for game in games
                    if not self._only_missing or self.needs_steam(game)
                ]
                # `str`, because `steam_appid` is read from the game's own JSON
                # and a hand-edited record can hold the number unquoted. The
                # manager looks the tags up under `str(appid)`, so an int key
                # here would simply never be found.
                appids = [str(game.steam_appid) for game in wanted if game.steam_appid]
                helper = shared.store.managers[SteamAPIManager].steam_api_helper
                if appids:
                    tags = helper.get_store_tags_bulk(
                        appids, should_stop=lambda: self.cancelled
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                # Nothing may escape this thread. It is the only thing that
                # schedules `_run_queue`, so an exception getting out left
                # `running` True with no queue behind it: the button never came
                # back and no refresh could be started again for the life of
                # the process. An empty mapping is the same conservative state
                # a failed bulk request produces — the run goes ahead and
                # leaves every genre exactly as it is.
                logging.exception("Metadata refresh: could not prefetch Steam tags")
            GLib.idle_add(self._run_queue, tags)

        Thread(target=prefetch, daemon=True).start()
        return True

    def cancel(self) -> None:
        """Stop after the game currently in flight.

        Only the queue is stopped; the running lookup is left to finish rather
        than abandoned, so the game it is about keeps a consistent record.
        """
        if self.running:
            self.cancelled = True

    def managers_for(self, game: Game) -> list[Any]:
        """The sources to run for ``game`` on this run.

        Order is kept: the HowLongToBeat search goes second because the Steam
        lookup is what corrects the title it searches for. Granularity is per
        source rather than per field, because that is the granularity the API
        has — one appdetails request answers developer, publisher, release
        date, Metacritic, controller support and the gamepad recommendation
        together, so there is no cheaper way to ask for just one of them.
        """
        if not self._only_missing:
            return list(self._managers)
        wanted = (self.needs_steam(game), self.needs_hltb(game))
        return [manager for manager, needed in zip(self._managers, wanted) if needed]

    def _run_queue(self, tags: dict[str, list[int]]) -> bool:
        """Walk the queue, one game and one manager at a time.

        Sequential on purpose. The Steam limiter spaces requests 1.5 s apart no
        matter how many are in flight, so running them in parallel would buy
        nothing while making the progress meaningless and cancelling
        impossible. It also keeps the HowLongToBeat search behind the Steam
        lookup, which is what corrects the title it searches for.
        """
        # "Fetch everything" has to mean it, including the completion times the
        # HowLongToBeat manager otherwise refuses to look up twice. Those times
        # do drift: they are a running average of user submissions, so a game
        # imported near release sits on a small sample that keeps moving. The
        # honest reason for the flag is smaller than that, though — an option
        # that fetches everything except one thing is an option nobody
        # remembers the shape of three months later.
        additional_data = {
            "steam_tags": tags,
            "refresh_hltb": not self._only_missing,
            # Lido pelo SteamAPIManager: no modo só-o-que-falta os campos
            # editáveis à mão só preenchem o que está vazio, em vez de reverter
            # edições do usuário — a fila escolhe os jogos, isto escolhe os
            # campos.
            "only_missing": self._only_missing,
        }

        def next_game() -> None:
            if self.cancelled or not self._queue:
                self._finish()
                return
            game = self._queue.pop(0)
            managers = self.managers_for(game)

            def next_manager(index: int) -> None:
                if index >= len(managers):
                    # Only if the game is still the one the library holds under
                    # that id. A reset wipes the store and the files on disk
                    # while this queue is still walking its own list of Game
                    # objects, and `save()` writes a record whether or not
                    # anything still refers to it — so the games the user had
                    # just deleted came back on disk and were loaded again on
                    # the next launch. `cancel()` alone does not cover it: it
                    # stops the queue but lets the game in flight finish, which
                    # is exactly the one that would be rewritten.
                    if self._in_library(game):
                        game.save()
                        game.update()
                    self.done += 1
                    self.emit("progress")
                    next_game()
                    return
                managers[index].process_game(
                    game, additional_data, lambda _manager: next_manager(index + 1)
                )

            next_manager(0)

        next_game()
        return GLib.SOURCE_REMOVE

    def _finish(self) -> None:
        for manager in self._managers:
            for error in manager.collect_errors():
                if isinstance(error, FriendlyError):
                    logging.warning("Metadata refresh: %s", error.title)

        done, total, cancelled = self.done, self.total, self.cancelled
        self.running = False
        self._queue = []
        self._managers = []
        self.emit("progress")
        self._announce(done, total, cancelled)

    @staticmethod
    def _announce(done: int, total: int, cancelled: bool) -> None:
        """Say how it went, on the main window rather than the dialog.

        By the time a long run ends the preferences are usually closed, and a
        toast into a closed dialog is a toast nobody sees.
        """
        if cancelled:
            # The variables are how many games were done and how many there were
            message = _("Atualização cancelada em {} de {}").format(done, total)
        else:
            # The variable is how many games were updated
            message = _("Metadados atualizados para {} jogos").format(done)
        if shared.win is not None:
            shared.win.toast_queue.add(Adw.Toast.new(message))


_refresh: Optional[MetadataRefresh] = None  # pylint: disable=invalid-name


def get_metadata_refresh() -> MetadataRefresh:
    """Return the shared refresh.

    One per process: it is the run itself, so a second instance would mean a
    second queue racing the first over the same games and the same rate limit.
    """
    global _refresh  # pylint: disable=global-statement
    if _refresh is None:
        _refresh = MetadataRefresh()
    return _refresh
