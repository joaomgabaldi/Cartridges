# test_process_session.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The automatic play session: what counts as running, and what gets written.

Every test here drives ``_poll`` by hand against a controlled clock. Nothing
starts a real GLib timer, because the thing being tested is the state machine,
not GLib's ability to fire a callback.

The clock is monotonic on purpose and the tests reflect that: an NTP correction,
a manual clock change or a resume from sleep with a drifted RTC all move
``time()``, and a forward jump used to be credited to the game as playtime it
never had.
"""

import pytest

from cartridges import process_session as ps
from cartridges.process_session import ProcessSession

PACKAGED = "explorer.exe shell:AppsFolder\\Microsoft.Halo_8wekyb3d8bbwe!Game"
CLASSIC = 'start "" "D:\\SteamLibrary\\steamapps\\common\\Halo\\halo.exe"'


@pytest.fixture
def clock(monkeypatch):
    """A monotonic clock the test moves by hand."""

    class Clock:
        def __init__(self):
            self.now = 1000.0

        def __call__(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds

    instance = Clock()
    monkeypatch.setattr(ps, "monotonic", instance)
    return instance


@pytest.fixture
def running(monkeypatch):
    """Control all three answers ``_is_running`` can get."""

    class Answers:
        package = False
        name = False
        folder = False
        asked: list = []

    answers = Answers()
    answers.asked = []

    def package(family):
        answers.asked.append(("package", family))
        return answers.package

    def name(exe):
        answers.asked.append(("name", exe))
        return answers.name

    def folder(directory):
        answers.asked.append(("folder", directory))
        return answers.folder

    monkeypatch.setattr(ps, "is_package_running", package)
    monkeypatch.setattr(ps, "is_process_running", name)
    monkeypatch.setattr(ps, "is_process_running_under", folder)
    return answers


@pytest.fixture
def session_window(monkeypatch):
    """Capture the manual window instead of building a real one."""
    import cartridges.session_window as sw

    built: list = []

    class FakeSessionWindow:
        def __init__(self, game):
            built.append(game)

        def present(self):
            return None

    monkeypatch.setattr(sw, "SessionWindow", FakeSessionWindow)
    return built


@pytest.fixture(autouse=True)
def no_active_session():
    ProcessSession.active = None
    yield
    ProcessSession.active = None


def make_session(make_game, executable=PACKAGED, **overrides):
    game = make_game(executable=executable, **overrides)
    return ProcessSession(game)


# ---------------------------------------------------------------------------
# 5.1  What counts as running
# ---------------------------------------------------------------------------


def test_package_identity_alone_is_enough(make_game, running, clock):
    session = make_session(make_game)
    running.package = True

    assert session._is_running() is True


def test_a_configured_name_is_honoured_for_a_packaged_game(
    make_game, running, clock
):
    """T5.1 The regression: the package path used to return early.

    ``OpenProcess`` being refused comes back from the monitor as the same "no
    package" a plain unpackaged process does, so a package that says nothing is
    not evidence of a game that is not running. A user who went to the trouble
    of configuring a process name must get it honoured.
    """
    session = make_session(
        make_game, track_process=True, process_executable="halo.exe"
    )
    assert session.package_family, "precondition: this is a packaged game"
    running.package = False
    running.name = True

    assert session._is_running() is True


def test_the_install_folder_is_the_third_answer(make_game, running, clock):
    """T5.1"""
    session = make_session(make_game, executable=CLASSIC)
    assert session.install_dir, "precondition: the command names a folder"
    running.folder = True

    assert session._is_running() is True


def test_nothing_running_is_not_running(make_game, running, clock):
    session = make_session(
        make_game, track_process=True, process_executable="halo.exe"
    )
    assert session._is_running() is False


def test_a_name_the_user_turned_off_is_not_used(make_game, running, clock):
    """The field keeps its value while the switch is off; it must not be read."""
    session = make_session(
        make_game, track_process=False, process_executable="halo.exe"
    )
    assert session.exe_name == ""


# ---------------------------------------------------------------------------
# 5.2 - 5.3  Accumulating time
# ---------------------------------------------------------------------------


def test_sub_second_remainder_is_carried(make_game, running, clock):
    """T5.2 100 polls of 2.5 s are 250 s, not 200.

    Truncating every poll quietly lost time on a long session.
    """
    session = make_session(make_game)
    session.started = True
    session.counting = True
    session.last_tick = clock.now

    for _ in range(100):
        clock.advance(2.5)
        session._accumulate()

    assert session.session_seconds == 250
    assert session.game.playtime == 250


def test_a_wall_clock_jump_changes_nothing(make_game, running, clock, monkeypatch):
    """T5.3 The wall clock is never read; only the monotonic one is."""
    session = make_session(make_game)
    session.started = True
    session.counting = True
    session.last_tick = clock.now

    monkeypatch.setattr("time.time", lambda: 1_000_000_000.0)
    clock.advance(10)
    session._accumulate()

    monkeypatch.setattr("time.time", lambda: 0.0)
    clock.advance(10)
    session._accumulate()

    assert session.session_seconds == 20


def test_paused_time_is_not_counted(make_game, running, clock):
    """The grace wait after a process vanishes must never become playtime."""
    session = make_session(make_game)
    session.started = True
    session.counting = False
    session.last_tick = clock.now

    clock.advance(60)
    session._accumulate()

    assert session.session_seconds == 0


# ---------------------------------------------------------------------------
# 5.4 - 5.5  The process never appears
# ---------------------------------------------------------------------------


def test_a_packaged_game_that_never_appeared_records_nothing(
    make_game, running, clock, win, session_window
):
    """T5.4 "No process of this package" is the game not having started.

    Handing that to the manual window puts a counter on screen that runs until
    somebody closes it, and shutdown then writes hours the game never had.
    """
    session = make_session(make_game)
    session.poll_id = 0

    for _ in range(session.PACKAGE_STARTUP_GRACE // session.POLL_INTERVAL):
        session._poll()

    assert session.game.playtime == 0
    assert session.game.saves == 0
    assert session_window == [], "must not fall back to the manual window"
    assert len(win.toast_queue.added) == 1
    assert ProcessSession.active is None


def test_a_classic_game_that_never_appeared_falls_back_to_the_manual_window(
    make_game, running, clock, session_window
):
    """T5.5 Here "never seen" really can mean "lost track of it"."""
    session = make_session(make_game, executable=CLASSIC)
    session.poll_id = 0

    for _ in range(session.STARTUP_GRACE // session.POLL_INTERVAL):
        session._poll()

    assert len(session_window) == 1
    assert session_window[0] is session.game


def test_the_two_startup_graces_differ(make_game, running, clock):
    """A packaged game either shows a process within seconds or it failed."""
    packaged = make_session(make_game)
    classic = make_session(make_game, executable=CLASSIC)

    assert packaged.startup_grace == ProcessSession.PACKAGE_STARTUP_GRACE
    assert classic.startup_grace == ProcessSession.STARTUP_GRACE
    assert packaged.startup_grace < classic.startup_grace


# ---------------------------------------------------------------------------
# 5.6 - 5.7  The grace window
# ---------------------------------------------------------------------------


def test_a_game_that_relaunches_itself_keeps_its_session(
    make_game, running, clock, schema
):
    """T5.6 The session survives, and the wait is not counted.

    "Not counted" is precise about where the boundary sits. When a poll finds
    the process gone, the stretch since the previous poll — when it was still
    there — is banked: the game died at some unknown point inside that interval,
    and crediting the whole of it is the conservative end of a two-second
    uncertainty. What is dropped is everything after that, the whole grace wait,
    which is the part that would otherwise turn a relaunch into free playtime.
    """
    schema["process-tracking-grace"] = 30
    session = make_session(make_game)
    # `start()` is what normally publishes this; these tests drive `_poll`
    # directly, so it is set by hand to model a session already under way.
    ProcessSession.active = session
    running.package = True

    session._poll()  # seen: the clock starts
    clock.advance(10)
    session._poll()
    assert session.session_seconds == 10

    running.package = False  # swapped itself for another executable
    clock.advance(10)
    session._poll()
    clock.advance(10)
    session._poll()

    running.package = True  # back
    clock.advance(10)
    session._poll()
    clock.advance(5)
    session._poll()

    assert session.counting is True
    assert ProcessSession.active is not None
    # 45 s of wall time: 10 + 10 banked while it was (last seen) running, then
    # 20 s of absence dropped, then 5 s after it came back.
    assert session.session_seconds == 25
    assert session.session_seconds < (clock.now - 1000)


def test_a_game_gone_past_the_grace_ends_and_records(
    make_game, running, clock, schema, win
):
    """T5.7"""
    schema["process-tracking-grace"] = 5
    session = make_session(make_game)
    ProcessSession.active = session
    running.package = True

    session._poll()
    clock.advance(120)
    session._poll()
    assert session.session_seconds == 120

    running.package = False
    session._poll()
    clock.advance(10)
    session._poll()

    assert ProcessSession.active is None
    assert session.game.playtime == 120
    assert session.game.saves >= 1
    assert win.toast_queue.added


# ---------------------------------------------------------------------------
# 5.8 - 5.11  Teardown
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("packaged", [True, False])
def test_the_glib_source_is_removed_exactly_once(
    make_game, running, clock, monkeypatch, session_window, packaged
):
    """T5.8 Returning SOURCE_REMOVE already destroys the source.

    Both give-up paths zero ``poll_id`` before calling ``stop()``, or the source
    would be removed a second time.
    """
    removals: list = []
    monkeypatch.setattr(ps.GLib, "source_remove", lambda sid: removals.append(sid))

    session = make_session(
        make_game, executable=PACKAGED if packaged else CLASSIC
    )
    session.poll_id = 42

    result = None
    for _ in range(session.startup_grace // session.POLL_INTERVAL):
        result = session._poll()

    assert result == ps.GLib.SOURCE_REMOVE
    assert removals == [], "the source destroys itself by returning SOURCE_REMOVE"
    assert session.poll_id == 0


def test_stop_removes_a_live_source_once(make_game, running, clock, monkeypatch):
    """T5.8 (the other direction) Stopping early does have to remove it."""
    removals: list = []
    monkeypatch.setattr(ps.GLib, "source_remove", lambda sid: removals.append(sid))

    session = make_session(make_game)
    session.poll_id = 7
    session.stop(record=False)
    session.stop(record=False)

    assert removals == [7]


def test_flush_writes_the_current_stretch_and_touches_no_widget(
    make_game, running, clock, win
):
    """T5.9 Used on shutdown, when widgets may already be gone."""
    session = make_session(make_game)
    running.package = True
    session._poll()
    clock.advance(45)

    session.flush()

    assert session.game.playtime == 45
    assert session.game.saves == 1
    assert win.toast_queue.added == []
    assert win.presented == 0


def test_flush_before_the_game_was_ever_seen_writes_nothing(
    make_game, running, clock
):
    """T5.9 Nothing was counted, so nothing is persisted."""
    session = make_session(make_game)

    session.flush()

    assert session.game.saves == 0


def test_a_second_launch_ends_the_first_session_recording_it(
    make_game, running, clock, win
):
    """T5.10 Two trackers must never count at once."""
    first = make_session(make_game)
    ProcessSession.active = first
    running.package = True
    first._poll()
    clock.advance(60)

    # What Game.launch does before starting the next session.
    if ProcessSession.active is not None:
        ProcessSession.active.stop(record=True)

    assert ProcessSession.active is None
    assert first.game.playtime == 60
    assert first.game.saves >= 1


def test_the_session_toast_does_not_parse_the_title_as_markup(
    make_game, running, clock, win
):
    """T5.11 An "&" in a game's name makes Pango drop the label."""
    session = make_session(make_game, name="Sam & Max <Save the World>")
    running.package = True
    session._poll()
    clock.advance(30)

    session.stop(record=True)

    toast = win.toast_queue.added[-1]
    assert toast.get_use_markup() is False
    assert "Sam & Max <Save the World>" in toast.get_title()


def test_the_never_launched_toast_does_not_parse_the_title_as_markup(
    make_game, running, clock, win
):
    """T5.11 The same applies to the "did not start" notice."""
    session = make_session(make_game, name="Sam & Max")

    session.stop(record=False, never_launched=True)

    toast = win.toast_queue.added[-1]
    assert toast.get_use_markup() is False
    assert "Sam & Max" in toast.get_title()


def test_stopping_hides_the_session_blocker(make_game, running, clock, win):
    """The main window is blocked for the length of a session and no longer."""
    session = make_session(make_game)
    session.stop(record=False)

    assert None in win.session_blocker_shown
