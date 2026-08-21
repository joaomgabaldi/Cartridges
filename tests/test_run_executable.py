# test_run_executable.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pulling the AUMID back out of a launch command.

T6.27. The same cases as T4.14, but as a unit and without the Windows-only
skip that gates ``test_process_monitor`` — this function is pure string work and
three separate features read it: elevation, playtime tracking, and the details
dialog deciding whether a game is packaged.

Its return value doubles as the "is this a Store game?" test, so "" has to mean
no, and anything else has to be a launchable identity.
"""

import pytest

from cartridges.utils.run_executable import aumid_from_command


@pytest.mark.parametrize(
    "command,expected",
    [
        # What the importer writes for a resolved AUMID.
        ("explorer.exe shell:AppsFolder\\Pkg_hash!App", "Pkg_hash!App"),
        # A .url shortcut imports quoted. Taking everything after the marker
        # gave back a trailing quote, which the tracking side hid (it splits on
        # "!" and drops the tail) while ShellExecuteEx choked on it: the
        # elevated launch failed with nothing but a warning in the log, by which
        # point the main window had already minimised for a game that was never
        # going to start.
        ('start "" "shell:AppsFolder\\Pkg_hash!App"', "Pkg_hash!App"),
        ("start \"\" 'shell:AppsFolder\\Pkg_hash!App'", "Pkg_hash!App"),
        # Trailing whitespace and arguments are not part of the identity.
        ("explorer.exe shell:AppsFolder\\Pkg_hash!App   ", "Pkg_hash!App"),
        ("explorer.exe shell:AppsFolder\\Pkg_hash!App -windowed", "Pkg_hash!App"),
        # A grouping id has no "!" and must still come back: rejecting it here
        # would only move the game to the manual session window, where one the
        # shell cannot launch at all would sit collecting playtime.
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


def test_the_result_is_usable_as_a_package_family():
    """``ProcessSession`` splits it on "!" to get the family name to watch."""
    aumid = aumid_from_command("explorer.exe shell:AppsFolder\\Pkg_hash!App")
    assert aumid.split("!", 1)[0] == "Pkg_hash"


def test_a_grouping_id_yields_no_usable_family():
    """It has no "!", so the whole string comes back — and matches no real PFN.

    That is why the importer keeps a grouping id out of the ``shell:AppsFolder``
    command entirely: a game tracked on a family name no process will ever
    report would wait out the startup grace and then be told it never launched.
    """
    aumid = aumid_from_command("explorer.exe shell:AppsFolder\\XboxGames.Halo_Halo")
    assert "!" not in aumid
