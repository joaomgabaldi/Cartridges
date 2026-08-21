# file_manager.py
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

import json
from uuid import uuid4

from cartridges import shared

# Re-exported so tests (and this module's own writer below) keep one name for
# "everything a record persists". The tuple itself lives beside Game because it
# is also the whitelist of what `Game.update_values` accepts — the two lists
# drifting apart is how a field could be saved but never loadable, or vice
# versa. The edit-dialog guard in the tests asserts against this import path.
from cartridges.game import Game, PERSISTED_ATTRS
from cartridges.store.managers.async_manager import AsyncManager
from cartridges.store.managers.hltb_manager import HLTBManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager


class FileManager(AsyncManager):
    """Manager in charge of saving a game to a file"""

    # Saving last: writing before the online lookups finish would persist a
    # game without the metadata that is about to arrive, and the next launch
    # would show it as permanently missing.
    run_after = (SteamAPIManager, HLTBManager)
    signals = {"save-ready"}

    def main(self, game: Game, additional_data: dict) -> None:
        if additional_data.get("skip_save"):  # Skip saving when loading games from disk
            return

        shared.games_dir.mkdir(parents=True, exist_ok=True)

        attrs = PERSISTED_ATTRS

        # Write to a temp file, then replace: an interrupted write (crash,
        # power loss) can't leave a truncated JSON behind.
        #
        # The temp name carries a unique suffix. This manager is asynchronous,
        # so two saves of the *same* game (the update checker raising a notice
        # while a play session persists its minute, say) run on two Gio.Task
        # threads at once. With a single fixed `<id>.json.tmp` they opened the
        # same file and interleaved their writes, and whichever renamed second
        # published whatever mixture was on disk — the atomic replace protected
        # against a torn write but not against two writers.
        path = shared.games_dir / f"{game.game_id}.json"
        tmp_path = path.with_name(f"{game.game_id}.{uuid4().hex}.json.tmp")
        try:
            with tmp_path.open("w", encoding="utf-8") as file:
                json.dump(
                    {attr: getattr(game, attr) for attr in attrs},
                    file,
                    indent=4,
                    sort_keys=True,
                )
            tmp_path.replace(path)
        except BaseException:
            # A failed write must not leave its scratch file in the games
            # folder, where the loader would have to learn to skip it.
            tmp_path.unlink(missing_ok=True)
            raise
