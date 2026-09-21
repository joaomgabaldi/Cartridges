# test_game_folder.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Reading a game's own folder out of the command that launches it.

This is what decides whether the details dialog offers to open the folder at
all, so the interesting half is everything it refuses: a launcher URI, a Start
menu shortcut, a path to a file that is no longer there. Offering a button that
opens the wrong folder — or nothing — is worse than offering none.

Existence on disk is part of the answer, not a detail, which is why these build
real files under ``tmp_path`` instead of asserting on strings alone.
"""

import itertools
import os
import winreg

import pytest

from cartridges.utils.game_folder import game_folder, open_folder

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="game_folder reads the Windows package registry"
)


def _win32(path) -> str:
    """A path with the separators Windows uses, whatever os.sep says today.

    MSYS2's Python — the one the app ships on — has os.sep and os.altsep the
    other way round, so anything built through pathlib comes back with forward
    slashes while what the shell needs (and what this returns) has backslashes.
    """
    return str(path).replace("/", "\\")


@pytest.fixture
def game_exe(tmp_path):
    """A game laid out the way an installer leaves one: an exe inside a folder."""
    folder = tmp_path / "Halo"
    (folder / "bin").mkdir(parents=True)
    exe = folder / "bin" / "halo.exe"
    exe.write_bytes(b"")
    return exe


# ---------------------------------------------------------------------------
# Classic games: the folder is the one holding the executable
# ---------------------------------------------------------------------------


def test_quoted_path_from_the_file_chooser(game_exe):
    """What `set_executable` writes when a file is picked in the dialog."""
    assert game_folder(f'"{_win32(game_exe)}"') == _win32(game_exe.parent)


def test_command_the_importer_writes(game_exe):
    """`start "" /D "<workdir>" "<target>" <args>`, from a .lnk."""
    command = (
        f'start "" /D "{_win32(game_exe.parent.parent)}" '
        f'"{_win32(game_exe)}" -windowed'
    )
    assert game_folder(command) == _win32(game_exe.parent)


def test_unquoted_path(game_exe):
    """Typed by hand, without quotes — accepted while it holds no spaces."""
    assert game_folder(_win32(game_exe)) == _win32(game_exe.parent)


def test_working_directory_when_the_target_is_relative(game_exe):
    """No absolute executable to point at, so the /D folder is the answer."""
    command = f'start "" /D "{_win32(game_exe.parent)}" "halo.exe"'
    assert game_folder(command) == _win32(game_exe.parent)


def test_last_executable_wins(tmp_path):
    """A launcher in front of the game names its own folder first.

    Same rule the rest of the app reads these commands by (`exe_name_from_command`,
    `install_dir_from_command`): what starts the game comes last.
    """
    for name in ("Launcher", "Game"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "run.exe").write_bytes(b"")

    command = (
        f'start "" "{_win32(tmp_path / "Launcher" / "run.exe")}" '
        f'"{_win32(tmp_path / "Game" / "run.exe")}"'
    )
    assert game_folder(command) == _win32(tmp_path / "Game")


def test_batch_file_counts_as_the_executable(tmp_path):
    """Not every game is started by an .exe."""
    script = tmp_path / "play.bat"
    script.write_text("")
    assert game_folder(f'start "" "{_win32(script)}"') == _win32(tmp_path)


def test_bare_exe_with_a_quoted_folder_argument(game_exe, tmp_path):
    """Mixed command: the bare exe wins, not the quoted argument after it.

    `quoted or bare` used to drop the bare exe the moment any quoted path
    appeared, and the answer became the argument's folder — the exact "wrong
    folder" the module promises never to open.
    """
    saves = tmp_path / "Saves"
    saves.mkdir()
    command = f'{_win32(game_exe)} -savedir "{_win32(saves)}"'
    assert game_folder(command) == _win32(game_exe.parent)


def test_bare_exe_with_a_quoted_file_argument(game_exe, tmp_path):
    """The other face of the same defect: a quoted config file after the bare
    exe used to answer None and hide the button with the game installed."""
    config = tmp_path / "halo.cfg"
    config.write_text("")
    command = f'{_win32(game_exe)} -config "{_win32(config)}"'
    assert game_folder(command) == _win32(game_exe.parent)


# ---------------------------------------------------------------------------
# Commands that name no folder anyone here can find
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        'start "" "steam://rungameid/440"',
        'start "" "com.epicgames.launcher://apps/fortnite?action=launch"',
        'start "" "goggalaxy://openGameView/1207658930"',
        "",
        "   ",
    ],
)
def test_launcher_commands_have_no_folder(command):
    """The launcher is the only thing that knows where it put the game."""
    assert game_folder(command) is None


def test_shortcut_target_has_no_folder(tmp_path):
    """A .lnk is a pointer; the folder holding it is the Start menu, not the game.

    This is the shape the importer falls back to for a packaged game whose AUMID
    it could not resolve into a launchable one.
    """
    shortcut = tmp_path / "Halo.lnk"
    shortcut.write_bytes(b"")
    assert game_folder(f'start "" "{_win32(shortcut)}"') is None


def test_missing_executable_has_no_folder(tmp_path):
    """Uninstalled or moved reads the same as unknowable: there is nothing to open."""
    command = f'start "" "{_win32(tmp_path / "gone.exe")}"'
    assert game_folder(command) is None


def test_missing_executable_with_a_surviving_workdir_has_no_folder(tmp_path):
    """The /D folder outliving the game is not the game's folder.

    The importer writes `/D "<workdir>"` for every .lnk with a working
    directory, and a shortcut's "Start in" can point at the whole library.
    Uninstalling has to read as None, not as "open whatever is left standing":
    that folder holds everybody else's games.
    """
    command = (
        f'start "" /D "{_win32(tmp_path)}" '
        f'"{_win32(tmp_path / "Halo" / "halo.exe")}"'
    )
    assert game_folder(command) is None


def test_missing_executable_with_a_surviving_argument_folder_has_no_folder(tmp_path):
    """Same rule when the survivor is an argument rather than the /D."""
    saves = tmp_path / "Saves"
    saves.mkdir()
    command = f'"{_win32(tmp_path / "gone.exe")}" -savedir "{_win32(saves)}"'
    assert game_folder(command) is None


def test_a_truncated_bare_path_never_resolves_to_a_neighbour(tmp_path):
    """A bare path with spaces truncates at the first space; the fragment must
    not land on a sibling folder that happens to share the prefix (Halo CE →
    Halo). The documented answer for a bare path with spaces is None."""
    for name in ("Halo", "Halo CE"):
        (tmp_path / name).mkdir()
    exe = tmp_path / "Halo CE" / "halo.exe"
    exe.write_bytes(b"")
    assert game_folder(_win32(exe)) is None


# ---------------------------------------------------------------------------
# Packaged games: the folder comes from the package registry
# ---------------------------------------------------------------------------


_PACKAGES_KEY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows"
    r"\CurrentVersion\AppModel\Repository\Packages"
)


def _installed_family() -> str:
    """A package family name this machine actually has, or "" if none.

    Read straight from the registry rather than naming an app: no particular
    Store app is guaranteed to be installed, and the point here is that a real
    entry resolves, not which one.
    """
    try:
        packages = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PACKAGES_KEY)
    except OSError:  # pragma: no cover - environment guard
        return ""

    with packages:
        for index in itertools.count():
            try:
                full_name = winreg.EnumKey(packages, index)
            except OSError:
                return ""
            parts = full_name.split("_")
            # Name_Version_Architecture_ResourceId_PublisherId, main package only
            if len(parts) != 5 or parts[3].casefold().startswith("split."):
                continue
            try:
                with winreg.OpenKey(packages, full_name) as package:
                    root = winreg.QueryValueEx(package, "PackageRootFolder")[0]
            except OSError:
                continue
            if root and os.path.isdir(root):
                return f"{parts[0]}_{parts[4]}"


def test_packaged_game_resolves_to_its_install_folder():
    """A `shell:AppsFolder` command is answered from the package repository."""
    family = _installed_family()
    if not family:  # pragma: no cover - environment guard
        pytest.skip("no packaged app installed for this user")

    folder = game_folder(f"explorer.exe shell:AppsFolder\\{family}!App")
    assert folder and os.path.isdir(folder)
    assert "/" not in folder  # handed to Explorer, which wants backslashes


def test_unknown_package_has_no_folder():
    """Nothing installed under that family; the button must not appear."""
    command = "explorer.exe shell:AppsFolder\\NotInstalled.Game_0000000000000!App"
    assert game_folder(command) is None


def test_open_folder_reports_success(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "startfile", lambda _directory: None, raising=False)
    assert open_folder(str(tmp_path)) is True


def test_open_folder_reports_failure_instead_of_raising(monkeypatch):
    """The folder was there when the button was shown; gone by the click is a
    message to the user, not an unhandled exception — see `details_dialog.py`."""

    def _missing(_directory):
        raise OSError("gone")

    monkeypatch.setattr(os, "startfile", _missing, raising=False)
    assert open_folder("C:\\Nonexistent\\Folder") is False


def test_open_folder_with_no_directory_is_a_no_op(monkeypatch):
    called = []
    monkeypatch.setattr(os, "startfile", lambda d: called.append(d), raising=False)
    assert open_folder("") is False
    assert called == []
