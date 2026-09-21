# source.py
#
# Copyright 2023 Geoffrey Coulaud
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

from abc import abstractmethod
from collections.abc import Iterable
from typing import Any, Generator, Optional

from cartridges.errors.friendly_error import FriendlyError
from cartridges.game import Game

# Type of the data returned by iterating on a Source
SourceIterationResult = Optional[Game | tuple[Game, tuple[Any]]]


class SourceScanError(FriendlyError):
    """Raised by a source whose scan could not be completed.

    A source that simply finds nothing and a source that could not look are
    indistinguishable from the outside — both produce no games — and the
    Importer draws a drastic conclusion from an empty scan: every game that
    source owns is gone, and gets marked removed.

    That conclusion is only safe when the source actually looked. This is how a
    source says it did not, so its games are left alone until a scan succeeds.
    Raise it from `__iter__`, at whatever point the failure becomes known; games
    already yielded still count, and only the rest of the scan is abandoned.

    A `FriendlyError` on purpose, and not just a log line: a scan that quietly
    gives up is worse than one that says so, so its title/subtitle are what the
    importer's warning dialog shows the user.
    """


class SourceIterable(Iterable):
    """Data producer for a source of games"""

    source: "Source"

    def __init__(self, source: "Source") -> None:
        self.source = source

    @abstractmethod
    def __iter__(self) -> Generator[SourceIterationResult, None, None]:
        """
        Method that returns a generator that produces games
        * Should be implemented as a generator method
        * May yield `None` when an iteration hasn't produced a game
        * In charge of handling per-game errors
        * Returns when exhausted
        """


class Source(Iterable):
    """Source of games. E.g an installed app with a config file that lists game directories"""

    source_id: str
    name: str
    variant: Optional[str] = None
    iterable_class: type[SourceIterable]

    @property
    def full_name(self) -> str:
        """The source's full name"""
        full_name_ = self.name
        if self.variant:
            full_name_ += f" ({self.variant})"
        return full_name_

    @property
    def game_id_format(self) -> str:
        """The string format used to construct game IDs"""
        return self.source_id + "_{game_id}"

    @property
    def is_available(self) -> bool:
        """Whether the source can be scanned. Subclasses narrow this."""
        return True

    def __iter__(self) -> Generator[SourceIterationResult, None, None]:
        """Get an iterator for the source"""
        return iter(self.iterable_class(self))
