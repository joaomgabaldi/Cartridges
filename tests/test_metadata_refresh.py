# test_metadata_refresh.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks for the whole-library metadata refresh.

The run is deliberately owned by :mod:`cartridges.metadata_refresh` rather than
by the preferences dialog, so the two halves are tested apart: the queue and
its counters on one side, and on the other that the dialog reflects them —
including a dialog opened in the middle of a run, which is the case that broke
when the state lived in the dialog::

    python3 -m pytest tests/test_metadata_refresh.py
"""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cartridges.metadata_refresh import MetadataRefresh  # noqa: E402
from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: E402


class FakeManager:
    """Stands in for the Steam and HowLongToBeat managers."""

    def __init__(self, on_process=None) -> None:
        self.processed: list = []
        self.resets = 0
        self._on_process = on_process

    def reset_cancellable(self) -> None:
        self.resets += 1

    def collect_errors(self):
        return []

    def process_game(self, game, additional_data, callback) -> None:
        self.processed.append((game, additional_data))
        if self._on_process:
            self._on_process(game)
        callback(self)


class FakeStore:
    """Only the id lookup the refresh does before saving a game."""

    def __init__(self) -> None:
        self.games_by_id: dict = {}

    def get(self, game_id, default=None):
        return self.games_by_id.get(game_id, default)


_counter = iter(range(1, 10_000))


def make_game(genre=None, appid=None):
    game = SimpleNamespace(
        game_id=f"imported_{next(_counter)}",
        genre=genre,
        steam_appid=appid,
        saved=0,
        updated=0,
    )
    game.save = lambda: setattr(game, "saved", game.saved + 1)
    game.update = lambda: setattr(game, "updated", game.updated + 1)
    return game



def complete_game(**overrides):
    """A game every source has already answered for, so a test only has to say
    what is missing about it."""
    game = make_game(genre="Metroidvania", appid="367520")
    game.developer = "Team Cherry"
    game.release_date = "Fev 2017"
    game.controller_support = "full"
    game.gamepad_recommended = True
    game.metacritic = 90
    game.steam_review = "Extremamente positivas"
    game.steam_checked = STEAM_METADATA_VERSION
    game.hltb_main = 90000
    game.hltb_chapters = None
    for field, value in overrides.items():
        setattr(game, field, value)
    # Mirrors Game.has_hltb_times, which is what the real rule reads.
    game.has_hltb_times = bool(game.hltb_main) or bool(game.hltb_chapters)
    return game


@pytest.fixture
def refresh(monkeypatch):
    """A refresh whose managers, store and toasts are stubbed out."""
    from cartridges import shared  # noqa: PLC0415

    monkeypatch.setattr(shared, "store", FakeStore(), raising=False)
    instance = MetadataRefresh()
    monkeypatch.setattr(instance, "_announce", lambda *_a: None)
    return instance


def drive(refresh_obj, managers, tags=None):
    """Run the queue synchronously, skipping the prefetch thread.

    The queued games are put in the store first: the refresh only saves a game
    the library still holds, so a queue of games nobody knows about would be
    walked without a single record being written.
    """
    from cartridges import shared  # noqa: PLC0415

    for game in refresh_obj._queue:  # pylint: disable=protected-access
        shared.store.games_by_id[game.game_id] = game
    refresh_obj._managers = managers  # pylint: disable=protected-access
    refresh_obj._run_queue(tags or {})  # pylint: disable=protected-access


# region The run itself


def test_counters_track_the_queue(refresh, monkeypatch) -> None:
    monkeypatch.setattr(refresh, "_finish", lambda: None)
    games = [make_game() for _ in range(4)]
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = 4
    refresh.running = True

    drive(refresh, [FakeManager()])

    assert refresh.done == 4
    assert refresh.fraction == pytest.approx(1)
    assert all(game.saved == 1 and game.updated == 1 for game in games)


def test_every_manager_runs_before_the_game_is_saved(refresh, monkeypatch) -> None:
    """Saving between managers would persist a half-updated record."""
    saves_seen = []
    steam = FakeManager()
    hltb = FakeManager(on_process=lambda game: saves_seen.append(game.saved))
    monkeypatch.setattr(refresh, "_finish", lambda: None)
    refresh._queue = [make_game()]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True

    drive(refresh, [steam, hltb])

    assert saves_seen == [0]
    assert len(steam.processed) == len(hltb.processed) == 1


def test_prefetched_tags_reach_the_managers(refresh, monkeypatch) -> None:
    monkeypatch.setattr(refresh, "_finish", lambda: None)
    manager = FakeManager()
    refresh._queue = [make_game()]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True

    drive(refresh, [manager], tags={"2519060": [1663]})

    assert manager.processed[0][1]["steam_tags"] == {"2519060": [1663]}


def test_cancel_stops_between_games(refresh, monkeypatch) -> None:
    monkeypatch.setattr(refresh, "_finish", lambda: None)
    manager = FakeManager(on_process=lambda _game: refresh.cancel())
    refresh._queue = [make_game() for _ in range(5)]  # pylint: disable=protected-access
    refresh.total = 5
    refresh.running = True

    drive(refresh, [manager])

    assert len(manager.processed) == 1
    assert refresh.done == 1


def test_cancel_while_idle_does_nothing(refresh) -> None:
    refresh.cancel()
    assert not refresh.cancelled


def test_start_refuses_an_empty_selection(refresh) -> None:
    assert refresh.start([]) is False
    assert not refresh.running


def test_a_fully_looked_up_game_needs_nothing(refresh) -> None:
    assert refresh.needs_steam(complete_game()) is False
    assert refresh.needs_hltb(complete_game()) is False
    assert refresh.is_incomplete(complete_game()) is False


def test_each_source_is_asked_for_separately(refresh) -> None:
    """One game short of its completion times and another short of its genre
    must not drag each other's lookups along."""
    only_hltb = complete_game(hltb_main=0, hltb_chapters=None)
    only_steam = complete_game(genre=None)

    assert (refresh.needs_steam(only_hltb), refresh.needs_hltb(only_hltb)) == (False, True)
    assert (refresh.needs_steam(only_steam), refresh.needs_hltb(only_steam)) == (True, False)


def test_missing_developer_or_release_date_brings_steam_back(refresh) -> None:
    """Fields every successful lookup produces: empty means never looked up."""
    assert refresh.needs_steam(complete_game(developer=None)) is True
    assert refresh.needs_steam(complete_game(release_date=None)) is True


def test_a_game_never_matched_on_steam_is_always_incomplete(refresh) -> None:
    assert refresh.needs_steam(complete_game(steam_appid=None)) is True


def test_an_older_stamp_brings_the_game_back_once(refresh) -> None:
    """How a field added after the game was imported ever gets filled in."""
    assert refresh.needs_steam(complete_game(steam_checked=0)) is True
    assert refresh.needs_steam(complete_game(steam_checked=STEAM_METADATA_VERSION)) is False


def test_legitimately_empty_fields_are_not_treated_as_gaps(refresh) -> None:
    """The trap this design exists to avoid.

    Fresh from the API, 29 of 30 games carry no gamepad recommendation and 5 no
    controller support. Reading those as work to do would put nearly the whole
    library back in the queue on every single run, and "only what is missing"
    would cost exactly what "fetch everything" costs.
    """
    for field in ("gamepad_recommended", "controller_support", "metacritic", "steam_review"):
        game = complete_game(**{field: None if field != "gamepad_recommended" else False})
        assert refresh.needs_steam(game) is False, field


def test_fraction_is_zero_before_anything_starts(refresh) -> None:
    assert refresh.fraction == pytest.approx(0)


def test_a_wiped_library_is_not_written_back(refresh, monkeypatch) -> None:
    """Resetting the app clears the store and deletes the records. A refresh
    still walking its own list of Game objects used to save every one of them
    afterwards, putting the games the user had just deleted back on disk."""
    from cartridges import shared  # noqa: PLC0415

    monkeypatch.setattr(refresh, "_finish", lambda: None)
    games = [make_game() for _ in range(3)]
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = 3
    refresh.running = True

    manager = FakeManager(on_process=lambda _game: shared.store.games_by_id.clear())
    drive(refresh, [manager])

    assert all(game.saved == 0 for game in games)
    assert all(game.updated == 0 for game in games)
    # The queue still drains, so the run ends instead of hanging
    assert refresh.done == 3


def test_a_reimported_game_is_not_overwritten(refresh) -> None:
    """Same id, different record: writing this one over it would undo the
    import that replaced it."""
    from cartridges import shared  # noqa: PLC0415

    game = make_game()
    replacement = make_game()
    replacement.game_id = game.game_id

    refresh._queue = [game]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True
    drive(
        refresh,
        [
            FakeManager(
                on_process=lambda _g: shared.store.games_by_id.update(
                    {game.game_id: replacement}
                )
            )
        ],
    )

    assert game.saved == 0
    assert replacement.saved == 0


def test_prefetch_failure_does_not_wedge_the_run(refresh, monkeypatch) -> None:
    """The prefetch thread is the only thing that schedules the queue. Anything
    escaping it left `running` True with no queue behind it, and no refresh
    could ever be started again."""
    from gi.repository import GLib  # noqa: PLC0415

    from cartridges import shared  # noqa: PLC0415
    from cartridges.store.managers.hltb_manager import HLTBManager  # noqa: PLC0415
    from cartridges.store.managers.steam_api_manager import (  # noqa: PLC0415
        SteamAPIManager,
    )

    class Exploding:
        def reset_cancellable(self) -> None:
            pass

        @property
        def steam_api_helper(self):
            raise AttributeError("boom")

    scheduled: list = []
    monkeypatch.setattr(GLib, "idle_add", lambda *args: scheduled.append(args))
    shared.store.managers = {
        SteamAPIManager: Exploding(),
        HLTBManager: Exploding(),
    }

    assert refresh.start([make_game(appid="440")]) is True
    for thread in list(threading.enumerate()):
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=5)

    # The queue was scheduled anyway, with the same empty mapping a failed bulk
    # request produces — every genre left exactly as it is.
    assert scheduled and scheduled[-1][1] == {}


def test_prefetch_stringifies_a_numeric_appid(refresh, monkeypatch) -> None:
    """A hand-edited record can hold the appid unquoted, and the manager looks
    the tags up under `str(appid)`."""
    from gi.repository import GLib  # noqa: PLC0415

    from cartridges import shared  # noqa: PLC0415
    from cartridges.store.managers.hltb_manager import HLTBManager  # noqa: PLC0415
    from cartridges.store.managers.steam_api_manager import (  # noqa: PLC0415
        SteamAPIManager,
    )

    asked: list = []

    class Recording:
        def reset_cancellable(self) -> None:
            pass

        @property
        def steam_api_helper(self):
            return SimpleNamespace(
                get_store_tags_bulk=lambda appids, should_stop=None: asked.append(
                    appids
                )
                or {}
            )

    monkeypatch.setattr(GLib, "idle_add", lambda *args: None)
    shared.store.managers = {
        SteamAPIManager: Recording(),
        HLTBManager: Recording(),
    }

    refresh.start([make_game(appid=440)])
    for thread in list(threading.enumerate()):
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(timeout=5)

    assert asked == [["440"]]


# endregion
# region The dialog as a view onto it


@pytest.fixture
def preferences(win, monkeypatch):
    """The real preferences dialog, wired to a refresh under our control."""
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    instance = MetadataRefresh()
    monkeypatch.setattr(
        preferences_module, "get_metadata_refresh", lambda: instance, raising=True
    )
    dialog = preferences_module.CartridgesPreferences()
    return dialog, instance


def test_row_starts_idle(preferences) -> None:
    dialog, _refresh = preferences

    assert dialog.metadata_stack.get_visible_child() is dialog.metadata_fetch_button
    assert not dialog.metadata_progress_bar.get_visible()


def test_dialog_opened_mid_run_shows_the_current_position(preferences) -> None:
    """The case this whole split exists for: close the dialog at game 12 of 47,
    reopen it, and the bar must still say 12 of 47."""
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    _dialog, refresh = preferences
    refresh.running = True
    refresh.done = 12
    refresh.total = 47

    reopened = preferences_module.CartridgesPreferences()

    assert reopened.metadata_stack.get_visible_child() is reopened.metadata_cancel_button
    assert reopened.metadata_progress_bar.get_visible()
    assert reopened.metadata_progress_bar.get_text() == "12 de 47"
    assert reopened.metadata_progress_bar.get_fraction() == pytest.approx(12 / 47)


def test_progress_signal_updates_an_open_dialog(preferences) -> None:
    dialog, refresh = preferences
    refresh.running = True
    refresh.done = 3
    refresh.total = 12
    refresh.emit("progress")

    assert dialog.metadata_progress_bar.get_text() == "3 de 12"
    assert dialog.metadata_progress_bar.get_fraction() == pytest.approx(0.25)


def test_finishing_returns_the_row_to_idle(preferences) -> None:
    dialog, refresh = preferences
    refresh.running = True
    refresh.done = 12
    refresh.total = 12
    refresh.emit("progress")
    refresh.running = False
    refresh.emit("progress")

    assert dialog.metadata_stack.get_visible_child() is dialog.metadata_fetch_button
    assert not dialog.metadata_progress_bar.get_visible()


def test_closed_dialog_stops_following_the_run(preferences) -> None:
    """The handler holds the dialog alive, so it has to go on close — and a
    stale dialog must not fight a live one over the same widgets."""
    dialog, refresh = preferences
    dialog.emit("closed")
    refresh.running = True
    refresh.done = 9
    refresh.total = 9
    refresh.emit("progress")

    assert dialog.metadata_progress_bar.get_text() != "9 de 9"


def test_row_is_insensitive_when_both_sources_are_off(preferences) -> None:
    """Both managers no-op with their setting off, so the button would walk the
    whole library and change nothing."""
    dialog, _refresh = preferences
    dialog.steam_metadata_switch.set_active(False)
    dialog.hltb_metadata_switch.set_active(False)
    dialog.update_metadata_sensitive()
    assert not dialog.metadata_update_row.get_sensitive()

    dialog.hltb_metadata_switch.set_active(True)
    dialog.update_metadata_sensitive()
    assert dialog.metadata_update_row.get_sensitive()


def test_cancel_button_greys_out_once_pressed(preferences) -> None:
    dialog, refresh = preferences
    refresh.running = True
    refresh.total = 5
    dialog.cancel_metadata_update()

    assert refresh.cancelled
    assert not dialog.metadata_cancel_button.get_sensitive()


# endregion


def test_only_missing_runs_just_the_sources_each_game_needs(refresh) -> None:
    """The four cases, in one run.

    A is short of its completion times, B of its controller support, C of its
    genre and D of its developer. A must cost one HowLongToBeat lookup and no
    Steam requests; B, C and D must cost the Steam lookup and no HowLongToBeat
    search. B is the one field emptiness cannot detect on its own — it is an
    older stamp that brings it back.
    """
    from cartridges import shared  # noqa: PLC0415

    game_a = complete_game(hltb_main=0)
    game_b = complete_game(controller_support=None, steam_checked=0)
    game_c = complete_game(genre=None)
    game_d = complete_game(developer=None)
    games = [game_a, game_b, game_c, game_d]
    for game in games:
        shared.store.games_by_id[game.game_id] = game

    steam, hltb = FakeManager(), FakeManager()
    refresh._managers = [steam, hltb]  # pylint: disable=protected-access
    refresh._only_missing = True  # pylint: disable=protected-access
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = len(games)
    refresh.running = True
    refresh._run_queue({})  # pylint: disable=protected-access

    assert [g for g, _ in steam.processed] == [game_b, game_c, game_d]
    assert [g for g, _ in hltb.processed] == [game_a]


def test_fetch_everything_ignores_what_is_already_there(refresh) -> None:
    """The other half of the promise: "fetch everything" really does."""
    from cartridges import shared  # noqa: PLC0415

    games = [complete_game() for _ in range(3)]
    for game in games:
        shared.store.games_by_id[game.game_id] = game

    steam, hltb = FakeManager(), FakeManager()
    refresh._managers = [steam, hltb]  # pylint: disable=protected-access
    refresh._only_missing = False  # pylint: disable=protected-access
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = 3
    refresh.running = True
    refresh._run_queue({})  # pylint: disable=protected-access

    assert len(steam.processed) == 3
    assert len(hltb.processed) == 3


def test_steam_stays_ahead_of_hltb_when_both_run(refresh) -> None:
    """HowLongToBeat searches by title, and the Steam lookup is what corrects
    it — selecting sources per game must not reorder them."""
    game = complete_game(developer=None, hltb_main=0)
    steam, hltb = FakeManager(), FakeManager()
    refresh._managers = [steam, hltb]  # pylint: disable=protected-access
    refresh._only_missing = True  # pylint: disable=protected-access

    assert refresh.managers_for(game) == [steam, hltb]


def test_a_game_needing_nothing_gets_no_lookups(refresh) -> None:
    refresh._only_missing = True  # pylint: disable=protected-access
    refresh._managers = [FakeManager(), FakeManager()]  # pylint: disable=protected-access

    assert refresh.managers_for(complete_game()) == []


def test_fetch_everything_forces_the_completion_times_too(refresh) -> None:
    """The HowLongToBeat manager declines to look up a game that already has
    times unless told otherwise, so without the flag "fetch everything" would
    quietly skip them — an option that fetches all but one thing."""
    from cartridges import shared  # noqa: PLC0415

    game = complete_game()
    shared.store.games_by_id[game.game_id] = game

    manager = FakeManager()
    refresh._managers = [manager]  # pylint: disable=protected-access
    refresh._only_missing = False  # pylint: disable=protected-access
    refresh._queue = [game]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True
    refresh._run_queue({})  # pylint: disable=protected-access

    assert manager.processed[0][1]["refresh_hltb"] is True


def test_only_missing_never_forces_them(refresh) -> None:
    """There the games with times are not queued for HowLongToBeat at all, so
    forcing a refetch would only be a way to spend requests."""
    from cartridges import shared  # noqa: PLC0415

    game = complete_game(hltb_main=0)
    shared.store.games_by_id[game.game_id] = game

    manager = FakeManager()
    refresh._managers = [FakeManager(), manager]  # pylint: disable=protected-access
    refresh._only_missing = True  # pylint: disable=protected-access
    refresh._queue = [game]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True
    refresh._run_queue({})  # pylint: disable=protected-access

    assert manager.processed[0][1]["refresh_hltb"] is False


def _fully_looked_up(stamp):
    """A game with everything Steam produces, carrying ``stamp``."""
    game = make_game(genre="g", appid="440")
    game.developer = "d"
    game.release_date = "2020"
    game.steam_checked = stamp
    return game


@pytest.mark.parametrize("stamp", [None, "", [], {}, object(), "abc"])
def test_an_unreadable_version_stamp_reads_as_unchecked(refresh, stamp) -> None:
    """`needs_steam` runs inside a comprehension over the whole library, on the
    main thread. `None < 2` raising there stopped the scope dialog opening at
    all, for every game, because of one bad record. Anything unreadable is
    treated as "never looked up", which only costs a lookup."""
    assert refresh.needs_steam(_fully_looked_up(stamp)) is True


@pytest.mark.parametrize("as_type,expected", [(str, False), (float, False)])
def test_a_readable_stamp_is_honoured_whatever_its_type(
    refresh, as_type, expected
) -> None:
    """A number written as a string is still a number. Derived from the
    constant, not spelled out, so bumping the version cannot leave this test
    quietly asserting the old one."""
    from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: PLC0415

    stamp = as_type(STEAM_METADATA_VERSION)
    assert refresh.needs_steam(_fully_looked_up(stamp)) is expected


def test_a_fractional_stamp_errs_towards_looking_again(refresh) -> None:
    """Truncation has to round down, never up onto the current version."""
    from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: PLC0415

    assert refresh.needs_steam(_fully_looked_up(STEAM_METADATA_VERSION - 0.5)) is True


def test_a_usable_stamp_still_short_circuits(refresh) -> None:
    """The guard must not turn every game into work."""
    from cartridges.utils.steam import STEAM_METADATA_VERSION

    game = make_game(genre="g", appid="440")
    game.developer = "d"
    game.release_date = "2020"
    game.steam_checked = STEAM_METADATA_VERSION

    assert refresh.needs_steam(game) is False
    game.steam_checked = STEAM_METADATA_VERSION - 1
    assert refresh.needs_steam(game) is True
