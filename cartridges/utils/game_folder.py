# game_folder.py
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

"""Where a game's files are, taken from the command that launches it.

Only two kinds of command say where the game lives. A classic one names the
executable, and the folder is the one holding it — even when that executable
is a store client's own (``steam.exe -applaunch 440``): the folder offered is
the client's, because that is what the command runs, and telling "a game's
exe" from "a launcher's exe" would take a blocklist of every client ever
shipped. A packaged one (Microsoft Store / Game Pass) names an AUMID, and
Windows records the install folder against the package.

Everything else — ``steam://rungameid/…``, the Epic and GOG launcher URIs, a
Start menu ``.lnk`` standing in for a package with no launchable AUMID — is a
request for some other program to start the game, and that program is the only
one that knows where it put it. There is nothing to guess from, so those get
None and the caller hides the button rather than opening the wrong folder.
"""

import itertools
import logging
import os
import re
import winreg
from typing import Optional

from cartridges.utils.run_executable import aumid_from_command

# The launch command's own paths, quoted (what the file chooser and the
# importer write) or bare (typed by hand), collected in the order they appear —
# so "the last launchable one is the game" keeps meaning that even when the two
# forms mix in one command, a bare exe typed by hand with a quoted argument
# after it. A bare path still stops at whitespace, because one with spaces
# cannot be told apart from its arguments.
_PATH = re.compile(
    r'"(?P<quoted>[A-Za-z]:[\\/][^"]*)"'
    r'|(?<!\S)(?P<bare>[A-Za-z]:[\\/][^\s"]*)(?!\S)'
)

# What counts as "the game's own executable" among the paths in a command. A
# `.lnk` or `.url` is excluded on purpose: those are pointers, and the folder
# holding the pointer is the Start menu, not the game.
_LAUNCHABLE_SUFFIXES = (".exe", ".bat", ".cmd", ".com")

# Where Windows records every package installed for this user, one subkey per
# package full name (``Name_Version_Architecture_ResourceId_PublisherId``), each
# carrying the folder its files were laid down in.
_PACKAGES_KEY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows"
    r"\CurrentVersion\AppModel\Repository\Packages"
)


def game_folder(command: str) -> Optional[str]:
    """The folder a launch command points into, or None when it cannot be known.

    The folder is returned only when it exists on disk, so a game that has since
    been uninstalled or moved reads the same as one whose launcher hides it: no
    folder to offer — even when the command still names folders that outlived
    the executable, like a ``/D`` working directory or a settings path among
    the arguments. Those are near the game, not the game.
    """
    if not (command := (command or "").strip()):
        return None

    if aumid := aumid_from_command(command):
        return _package_folder(aumid)

    return _executable_folder(command)


def _executable_folder(command: str) -> Optional[str]:
    """The folder holding the executable a classic command runs."""
    candidates = []
    for match in _PATH.finditer(command):
        if quoted := match.group("quoted"):
            candidates.append(quoted)
        elif match.group("bare").casefold().endswith(_LAUNCHABLE_SUFFIXES):
            # A bare path is only trusted whole. Truncated at a space, the
            # fragment ("C:\Games\Halo" out of "C:\Games\Halo CE\halo.exe")
            # carries no launchable suffix — and keeping it as a folder
            # candidate would resolve to whatever neighbour shares the prefix.
            candidates.append(match.group("bare"))

    # The game's executable comes after whatever precedes it (the `start`
    # title, a `/D` working directory), and before any argument that happens
    # to be a path too — so the last launchable one is the game.
    launchable = [
        candidate
        for candidate in candidates
        if candidate.casefold().endswith(_LAUNCHABLE_SUFFIXES)
    ]
    for candidate in reversed(launchable):
        if os.path.isfile(candidate):
            return _win32_dir(os.path.dirname(candidate))

    # The command names its executable and the disk no longer has it. The game
    # is gone, and any folder still standing in the command — the `/D` working
    # directory, a settings path among the arguments — is not the game's:
    # offering it would open somebody else's folder.
    if launchable:
        return None

    # No absolute executable named at all: the importer's form for a relative
    # target, `start "" /D "<workdir>" "game.exe"`. The first folder that
    # exists is that working directory.
    for candidate in candidates:
        if os.path.isdir(candidate):
            return _win32_dir(candidate)

    return None


def _package_folder(aumid: str) -> Optional[str]:
    """The install folder of the package an AUMID belongs to.

    The AUMID's family name (``Name_PublisherId``) is not what the registry
    files packages under — that is the full name, which carries the version,
    architecture and resource id in between. So the packages are walked and
    matched on the two ends the family name gives us.
    """
    family = aumid.split("!", 1)[0]
    name, _sep, publisher = family.rpartition("_")
    if not name or not publisher:
        return None

    prefix = (name + "_").casefold()
    suffix = ("_" + publisher).casefold()

    # A family can have several packages registered at once: resource packages
    # (``split.language-pt`` and friends, which hold no executable) alongside
    # the main one, and an older version alongside the one an update is
    # replacing it with. Skip the first kind, and prefer the newest of the rest.
    best: Optional[tuple[tuple[int, ...], str]] = None
    try:
        packages = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PACKAGES_KEY)
    except OSError:
        logging.debug("No package repository in the registry")
        return None

    with packages:
        for index in itertools.count():
            try:
                full_name = winreg.EnumKey(packages, index)
            except OSError:
                break  # end of the list

            folded = full_name.casefold()
            if not (folded.startswith(prefix) and folded.endswith(suffix)):
                continue

            middle = full_name[len(prefix) : len(full_name) - len(suffix)].split("_")
            if len(middle) != 3 or middle[2].casefold().startswith("split."):
                continue

            try:
                with winreg.OpenKey(packages, full_name) as package:
                    root = winreg.QueryValueEx(package, "PackageRootFolder")[0]
            except OSError:
                continue

            if not root or not os.path.isdir(root):
                continue

            try:
                version = tuple(int(part) for part in middle[0].split("."))
            except ValueError:
                version = ()

            if best is None or version > best[0]:
                best = (version, root)

    return _win32_dir(best[1]) if best else None


def _win32_dir(directory: str) -> str:
    """``directory`` in the shape the Windows shell accepts.

    `os.path.dirname` hands back whatever `os.sep` says, and on the interpreter
    this app ships with (MSYS2 ucrt64) that is a forward slash — which Explorer
    does not open.
    """
    return directory.replace("/", "\\")


def open_folder(directory: str) -> None:
    """Show ``directory`` in Explorer."""
    if not directory:
        return

    logging.info("Opening folder `%s`", directory)
    try:
        os.startfile(directory)  # type: ignore[attr-defined]  # Windows-only
    except OSError:
        # The folder was there when the button was shown; if it went away since,
        # that is worth a line in the log and nothing more.
        logging.exception("Could not open folder `%s`", directory)
