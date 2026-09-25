# test_ui_logic.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The decisions inside widgets, tested without testing the widgets.

Layout, theming and drawing are not tested here — the cost is high, the value
low, and GTK moves underneath. What is tested is the logic that happens to live
in a widget class: which search box a filter reads, whether a comparator is a
total order, whether a counter balances. Those are where the bugs were.

The plan proposed extracting each of these into a pure function first. Building
the real window turned out to be cheap — no display is presented, only realised
— so they are driven directly instead, which tests the wiring as well as the
rule.
"""

import logging
from types import SimpleNamespace

import pytest
from gi.repository import GLib, Gtk

from cartridges import gamepad as gp
from cartridges.logging.session_file_handler import SessionFileHandler
from cartridges.utils.animated_flow_box import AnimatedFlowBox
from cartridges.utils import window_geometry
from cartridges.window import CartridgesWindow


# ---------------------------------------------------------------------------
# T7.1  The filter reads the box belonging to its own grid
# ---------------------------------------------------------------------------


def add_game_to(window, game):
    window.library.append(game)
    return window.library


def test_filter_matches_against_the_grid_the_child_lives_in(
    real_window, make_game, store
):
    """T7.1 The same filter is installed on both grids.

    Deciding by the visible page matched a game against the wrong box whenever
    the two disagreed. GTK re-runs the filter on ``append``, so a game imported
    while the other page was open was tested against the wrong box, came out
    filtered, and stayed invisible — and nothing invalidates the filter again
    once the import is over.
    """
    from cartridges.game import Game

    real_window.search_entry.set_text("zelda")

    matching = Game(
        {
            "source": "shortcuts",
            "game_id": "shortcuts_1",
            "name": "Zelda",
            "executable": "x",
            "added": 0,
        }
    )
    other = Game(
        {
            "source": "shortcuts",
            "game_id": "shortcuts_2",
            "name": "Halo",
            "executable": "x",
            "added": 0,
        }
    )

    add_game_to(real_window, matching)
    add_game_to(real_window, other)

    assert real_window.filter_func(matching.get_parent()) is True
    assert real_window.filter_func(other.get_parent()) is False


# ---------------------------------------------------------------------------
# T7.2  compare_names is a total order
# ---------------------------------------------------------------------------


def names(*pairs):
    return [SimpleNamespace(name=name, game_id=game_id) for name, game_id in pairs]


def test_identical_records_compare_equal():
    """T7.2 ``(name1 > name2) * 2 - 1`` never returned 0."""
    game = SimpleNamespace(name="Halo", game_id="shortcuts_1")
    assert CartridgesWindow.compare_names(game, game) == 0


def test_the_same_title_from_two_sources_has_a_stable_order():
    """T7.2 The pair used to trade places on every invalidate_sort."""
    first, second = names(("Halo", "shortcuts_1"), ("Halo", "steam_2"))

    forward = CartridgesWindow.compare_names(first, second)
    backward = CartridgesWindow.compare_names(second, first)

    assert forward != 0
    assert forward == -backward


def test_the_order_is_antisymmetric_and_transitive():
    """T7.2 The three properties a sort function has to have."""
    games = names(
        ("Alien", "shortcuts_1"),
        ("Halo", "shortcuts_2"),
        ("Halo", "shortcuts_3"),
        ("halo", "shortcuts_4"),
        ("Zelda", "shortcuts_5"),
    )
    compare = CartridgesWindow.compare_names

    for left in games:
        assert compare(left, left) == 0  # reflexive
        for right in games:
            assert compare(left, right) == -compare(right, left)  # antisymmetric
            for third in games:
                if compare(left, right) <= 0 and compare(right, third) <= 0:
                    assert compare(left, third) <= 0  # transitive


def test_sorting_is_case_insensitive_on_the_title():
    lower, upper = names(("halo", "shortcuts_9"), ("Alien", "shortcuts_1"))
    assert CartridgesWindow.compare_names(upper, lower) < 0


# ---------------------------------------------------------------------------
# T7.3  The Apply button always comes back
# ---------------------------------------------------------------------------


def test_loading_operations_balance(details_dialog):
    """T7.3 Two overlapping operations used to leave Apply off for good."""
    dialog = details_dialog
    assert dialog.apply_button.get_sensitive() is True

    dialog.begin_loading()
    dialog.begin_loading(cover=True)
    assert dialog.apply_button.get_sensitive() is False

    dialog.end_loading(cover=True)
    assert dialog.apply_button.get_sensitive() is False, "one is still running"

    dialog.end_loading()
    assert dialog.apply_button.get_sensitive() is True


def test_an_extra_end_never_drives_the_counter_negative(details_dialog):
    """T7.3 A thread dying twice must not make Apply un-disable-able."""
    dialog = details_dialog
    dialog.end_loading()
    dialog.end_loading()
    assert dialog._loading_ops == 0

    dialog.begin_loading()
    assert dialog.apply_button.get_sensitive() is False


@pytest.mark.parametrize("ending", ["success", "error", "picker_dismissed"])
def test_every_exit_path_releases_the_button(details_dialog, ending):
    """T7.3 Cancel (and losing the edits) was the only way out."""
    dialog = details_dialog
    dialog.begin_loading()
    assert dialog.apply_button.get_sensitive() is False

    # Whatever the outcome, the operation gives its slot back exactly once.
    dialog.end_loading()

    assert dialog.apply_button.get_sensitive() is True
    assert dialog._loading_ops == 0


# ---------------------------------------------------------------------------
# T7.4  The gamepad direction machine
# ---------------------------------------------------------------------------


def make_pad(buttons=0, thumb_x=0, thumb_y=0):
    return SimpleNamespace(wButtons=buttons, sThumbLX=thumb_x, sThumbLY=thumb_y)


@pytest.fixture
def pad_manager(monkeypatch):
    """A GamepadManager with only the direction state, and a clock we drive."""
    manager = gp.GamepadManager.__new__(gp.GamepadManager)
    manager._direction = None
    manager._direction_since = 0
    manager._repeats = 0
    manager._direction_latched = False
    manager._engaged = True
    manager._buttons = 0
    manager._resync = False

    moves: list = []
    monkeypatch.setattr(manager, "_move", moves.append)

    clock = {"now": 1_000_000}
    monkeypatch.setattr(gp.GLib, "get_monotonic_time", lambda: clock["now"])

    manager.moves = moves
    manager.clock = clock
    return manager


def test_a_direction_held_across_a_resync_does_not_move(pad_manager):
    """T7.4 Holding the d-pad in a game and alt-tabbing back must be silent.

    The repeat branch does not require an edge, so 400 ms after focus returned
    the grid started scrolling on its own at about 8 Hz with no new input.
    """
    pad = make_pad(buttons=gp.XINPUT_DPAD_DOWN)

    # What `_poll` does on a resync: adopt what is held as the baseline.
    pad_manager._direction = pad_manager._read_direction(pad)
    pad_manager._direction_since = pad_manager.clock["now"]
    pad_manager._repeats = 0
    pad_manager._direction_latched = True

    for _ in range(20):
        pad_manager.clock["now"] += 200_000
        pad_manager._handle_direction(pad)

    assert pad_manager.moves == []


def test_releasing_and_pressing_again_moves(pad_manager):
    """T7.4 Real input after the resync must work as it always did."""
    held = make_pad(buttons=gp.XINPUT_DPAD_DOWN)
    pad_manager._direction = Gtk.DirectionType.DOWN
    pad_manager._direction_latched = True

    pad_manager.clock["now"] += 100_000
    pad_manager._handle_direction(make_pad())  # released
    assert pad_manager.moves == []

    pad_manager.clock["now"] += 100_000
    pad_manager._handle_direction(held)  # pressed again

    assert pad_manager.moves == [Gtk.DirectionType.DOWN]


def test_changing_direction_without_releasing_moves(pad_manager):
    """T7.4 Trading one direction for another is real input too."""
    pad_manager._direction = Gtk.DirectionType.DOWN
    pad_manager._direction_latched = True

    pad_manager.clock["now"] += 100_000
    pad_manager._handle_direction(make_pad(buttons=gp.XINPUT_DPAD_UP))

    assert pad_manager.moves == [Gtk.DirectionType.UP]


def test_an_ordinary_press_repeats_after_the_delay(pad_manager):
    """T7.4 The control: nothing latched, so auto-repeat still works."""
    pad = make_pad(buttons=gp.XINPUT_DPAD_RIGHT)

    pad_manager._handle_direction(pad)  # first press moves at once
    assert pad_manager.moves == [Gtk.DirectionType.RIGHT]

    pad_manager.clock["now"] += gp.REPEAT_DELAY_US - 1
    pad_manager._handle_direction(pad)
    assert len(pad_manager.moves) == 1, "too early to repeat"

    pad_manager.clock["now"] += 2
    pad_manager._handle_direction(pad)
    assert len(pad_manager.moves) == 2


def test_the_dpad_beats_the_stick(pad_manager):
    """Both pushed at once resolves to one lane, not two."""
    pad = make_pad(buttons=gp.XINPUT_DPAD_LEFT, thumb_x=30_000)
    assert pad_manager._read_direction(pad) == Gtk.DirectionType.LEFT


def test_stick_drift_is_ignored_until_the_pad_is_engaged(pad_manager):
    """A freshly connected pad reporting an off-centre stick must stay still."""
    pad_manager._engaged = False
    drift = make_pad(thumb_x=12_000)

    assert pad_manager._read_direction(drift) is None

    deliberate = make_pad(thumb_x=30_000)
    assert pad_manager._read_direction(deliberate) == Gtk.DirectionType.RIGHT


# ---------------------------------------------------------------------------
# T7.5  The session log has a ceiling
# ---------------------------------------------------------------------------


def record(message="hello"):
    return logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)


def test_the_log_stops_at_the_cap_and_says_so(tmp_path, monkeypatch):
    """T7.5 An unbounded session log made the next startup read it all back."""
    monkeypatch.setattr(SessionFileHandler, "MAX_BYTES", 2000)
    handler = SessionFileHandler(filename=tmp_path / "cartridges.log", backup_count=2)
    handler.setFormatter(logging.Formatter("%(message)s"))

    for index in range(500):
        handler.emit(record(f"line {index} " + "x" * 50))
    handler.close()

    text = (tmp_path / "cartridges.log").read_text(encoding="utf-8")
    assert "Log capped at 2000 bytes" in text
    assert "line 0 " in text, "the beginning is what is kept"
    assert "line 499 " not in text


def test_emit_never_raises_into_the_caller(tmp_path):
    """T7.5 This runs inside somebody's logging call, often while handling an error."""
    handler = SessionFileHandler(filename=tmp_path / "cartridges.log", backup_count=2)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.close()

    handler.emit(record("after close"))  # must not raise


def test_rotation_keeps_the_previous_session(tmp_path):
    """T7.5 backup_count limits how many sessions are kept, not their size."""
    path = tmp_path / "cartridges.log"
    first = SessionFileHandler(filename=path, backup_count=2)
    first.setFormatter(logging.Formatter("%(message)s"))
    first.emit(record("session one"))
    first.close()

    second = SessionFileHandler(filename=path, backup_count=2)
    second.close()

    archived = [item for item in tmp_path.iterdir() if item.name != "cartridges.log"]
    assert archived, "the previous session should have been rotated away"


def test_rotation_survives_an_undecodable_log(tmp_path):
    """T7.5 A half-written file from a crash must not stop the app from starting."""
    path = tmp_path / "cartridges.log"
    path.write_bytes(b"\xff\xfe invalid \x00 bytes")

    handler = SessionFileHandler(filename=path, backup_count=2)
    handler.close()

    assert path.exists()


# ---------------------------------------------------------------------------
# Where the app writes
# ---------------------------------------------------------------------------


def test_nothing_is_written_to_the_browser_cache():
    """Session logs must not live in INetCache.

    `GLib.get_user_cache_dir()` resolves to CSIDL_INTERNET_CACHE on Windows —
    `AppData\\Local\\Microsoft\\Windows\\INetCache`, the browser's temporary
    files folder, which Disk Cleanup and Storage Sense empty by default. The
    session log does not survive that, and the log of the run that went
    wrong is exactly what a sweep takes away between the crash and somebody
    going to look for it.

    Read from the template rather than the test's synthetic `shared`: the
    synthetic one is this suite's own invention, so asserting against it would
    only prove the fixture agrees with itself.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    source = (root / "cartridges" / "shared.py.in").read_text(encoding="utf-8")
    code = [
        line
        for line in source.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert not any("get_user_cache_dir" in line for line in code)
    assert "log_dir = app_dir / \"logs\"" in code


# ---------------------------------------------------------------------------
# T7.6  Window geometry
# ---------------------------------------------------------------------------


def test_a_geometry_needs_a_size_to_be_usable():
    """T7.6 A zero-sized rectangle is what an unrealised window reports."""
    assert window_geometry.Geometry(0, 0, 0, 0, False).usable is False
    assert window_geometry.Geometry(10, 10, 1170, 795, False).usable is True


def test_a_maximized_geometry_keeps_the_restored_size():
    """T7.6 Saving the maximized size would grow the window on every run."""
    geometry = window_geometry.Geometry(10, 10, 1170, 795, True)
    assert geometry.maximized is True
    assert (geometry.width, geometry.height) == (1170, 795)


def test_reading_an_unrealised_window_gives_nothing(real_window):
    """T7.6 There is no placement to save before the window has one."""
    geometry = window_geometry.read(real_window)
    assert geometry is None or isinstance(geometry, window_geometry.Geometry)


def test_apply_size_sets_the_requested_size(real_window):
    """T7.6 The restore half of the round trip."""
    window_geometry.apply_size(
        real_window, window_geometry.Geometry(0, 0, 900, 600, False)
    )
    assert real_window.get_default_size() == (900, 600)


# ---------------------------------------------------------------------------
# The genre and gamepad-support rows on the edit dialog
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stored,position",
    [(None, 0), ("full", 1), ("partial", 2)],
)
def test_controller_support_round_trips(details_dialog, stored, position):
    """The row is the only place these values are entered by hand, so the map
    between them and the list positions has to survive both directions."""
    details_dialog.set_controller_support(stored)
    assert details_dialog.controller_support.get_selected() == position
    assert details_dialog.get_controller_support() == stored


def test_an_unknown_controller_value_falls_back_to_not_stated(details_dialog):
    """A hand-edited record can hold anything; the details page already treats
    an unrecognised value as "nothing said" and the row must agree."""
    details_dialog.set_controller_support("yes")
    assert details_dialog.controller_support.get_selected() == 0
    assert details_dialog.get_controller_support() is None


# ---------------------------------------------------------------------------
# The "open the game's folder" button on the executable row
# ---------------------------------------------------------------------------


def test_the_folder_button_follows_the_executable_field(details_dialog, tmp_path):
    """It has to track what is typed, not what the dialog opened on.

    Retargeting a game from its .exe to a Steam URI (or the reverse) is an
    ordinary edit, and a button left over from the previous value would open
    somebody else's folder — or nothing at all.
    """
    exe = tmp_path / "halo.exe"
    exe.write_bytes(b"")
    folder = str(tmp_path).replace("/", "\\")

    details_dialog.executable.set_text(f'start "" "{folder}\\halo.exe"')
    assert details_dialog.open_folder_button.get_visible() is True
    assert details_dialog._game_folder == folder

    details_dialog.executable.set_text('start "" "steam://rungameid/440"')
    assert details_dialog.open_folder_button.get_visible() is False
    assert details_dialog._game_folder is None


def test_the_folder_button_is_hidden_on_an_empty_dialog(details_dialog):
    """"Adicionar novo jogo" starts with no command, so there is nothing to open."""
    assert details_dialog.open_folder_button.get_visible() is False


def test_open_game_folder_tells_the_user_when_it_fails(details_dialog, monkeypatch):
    """The folder can vanish between the button appearing and the click — that
    used to only reach the log, leaving the click looking like it did nothing."""
    from cartridges import details_dialog as modulo  # noqa: PLC0415

    details_dialog._game_folder = "C:\\Some\\Folder"  # pylint: disable=protected-access
    monkeypatch.setattr(modulo, "open_folder", lambda _directory: False)
    shown = []
    monkeypatch.setattr(
        modulo, "create_dialog", lambda *args, **_kw: shown.append(args)
    )

    details_dialog.open_game_folder()

    assert shown


def test_the_rows_are_filled_from_the_game(win):
    """Opening the dialog on a game shows what it already holds."""
    from cartridges.details_dialog import DetailsDialog
    from cartridges.game import Game

    game = Game(
        {
            "game_id": "imported_1",
            "name": "Probe",
            "source": "imported",
            "executable": "x.exe",
            "added": 0,
            "genre": "Metroidvania",
            "controller_support": "partial",
        }
    )
    dialog = DetailsDialog(game)

    assert dialog.genre.get_text() == "Metroidvania"
    assert dialog.get_controller_support() == "partial"


@pytest.fixture
def no_hltb_lookup(monkeypatch):
    """`_fetch_metadata_done` encadeia a busca no HowLongToBeat numa thread, e
    ela ia à rede de verdade, com o erro aparecendo depois do fim da suíte."""
    from cartridges.details_dialog import DetailsDialog

    monkeypatch.setattr(DetailsDialog, "_fetch_hltb_thread", lambda *_args: None)


def test_a_steam_fetch_fills_the_rows_rather_than_hiding_the_values(
    details_dialog, no_hltb_lookup
):
    """They used to be fetched and dropped: the lookup pays a request for the
    store tags the genre is picked from, and the answer never reached the game."""
    details_dialog.executable.set_text("x.exe")
    details_dialog._fetch_metadata_done(
        {"name": "Probe", "genre": "Roguelike de Ação", "controller_support": "full"},
        None,
        "1145360",
    )

    assert details_dialog.genre.get_text() == "Roguelike de Ação"
    assert details_dialog.get_controller_support() == "full"


def test_apply_writes_both_rows_to_the_game(real_window, store):
    """Whitespace means empty, not an empty string sitting in the record —
    and "not stated" has to be able to undo a value, not just add one."""
    from cartridges.details_dialog import DetailsDialog
    from cartridges.game import Game
    from cartridges.store.managers.sgdb_manager import SgdbManager

    class StubSgdb:
        signals: set = set()

        def reset_cancellable(self):
            pass

        def collect_errors(self):
            return []

        def process_game(self, game, _data, callback):
            game.set_loading(-1)
            callback(self)

    store.managers[SgdbManager] = StubSgdb()

    game = Game(
        {
            "game_id": "imported_1",
            "name": "Probe",
            "source": "imported",
            "executable": "x.exe",
            "added": 0,
            "genre": "Metroidvania",
            "controller_support": "full",
        }
    )
    dialog = DetailsDialog(game)
    assert dialog.genre.get_text() == "Metroidvania"

    dialog.genre.set_text("  Soulslike  ")
    dialog.set_controller_support("partial")
    dialog.apply_preferences()
    assert game.genre == "Soulslike"
    assert game.controller_support == "partial"

    dialog = DetailsDialog(game)
    dialog.genre.set_text("   ")
    dialog.set_controller_support(None)
    dialog.apply_preferences()
    assert game.genre is None
    assert game.controller_support is None


# Every metadata field the record persists, each with a value that is not the
# class default — so a field the dialog forgets shows up as a change, not as a
# coincidence. This is the guard against the bug that already happened once:
# the genre and controller rows were written on apply before they were filled
# on open, so editing a game for any reason silently blanked both.
PERSISTED_METADATA = {
    "developer": "Team Cherry",
    "publisher": "Team Cherry",
    "release_date": "24/fev./2017",
    "metacritic": 90,
    "steam_review": "Extremamente positivas",
    "genre": "Metroidvania",
    "controller_support": "full",
    "gamepad_recommended": True,
    "description": "Forje seu caminho em Hollow Knight!",
    "steam_appid": "367520",
    "steam_checked": 1,
    "hltb_id": 26286,
    "hltb_main": 90000,
    "hltb_main_extra": 140000,
    "hltb_completionist": 230000,
    "hltb_chapters": [{"number": 1, "name": "Prólogo", "hltb_main": 3600}],
    "track_updates": True,
    "process_executable": "hollow_knight.exe",
    "status": "beaten",
    "rating": 4,
    # Com quebra de linha no meio de propósito: a anotação é um bloco, e
    # aplicar a edição não pode achatá-la numa linha só.
    "notes": "Parei no capítulo 4.\nSenha do cofre: 8815",
}


def _stub_sgdb(store):
    from cartridges.store.managers.sgdb_manager import SgdbManager

    class StubSgdb:
        signals: set = set()

        def reset_cancellable(self):
            pass

        def collect_errors(self):
            return []

        def process_game(self, game, _data, callback):
            game.set_loading(-1)
            callback(self)

    store.managers[SgdbManager] = StubSgdb()


def _probe_game():
    from cartridges.game import Game

    return Game(
        {
            "game_id": "imported_1",
            "name": "Probe",
            "source": "imported",
            "executable": "x.exe",
            "added": 0,
            **PERSISTED_METADATA,
        }
    )


def test_an_untouched_apply_costs_the_game_nothing(real_window, store):
    """Open the edit dialog, change nothing, apply: every field must survive.

    The dialog writes the game attribute by attribute, so a field is only safe
    while every row that writes one is also filled from the game on open. This
    checks the whole set at once rather than the field somebody remembered.
    """
    from cartridges.details_dialog import DetailsDialog

    _stub_sgdb(store)
    game = _probe_game()

    DetailsDialog(game).apply_preferences()

    for field, value in PERSISTED_METADATA.items():
        assert getattr(game, field) == value, f"apply lost {field}"


def test_editing_one_field_leaves_the_others_alone(real_window, store):
    """The realistic version: the user opens the dialog to fix the title."""
    from cartridges.details_dialog import DetailsDialog

    _stub_sgdb(store)
    game = _probe_game()

    dialog = DetailsDialog(game)
    dialog.name.set_text("Hollow Knight")
    dialog.apply_preferences()

    assert game.name == "Hollow Knight"
    for field, value in PERSISTED_METADATA.items():
        assert getattr(game, field) == value, f"editing the name lost {field}"


def test_a_steam_fetch_carries_the_gamepad_recommendation_to_the_game(
    real_window, store, no_hltb_lookup
):
    """It has no row of its own, so it rides on the fetch like the Metacritic
    score — and like it, must actually reach the record on apply."""
    from cartridges.details_dialog import DetailsDialog

    _stub_sgdb(store)
    game = _probe_game()
    game.gamepad_recommended = False

    dialog = DetailsDialog(game)
    dialog._fetch_metadata_done(
        {"name": "Probe", "gamepad_recommended": True}, None, "1030300"
    )
    dialog.apply_preferences()

    assert game.gamepad_recommended is True


def test_a_fetch_can_take_the_recommendation_away(
    real_window, store, no_hltb_lookup
):
    """False is an answer, not a missing value: a game that loses the category
    on Steam has to lose the line here too."""
    from cartridges.details_dialog import DetailsDialog

    _stub_sgdb(store)
    game = _probe_game()

    dialog = DetailsDialog(game)
    dialog._fetch_metadata_done(
        {"name": "Probe", "gamepad_recommended": False}, None, "367520"
    )
    dialog.apply_preferences()

    assert game.gamepad_recommended is False


def test_a_manual_edit_without_a_fetch_keeps_the_recommendation(real_window, store):
    """Nothing was looked up, so nothing is known — the stored value stands."""
    from cartridges.details_dialog import DetailsDialog

    _stub_sgdb(store)
    game = _probe_game()

    dialog = DetailsDialog(game)
    dialog.name.set_text("Outro nome")
    dialog.apply_preferences()

    assert game.gamepad_recommended is True


# Fields the record keeps that say nothing about the game itself: identity,
# bookkeeping and the update-notice state. They are exempt from the guard
# above because the edit dialog has no business preserving them.
NOT_GAME_METADATA = {
    "added",
    "blacklisted",
    "executable",
    "game_id",
    "last_played",
    "name",
    "playtime",
    "removed",
    "run_as_admin",
    "shortcut_mtime",
    "install_size",
    "install_size_ts",
    "shortcut_path",
    "source",
    "track_process",
    "update_available_ts",
    "update_dismissed_ts",
    "update_url",
    "version",
}


def test_the_guard_covers_every_persisted_field():
    """Keeps the check above honest.

    ``PERSISTED_METADATA`` is written by hand, so without this a field added to
    the record would simply not be covered, and the guard would keep passing
    while the bug it exists for came back. Adding a field now forces a choice:
    put it in the guard, or say here why it does not belong.
    """
    from cartridges.store.managers.file_manager import PERSISTED_ATTRS

    covered = set(PERSISTED_METADATA) | NOT_GAME_METADATA
    assert set(PERSISTED_ATTRS) - covered == set(), "field not covered by the guard"
    assert covered - set(PERSISTED_ATTRS) == set(), "guard lists a field nobody saves"


# ---------------------------------------------------------------------------
# The details page decodes its own cover
# ---------------------------------------------------------------------------


@pytest.fixture
def cover_file(app_dirs):
    """A still cover master, at the resolution they are stored in."""
    from PIL import Image

    path = app_dirs.covers / "probe.tiff"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 900), "red").save(path, compression=None)
    return path


def test_the_grid_texture_stays_at_the_grid_size(cover_file):
    """Raising it would cost the whole library to sharpen one picture."""
    from cartridges import shared
    from cartridges.game_cover import GameCover

    cover = GameCover(set(), cover_file)
    texture = cover.get_texture()
    assert (texture.get_width(), texture.get_height()) == shared.display_size


def test_the_details_picture_gets_a_texture_at_its_own_size(cover_file):
    """It draws at 280x420; a 200x300 texture was being stretched 1.4x."""
    from cartridges import shared
    from cartridges.game_cover import GameCover

    picture = Gtk.Picture()
    cover = GameCover(set(), cover_file)
    cover.add_details_picture(picture)

    painted = picture.get_paintable()
    assert (painted.get_width(), painted.get_height()) == shared.details_size
    assert shared.details_size != shared.display_size


def test_the_sharp_texture_is_dropped_when_the_page_moves_on(cover_file):
    """`game_covers` never evicts, so one kept here would be kept forever."""
    from cartridges.game_cover import GameCover

    picture = Gtk.Picture()
    cover = GameCover(set(), cover_file)
    cover.add_details_picture(picture)
    assert cover._details_texture is not None

    cover.release_details_picture(picture)
    assert cover._details_texture is None
    assert cover._details_picture is None
    assert picture not in cover.pictures


def test_releasing_a_picture_the_cover_never_held_is_not_an_error(cover_file):
    """The old code used `pictures.remove`, which raised KeyError when the
    previous cover had already let the picture go."""
    from cartridges.game_cover import GameCover

    cover = GameCover(set(), cover_file)
    cover.release_details_picture(Gtk.Picture())  # must not raise


def test_the_grid_keeps_its_own_texture_while_details_is_open(cover_file):
    """Two sizes on screen at once: the same cover in the grid and the page."""
    from cartridges import shared
    from cartridges.game_cover import GameCover

    grid, details = Gtk.Picture(), Gtk.Picture()
    cover = GameCover({grid}, cover_file)
    cover.add_picture(grid)
    cover.add_details_picture(details)

    assert (
        grid.get_paintable().get_width(),
        grid.get_paintable().get_height(),
    ) == shared.display_size
    assert (
        details.get_paintable().get_width(),
        details.get_paintable().get_height(),
    ) == shared.details_size


def test_a_new_cover_recomputes_the_blur_for_the_open_page(cover_file, app_dirs):
    """Adding a cover to a game whose page is open must refresh the backdrop.

    The page's blur request stays registered across `new_cover`, which
    restarts the computation itself. Every window-side call runs before the
    deferred cover reload (`save_cover` hands it over by idle), so nothing
    else would ever ask again — the backdrop just went black and stayed.
    """
    import time as time_mod

    from gi.repository import GLib
    from cartridges.game_cover import GameCover

    seen = []
    cover = GameCover(set())  # um jogo sem capa
    cover.ensure_blurred(seen.append)

    # Sem capa o placeholder sai síncrono: nada de quadro preto no meio.
    assert seen and cover.blurred is cover.placeholder_small

    cover.new_cover(cover_file)

    context = GLib.MainContext.default()
    deadline = time_mod.time() + 5
    while time_mod.time() < deadline and len(seen) < 2:
        context.iteration(False)
        time_mod.sleep(0.005)

    assert len(seen) == 2, "o fundo da capa nova nunca chegou"
    assert cover.blurred is not None
    assert cover.blurred is not cover.placeholder_small
    assert cover.luminance is not None


def test_releasing_the_details_picture_drops_the_blur_request(cover_file):
    """A page that moved on must not be repainted by a later cover edit."""
    from cartridges.game_cover import GameCover

    seen = []
    picture = Gtk.Picture()
    cover = GameCover(set(), cover_file)
    cover.add_details_picture(picture)
    cover.ensure_blurred(seen.append)

    cover.release_details_picture(picture)
    assert cover._blur_callback is None


def test_editing_the_cover_refreshes_the_open_details_page(cover_file, app_dirs):
    """`new_cover` drops the sharp copy; it is of the old image."""
    from PIL import Image
    from cartridges import shared
    from cartridges.game_cover import GameCover

    picture = Gtk.Picture()
    cover = GameCover(set(), cover_file)
    cover.add_details_picture(picture)
    first = picture.get_paintable()

    replacement = app_dirs.covers / "probe2.tiff"
    Image.new("RGB", (600, 900), "blue").save(replacement, compression=None)
    cover.new_cover(replacement)

    assert picture.get_paintable() is not first
    assert (
        picture.get_paintable().get_width(),
        picture.get_paintable().get_height(),
    ) == shared.details_size


def test_an_unchanged_apply_keeps_the_computed_blur(real_window, store, app_dirs):
    """Apply replaces the game's GameCover with the dialog's own object; when
    the cover file did not change, the computed backdrop must ride along —
    without it the details page flashed black for a frame while the identical
    blur was recomputed from scratch."""
    from PIL import Image
    from cartridges import shared
    from cartridges.details_dialog import DetailsDialog
    from cartridges.game import Game
    from cartridges.game_cover import GameCover

    game = Game(
        {
            "game_id": "imported_8",
            "name": "Probe",
            "source": "imported",
            "executable": "x.exe",
            "added": 0,
        }
    )
    cover_path = shared.covers_dir / "imported_8.tiff"
    cover_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (600, 900), "green").save(cover_path, compression=None)

    old_cover = GameCover(set(), cover_path)
    old_blur = old_cover.get_blurred()
    shared.win.game_covers[game.game_id] = old_cover

    DetailsDialog(game).apply_preferences()

    new_cover = shared.win.game_covers[game.game_id]
    assert new_cover is not old_cover, "apply swaps the cover object"
    assert new_cover.blurred is old_blur, "the backdrop must be inherited"
    assert new_cover.luminance == old_cover.luminance


def test_a_logo_can_come_from_a_local_file(real_window, store, app_dirs):
    """SteamGridDB is no longer the only source: a local file becomes the
    logo through the same staged path, and the choice comes out locked."""
    from PIL import Image
    from cartridges.details_dialog import DetailsDialog
    from cartridges.game import Game
    from cartridges.utils.game_logo import cached_logo_path, logo_choice

    game = Game(
        {
            "game_id": "imported_9",
            "name": "Probe",
            "source": "imported",
            "executable": "x.exe",
            "added": 0,
        }
    )
    source = app_dirs.covers / "logo-fonte.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (400, 120), (255, 0, 0, 255)).save(source)

    dialog = DetailsDialog(game)
    dialog.set_logo_from_path(source)
    assert dialog.logo_row.get_subtitle() == "Escolhido manualmente"
    assert dialog.logo_button_reset.get_visible() is True

    assert dialog.apply_logo_choice(game) is True
    assert logo_choice(game) == "manual"
    assert cached_logo_path(game) is not None


# ---------------------------------------------------------------------------
# The library grid slides instead of jumping
# ---------------------------------------------------------------------------


def stage_layout(grid, positions, columns):
    """Leave the grid as a finished allocation would have left it."""
    grid._targets = {
        child: (x, y, 100, 150) for child, (x, y) in positions.items()
    }
    grid._positions = dict(positions)
    grid._columns = columns


def sized(positions):
    """The same mapping in the shape `_reflowed` reads."""
    return {child: (x, y, 100, 150) for child, (x, y) in positions.items()}


def covers(count):
    return [Gtk.FlowBoxChild() for _ in range(count)]


def test_the_library_grids_are_the_sliding_kind(real_window):
    """The template asks for a type GTK only knows because we registered it.

    `$AnimatedFlowBox` in the blueprint is resolved by name at build time, so a
    missing import in `window.py` does not fail the build — it fails when the
    window is constructed, which is every launch.
    """
    assert isinstance(real_window.library, AnimatedFlowBox)
    assert isinstance(real_window.zerados_library, AnimatedFlowBox)


def test_a_new_column_count_slides_the_covers():
    """Resizing the window until another column fits is the whole point."""
    grid = AnimatedFlowBox()
    first, second, third = covers(3)
    stage_layout(
        grid, {first: (0, 0), second: (112, 0), third: (0, 162)}, columns=2
    )

    assert (
        grid._reflowed(
            sized({first: (0, 0), second: (112, 0), third: (224, 0)}), 3
        )
        is True
    )


def test_the_grid_recentring_under_the_cursor_does_not_slide():
    """Dragging the window edge must stay glued to the cursor.

    The grid re-centres itself as the window grows, which shifts every cover
    sideways on every frame without any reflow. Treating that as movement
    would restart the spring each frame from the position it had just reached,
    and the covers would sit still instead of following the drag.
    """
    grid = AnimatedFlowBox()
    first, second = covers(2)
    stage_layout(grid, {first: (40, 0), second: (152, 0)}, columns=2)

    assert grid._reflowed(sized({first: (68, 0), second: (180, 0)}), 2) is False


def test_a_cover_changing_row_slides():
    """Re-sorting moves covers between rows without touching the columns."""
    grid = AnimatedFlowBox()
    first, second, third = covers(3)
    stage_layout(
        grid, {first: (0, 0), second: (112, 0), third: (0, 162)}, columns=2
    )

    assert (
        grid._reflowed(
            sized({first: (0, 162), second: (112, 0), third: (0, 0)}), 2
        )
        is True
    )


def test_a_grid_that_gained_a_cover_jumps():
    """A cover that was nowhere a frame ago cannot slide in from anywhere.

    Importing, un-hiding and searching all change which covers exist. Sliding
    the survivors from wherever the old layout had them reads as a glitch, not
    as movement, so the grid is left to jump the way it always did.
    """
    grid = AnimatedFlowBox()
    first, second, third = covers(3)
    stage_layout(grid, {first: (0, 0), second: (112, 0)}, columns=2)

    assert (
        grid._reflowed(
            sized({first: (0, 0), second: (112, 0), third: (0, 162)}), 2
        )
        is False
    )


def test_the_first_layout_has_nowhere_to_slide_from():
    """Nothing has been drawn yet, so there is no journey to animate."""
    grid = AnimatedFlowBox()
    first, second = covers(2)

    assert grid._reflowed(sized({first: (0, 0), second: (112, 0)}), 2) is False


def test_a_filtered_cover_leaves_the_grid_signature():
    """Searching has to invalidate the positions cached from last frame.

    Reusing them is only safe while the grid is provably unchanged, and that
    proof is this walk. A filtered cover is not allocated, so counting it would
    both keep a stale position alive and throw off the column count.
    """
    grid = AnimatedFlowBox()
    for _ in range(4):
        grid.append(Gtk.Label())

    assert len(grid._visible_children()) == 4

    grid.set_filter_func(lambda child: child.get_index() % 2 == 0)

    assert len(grid._visible_children()) == 2


def allocated(grid, width):
    """One real allocation pass at ``width``, exactly as GTK would run it."""
    grid.allocate(width, 2000, -1, None)


def sized_covers(count):
    """Fixed-size stand-ins for covers, so column arithmetic is predictable."""
    children = []
    for _ in range(count):
        child = Gtk.FlowBoxChild()
        box = Gtk.Box()
        box.set_size_request(100, 150)
        child.set_child(box)
        children.append(child)
    return children


def sliding_grid(covers_count):
    grid = AnimatedFlowBox(homogeneous=True)
    for child in sized_covers(covers_count):
        grid.append(child)
    return grid


# The widths bracket the theme's cell padding: they pick the intended column
# count for any cell between 100 and 116px wide, so a small CSS change does
# not silently turn these into tests of Adwaita's padding.
TWO_COLUMNS_WIDE = 239
FOUR_COLUMNS_WIDE = 467


def test_a_real_allocation_snaps_when_the_animation_is_skipped():
    """The whole do_size_allocate path, driven for real.

    An unmapped widget skips Adw animations — play() jumps straight to the end
    value — so the pass is deterministic: after a genuine reflow the covers
    must be snapped onto the layout the chain-up produced, with none of the
    spring's bookkeeping left behind.
    """
    grid = sliding_grid(4)

    allocated(grid, TWO_COLUMNS_WIDE)
    assert grid._columns == 2
    first_positions = dict(grid._positions)
    assert len(first_positions) == 4

    allocated(grid, FOUR_COLUMNS_WIDE)
    assert grid._columns == 4
    assert grid._progress == 1.0
    assert grid._origins == {}
    assert grid._positions == {
        child: target[:2] for child, target in grid._targets.items()
    }
    assert grid._positions != first_positions


# ---------------------------------------------------------------------------
# The "Filtrar por" menu
# ---------------------------------------------------------------------------


def menu_labels(menu):
    """The labels of a Gio.Menu, in order."""
    from gi.repository import GLib

    return [
        menu.get_item_attribute_value(i, "label", GLib.VariantType("s")).get_string()
        for i in range(menu.get_n_items())
    ]


def filter_submenu(window, index):
    """0 = Gêneros, 1 = Ano de lançamento, 2 = Status."""
    return window._filter_menu.get_item_link(index, "submenu")


def library_game(store, number, **fields):
    from cartridges.game import Game

    game = Game(
        {
            "source": "shortcuts",
            "game_id": f"shortcuts_f{number}",
            "name": f"Game {number}",
            "executable": "x",
            "added": 0,
            **fields,
        }
    )
    store.source_games.setdefault("shortcuts", {})[game.game_id] = game
    store.games_by_id[game.game_id] = game
    return game


def test_the_menu_offers_only_what_the_library_holds(real_window, store):
    """Dynamic content: genres alphabetical (accents included), years newest
    first, and only values some game actually carries."""
    library_game(store, 1, genre="Metroidvania", release_date="Fev 2017")
    library_game(store, 2, genre="Ação", release_date="2024")
    library_game(store, 3, genre="Aventura")
    library_game(store, 4)  # sem gênero e sem data: não acrescenta opção

    real_window.rebuild_filter_menu()

    # "Ação" antes de "Aventura": a ordenação não pode exilar os acentos.
    assert menu_labels(filter_submenu(real_window, 0)) == [
        "Todos",
        "Ação",
        "Aventura",
        "Metroidvania",
    ]
    assert menu_labels(filter_submenu(real_window, 1)) == ["Todos", "2024", "2017"]


def test_a_removed_games_values_leave_the_menu(real_window, store):
    """A tombstone must not keep its genre alive as an option."""
    game = library_game(store, 1, genre="Corrida", release_date="2020")
    game.removed = True

    real_window.rebuild_filter_menu()

    assert menu_labels(filter_submenu(real_window, 0)) == ["Todos"]
    assert menu_labels(filter_submenu(real_window, 1)) == ["Todos"]


def test_a_zerados_values_stay_in_the_menu(real_window, store):
    """A página Jogos Zerados usa o mesmo menu: o gênero de um zerado fica."""
    game = library_game(store, 1, genre="Corrida", release_date="2020")
    game.removed = True
    game.status = "beaten"

    real_window.rebuild_filter_menu()

    assert menu_labels(filter_submenu(real_window, 0)) == ["Todos", "Corrida"]
    assert menu_labels(filter_submenu(real_window, 1)) == ["Todos", "2020"]


def test_the_genre_filter_hides_what_does_not_match(real_window, store):
    """The filter reads the game, not the search box."""
    real_window.search_entry.set_text("")

    matching = library_game(store, 1, genre="Metroidvania")
    other = library_game(store, 2, genre="Ação")
    missing = library_game(store, 3)
    add_game_to(real_window, matching)
    add_game_to(real_window, other)
    add_game_to(real_window, missing)

    real_window.set_filter("filter_genre", "Metroidvania")

    assert real_window.filter_func(matching.get_parent()) is True
    assert real_window.filter_func(other.get_parent()) is False
    # Sem gênero não é um gênero: o jogo só aparece em "Todos".
    assert real_window.filter_func(missing.get_parent()) is False

    real_window.set_filter("filter_genre", "")
    assert real_window.filter_func(other.get_parent()) is True


def test_the_search_looks_inside_the_notes(real_window, store):
    """Quem escreveu "senha do cofre: 8815" há seis meses lembra da palavra, e
    não de qual jogo era — a mesma razão de a busca já olhar a desenvolvedora."""
    game = library_game(store, 1, notes="Parei no capítulo 4.\nCofre: 8815")
    other = library_game(store, 2)
    for each in (game, other):
        add_game_to(real_window, each)

    real_window.search_entry.set_text("cofre")
    assert real_window.filter_func(game.get_parent()) is True
    assert real_window.filter_func(other.get_parent()) is False

    real_window.search_entry.set_text("")


def test_filters_and_search_combine(real_window, store):
    """Both must agree for a game to show."""
    game = library_game(store, 1, genre="Ação", release_date="2024")
    add_game_to(real_window, game)

    real_window.set_filter("filter_genre", "Ação")
    real_window.set_filter("filter_year", "2024")
    real_window.search_entry.set_text("game")
    assert real_window.filter_func(game.get_parent()) is True

    real_window.search_entry.set_text("zelda")
    assert real_window.filter_func(game.get_parent()) is False

    real_window.search_entry.set_text("")
    real_window.set_filter("filter_year", "2023")
    assert real_window.filter_func(game.get_parent()) is False


# Gênero, ano e status: os três submenus fixos do "Filtrar por". "Limpar"
# entra como um quarto item, e é a sua presença que os testes abaixo contam.
FILTER_SUBMENUS = 3


def test_clear_appears_only_while_a_filter_is_active(real_window, store):
    """One click undoes every filter — but only offered when there is
    something to undo, so the page stays clean the rest of the time."""
    library_game(store, 1, genre="Ação", release_date="2024")

    real_window.rebuild_filter_menu()
    assert (
        real_window._filter_menu.get_n_items() == FILTER_SUBMENUS
    ), "nothing to clear yet"

    real_window.set_filter("filter_genre", "Ação")
    real_window.rebuild_filter_menu()
    assert real_window._filter_menu.get_n_items() == FILTER_SUBMENUS + 1

    real_window.set_filter("filter_year", "2024")
    real_window.set_filter("filter_status", "beaten")
    real_window.lookup_action("clear_filters").activate(None)

    assert real_window.filter_genre_state == ""
    assert real_window.filter_year_state == ""
    assert real_window.filter_status_state == ""
    real_window.rebuild_filter_menu()
    assert real_window._filter_menu.get_n_items() == FILTER_SUBMENUS

    # Só o status basta para o "Limpar" aparecer: os três filtros são um só
    # botão, e o menu que esquecesse um deixaria como única saída entrar na
    # lista e marcar "Todos" à mão.
    real_window.set_filter("filter_status", "playing")
    real_window.rebuild_filter_menu()
    assert real_window._filter_menu.get_n_items() == FILTER_SUBMENUS + 1
    real_window.set_filter("filter_status", "")


def test_a_vanished_selection_resets_to_all(real_window, store):
    """Removing the last game of the chosen genre must not strand the grid
    empty behind an option the menu no longer offers."""
    game = library_game(store, 1, genre="Corrida", release_date="2020")

    real_window.rebuild_filter_menu()
    real_window.set_filter("filter_genre", "Corrida")
    real_window.set_filter("filter_year", "2020")

    game.removed = True
    real_window.rebuild_filter_menu()

    assert real_window.filter_genre_state == ""
    assert real_window.filter_year_state == ""


def test_an_unchanged_allocation_reuses_the_cached_layout():
    """The signature cache is what keeps an idle re-allocation at 0.3ms.

    Scrolling re-allocates the grid every frame at the same size; each of
    those passes must reuse the cached layout instead of asking every cover
    where it is. A pass at a new size must still read it fresh.
    """
    grid = sliding_grid(4)
    allocated(grid, TWO_COLUMNS_WIDE)

    reads = []
    original = grid._read_layout
    grid._read_layout = lambda children: reads.append(1) or original(children)

    allocated(grid, TWO_COLUMNS_WIDE)
    assert reads == []

    allocated(grid, FOUR_COLUMNS_WIDE)
    assert reads == [1]


# ---------------------------------------------------------------------------
# The dimmed area around a dialog does not drag the window
# ---------------------------------------------------------------------------


def capture_clicks(widget):
    """The capture-phase click gestures installed on `widget`."""
    controllers = widget.observe_controllers()
    return [
        controller
        for i in range(controllers.get_n_items())
        if isinstance(controller := controllers.get_item(i), Gtk.GestureClick)
        and controller.get_propagation_phase() == Gtk.PropagationPhase.CAPTURE
    ]


def backdrop_of(dialog):
    """libadwaita's dimming layer: the one window handle holding nothing."""
    pending = [dialog]
    while pending:
        widget = pending.pop()
        if isinstance(widget, Gtk.WindowHandle) and widget.get_child() is None:
            return widget
        child = widget.get_first_child()
        while child is not None:
            pending.append(child)
            child = child.get_next_sibling()
    return None


def test_a_presented_dialog_gets_the_backdrop_guard(real_window, details_dialog):
    """Every dialog goes through `visible-dialog`, so one handler covers them all.

    libadwaita builds the dimmed area around a floating dialog out of a
    GtkWindowHandle, which drags the whole window — most of the screen behaving
    like a title bar for as long as a dialog is open.
    """
    details_dialog.present(real_window)

    assert real_window.get_visible_dialog() is details_dialog
    assert len(capture_clicks(details_dialog)) == 1


def test_the_guard_is_installed_once(real_window, details_dialog):
    """A dialog becomes visible again whenever one stacked over it closes."""
    details_dialog.present(real_window)
    real_window.block_dialog_backdrop_drag()
    real_window.block_dialog_backdrop_drag()

    assert len(capture_clicks(details_dialog)) == 1


def test_the_backdrop_is_the_only_empty_window_handle(real_window, details_dialog):
    """What the guard recognises the backdrop by, pinned.

    It claims a press when the widget under it is a window handle with no child.
    Every other handle in a dialog wraps a header bar's box, so this is what
    keeps a press on the dialog's own title bar moving the window, as it should.
    Should libadwaita build the dimming out of something else, this fails here
    rather than silently going back to a window that follows any drag.
    """
    details_dialog.present(real_window)

    assert backdrop_of(details_dialog) is not None


# ---------------------------------------------------------------------------
# Status e nota pessoal
# ---------------------------------------------------------------------------


def test_the_status_menu_offers_every_status_whatever_the_library_holds(
    real_window, store
):
    """Fixa, ao contrário de gêneros e anos: perguntar "o que eu zerei?" tem de
    ser possível numa biblioteca em que nada foi zerado ainda — a resposta
    "nenhum" é informação, e um menu que esconde a opção não a dá."""
    library_game(store, 1)

    real_window.rebuild_filter_menu()

    assert menu_labels(filter_submenu(real_window, 2)) == [
        "Todos",
        "Quero jogar",
        "Jogando",
        "Zerado",
        "Abandonado",
    ]


def test_the_status_filter_hides_what_does_not_match(real_window, store):
    real_window.search_entry.set_text("")

    beaten = library_game(store, 1, status="beaten")
    playing = library_game(store, 2, status="playing")
    none = library_game(store, 3)
    for game in (beaten, playing, none):
        add_game_to(real_window, game)

    real_window.set_filter("filter_status", "beaten")

    assert real_window.filter_func(beaten.get_parent()) is True
    assert real_window.filter_func(playing.get_parent()) is False
    # Sem status não é um status: o jogo só aparece em "Todos".
    assert real_window.filter_func(none.get_parent()) is False

    real_window.set_filter("filter_status", "")
    assert real_window.filter_func(playing.get_parent()) is True


def test_setting_a_status_saves_it_and_relabels_the_button(real_window, store):
    game = library_game(store, 1)
    real_window.active_game = game

    real_window.lookup_action("set_status").activate(GLib.Variant("s", "beaten"))

    assert game.status == "beaten"
    assert real_window.details_view_status_button.get_label() == "Zerado"

    real_window.lookup_action("set_status").activate(GLib.Variant("s", ""))

    assert game.status == ""
    assert real_window.details_view_status_button.get_label() == "Definir status"


def test_the_notes_button_follows_the_status_or_the_note(real_window, store):
    """O botão aparece em "Jogando", que é onde a pergunta tem resposta — e em
    qualquer jogo que já tenha anotação, porque este é o único lugar onde ela
    se edita: sem o botão, um texto escrito lá atrás ficaria preso na tela."""
    game = library_game(store, 1, status="playing")
    real_window.active_game = game

    real_window.update_notes_block(game)
    assert real_window.details_view_notes_button.get_visible() is True
    assert real_window.details_view_notes_box.get_visible() is False

    real_window.lookup_action("set_status").activate(GLib.Variant("s", "beaten"))
    assert real_window.details_view_notes_button.get_visible() is False

    game.notes = "Cofre: 8815"
    real_window.update_notes_block(game)

    # Zerado, mas com anotação: o texto à mostra e o botão junto dele.
    assert real_window.details_view_notes_button.get_visible() is True
    assert real_window.details_view_notes_box.get_visible() is True
    assert real_window.details_view_notes.get_label() == "Cofre: 8815"


def test_a_note_written_during_a_session_goes_to_the_game_being_played(
    real_window, store
):
    """A tela de detalhes por trás do bloqueador pode ter ficado em qualquer
    jogo — dar play num e estar com a tela de outro aberta é possível. Quem
    manda ali é o jogo da sessão, que é o que o bloqueador anuncia."""
    played = library_game(store, 1, status="playing")
    other = library_game(store, 2, notes="nada a ver com isto")
    real_window.active_game = other
    real_window.show_session_blocker(played)

    opening = SimpleNamespace(get_visible=lambda: True)
    closing = SimpleNamespace(get_visible=lambda: False)
    real_window.on_session_notes_popover_toggled(opening, None)
    real_window.session_blocker_notes_view.get_buffer().set_text(
        "Parei na missão do trem"
    )
    real_window.on_session_notes_popover_toggled(closing, None)

    assert played.notes == "Parei na missão do trem"
    assert other.notes == "nada a ver com isto"

    real_window.hide_session_blocker()
    assert real_window.session_game is None


def test_closing_the_notes_popover_saves_the_text(real_window, store):
    """O balão grava ao fechar, com o mesmo tratamento de espaços da tela de
    edição — uma caixa em que só se apertou Enter conta como vazia.

    O balão é aberto e fechado pelo handler, e não por `popup()`: a janela dos
    testes é realizada mas nunca apresentada, e mapear um popover nela derruba
    o GTK no Windows.
    """
    game = library_game(store, 1, status="playing")
    real_window.active_game = game
    opening = SimpleNamespace(get_visible=lambda: True)
    closing = SimpleNamespace(get_visible=lambda: False)
    buffer = real_window.details_view_notes_view.get_buffer()

    real_window.on_notes_popover_toggled(opening, None)
    assert buffer.get_char_count() == 0

    buffer.set_text("\n  Parei no capítulo 4.\nCofre: 8815  \n")
    real_window.on_notes_popover_toggled(closing, None)

    assert game.notes == "Parei no capítulo 4.\nCofre: 8815"
    assert real_window.details_view_notes.get_label() == (
        "Parei no capítulo 4.\nCofre: 8815"
    )

    real_window.on_notes_popover_toggled(opening, None)
    buffer.set_text("\n\n")
    real_window.on_notes_popover_toggled(closing, None)

    assert game.notes == ""
    assert real_window.details_view_notes_box.get_visible() is False


def test_a_hand_edited_status_reads_as_none(real_window, store):
    """O registro é um arquivo editável: um valor que ninguém reconhece não
    pode derrubar a tela nem se passar por um status."""
    game = library_game(store, 1, status="banana")
    real_window.active_game = game

    real_window.update_status_button(game)

    assert real_window.details_view_status_button.get_label() == "Definir status"


def test_the_stars_clamp_a_hand_edited_rating(store):
    """Tudo que desenha estrelas passa por `stars`, então é aqui que um valor
    absurdo tem de morrer — e não num IndexError lá na frente."""
    assert library_game(store, 1, rating=3).stars == 3
    assert library_game(store, 2, rating=9).stars == 5
    assert library_game(store, 3, rating=-1).stars == 0
    assert library_game(store, 4, rating="ótimo").stars == 0
    assert library_game(store, 5).stars == 0


def test_sorting_by_rating_puts_the_unrated_last(real_window, store):
    """0 é ausência de nota, não nota zero: um jogo que ninguém avaliou não
    pode aparecer abaixo do que se achou ruim."""
    five = library_game(store, 1, rating=5)
    two = library_game(store, 2, rating=2)
    unrated = library_game(store, 3)
    for game in (five, two, unrated):
        add_game_to(real_window, game)

    real_window.sort_state = "rating"
    order = real_window.sort_func

    assert order(five.get_parent(), two.get_parent()) == -1
    assert order(two.get_parent(), five.get_parent()) == 1
    assert order(two.get_parent(), unrated.get_parent()) == -1
    assert order(unrated.get_parent(), two.get_parent()) == 1


def test_ties_on_rating_fall_back_to_the_title(real_window, store):
    """Sem critério de desempate a grade trocaria os dois de lugar a cada
    reordenação, que é o que já aconteceu com títulos iguais."""
    first = library_game(store, 1, rating=4)
    second = library_game(store, 2, rating=4)
    add_game_to(real_window, first)
    add_game_to(real_window, second)

    real_window.sort_state = "rating"

    assert real_window.sort_func(first.get_parent(), second.get_parent()) == -1
    assert real_window.sort_func(second.get_parent(), first.get_parent()) == 1


def test_sorting_by_size_puts_the_unmeasured_last(real_window, store):
    """Zero é "não medido", não "não ocupa nada".

    A varredura leva um tempo até passar pela biblioteca inteira, então esta
    ordenação convive com jogos sem tamanho o tempo todo — e a pergunta que ela
    responde é "o que ocupa mais", que um jogo sem tamanho conhecido não tem
    como disputar.
    """
    big = library_game(store, 1, install_size=90 * 1024**3)
    small = library_game(store, 2, install_size=3 * 1024**3)
    unmeasured = library_game(store, 3)
    for game in (big, small, unmeasured):
        add_game_to(real_window, game)

    real_window.sort_state = "install_size"
    order = real_window.sort_func

    assert order(big.get_parent(), small.get_parent()) == -1
    assert order(small.get_parent(), big.get_parent()) == 1
    assert order(small.get_parent(), unmeasured.get_parent()) == -1
    assert order(unmeasured.get_parent(), small.get_parent()) == 1


def test_the_details_page_hides_the_size_until_it_is_known(real_window, store):
    """Um jogo ainda não medido fica sem a linha, e não com um "0 B"."""
    measured = library_game(store, 1, install_size=int(1024**3 * 87.42))
    unmeasured = library_game(store, 2)

    real_window.update_install_size_label(measured)
    assert real_window.details_view_size.get_visible()
    assert real_window.details_view_size.get_label() == "Tamanho: 87,4 GB"

    real_window.update_install_size_label(unmeasured)
    assert not real_window.details_view_size.get_visible()


def test_clicking_the_marked_star_takes_the_rating_away(real_window, store):
    """Sem isso, uma estrela viraria o piso e "sem nota" seria irrecuperável."""
    from cartridges.details_dialog import DetailsDialog

    _stub_sgdb(store)
    game = _probe_game()
    dialog = DetailsDialog(game)
    assert dialog._rating == 4  # vem de PERSISTED_METADATA

    dialog.on_star_clicked(None, 2)
    assert dialog._rating == 2
    dialog.on_star_clicked(None, 2)
    assert dialog._rating == 0

    dialog.apply_preferences()
    assert game.rating == 0


def test_the_status_row_round_trips_through_the_dialog(real_window, store):
    from cartridges.details_dialog import DetailsDialog

    _stub_sgdb(store)
    game = _probe_game()

    dialog = DetailsDialog(game)
    assert dialog.get_status() == "beaten"

    dialog.set_status("playing")
    dialog.apply_preferences()
    assert game.status == "playing"

    dialog = DetailsDialog(game)
    dialog.set_status("")
    dialog.apply_preferences()
    assert game.status == ""


# ---------------------------------------------------------------------------
# Auditoria 26/08 — regressões
# ---------------------------------------------------------------------------


def test_a_negative_coordinate_is_usable():
    """Um monitor real em coordenada negativa vale como posição gravada."""
    assert window_geometry.Geometry(-476, 100, 800, 600, False).usable


def test_a_minimized_window_is_not_read(monkeypatch):
    """A1: fechar pela taskbar com a janela minimizada (o estado normal
    enquanto um jogo roda) gravava o retângulo icônico como geometria."""

    class FakeUser32:
        @staticmethod
        def IsIconic(_hwnd):
            return 1

        @staticmethod
        def GetWindowRect(*_args):
            raise AssertionError("não se pergunta o rect de uma janela icônica")

    monkeypatch.setattr(window_geometry, "_user32", FakeUser32())
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _window: 42)

    assert window_geometry.read(object()) is None


class _FakePlacementUser32:
    """O bastante do user32 para o vaivém da janela entre monitores.

    Guarda cada `SetWindowPlacement` recebido, que é o que o teste tem para
    olhar: é a única coisa que a mudança de monitor faz com a janela.
    """

    def __init__(self, rect=(100, 50, 900, 650), show=1):
        self.rect = rect
        self.show = show  # SW_SHOWNORMAL, ou 3 para uma janela maximizada
        self.written: list = []

    @staticmethod
    def IsIconic(_hwnd):
        return 0

    def GetWindowRect(self, _hwnd, ref):
        (
            ref._obj.left,
            ref._obj.top,
            ref._obj.right,
            ref._obj.bottom,
        ) = self.rect
        return 1

    def GetWindowPlacement(self, _hwnd, ref):
        ref._obj.showCmd = self.show
        (
            ref._obj.rcNormalPosition.left,
            ref._obj.rcNormalPosition.top,
            ref._obj.rcNormalPosition.right,
            ref._obj.rcNormalPosition.bottom,
        ) = self.rect
        return 1

    def SetWindowPlacement(self, _hwnd, ref):
        rect = ref._obj.rcNormalPosition
        self.written.append(
            (ref._obj.showCmd, (rect.left, rect.top, rect.right, rect.bottom))
        )
        return 1


class _FakeWindow:
    def __init__(self, maximized=False):
        self.maximized = maximized

    def is_maximized(self):
        return self.maximized


def _no_session(monkeypatch):
    """Zera o estado de módulo, e devolve-o intacto ao fim do teste."""
    monkeypatch.setattr(window_geometry, "_before_session", None)
    monkeypatch.setattr(window_geometry, "_before_placement", None)


def test_the_window_never_moves_to_a_monitor_that_is_not_there(monkeypatch):
    """O monitor escolhido foi desligado: a janela fica onde está.

    Mandá-la para coordenadas de uma tela que não existe é perdê-la — e é por
    isso que o falso aqui é a resposta que faz quem chamou minimizar, como o
    app fazia antes desta opção existir.
    """
    _no_session(monkeypatch)
    monkeypatch.setattr(window_geometry, "monitors", list)
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _window: 42)

    assert window_geometry.move_to_monitor(_FakeWindow(), "\\\\.\\DISPLAY2") is False
    assert window_geometry.session_geometry() is None


def test_the_window_never_moves_onto_the_primary_monitor(monkeypatch):
    """O principal é onde o jogo roda: maximizada ali, a janela o cobriria.

    O caso real é o palpite antigo das Preferências, que num computador com um
    monitor só gravava o próprio principal como destino.
    """
    _no_session(monkeypatch)
    user32 = _FakePlacementUser32()
    monkeypatch.setattr(window_geometry, "_user32", user32)
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _window: 42)
    monkeypatch.setattr(
        window_geometry,
        "monitors",
        lambda: [window_geometry.Monitor("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, True)],
    )

    assert window_geometry.move_to_monitor(_FakeWindow(), "\\\\.\\DISPLAY1") is False
    assert user32.written == []
    assert window_geometry.session_geometry() is None


def test_a_secondary_monitor_is_any_monitor_but_the_primary(monkeypatch):
    principal = window_geometry.Monitor("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, True)
    deitado = window_geometry.Monitor("\\\\.\\DISPLAY2", 1920, 0, 1920, 1080, False)

    monkeypatch.setattr(window_geometry, "monitors", lambda: [principal])
    assert window_geometry.has_secondary_monitor() is False

    monkeypatch.setattr(window_geometry, "monitors", lambda: [principal, deitado])
    assert window_geometry.has_secondary_monitor() is True

    # Enumeração que falhou: o lado seguro é "não há".
    monkeypatch.setattr(window_geometry, "monitors", list)
    assert window_geometry.has_secondary_monitor() is False


def test_the_session_move_puts_the_window_back_exactly(monkeypatch):
    """Ida e volta: maximiza no monitor escolhido, volta ao estado de origem.

    O `session_geometry` no meio é o que salva a posição lembrada: fechar o app
    com o jogo aberto tem de gravar de onde a janela saiu, não onde ela está
    estacionada.
    """
    _no_session(monkeypatch)
    user32 = _FakePlacementUser32()
    monkeypatch.setattr(window_geometry, "_user32", user32)
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _window: 42)
    monkeypatch.setattr(
        window_geometry,
        "monitors",
        lambda: [
            window_geometry.Monitor("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, True),
            window_geometry.Monitor("\\\\.\\DISPLAY2", -1080, -512, 1080, 1920, False),
        ],
    )
    window = _FakeWindow()

    assert window_geometry.move_to_monitor(window, "\\\\.\\DISPLAY2") is True
    # Primeiro pousa no monitor escolhido (SW_SHOWNORMAL) e só então maximiza
    # (SW_SHOWMAXIMIZED): pedir as duas coisas de uma vez não move janela
    # maximizada nenhuma, que é o que o teste seguinte guarda.
    parked = (-1080, -512, 0, 1408)
    assert user32.written == [(1, parked), (3, parked)]
    assert window_geometry.session_geometry() == window_geometry.Geometry(
        100, 50, 800, 600, False
    )

    window_geometry.restore_from_monitor(window)
    assert user32.written[-1] == (1, (100, 50, 900, 650))
    assert window_geometry.session_geometry() is None

    # Chamar de novo não mexe em janela nenhuma: a sessão já acabou.
    window_geometry.restore_from_monitor(window)
    assert len(user32.written) == 3


def test_a_maximized_window_comes_back_maximized_where_it_was(monkeypatch):
    """Maximizada antes do jogo, maximizada depois — no monitor de origem.

    O caso que uma escrita só não resolve em nenhuma das duas pontas: o Windows
    lê o retângulo de uma janela maximizada como "para onde restaurar" e segue
    maximizando-a sobre o monitor onde ela já está. Sem os dois passos, a ida
    dizia ter mudado sem ter mudado nada, e a volta deixava a janela no monitor
    do jogo para sempre.
    """
    _no_session(monkeypatch)
    user32 = _FakePlacementUser32(show=3)
    monkeypatch.setattr(window_geometry, "_user32", user32)
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _window: 42)
    monkeypatch.setattr(
        window_geometry,
        "monitors",
        lambda: [
            window_geometry.Monitor("\\\\.\\DISPLAY2", -1080, -512, 1080, 1920, False)
        ],
    )

    assert (
        window_geometry.move_to_monitor(_FakeWindow(maximized=True), "\\\\.\\DISPLAY2")
        is True
    )
    window_geometry.restore_from_monitor(_FakeWindow(maximized=True))

    home = (100, 50, 900, 650)
    parked = (-1080, -512, 0, 1408)
    assert user32.written == [(1, parked), (3, parked), (1, home), (3, home)]


def test_wrong_typed_numeric_fields_are_dropped_on_load():
    """B4: `"playtime": "5h"` num registro editado à mão passava e estourava
    TypeError na tela de detalhes e na ordenação. Cai o campo, não o jogo."""
    from cartridges.main import sanitize_game_fields

    data = {
        "name": "Probe",
        "playtime": "5h",
        "metacritic": "bom",
        "install_size": 1024,
        "hltb_main": None,
    }
    cleaned = sanitize_game_fields(data, "probe.json")

    assert "playtime" not in cleaned
    assert "metacritic" not in cleaned
    assert cleaned["install_size"] == 1024
    assert cleaned["hltb_main"] is None
    assert cleaned["name"] == "Probe"


def test_enter_cannot_apply_mid_fetch(real_window, store):
    """M2: entry-activated chamava apply_preferences direto, driblando o
    botão que begin_loading desabilita — salvava sem os dados em voo."""
    from cartridges.details_dialog import DetailsDialog

    _stub_sgdb(store)
    game = _probe_game()
    dialog = DetailsDialog(game)

    dialog.name.set_text("Nome Novo")
    dialog.begin_loading()
    dialog.apply_preferences()
    assert game.name == "Probe", "aplicar no meio do fetch tem que ser ignorado"

    dialog.end_loading()
    dialog.apply_preferences()
    assert game.name == "Nome Novo"


def test_switching_empty_notices_does_not_stack_them(real_window, monkeypatch):
    """M4: a transição direta 'Nenhum jogo' → 'Nenhum jogo encontrado'
    adicionava o aviso novo sem remover o antigo; os dois ficavam sobrepostos."""
    from cartridges import shared

    win = real_window

    monkeypatch.setattr(shared, "store", [])
    win.set_library_child()
    assert win.notice_empty.get_parent() is win.library_overlay

    filtered = SimpleNamespace(
        removed=False, blacklisted=False, filtered=True
    )
    monkeypatch.setattr(shared, "store", [filtered])
    win.set_library_child()

    assert win.notice_no_results.get_parent() is win.library_overlay
    assert win.notice_empty.get_parent() is None, "o aviso antigo tem que sair"

    # E a volta: some o filtro, some o aviso de busca.
    monkeypatch.setattr(shared, "store", [])
    win.set_library_child()
    assert win.notice_empty.get_parent() is win.library_overlay
    assert win.notice_no_results.get_parent() is None


def test_rotation_survives_a_crash_between_compress_and_unlink(tmp_path):
    """B10: a queda deixava `.log` e `.log.xz` no mesmo número; a próxima
    inicialização levantava na rotação, o dictConfig virava ValueError e a
    sessão rodava sem log nenhum — justamente a sessão depois de um crash."""
    import lzma as lzma_module

    path = tmp_path / "cartridges.log"
    path.write_text("sessão interrompida\n", encoding="utf-8")
    with lzma_module.open(tmp_path / "cartridges.log.xz", "wb") as file:
        file.write(b"metade comprimida")

    handler = SessionFileHandler(filename=path, backup_count=2)  # não pode levantar
    handler.close()


# ---------------------------------------------------------------------------
# A biblioteca no topo também precisa ser segurada
# ---------------------------------------------------------------------------


def test_restoring_the_top_of_the_library_still_suppresses_scroll_to_focus(
    real_window,
):
    """Zero é uma posição, não "nada para restaurar".

    Ao fechar a tela de edição o foco volta para a capa do jogo editado e o
    viewport rola até ela. Com a grade no topo, `restore_library_scroll` pulava
    a supressão porque o valor guardado era zero — que é exatamente o caso em
    que o salto só pode ser para baixo.
    """

    viewport = real_window.scrolledwindow.get_child()
    assert isinstance(viewport, Gtk.Viewport)

    real_window.scrolledwindow.get_vadjustment().set_value(0)
    real_window.store_library_scroll()
    real_window.restore_library_scroll()

    assert viewport.get_scroll_to_focus() is False


def test_the_manual_session_clock_survives_the_minute_flush(monkeypatch):
    """O relógio da sessão manual não volta a zero quando o minuto é gravado.

    `SessionWindow.flush` banca o tempo a cada minuto adiantando
    `session_start`. Um relógio que lê só `monotonic() - session_start` volta
    a 0:00:00 a cada gravação; ele tem de somar o que já foi gravado.
    """
    import types

    from cartridges import session_window, window
    from cartridges.process_session import ProcessSession
    from cartridges.session_window import SessionWindow

    agora = [1000.0]
    monkeypatch.setattr(session_window, "monotonic", lambda: agora[0])
    monkeypatch.setattr(window, "monotonic", lambda: agora[0])
    game = types.SimpleNamespace(playtime=0, save=lambda: None)
    ativa = types.SimpleNamespace(
        game=game,
        session_start=1000.0,
        session_seconds=0,
        MAX_GAP=SessionWindow.MAX_GAP,
        TICK_INTERVAL=SessionWindow.TICK_INTERVAL,
    )
    monkeypatch.setattr(ProcessSession, "active", None)
    monkeypatch.setattr(SessionWindow, "active", ativa)

    agora[0] = 1065.0
    SessionWindow.flush(ativa)  # o tick de um minuto
    agora[0] = 1070.0

    assert CartridgesWindow.session_elapsed(None) == 70
