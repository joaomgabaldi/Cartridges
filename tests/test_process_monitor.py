# test_process_monitor.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Deciding whether a game is running, and the cache that makes it affordable.
Parsing turns a launch command into a folder to watch; getting it wrong credits another process as this game's playtime, hence the many refusals.
The cache holds only "no package identity", never a refusal to open a process: caching that turned one unlucky call into a permanent verdict.
The Win32 calls themselves are not tested (a test would only exercise the stub)."""

import os

import pytest

from kyron.utils import process_monitor as pm

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="process_monitor binds kernel32 at import"
)

# MSYS2's Python (the one the app ships on) reports os.name "nt" and uses ntpath with the separators swapped:
# os.sep is "/" and os.altsep is "\\". Anything through normpath/realpath/join comes back slash-separated,
# while Win32 paths (QueryFullProcessImageNameW, %SystemRoot%) are backslash-separated.
# `_win32` spells out which side of the convention a value is on.
def _win32(path: str) -> str:
    """A path in the form Win32 hands it to us, whatever os.sep says today."""
    return path.replace("/", "\\")


# --- Reading a folder out of a launch command ---


@pytest.mark.parametrize(
    "command,expected_tail",
    [
        ('start "" "C:\\SteamLibrary\\Halo\\halo.exe"', "SteamLibrary\\Halo"),
        ('start "" C:\\SteamLibrary\\Halo\\halo.exe', "SteamLibrary\\Halo"),
        ("C:\\XboxGames\\Halo\\Content\\game.exe", "XboxGames\\Halo"),
    ],
)
def test_install_dir_is_read_from_the_command(command, expected_tail):
    """Quoted and unquoted paths both resolve."""
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
    """A bare path with spaces cannot be told from its trailing arguments, so it is refused rather than guessed."""
    assert pm.install_dir_from_command(command) == ""


def test_the_last_executable_in_the_command_wins():
    """The game's executable comes after any launcher argument."""
    command = (
        'start "" /D "C:\\Launcher" "C:\\Launcher\\run.exe" '
        '"C:\\SteamLibrary\\Halo\\halo.exe"'
    )
    assert _win32(pm.install_dir_from_command(command)).endswith("SteamLibrary\\Halo")


# --- Climbing to the game's root ---


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
    assert _win32(pm._game_root(directory)) == expected


@pytest.mark.parametrize(
    ("directory", "expected"),
    [
        ("C:/Program Files/Epic Games/GTAV", "C:/Program Files/Epic Games/GTAV"),
        ("C:/Program Files/EA Games/Battlefield 6/SP", "C:/Program Files/EA Games/Battlefield 6"),
        ("C:/Program Files (x86)/Rockstar Games/Red Dead Redemption 2", "C:/Program Files (x86)/Rockstar Games/Red Dead Redemption 2"),
        # Um jogo direto em Program Files continua na própria pasta.
        ("C:/Program Files (x86)/Steam", "C:/Program Files (x86)/Steam"),
        # Os contêineres de antes não mudam.
        ("C:/Program Files/Steam/steamapps/common/Halo/bin", "C:/Program Files/Steam/steamapps/common/Halo"),
    ],
)
def test_m7_pasta_de_editora_nao_e_pasta_de_jogo(directory, expected):
    """Epic Games, EA Games e Rockstar Games são pastas de editora, não de jogo."""
    assert _win32(pm._game_root(directory)) == _win32(expected)


def test_game_root_gives_up_at_the_drive_root():
    """A layout we do not recognise is better admitted than guessed."""
    assert pm._game_root("D:\\SomeGame\\Bin") == ""


def test_game_root_respects_the_walk_limit():
    """A malformed path must not walk forever: no container in the path and deeper than the walk allows, so the limit stops it, not the drive root."""
    deep = "D:\\" + "\\".join(f"level{index}" for index in range(20))
    assert pm._game_root(deep) == ""


@pytest.mark.parametrize(
    "marker,is_dir,expected",
    [
        # Inno Setup, the installer behind every repack: the folder is a game.
        ("unins000.exe", False, "Unreal Tournament III"),
        # EA app installs leave this behind at the game's root.
        ("__Installer", True, "Unreal Tournament III"),
        # No installer at the top: could be a publisher, so stay one level down.
        (None, False, "Unreal Tournament III\\Binaries"),
    ],
)
def test_game_root_in_program_files_trusts_an_uninstaller(
    tmp_path, marker, is_dir, expected
):
    """A game directly in Program Files with its exe in a subfolder (Unreal Tournament III launches ``Binaries\\UT3.exe``): measuring Binaries alone undercounts the install."""
    game = tmp_path / "Program Files" / "Unreal Tournament III"
    binaries = game / "Binaries"
    binaries.mkdir(parents=True)
    if marker and is_dir:
        (game / marker).mkdir()
    elif marker:
        (game / marker).write_bytes(b"")

    root = _win32(pm._game_root(str(binaries)))
    assert root == _win32(str(tmp_path / "Program Files" / expected))


@pytest.mark.parametrize("library", ["jogos", "jogos instalados", "Meus Jogos"])
def test_game_root_anywhere_is_found_by_its_uninstaller(tmp_path, library):
    """Games live wherever their owner put them: ``tmp_path`` sits under no container, like ``Y:\\jogos``."""
    game = tmp_path / library / "Unreal Tournament III"
    binaries = game / "Binaries"
    binaries.mkdir(parents=True)
    (game / "unins000.exe").write_bytes(b"")

    assert _win32(pm._game_root(str(binaries))) == _win32(str(game))


def test_game_root_anywhere_without_uninstaller_is_still_unknown(tmp_path):
    """A portable game outside any container: guessing the exe's folder would undercount the install."""
    binaries = tmp_path / "jogos" / "Portatil" / "Binaries" / "Win64"
    binaries.mkdir(parents=True)

    assert pm._game_root(str(binaries)) == ""


# --- Refusing folders that are not one game ---


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
    """Watching a container credits every other game's processes."""
    assert pm._is_watchable_dir(directory) is False


def test_windows_own_folder_is_never_watchable():
    """The shell hosts that live there would count as playtime forever. `_is_watchable_dir` normalises its own argument, so it needs the separator fix itself: `normpath` puts forward slashes back."""
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
    """The prefix ends at a separator, so ".../Battlefield 1" does not match ".../Battlefield 11/game.exe"."""
    one = tmp_path / "Battlefield 1"
    eleven = tmp_path / "Battlefield 11"
    one.mkdir()
    eleven.mkdir()

    prefix = pm._as_path_prefix(str(one))

    assert prefix.endswith(("\\", "/"))
    assert not pm._as_path_prefix(str(eleven)).startswith(prefix)


def test_folder_matching_accepts_a_win32_process_path(tmp_path):
    """The comparison is against what Win32 reports, not what we built: `_as_path_prefix` came back slash-separated on MSYS2's Python while `QueryFullProcessImageNameW` reports backslashes, so `startswith` never matched."""
    game_dir = tmp_path / "XboxGames" / "Halo"
    game_dir.mkdir(parents=True)
    prefix = pm._as_path_prefix(str(game_dir))
    reported = _win32(str(game_dir / "Content" / "halo.exe"))

    assert reported.casefold().startswith(prefix)


def test_folder_matching_survives_a_slash_separated_install_dir(tmp_path):
    """The stored folder may come from an interpreter of either kind: `install_dir` is persisted, so a library written by one build and read by another has to keep matching."""
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
    """Latent until someone "tidies" a path through pathlib: the regexes accepted only backslashes."""
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
    """The ".exe" suffix is optional on both sides."""
    assert pm._matches(running, pm._name_variants(configured)) is expected


# --- The package cache ---


@pytest.fixture
def snapshot(monkeypatch):
    """Replace the Toolhelp walk with a scripted process list; ``processes`` is set per poll and every pid the predicate asked the kernel about is recorded."""

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
    """The common case is a machine full of unpackaged processes."""
    snapshot.processes = [(100, "notepad.exe")]
    snapshot.answers = {100: None}

    pm.is_package_running("some.package_hash")
    pm.is_package_running("some.package_hash")

    assert snapshot.asked == [100], "the second poll should not have asked again"


def test_a_refused_handle_is_never_cached(snapshot):
    """Caching a refusal turned one unlucky call into a permanent verdict; a packaged game never seen ends its session outright."""
    snapshot.processes = [(100, "game.exe")]
    snapshot.answers = {100: pm._UNREADABLE}

    pm.is_package_running("some.package_hash")
    pm.is_package_running("some.package_hash")

    assert snapshot.asked == [100, 100], "a refusal must be retried"


def test_a_matching_package_is_re_established_every_poll(snapshot):
    """A match keeps a session counting: only "no package" is cached; a process that carried an identity is asked again, because a recycled pid running another title's GameLaunchHelper.exe would match on name."""
    snapshot.processes = [(100, "gamelaunchhelper.exe")]
    snapshot.answers = {100: "some.package_hash"}

    assert pm.is_package_running("some.package_hash") is True
    assert pm.is_package_running("some.package_hash") is True
    assert snapshot.asked == [100, 100]


def test_a_pid_that_left_the_snapshot_is_evicted(snapshot):
    """The cache is rebuilt from the walk, so it cannot hold a dead pid."""
    snapshot.processes = [(100, "notepad.exe")]
    snapshot.answers = {100: None}
    pm.is_package_running("some.package_hash")

    snapshot.processes = []  # the process exited
    pm.is_package_running("some.package_hash")

    assert 100 not in pm._package_family_cache


def test_a_recycled_pid_under_a_new_name_is_asked_again(snapshot):
    """Windows hands a pid out again as soon as it is free."""
    snapshot.processes = [(100, "notepad.exe")]
    snapshot.answers = {100: None}
    pm.is_package_running("some.package_hash")

    snapshot.processes = [(100, "game.exe")]  # same pid, different program
    snapshot.answers = {100: "some.package_hash"}

    assert pm.is_package_running("some.package_hash") is True
    assert snapshot.asked == [100, 100]


def test_pseudo_pids_and_system_processes_are_skipped(snapshot):
    """Never open a handle we already know the answer for."""
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


# --- AUMID extraction ---


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
    """Also the "is this a Store game?" test, so "" has to mean no."""
    from kyron.utils.run_executable import aumid_from_command

    assert aumid_from_command(command) == expected


def test_folder_matching_skips_system_names_without_opening_handles(
    snapshot, monkeypatch, tmp_path
):
    """O pré-filtro por nome/pid também vale para a vigília por pasta, que pagava um OpenProcess por processo da máquina a cada 2 s."""
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
