# test_process_monitor.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deciding whether a game is running, and the cache that makes it affordable.

Two separable halves. The parsing half turns a launch command into a folder to
watch, and getting it wrong means crediting somebody else's process as this
game's playtime — which is why it refuses so much.

The cache half exists because this poll runs on the GTK main thread with a
Toolhelp snapshot held open, every two seconds, over every process on the
machine. Only one answer is ever cached: "this process carries no package
identity". A refusal to open a process is deliberately *not* cached, because
caching it turned one unlucky call into a permanent verdict, and a packaged game
that is never seen ends its session outright.

The Win32 calls themselves are not tested: they were read against the API
contract, and a test of them would be testing the stub, not Windows.
"""

import os

import pytest

from cartridges.utils import process_monitor as pm

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="process_monitor binds kernel32 at import"
)

# MSYS2's Python — the one the app actually ships on — reports os.name "nt" and
# uses ntpath, but with the separators swapped round: os.sep is "/" and
# os.altsep is "\\", the opposite of stock CPython on Windows. Anything that
# goes through normpath/realpath/join therefore comes back slash-separated,
# while every path Win32 reports (QueryFullProcessImageNameW, %SystemRoot%) is
# backslash-separated. Comparing the two as strings was the bug `_win32_path`
# in process_monitor now fixes; the tests below pin that fix in place (they
# were strict xfails until it landed). `_win32` spells out which side of the
# convention a value is on.
def _win32(path: str) -> str:
    """A path in the form Win32 hands it to us, whatever os.sep says today."""
    return path.replace("/", "\\")


# ---------------------------------------------------------------------------
# 4.1 - 4.2  Reading a folder out of a launch command
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command,expected_tail",
    [
        ('start "" "C:\\SteamLibrary\\Halo\\halo.exe"', "SteamLibrary\\Halo"),
        ('start "" C:\\SteamLibrary\\Halo\\halo.exe', "SteamLibrary\\Halo"),
        ("C:\\XboxGames\\Halo\\Content\\game.exe", "XboxGames\\Halo"),
    ],
)
def test_install_dir_is_read_from_the_command(command, expected_tail):
    """T4.1 Quoted and unquoted paths both resolve."""
    result = _win32(pm.install_dir_from_command(command))
    assert result.endswith(expected_tail)


@pytest.mark.parametrize(
    "command",
    [
        "",
        'start "" "steam://rungameid/440"',
        "explorer.exe shell:AppsFolder\\Pkg_h!App",
        "C:\\Program Files\\My Game\\game.exe",  # bare path with spaces
    ],
)
def test_commands_with_no_certain_folder_give_nothing(command):
    """T4.1 Being sure matters more than being clever.

    A bare path with spaces cannot be told apart from its trailing arguments,
    so it is refused rather than guessed at.
    """
    assert pm.install_dir_from_command(command) == ""


def test_the_last_executable_in_the_command_wins():
    """T4.2 The game's executable comes after any launcher argument."""
    command = (
        'start "" /D "C:\\Launcher" "C:\\Launcher\\run.exe" '
        '"C:\\SteamLibrary\\Halo\\halo.exe"'
    )
    assert _win32(pm.install_dir_from_command(command)).endswith("SteamLibrary\\Halo")


# ---------------------------------------------------------------------------
# 4.3 - 4.5  Climbing to the game's root
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directory,expected",
    [
        # Unreal: launched out of Binaries\Win64, rooted three levels up.
        (
            "C:\\SteamLibrary\\steamapps\\common\\MyGame\\Binaries\\Win64",
            "C:\\SteamLibrary\\steamapps\\common\\MyGame",
        ),
        # A launcher in a sibling subfolder of the game's root.
        (
            "D:\\XboxGames\\Poppy\\PlaytimeLauncher",
            "D:\\XboxGames\\Poppy",
        ),
        # Already at the root.
        ("D:\\XboxGames\\Halo", "D:\\XboxGames\\Halo"),
    ],
)
def test_game_root_climbs_to_the_folder_below_a_container(directory, expected):
    """T4.3"""
    assert _win32(pm._game_root(directory)) == expected


def test_game_root_gives_up_at_the_drive_root():
    """T4.4 A layout we do not recognise is better admitted than guessed."""
    assert pm._game_root("D:\\SomeGame\\Bin") == ""


def test_game_root_respects_the_walk_limit():
    """T4.5 A malformed path must not walk forever.

    No container anywhere in the path, and deeper than the walk allows, so the
    limit is what stops it rather than the drive root.
    """
    deep = "D:\\" + "\\".join(f"level{index}" for index in range(20))
    assert pm._game_root(deep) == ""


# ---------------------------------------------------------------------------
# 4.6 - 4.8  Refusing folders that are not one game
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "directory",
    [
        "",
        "D:\\",
        "C:\\Program Files",
        "D:\\XboxGames",
        "C:\\SteamLibrary\\steamapps\\common",
    ],
)
def test_unwatchable_directories(directory):
    """T4.6 Watching a container credits every other game's processes."""
    assert pm._is_watchable_dir(directory) is False


def test_windows_own_folder_is_never_watchable():
    """T4.6 The shell hosts that live there would count as playtime forever.

    `_is_watchable_dir` normalises its own argument, so it needs the separator
    fix in its own right — having `_game_root` hand it a Win32-shaped path is
    not enough, because `normpath` here puts the forward slashes straight back.
    """
    system_root = os.environ.get("SystemRoot", "C:\\Windows")
    assert pm._is_watchable_dir(f"{system_root}\\System32\\SomeGame") is False


def test_windows_own_folder_is_unwatchable_however_it_is_spelled():
    """The comparison must survive both conventions and either case."""
    system_root = os.environ.get("SystemRoot", "C:\\Windows")
    for spelling in (
        f"{system_root}\\System32\\SomeGame",
        f"{system_root}/System32/SomeGame".replace("\\", "/"),
        f"{system_root}\\System32\\SomeGame".upper(),
        f"{system_root}\\System32\\SomeGame".lower(),
    ):
        assert pm._is_watchable_dir(spelling) is False, spelling


def test_path_prefix_ends_on_a_boundary(tmp_path):
    """T4.7 (the property that does hold) The prefix ends at a separator.

    That trailing separator is what stops ".../Battlefield 1" from matching
    ".../Battlefield 11/game.exe" — the comparison has to land on a path
    boundary rather than in the middle of a folder name.
    """
    one = tmp_path / "Battlefield 1"
    eleven = tmp_path / "Battlefield 11"
    one.mkdir()
    eleven.mkdir()

    prefix = pm._as_path_prefix(str(one))

    assert prefix.endswith(("\\", "/"))
    assert not pm._as_path_prefix(str(eleven)).startswith(prefix)


def test_folder_matching_accepts_a_win32_process_path(tmp_path):
    """T4.7 The comparison is against what Win32 reports, not what we built.

    This is the one that was dead in production: `_as_path_prefix` normalised
    through realpath/join and came back slash-separated on MSYS2's Python, while
    `QueryFullProcessImageNameW` reports backslashes, so the `startswith` could
    never match and folder-based tracking never fired.
    """
    game_dir = tmp_path / "XboxGames" / "Halo"
    game_dir.mkdir(parents=True)
    prefix = pm._as_path_prefix(str(game_dir))
    reported = _win32(str(game_dir / "Content" / "halo.exe"))

    assert reported.casefold().startswith(prefix)


def test_folder_matching_survives_a_slash_separated_install_dir(tmp_path):
    """The stored folder may have been written by an interpreter of either kind.

    `install_dir` is persisted with the game, so a library written by one build
    and read by another has to keep matching.
    """
    game_dir = tmp_path / "XboxGames" / "Halo"
    game_dir.mkdir(parents=True)
    reported = _win32(str(game_dir / "halo.exe"))

    for spelling in (
        str(game_dir),
        str(game_dir).replace("\\", "/"),
        str(game_dir).upper(),
    ):
        prefix = pm._as_path_prefix(spelling)
        assert reported.casefold().startswith(prefix), spelling


def test_install_dir_is_read_from_a_slash_separated_command(tmp_path):
    """Latent until someone 'tidies' a path through pathlib.

    The regexes accepted only backslashes, which held only because
    `Gio.File.get_path()` happens to return them today.
    """
    assert (
        _win32(pm.install_dir_from_command('start "" "D:/XboxGames/Halo/halo.exe"'))
        == "D:\\XboxGames\\Halo"
    )
    assert (
        _win32(pm.install_dir_from_command("D:/XboxGames/Halo/halo.exe"))
        == "D:\\XboxGames\\Halo"
    )


@pytest.mark.parametrize(
    "configured,running,expected",
    [
        ("game", "game.exe", True),
        ("game.exe", "game", True),
        ("GAME.EXE", "game.exe", True),
        ("game", "othergame.exe", False),
    ],
)
def test_name_variants(configured, running, expected):
    """T4.8 The ".exe" suffix is optional on both sides."""
    assert pm._matches(running, pm._name_variants(configured)) is expected


# ---------------------------------------------------------------------------
# 4.9 - 4.13  The package cache
# ---------------------------------------------------------------------------


@pytest.fixture
def snapshot(monkeypatch):
    """Replace the Toolhelp walk with a scripted process list.

    Returns a controller whose ``processes`` the test sets per poll, and which
    records every pid the predicate actually asked the kernel about.
    """

    class Controller:
        def __init__(self):
            self.processes: list[tuple[int, str]] = []
            self.asked: list[int] = []
            self.answers: dict[int, object] = {}

        def run(self, predicate):
            for pid, name in self.processes:
                if predicate(pid, name):
                    return True
            return False

        def family(self, pid):
            self.asked.append(pid)
            return self.answers.get(pid)

    controller = Controller()
    monkeypatch.setattr(pm, "_any_process", controller.run)
    monkeypatch.setattr(pm, "_process_package_family", controller.family)
    monkeypatch.setattr(pm, "_package_family_cache", {})
    return controller


def test_a_no_package_answer_is_reused(snapshot):
    """T4.9 The common case is a machine full of unpackaged processes."""
    snapshot.processes = [(100, "notepad.exe")]
    snapshot.answers = {100: None}

    pm.is_package_running("some.package_hash")
    pm.is_package_running("some.package_hash")

    assert snapshot.asked == [100], "the second poll should not have asked again"


def test_a_refused_handle_is_never_cached(snapshot):
    """T4.10 Caching a refusal turned one unlucky call into a permanent verdict.

    A packaged game that is never seen ends its session outright, so the cost of
    being wrong here is the whole session.
    """
    snapshot.processes = [(100, "game.exe")]
    snapshot.answers = {100: pm._UNREADABLE}

    pm.is_package_running("some.package_hash")
    pm.is_package_running("some.package_hash")

    assert snapshot.asked == [100, 100], "a refusal must be retried"


def test_a_matching_package_is_re_established_every_poll(snapshot):
    """T4.9 (the other half) A match is what keeps a session counting.

    Only "no package" is taken from the cache; a process that did carry an
    identity is asked again, because a recycled pid running another title's
    GameLaunchHelper.exe would match on name while being a different game.
    """
    snapshot.processes = [(100, "gamelaunchhelper.exe")]
    snapshot.answers = {100: "some.package_hash"}

    assert pm.is_package_running("some.package_hash") is True
    assert pm.is_package_running("some.package_hash") is True
    assert snapshot.asked == [100, 100]


def test_a_pid_that_left_the_snapshot_is_evicted(snapshot):
    """T4.11 The cache is rebuilt from the walk, so it cannot hold a dead pid."""
    snapshot.processes = [(100, "notepad.exe")]
    snapshot.answers = {100: None}
    pm.is_package_running("some.package_hash")

    snapshot.processes = []  # the process exited
    pm.is_package_running("some.package_hash")

    assert 100 not in pm._package_family_cache


def test_a_recycled_pid_under_a_new_name_is_asked_again(snapshot):
    """T4.12 Windows hands a pid out again as soon as it is free."""
    snapshot.processes = [(100, "notepad.exe")]
    snapshot.answers = {100: None}
    pm.is_package_running("some.package_hash")

    snapshot.processes = [(100, "game.exe")]  # same pid, different program
    snapshot.answers = {100: "some.package_hash"}

    assert pm.is_package_running("some.package_hash") is True
    assert snapshot.asked == [100, 100]


def test_pseudo_pids_and_system_processes_are_skipped(snapshot):
    """T4.13 Never open a handle we already know the answer for."""
    snapshot.processes = [
        (0, "System Idle Process"),
        (4, "System"),
        (200, "RuntimeBroker.exe"),
        (201, "svchost.exe"),
    ]

    assert pm.is_package_running("some.package_hash") is False
    assert snapshot.asked == []


def test_an_empty_package_family_is_never_running():
    """A game with no package identity must not match every process."""
    assert pm.is_package_running("") is False
    assert pm.is_package_running("   ") is False


# ---------------------------------------------------------------------------
# 4.14  AUMID extraction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command,expected",
    [
        ("explorer.exe shell:AppsFolder\\Pkg_hash!App", "Pkg_hash!App"),
        # A .url shortcut imports quoted; the closing quote is not the AUMID.
        # It stayed invisible on the tracking side (which splits on "!") but the
        # raw value is what ShellExecuteEx gets for an elevated launch.
        ('start "" "shell:AppsFolder\\Pkg_hash!App"', "Pkg_hash!App"),
        ("explorer.exe shell:AppsFolder\\Pkg_hash!App  ", "Pkg_hash!App"),
        # A grouping id has no "!" and must still come back, or a game the
        # shell cannot launch would land in the manual session window.
        ("explorer.exe shell:AppsFolder\\XboxGames.Halo_Halo", "XboxGames.Halo_Halo"),
        ('start "" "C:\\Games\\halo.exe"', ""),
        ("", ""),
    ],
)
def test_aumid_from_command(command, expected):
    """T4.14 Also the "is this a Store game?" test, so "" has to mean no."""
    from cartridges.utils.run_executable import aumid_from_command

    assert aumid_from_command(command) == expected


def test_folder_matching_skips_system_names_without_opening_handles(
    snapshot, monkeypatch, tmp_path
):
    """Auditoria 26/08, M10: o pré-filtro por nome/pid — construído neste
    módulo depois do custo de "centenas de ms por poll" — agora vale também
    para a vigília por pasta, que pagava um OpenProcess por processo da
    máquina a cada 2 s na main thread."""
    asked = []
    monkeypatch.setattr(pm, "_process_path", lambda pid: asked.append(pid) or None)

    game_dir = tmp_path / "Jogos" / "Halo"
    game_dir.mkdir(parents=True)

    snapshot.processes = [
        (0, ""),
        (4, "System"),
        (200, "svchost.exe"),
        (300, "RuntimeBroker.exe"),
    ]
    assert pm.is_process_running_under(str(game_dir)) is False
    assert asked == []

    # E um processo comum continua sendo perguntado ao kernel.
    snapshot.processes = [(500, "game.exe")]
    pm.is_process_running_under(str(game_dir))
    assert asked == [500]
