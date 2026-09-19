# store.py
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
import logging
from pathlib import Path
from threading import RLock
from typing import Any, Generator, Iterable, MutableMapping, Optional
from uuid import uuid4

from gi.repository import GLib

from cartridges import shared
from cartridges.game import Game
from cartridges.store.managers.manager import Manager
from cartridges.store.pipeline import Pipeline
from cartridges.utils.game_logo import IMAGE_SUFFIXES, remove_logo
from cartridges.utils.run_executable import aumid_from_command
from cartridges.utils.save_cover import ANIMATED_SUFFIXES
from cartridges.utils.wallhaven import IMAGE_SUFFIXES as WALLPAPER_SUFFIXES


def _path_key(path: str) -> str:
    """A shortcut path in the one shape comparisons may use.

    Two conventions have to be flattened before two paths naming one file can be
    told to be equal. Separators, because the interpreter this ships with (MSYS2
    ucrt64) has `os.sep` and `os.altsep` the other way round, so a library
    written by one build and rescanned by another disagrees with itself — and
    the anchor index is keyed by exactly this value, so a disagreement there
    means a game is not recognised, is imported again, and has its old record
    removed with everything on it. And case, because Windows paths are
    case-insensitive while Python strings are not: re-picking the shortcuts
    folder with a different capitalisation is enough.
    """
    return path.replace("/", "\\").casefold()


def _is_derived_command(game: Game) -> bool:
    """Does this game's launch command look like one the importer built?

    True for the two shapes a packaged (Store / Game Pass) game can take: the
    ``shell:AppsFolder`` command built from a resolved AUMID, and the fallback
    that launches the shortcut file itself when no launchable AUMID was found.
    Only those two, because they are the only commands that can go stale without
    the game's identity changing with them — everywhere else the command is what
    the identity is derived from.
    """
    if aumid_from_command(game.executable):
        return True
    # Compared through `_path_key` because the two sides age differently: the
    # command is rewritten by a rescan while the stored path is not, so a
    # library that changed interpreters has one in each convention. Left as a
    # plain string comparison, a game on the fallback stopped being recognised
    # as derived and could never be lifted back onto its AUMID command.
    return bool(game.shortcut_path) and _path_key(game.executable) == _path_key(
        f'start "" "{game.shortcut_path}"'
    )


def _dump_json_atomic(path: Path, data: dict, **dump_kwargs: Any) -> None:
    """Escreve via tmp + replace — o mesmo idioma do FileManager.

    Os dois regravadores da adoção escreviam no lugar (truncate + write): uma
    queda no meio deixava um JSON truncado, o loader pulava o arquivo e o jogo
    voltava zerado no próximo scan. Uma queda agora custa um ``.tmp`` órfão,
    que o loader já ignora pelo sufixo.
    """
    tmp_path = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, **dump_kwargs)
        tmp_path.replace(path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _migrate_game_files(old_id: str, new_id: str) -> None:
    """Move everything filed under ``old_id`` to ``new_id``.

    A game owns five sets of files, all named after its id: its JSON record,
    its cover, its logo and session wallpaper, each an image plus the sidecar
    recording how it was chosen, and the LED strip colour picked for it.
    Best effort throughout — a file that will not move is left where it is
    rather than taking the migration down with it, because the alternative is
    an aborted adoption, which costs the whole game record.
    """
    record = shared.games_dir / f"{new_id}.json"
    moves = [(shared.games_dir / f"{old_id}.json", record)]
    for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
        moves.append(
            (shared.covers_dir / f"{old_id}{suffix}", shared.covers_dir / f"{new_id}{suffix}")
        )
    for suffix in (".json", *IMAGE_SUFFIXES):
        moves.append(
            (shared.logos_dir / f"{old_id}{suffix}", shared.logos_dir / f"{new_id}{suffix}")
        )
    for suffix in (".json", *WALLPAPER_SUFFIXES):
        moves.append(
            (
                shared.wallpapers_dir / f"{old_id}{suffix}",
                shared.wallpapers_dir / f"{new_id}{suffix}",
            )
        )

    moves.append(
        (shared.fitas_dir / f"{old_id}.json", shared.fitas_dir / f"{new_id}.json")
    )

    for source, dest in moves:
        try:
            if source.exists():
                source.replace(dest)
        except OSError as error:
            logging.warning("Could not move %s to %s: %s", source, dest, error)

    # The record names its own id, and moving the file does not change what is
    # written inside it. Done here rather than left to the caller's `save()`
    # because a removed game has no managers connected — its `save()` emits a
    # signal nobody is listening for — so a tombstone would keep the old id
    # inside a file named after the new one, and the next startup would undo the
    # adoption and redo it on every scan after that.
    #
    # The id, and only the id. Adoption also updates `executable` and
    # `shortcut_path`, and for a tombstone both stay stale on disk — deliberately
    # left that way rather than written here, because for a removed game they are
    # dead fields. It is never launched, so its command is never read. A live
    # game's `save()` writes all three a moment later anyway.
    #
    # The stale path can be *matched* on, though, and it is worth being exact
    # about what stops that becoming a problem, because the obvious answer is
    # the wrong one. It is NOT the poisoning in `_index_shortcut`: `add_game`
    # consults the anchor before it indexes anything, so the first game to
    # arrive at a tombstone's path adopts it — there is no contested key yet.
    # What holds is `shortcut_mtime`, which adoption never touches. A shortcut
    # file that has not changed is the same file the user deleted, so inheriting
    # the tombstone is the right answer; a recreated one has a newer mtime and
    # comes back through the reinstall branch. Verified both ways.
    try:
        if record.exists():
            with record.open(encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict) and data.get("game_id") != new_id:
                data["game_id"] = new_id
                _dump_json_atomic(record, data, indent=4, sort_keys=True)
    except (OSError, ValueError) as error:
        logging.warning("Could not restamp the record for %s: %s", new_id, error)

    # Both sidecars name their image file, so the rename above has to be
    # reflected inside them too — otherwise the record points at a file that no
    # longer exists and the image is silently re-fetched (or, for one the user
    # chose by hand, silently lost).
    for kind, sidecar in (
        ("logo", shared.logos_dir / f"{new_id}.json"),
        ("wallpaper", shared.wallpapers_dir / f"{new_id}.json"),
    ):
        try:
            if not sidecar.exists():
                continue
            with sidecar.open(encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not data.get("file"):
                continue
            data["file"] = str(data["file"]).replace(old_id, new_id, 1)
            _dump_json_atomic(sidecar, data)
        except (OSError, ValueError) as error:
            logging.warning("Could not update the %s record for %s: %s", kind, new_id, error)


class Store:
    """Class in charge of handling games being added to the app."""

    managers: dict[type[Manager], Manager]
    pipeline_managers: set[Manager]
    source_games: MutableMapping[str, MutableMapping[str, Game]]
    # Flat game_id -> Game index kept in sync with source_games so lookups by id
    # are O(1) instead of scanning every game (adding N games was O(N²)).
    games_by_id: dict[str, Game]
    # None marks a path more than one record claims: see `_index_shortcut`
    _games_by_shortcut: dict[tuple[str, str], Optional[Game]]
    new_game_ids: set[str]
    duplicate_game_ids: set[str]

    def __init__(self) -> None:
        self.managers = {}
        self.pipeline_managers = set()
        self.source_games = {}
        self.games_by_id = {}
        self.new_game_ids = set()
        self.duplicate_game_ids = set()
        # (base source, shortcut path) -> Game, for games that came from a
        # shortcut file. The anchor `adopt_legacy_game` falls back on; kept as
        # an index because the alternative is scanning the library once per
        # imported game.
        self._games_by_shortcut = {}
        # `add_game` runs on the importer's source worker threads, while the
        # main thread walks the store to lay out the library and to match games
        # against the update feed. Both touch these dicts, and a plain
        # `for game in store` raised "dictionary changed size during iteration"
        # partway through an import — killing the update pass for the rest of
        # the session, since it only runs every few hours.
        self._lock = RLock()

    def __contains__(self, obj: object) -> bool:
        """Check if the game is present in the store with the `in` keyword"""
        if not isinstance(obj, Game):
            return False
        with self._lock:
            if not (source_mapping := self.source_games.get(obj.base_source)):
                return False
            return obj.game_id in source_mapping

    def __iter__(self) -> Generator[Game, None, None]:
        """Iterate through the games in the store with `for ... in`

        Iterates a snapshot rather than the live mappings. Holding the lock for
        the whole loop is not an option — a caller is free to abandon the
        generator, or to call back into the store from inside it — and the
        callers here do real work per game (building widgets, fuzzy-matching
        titles), which is exactly the window a concurrent import needs to
        invalidate a live iterator.
        """
        with self._lock:
            games = [
                game
                for games_mapping in self.source_games.values()
                for game in games_mapping.values()
            ]
        yield from games

    def __len__(self) -> int:
        """Get the number of games in the store with the `len` builtin"""
        with self._lock:
            return sum(
                len(source_mapping) for source_mapping in self.source_games.values()
            )

    def __getitem__(self, game_id: str) -> Game:
        """Get a game by its id with `store["game_id_goes_here"]`"""
        try:
            return self.games_by_id[game_id]
        except KeyError:
            raise KeyError("Game not found in store") from None

    def clear(self) -> None:
        """Remove every game from the store (used when resetting the app)"""
        with self._lock:
            self.source_games = {}
            self.games_by_id = {}
            self._games_by_shortcut = {}

    def get(self, game_id: str, default: Any = None) -> Game | Any:
        """Get a game by its ID, with a fallback if not found"""
        try:
            game = self[game_id]
            return game
        except KeyError:
            return default

    def add_manager(self, manager: Manager, in_pipeline: bool = True) -> None:
        """Add a manager to the store"""
        manager_type = type(manager)
        self.managers[manager_type] = manager
        self.toggle_manager_in_pipelines(manager_type, in_pipeline)

    def toggle_manager_in_pipelines(
        self, manager_type: type[Manager], enable: bool
    ) -> None:
        """Change if a manager should run in new pipelines"""
        if enable:
            self.pipeline_managers.add(self.managers[manager_type])
        else:
            self.pipeline_managers.discard(self.managers[manager_type])

    def cleanup_game(self, game: Game) -> None:
        """Remove a game's files, dismiss any loose toasts"""
        # Covers may be a still .tiff or an animated .gif/.webp
        # The session wallpaper and the LED strip colour are filed by id too,
        # and ids are stable: left behind, a reinstalled game would inherit the
        # removed one's locked choices.
        for path in (
            shared.games_dir / f"{game.game_id}.json",
            shared.covers_dir / f"{game.game_id}.tiff",
            shared.covers_dir / f"{game.game_id}.gif",
            shared.covers_dir / f"{game.game_id}.webp",
            shared.wallpapers_dir / f"{game.game_id}.json",
            *(
                shared.wallpapers_dir / f"{game.game_id}{suffix}"
                for suffix in WALLPAPER_SUFFIXES
            ),
            shared.fitas_dir / f"{game.game_id}.json",
        ):
            path.unlink(missing_ok=True)

        # The cached details-page logo and the record of its lookup
        remove_logo(game.game_id)

        # The toasts are libadwaita widgets and this runs on an import worker
        # thread, so the dismissal has to be handed to the main loop — the same
        # rule DisplayManager follows for everything it touches.
        # TODO: don't run this if the state is startup
        def dismiss_undo_toasts() -> bool:
            for undo in ("remove", "hide"):
                if toast := shared.win.toasts.pop((game, undo), None):
                    shared.win.toast_queue.dismiss(toast)
            return GLib.SOURCE_REMOVE

        GLib.idle_add(dismiss_undo_toasts)

    @staticmethod
    def _refresh_derived_executable(stored_game: Game, game: Game) -> bool:
        """Adopt a rescanned launch command when the stored one was derived.

        A duplicate is normally ignored wholesale, and for most games that is
        right: the command IS the identity there (a classic shortcut hashes
        ``target|arguments``, a .url hashes its URL), so a command that changed
        produces a different game rather than an update to this one.

        Packaged games are the exception, and the only one. Their identity is
        the AUMID the shortcut carries, while the command is built from the
        AUMID the Start menu resolves that to — two different values, so the
        command can go stale on its own when a title is updated or Microsoft
        re-issues its app id. Nothing else would ever fix it: the scan sees a
        duplicate every time and drops it.

        Only a command that looks generated is replaced, which spares the
        classic games (a .url whose URL is itself a ``shell:AppsFolder`` one
        does match, harmlessly: its command is a pure function of its identity,
        so a refresh is a no-op) — but note what that does and does not buy: a
        packaged command *is* something the user can type into the details
        dialog, and one they hand-wrote is indistinguishable from one we built,
        so it will be reverted by the next scan. The protection is for commands
        that do not look packaged, not for hand-written ones in general.

        Both shapes a packaged game can take count, and the second one is the
        point. A Store shortcut the Start menu cannot resolve falls back to
        launching the .lnk itself, which carries no AUMID — so testing only for
        an AUMID made the fallback absorbing: one incomplete `Get-StartApps`
        degraded a working command permanently, because the way back was not
        recognised as derived and never replaced it.

        The equality test below is not redundant with any of that, and is the
        stronger of the two guards — do not "simplify" it away. It means a false
        positive from `_is_derived_command` can only bite when the command
        genuinely changed, and for anything that is not packaged a changed
        command is a changed identity, so it never arrives here as a duplicate
        at all. A classic shortcut carrying `shell:AppsFolder\\…` somewhere in
        its arguments does read as derived, but its identity is
        ``target|arguments``, the rescan rebuilds the same command, and it stops
        on this line.
        """
        if stored_game.executable == game.executable:
            return False
        if not _is_derived_command(stored_game):
            return False
        logging.info(
            "Updating the launch command for %s (%s)", game.name, game.game_id
        )
        stored_game.executable = game.executable
        return True

    def _index_shortcut(self, game: Game) -> None:
        """Record a game under the shortcut file it came from.

        Caller holds the lock. A key two different records claim is poisoned
        (mapped to None) rather than resolved: the anchor authorises moving a
        game's save file onto another id, so an ambiguous answer has to be no
        answer. Records can legitimately collide — a stale record beside its
        replacement in a library carried across a change in how ids are derived
        — and picking either one of them would be a guess.

        Replacing the record for the same id is not a collision: that is the
        reinstall path swapping a tombstone for the game that came back under
        the same shortcut, and the index follows it rather than keeping the
        object the store has just dropped. A reinstall from a *different* path
        leaves the old key behind, which is why `adopt_legacy_game` re-checks
        that what the index names is still in the store.

        Poisoning is not permanent, despite what the early return below might
        suggest: `_reindex_shortcut` pops whatever a key holds, so a record that
        moves away from a contested path clears it. That is fine — a cleared key
        is unknown, not wrong.

        One shape of collision is not ambiguous, though, and treating it as if
        it were made the anchor useless in exactly the libraries that needed it.
        A live record beside a tombstone on one path is the wreckage of the very
        bug the anchor exists to stop: a game whose target changed was imported
        again under a new id while its old record was marked removed, and both
        name the shortcut they came from. Every affected game leaves that pair
        behind, so on the next boot every one of those paths was poisoned and
        stayed poisoned — the tombstone never moves, so nothing ever frees the
        key. The anchor was permanently disarmed for precisely the games it was
        supposed to protect, and the next patch lost another record.

        There is no guess to make there. A tombstone is a dead record: never
        shown, never launched, accumulating nothing. Whatever playtime and
        history exist are on the live one. So a live claimant takes the key from
        a tombstone and keeps it against one, in either arrival order — the disk
        is read in whatever order the directory gives, and that must not decide
        where a save file goes. Two live records still poison the key, which is
        the ambiguity the rule was written for and the only one it was ever
        actually about.

        A tombstone that is the *sole* claimant stays indexed, and that matters:
        a game the user removed on purpose, whose shortcut then gets patched,
        arrives under a new id and would resurrect itself if the anchor could
        not find the tombstone to inherit. It never competes with a live record
        for that role — if something live holds the path, the game is not
        removed.

        The check reads `removed` off the stored object rather than a snapshot
        taken at indexing time, which is what keeps it honest: `remove_games`
        flips that flag in place on records already in this index, so a record
        indexed while live is correctly seen as a tombstone afterwards.
        """
        if not game.shortcut_path:
            return
        key = (game.base_source, _path_key(game.shortcut_path))
        if key in self._games_by_shortcut:
            existing = self._games_by_shortcut[key]
            if existing is None:
                return  # contested; a second claimant does not settle it
            if existing.game_id != game.game_id:
                if existing.removed == game.removed:
                    self._games_by_shortcut[key] = None
                    return
                if game.removed:
                    return  # the live record already there keeps the key
        self._games_by_shortcut[key] = game

    def _reindex_shortcut(self, game: Game, shortcut_path: str) -> None:
        """Move ``game`` to a new shortcut path, index included.

        Caller holds the lock. Retiring the old key is the whole point; the new
        one still goes through `_index_shortcut`, so a path another record
        already claims is poisoned rather than quietly taken over.
        """
        self._games_by_shortcut.pop(
            (game.base_source, _path_key(game.shortcut_path)), None
        )
        game.shortcut_path = shortcut_path
        self._index_shortcut(game)

    def adopt_legacy_game(
        self, game: Game, legacy_ids: Iterable[str], anchor: bool = False
    ) -> Optional[Game]:
        """Re-file a stored game under ``game``'s id, keeping everything it has.

        A game id is a hash of how the game is identified, so changing what goes
        into that identity renames every game affected — and a renamed game is,
        to the rest of the app, a new game plus a missing one. The missing one
        gets removed, taking playtime, cover, logo and update tracking with it.

        Two ways to recognise the same game across such a change, tried in
        order. A source that knows how it used to derive an identity can say so
        through ``legacy_game_ids``. That is exact but not sufficient on its
        own: it can only reproduce a *past* derivation using *present* inputs,
        and the inputs move. A Store shortcut resolves its AUMID through the
        Start menu, so when that resolution stops working — the title updated
        and its Start entry is named differently — the scan cannot compute the
        id the game was filed under, and offers none at all. So the shortcut
        file itself is the fallback anchor: same source, same shortcut path,
        same game, whatever either id happens to hash to.

        The commoner case needs the anchor for a simpler reason: a classic
        shortcut's identity is its target, and a patch that repoints the .lnk
        changes that target without the source having any past derivation to
        replay — it cannot know what the old executable was called. The file it
        scanned is the only thing tying the two ids together.

        Note what none of it covers: the anchor IS the path, so a renamed
        shortcut is not found by it either. It does not need to be — a rename
        leaves the identity alone, so the id survives and the duplicate branch
        picks up the new path. Only a rename *and* a retarget in the same window
        loses the record, because then nothing held still.

        The anchor is opt-in per game (``identity_anchor`` in a game's
        additional data) and only a scanning source sets it. Loading the library
        from disk must not: two records naming one shortcut is a state the disk
        can hold — a stale record beside its replacement — and reading that as
        "the same game" would merge one game's save file into another's on
        startup. During a scan the path comes from a file that exists right now,
        which is a different claim entirely.

        Returns the adopted game, or None when there is nothing to adopt (the
        ordinary case: a genuinely new game).
        """
        candidates = list(legacy_ids)
        with self._lock:
            legacy = next(
                (
                    stored
                    for legacy_id in candidates
                    if (stored := self.games_by_id.get(legacy_id)) is not None
                    and stored.base_source == game.base_source
                ),
                None,
            )
            if legacy is None and anchor and game.shortcut_path:
                legacy = self._games_by_shortcut.get(
                    (game.base_source, _path_key(game.shortcut_path))
                )
            if legacy is None or legacy.game_id == game.game_id:
                return None
            legacy_id = legacy.game_id
            # The index can name a record the store has already dropped — a
            # tombstone replaced by the reinstall that came back under a
            # different shortcut path, say. Its `game_id` is then the id of the
            # *live* record that replaced it, so migrating it would move a
            # living game's save file, cover and logo onto this one and unfile
            # the game itself. Only ever adopt a record the store still holds.
            if self.games_by_id.get(legacy_id) is not legacy:
                logging.debug("Ignoring a stale anchor for %s", legacy_id)
                return None

        # Deliberately outside the lock: this is a dozen file operations, and
        # the main thread blocks on this lock to lay out the library. Nothing
        # here touches the mappings, and no other thread can be adopting the
        # same game — a source is scanned by one worker.
        logging.info("Adopting %s as %s (was %s)", legacy.name, game.game_id, legacy_id)
        _migrate_game_files(legacy_id, game.game_id)

        with self._lock:
            if (mapping := self.source_games.get(legacy.base_source)) is not None:
                mapping.pop(legacy_id, None)
                mapping[game.game_id] = legacy
            self.games_by_id.pop(legacy_id, None)
            self.games_by_id[game.game_id] = legacy

            # The launch command is the reason the identity moved in the first
            # place: whatever this scan resolved is more current than what is on
            # disk. Set before the id, so nothing can observe the new id on a
            # record still holding the stale command.
            legacy.executable = game.executable
            legacy.game_id = game.game_id
            # Retires the old key as it goes. Leaving one behind would leave the
            # index naming a path this game no longer has, and the anchor grants
            # file migration — a different game importing from that freed name
            # would find this one under it and take its save file, cover and
            # logo.
            self._reindex_shortcut(legacy, game.shortcut_path)

        # The cover widget is cached by id too, and DisplayManager does a
        # read-modify-write on that map from the main thread — so the re-key has
        # to happen there, not here, or the two interleave and the grid ends up
        # holding a cover the game no longer points at.
        def rekey_cover() -> bool:
            if shared.win is not None:
                cover = shared.win.game_covers.pop(legacy_id, None)
                if cover is not None:
                    shared.win.game_covers[game.game_id] = cover
                    # Its file moved with the rest: left on the old name, the
                    # blur fell back to the placeholder and the animation was
                    # gone until the next restart.
                    if cover.path is not None and cover.path.stem == legacy_id:
                        cover.new_cover(
                            shared.covers_dir / f"{game.game_id}{cover.path.suffix}"
                        )
            return GLib.SOURCE_REMOVE

        GLib.idle_add(rekey_cover)

        legacy.save()
        return legacy

    def add_game(
        self, game: Game, additional_data: dict, run_pipeline: bool = True
    ) -> Optional[Pipeline]:
        """Add a game to the app"""

        # Ignore games from a newer spec version
        if game.version > shared.SPEC_VERSION:
            return None

        stored_game = self.get(game.game_id)

        # Nothing under this id — but the game may be filed under one an older
        # version of the app derived differently. Adopt it rather than importing
        # a duplicate beside an original that `remove_games` would then delete.
        if stored_game is None:
            stored_game = self.adopt_legacy_game(
                game,
                additional_data.get("legacy_game_ids") or (),
                anchor=bool(additional_data.get("identity_anchor")),
            )

        # A removed game loaded from disk is kept as a "tombstone": it stays in
        # the store (so later scans know it was removed) but is never shown or
        # run through the pipeline. This is what stops a still-present shortcut
        # from re-adding a game the user deleted.
        if game.removed:
            if not stored_game:
                with self._lock:
                    self.source_games.setdefault(game.base_source, {})[
                        game.game_id
                    ] = game
                    self.games_by_id[game.game_id] = game
                    self._index_shortcut(game)
            return None

        # Handle game duplicates
        if not stored_game:
            # New game, do as normal
            logging.debug("New store game %s (%s)", game.name, game.game_id)
            self.new_game_ids.add(game.game_id)
        elif stored_game.removed:
            # Matches a tombstone. Only bring the game back if this shortcut is
            # newer than the one that was removed (i.e. it was reinstalled);
            # otherwise it's the same removed shortcut still in the folder, so
            # leave it removed and ignore the import.
            if game.shortcut_mtime <= stored_game.shortcut_mtime:
                logging.debug("Ignoring removed game %s (%s)", game.name, game.game_id)
                self.duplicate_game_ids.add(game.game_id)
                return None
            logging.debug(
                "Reinstall detected, restoring %s (%s)", game.name, game.game_id
            )
            self.cleanup_game(stored_game)
            self.new_game_ids.add(game.game_id)
        else:
            # Duplicate game, ignore it. Keep the tracked shortcut mtime current
            # so that, if this game is later removed, the tombstone reflects the
            # real file (and only a genuine future change counts as a reinstall).
            changed = False
            if game.shortcut_mtime > stored_game.shortcut_mtime:
                stored_game.shortcut_mtime = game.shortcut_mtime
                changed = True
            # Before the rename below, and that ordering is load-bearing:
            # `_is_derived_command` recognises the fallback command by comparing
            # it against the shortcut path, so following the rename first would
            # move the path out from under the comparison and leave a game stuck
            # on a fallback pointing at a file that no longer exists.
            if self._refresh_derived_executable(stored_game, game):
                changed = True
            # Follow a renamed shortcut. Renaming one changes no identity in
            # this source — a classic shortcut hashes its target, a Store one
            # the AUMID the file carries — so this branch is where a rename
            # lands, and dropping it left the record naming a file that no
            # longer exists and the anchor index holding a freed name.
            #
            # Only when the stored path is gone, though. Two shortcut files can
            # point at one game (a Start menu scanned recursively has plenty),
            # and they are duplicates of each other, not a rename: without this
            # test they took turns claiming the record, saving it twice per scan
            # and leaving which path it named up to iteration order.
            if (
                game.shortcut_path
                and game.shortcut_path != stored_game.shortcut_path
                and not (
                    stored_game.shortcut_path
                    and Path(stored_game.shortcut_path).exists()
                )
            ):
                with self._lock:
                    self._reindex_shortcut(stored_game, game.shortcut_path)
                changed = True
            # Reclaim the key if it is going spare. A contested path is poisoned
            # and stays that way — but when one of the two claimants later moves
            # off it, `_reindex_shortcut` pops whatever the key held, and the
            # record that legitimately stayed there has no other route back into
            # the index: from its first scan onward it is always a duplicate,
            # and duplicates were the one branch that never indexed. The anchor
            # was then unavailable for that path until the next startup, which
            # is precisely the chain it exists to cover, failing silently.
            #
            # Safe because `_index_shortcut` decides, not this call: an absent
            # key is claimed, a poisoned one is left poisoned, and the same id is
            # simply reasserted. It rebuilds what the pop removed and undoes no
            # contest.
            with self._lock:
                self._index_shortcut(stored_game)
            if changed:
                stored_game.save()
            logging.debug("Duplicate store game %s (%s)", game.name, game.game_id)
            self.duplicate_game_ids.add(game.game_id)
            return None

        # Connect signals
        for manager in self.managers.values():
            for signal in manager.signals:
                game.connect(signal, manager.run)

        # Add the game to the store
        with self._lock:
            if not game.base_source in self.source_games:
                self.source_games[game.base_source] = {}
            self.source_games[game.base_source][game.game_id] = game
            self.games_by_id[game.game_id] = game
            self._index_shortcut(game)

        # Run the pipeline for the game.
        #
        # The pipeline is intentionally *not* retained by the Store. It is kept
        # alive for the duration of its work by its real owners — the Importer's
        # ``game_pipelines`` set during an import, and, for the synchronous
        # startup load, by the in-flight Gio.Task whose completion callback is a
        # bound method of the pipeline. Once that work finishes the pipeline (and
        # the Game widget it references) becomes collectable. A previous version
        # stashed every pipeline in a ``self.pipelines`` dict that was never read
        # or cleared, which pinned every game — including removed ones and those
        # dropped on a library reset — in memory for the lifetime of the process.
        if not run_pipeline:
            return None
        pipeline = Pipeline(game, additional_data, self.pipeline_managers)
        pipeline.advance()
        return pipeline
