# test_run_executable.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pulling the AUMID back out of a launch command; its return value doubles as the "is this a Store game?" test, so "" has to mean no."""

import pytest

from kyron.utils.run_executable import aumid_from_command


@pytest.mark.parametrize(
    "command,expected",
    [
        # What the importer writes for a resolved AUMID.
        ("explorer.exe shell:AppsFolder\\Pkg_hash!App", "Pkg_hash!App"),
        # A .url shortcut imports quoted; a trailing quote made ShellExecuteEx fail the elevated launch after the window had already minimised.
        ('start "" "shell:AppsFolder\\Pkg_hash!App"', "Pkg_hash!App"),
        ("start \"\" 'shell:AppsFolder\\Pkg_hash!App'", "Pkg_hash!App"),
        # Trailing whitespace and arguments are not part of the identity.
        ("explorer.exe shell:AppsFolder\\Pkg_hash!App   ", "Pkg_hash!App"),
        ("explorer.exe shell:AppsFolder\\Pkg_hash!App -windowed", "Pkg_hash!App"),
        # A grouping id has no "!" and must still come back, or the game would land in the manual session window.
        ("explorer.exe shell:AppsFolder\\XboxGames.Halo_Halo", "XboxGames.Halo_Halo"),
        # Not a Store game.
        ('start "" "C:\\Games\\halo.exe"', ""),
        ('start "" "steam://rungameid/440"', ""),
        ("", ""),
        ("shell:AppsFolder", ""),
    ],
)
def test_aumid_from_command(command, expected):
    assert aumid_from_command(command) == expected


def test_the_marker_is_matched_case_insensitively():
    """The shell accepts the `shell:appsfolder` marker in any case."""
    assert (
        aumid_from_command('start "" "shell:appsfolder\\PFN.Game_abc!App"')
        == "PFN.Game_abc!App"
    )


def test_the_result_is_usable_as_a_package_family():
    """``ProcessSession`` splits it on "!" to get the family name to watch."""
    aumid = aumid_from_command("explorer.exe shell:AppsFolder\\Pkg_hash!App")
    assert aumid.split("!", 1)[0] == "Pkg_hash"


def test_a_grouping_id_yields_no_usable_family():
    """No "!", so the whole string comes back and matches no real PFN; the importer keeps a grouping id out of the `shell:AppsFolder` command because tracking it would wait out the startup grace."""
    aumid = aumid_from_command("explorer.exe shell:AppsFolder\\XboxGames.Halo_Halo")
    assert "!" not in aumid
