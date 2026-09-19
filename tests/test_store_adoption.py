# test_store_adoption.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Adoption: keeping a game's data when the id it is filed under changes.

A game id is a hash of how the game is identified, so any change to what goes
into that identity renames every affected game — and a renamed game is, to the
rest of the app, a new game plus a missing one. ``remove_games`` then deletes
the missing one, taking playtime, cover, logo and update tracking with it,
permanently: coming back requires the shortcut's mtime to rise, and nothing
touched the file.

That is the failure these tests exist to prevent. Every case here is either a
bug that already happened or the guard that stopped it.
"""

import json
import threading
import types

import pytest

from cartridges import shared
from cartridges.store import store as store_module
from cartridges.store.store import _path_key


def key_for(path, source="shortcuts"):
    """The anchor index key for a path, derived the way the store derives it."""
    return (source, _path_key(path))


@pytest.fixture
def seed(store):
    """Add a game the way a previous run would have left it, then start clean.

    The id bookkeeping is reset afterwards because ``Importer.__init__`` does
    the same at the top of every import: a test about what *this* scan does
    must not see the previous one's ids.
    """

    def seeder(game):
        store.add_game(game, {})
        store.new_game_ids = set()
        store.duplicate_game_ids = set()
        return game

    return seeder


OLD_ID = "shortcuts_1111111111111111"
NEW_ID = "shortcuts_2222222222222222"
LNK = "D:\\Atalhos\\Halo.lnk"


# ---------------------------------------------------------------------------
# 1.1 Adoption — matching
# ---------------------------------------------------------------------------


def test_adopts_by_legacy_game_id(store, make_game, seed):
    """T1.1 The record is re-filed, not duplicated, and keeps its playtime."""
    legacy = seed(
        make_game(game_id=OLD_ID, playtime=4321, shortcut_path=LNK, name="Halo")
    )
    scanned = make_game(game_id=NEW_ID, shortcut_path=LNK, name="Halo")

    assert store.add_game(scanned, {"legacy_game_ids": [OLD_ID]}) is None

    assert store.get(NEW_ID) is legacy
    assert store.get(OLD_ID) is None
    assert legacy.playtime == 4321
    assert len(store) == 1
    assert NEW_ID in store.duplicate_game_ids
    assert NEW_ID not in store.new_game_ids


def test_adopts_by_anchor_without_any_legacy_id(store, make_game, seed):
    """T1.2 The shortcut file is the fallback when no legacy id can be replayed.

    This is the case that matters most: when the AUMID cannot be resolved, the
    scan cannot compute the id the game was filed under, so it offers none.
    """
    legacy = seed(make_game(game_id=OLD_ID, playtime=77, shortcut_path=LNK))
    scanned = make_game(game_id=NEW_ID, shortcut_path=LNK)

    assert store.add_game(scanned, {"identity_anchor": LNK}) is None

    assert store.get(NEW_ID) is legacy
    assert legacy.playtime == 77
    assert len(store) == 1


def test_does_not_adopt_by_anchor_without_the_opt_in(store, make_game, seed):
    """T1.3 Loading the library from disk must never merge two records.

    Two records naming one shortcut is a state the disk can hold — a stale
    record beside its replacement — and ``load_games_from_disk`` passes no
    ``identity_anchor``. Reading that as "the same game" merged one game's save
    file into another's on startup.
    """
    seed(make_game(game_id=OLD_ID, shortcut_path=LNK))
    other = make_game(game_id=NEW_ID, shortcut_path=LNK)

    store.add_game(other, {"skip_save": True})

    assert store.get(OLD_ID) is not None
    assert store.get(NEW_ID) is other
    assert len(store) == 2


def test_does_not_adopt_itself(store, make_game, seed):
    """T1.4 Offering the id the game already has is not a migration."""
    game = seed(make_game(game_id=OLD_ID, shortcut_path=LNK))

    assert store.adopt_legacy_game(game, [OLD_ID]) is None
    assert store.get(OLD_ID) is game


def test_does_not_adopt_across_sources(store, make_game, seed):
    """T1.5 Same path, different source, different game."""
    seed(make_game(game_id="steam_1111111111111111", source="steam", shortcut_path=LNK))
    scanned = make_game(game_id=NEW_ID, source="shortcuts", shortcut_path=LNK)

    assert store.add_game(scanned, {"identity_anchor": LNK}) is not None
    assert len(store) == 2


def test_refuses_a_stale_index_entry(store, make_game, seed):
    """T1.6 An anchor naming a record the store has dropped must not migrate.

    Its ``game_id`` is by then the id of the *live* record that replaced it, so
    migrating would move a living game's save file, cover and logo onto this
    one and unfile the game itself.
    """
    stale = seed(make_game(game_id=OLD_ID, shortcut_path=LNK))
    # The store drops it and something else takes the id it claims.
    store.games_by_id.pop(OLD_ID)
    store.source_games["shortcuts"].pop(OLD_ID)
    live = make_game(game_id=OLD_ID, shortcut_path="D:\\Atalhos\\Other.lnk")
    store.add_game(live, {})
    store._games_by_shortcut[key_for(LNK)] = stale  # index still names it

    scanned = make_game(game_id=NEW_ID, shortcut_path=LNK)
    assert store.adopt_legacy_game(scanned, [], anchor=True) is None
    assert store.get(OLD_ID) is live


def test_stale_index_entry_migrates_no_files(store, make_game, seed, write_record):
    """T1.6 (effects) A refused adoption must not have touched the disk."""
    stale = seed(make_game(game_id=OLD_ID, shortcut_path=LNK))
    write_record(OLD_ID)
    store.games_by_id.pop(OLD_ID)
    store.source_games["shortcuts"].pop(OLD_ID)
    store._games_by_shortcut[key_for(LNK)] = stale

    scanned = make_game(game_id=NEW_ID, shortcut_path=LNK)
    store.adopt_legacy_game(scanned, [], anchor=True)

    assert (shared.games_dir / f"{OLD_ID}.json").exists()
    assert not (shared.games_dir / f"{NEW_ID}.json").exists()


def test_legacy_id_wins_over_the_anchor(store, make_game, seed):
    """T1.7 The exact answer beats the fallback when both match."""
    by_id = seed(make_game(game_id=OLD_ID, name="by legacy id"))
    other_path = "D:\\Atalhos\\Other.lnk"
    seed(
        make_game(
            game_id="shortcuts_3333333333333333",
            name="by anchor",
            shortcut_path=other_path,
        )
    )
    scanned = make_game(game_id=NEW_ID, shortcut_path=other_path)

    adopted = store.adopt_legacy_game(scanned, [OLD_ID], anchor=True)
    assert adopted is by_id


# ---------------------------------------------------------------------------
# 1.2 Adoption — effects
# ---------------------------------------------------------------------------


def test_migrates_record_cover_and_logo(
    store, make_game, seed, write_record, write_asset
):
    """T1.8 All three sets of files move together."""
    seed(make_game(game_id=OLD_ID, shortcut_path=LNK))
    write_record(OLD_ID)
    write_asset("covers", f"{OLD_ID}.tiff", b"cover")
    write_asset("logos", f"{OLD_ID}.png", b"logo")
    (shared.logos_dir / f"{OLD_ID}.json").write_text(
        json.dumps({"name": "Halo", "file": f"{OLD_ID}.png", "locked": False}),
        encoding="utf-8",
    )

    store.adopt_legacy_game(make_game(game_id=NEW_ID, shortcut_path=LNK), [OLD_ID])

    assert (shared.games_dir / f"{NEW_ID}.json").read_text(encoding="utf-8")
    assert (shared.covers_dir / f"{NEW_ID}.tiff").read_bytes() == b"cover"
    assert (shared.logos_dir / f"{NEW_ID}.png").read_bytes() == b"logo"
    assert not (shared.games_dir / f"{OLD_ID}.json").exists()
    assert not (shared.covers_dir / f"{OLD_ID}.tiff").exists()
    assert not (shared.logos_dir / f"{OLD_ID}.png").exists()


@pytest.mark.parametrize("suffix", [".tiff", ".gif", ".webp"])
def test_migrates_every_cover_format(
    store, make_game, seed, write_asset, suffix
):
    """T1.8 Animated covers are stored verbatim, so they have their own names."""
    seed(make_game(game_id=OLD_ID))
    write_asset("covers", f"{OLD_ID}{suffix}", b"c")

    store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

    assert (shared.covers_dir / f"{NEW_ID}{suffix}").exists()


def test_restamps_the_game_id_inside_the_record(
    store, make_game, seed, write_record
):
    """T1.9 Moving a file does not change what is written inside it.

    A tombstone has no managers connected, so its ``save()`` emits a signal
    nobody listens for. Without this restamp the record kept the old id inside
    a file named after the new one, and the next startup undid the adoption and
    redid it on every scan after that.
    """
    seed(make_game(game_id=OLD_ID, shortcut_path=LNK))
    write_record(OLD_ID, playtime=99)

    store.adopt_legacy_game(make_game(game_id=NEW_ID, shortcut_path=LNK), [OLD_ID])

    data = json.loads((shared.games_dir / f"{NEW_ID}.json").read_text(encoding="utf-8"))
    assert data["game_id"] == NEW_ID
    assert data["playtime"] == 99


def test_rewrites_the_logo_sidecar_filename(store, make_game, seed):
    """T1.10 The sidecar names its image; the rename has to reach inside it."""
    seed(make_game(game_id=OLD_ID))
    (shared.logos_dir / f"{OLD_ID}.json").write_text(
        json.dumps(
            {"name": "Halo", "file": f"{OLD_ID}.png", "timestamp": 1, "locked": False}
        ),
        encoding="utf-8",
    )

    store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

    sidecar = json.loads(
        (shared.logos_dir / f"{NEW_ID}.json").read_text(encoding="utf-8")
    )
    assert sidecar["file"] == f"{NEW_ID}.png"


def test_locked_logo_survives_the_migration(store, make_game, seed):
    """T1.11 A hand-picked logo is the one thing that must never be re-fetched."""
    seed(make_game(game_id=OLD_ID))
    (shared.logos_dir / f"{OLD_ID}.json").write_text(
        json.dumps(
            {"name": "Halo", "file": f"{OLD_ID}.webp", "timestamp": 1, "locked": True}
        ),
        encoding="utf-8",
    )

    store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

    sidecar = json.loads(
        (shared.logos_dir / f"{NEW_ID}.json").read_text(encoding="utf-8")
    )
    assert sidecar["locked"] is True
    assert sidecar["file"] == f"{NEW_ID}.webp"


def test_hand_picked_wallpaper_survives_the_migration(store, make_game, seed, write_asset):
    """T1.12 The session wallpaper is filed by id too, sidecar and image."""
    seed(make_game(game_id=OLD_ID))
    write_asset("wallpapers", f"{OLD_ID}.png", b"arte")
    (shared.wallpapers_dir / f"{OLD_ID}.json").write_text(
        json.dumps({"name": "Halo", "file": f"{OLD_ID}.png", "locked": True}),
        encoding="utf-8",
    )

    store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

    assert (shared.wallpapers_dir / f"{NEW_ID}.png").read_bytes() == b"arte"
    assert not (shared.wallpapers_dir / f"{OLD_ID}.png").exists()
    sidecar = json.loads(
        (shared.wallpapers_dir / f"{NEW_ID}.json").read_text(encoding="utf-8")
    )
    assert sidecar["locked"] is True
    assert sidecar["file"] == f"{NEW_ID}.png"


def test_missing_files_do_not_break_the_migration(store, make_game, seed):
    """T1.12 A game with no cover and no logo adopts fine."""
    legacy = seed(make_game(game_id=OLD_ID, playtime=5))

    adopted = store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

    assert adopted is legacy
    assert store.get(NEW_ID) is legacy


def test_a_file_that_will_not_move_only_logs(
    store, make_game, seed, write_record, write_asset, monkeypatch, caplog
):
    """T1.12 Aborting the migration would cost the whole record; it must not."""
    seed(make_game(game_id=OLD_ID))
    write_record(OLD_ID)
    write_asset("covers", f"{OLD_ID}.tiff", b"cover")

    real_replace = store_module.Path.replace

    def flaky(self, target):
        if self.suffix == ".tiff":
            raise OSError("locked by another process")
        return real_replace(self, target)

    monkeypatch.setattr(store_module.Path, "replace", flaky)

    adopted = store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

    assert adopted is not None
    assert (shared.games_dir / f"{NEW_ID}.json").exists()  # the record still moved
    assert (shared.covers_dir / f"{OLD_ID}.tiff").exists()  # the cover stayed put


def test_rekeys_all_three_indexes(store, make_game, seed):
    """T1.13 No old key may survive in any of the three mappings."""
    legacy = seed(make_game(game_id=OLD_ID, shortcut_path=LNK))
    new_path = "D:\\Atalhos\\Halo Infinite.lnk"

    store.adopt_legacy_game(
        make_game(game_id=NEW_ID, shortcut_path=new_path), [OLD_ID]
    )

    assert OLD_ID not in store.games_by_id
    assert OLD_ID not in store.source_games["shortcuts"]
    assert key_for(LNK) not in store._games_by_shortcut
    assert store.games_by_id[NEW_ID] is legacy
    assert store.source_games["shortcuts"][NEW_ID] is legacy
    assert store._games_by_shortcut[key_for(new_path)] is legacy


def test_cover_widget_is_rekeyed_on_the_idle(
    store, make_game, seed, win, flush_idle
):
    """T1.14 ``game_covers`` is read-modify-written from the main thread.

    Doing it inline from an import worker interleaved with DisplayManager and
    left the grid holding a cover the game no longer points at.
    """
    seed(make_game(game_id=OLD_ID))
    sentinel = types.SimpleNamespace(path=None)
    win.game_covers[OLD_ID] = sentinel

    store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

    assert win.game_covers == {OLD_ID: sentinel}, "must not be done inline"
    flush_idle()
    assert win.game_covers == {NEW_ID: sentinel}


def test_adopted_record_takes_the_scanned_command_and_path(
    store, make_game, seed
):
    """T1.15 Whatever this scan resolved is more current than what is on disk."""
    legacy = seed(
        make_game(
            game_id=OLD_ID,
            shortcut_path=LNK,
            executable="explorer.exe shell:AppsFolder\\Old_h!App",
        )
    )
    new_path = "D:\\Atalhos\\Halo Infinite.lnk"
    scanned = make_game(
        game_id=NEW_ID,
        shortcut_path=new_path,
        executable="explorer.exe shell:AppsFolder\\New_h!App",
    )

    store.adopt_legacy_game(scanned, [OLD_ID])

    assert legacy.executable == "explorer.exe shell:AppsFolder\\New_h!App"
    assert legacy.shortcut_path == new_path
    assert legacy.game_id == NEW_ID


def test_an_adopted_classic_game_launches_the_new_target(store, make_game, seed):
    """A retargeted shortcut must not keep pointing at the executable it replaced.

    Worth pinning separately from T1.15 because the duplicate branch would
    refuse this: ``_refresh_derived_executable`` only ever replaces a command
    that looks generated, and a classic one does not. Adoption rewriting the
    command unconditionally is what saves it — otherwise the record survives the
    patch and then fails to launch, which is a worse outcome than losing it
    loudly.
    """
    legacy = seed(
        make_game(
            game_id=OLD_ID,
            shortcut_path=LNK,
            playtime=500,
            executable='start "" "C:\\abc.exe"',
        )
    )
    scanned = make_game(
        game_id=NEW_ID,
        shortcut_path=LNK,
        executable='start "" "C:\\abc_patched.exe"',
    )

    assert store.add_game(scanned, {"identity_anchor": LNK}) is None

    assert store.get(NEW_ID) is legacy
    assert legacy.executable == 'start "" "C:\\abc_patched.exe"'
    assert legacy.playtime == 500
    assert len(store) == 1


def test_file_migration_does_not_hold_the_store_lock(
    store, make_game, seed, monkeypatch
):
    """T1.16 The main thread lays out the library under this lock.

    Asserted by reading the lock from another thread while the migration runs,
    rather than by timing anything: an RLock is reentrant, so only a second
    thread can tell whether it was held.
    """
    seed(make_game(game_id=OLD_ID))
    acquired: list = []

    def probing_migrate(old_id, new_id):
        def probe():
            got = store._lock.acquire(timeout=2)
            acquired.append(got)
            if got:
                store._lock.release()

        thread = threading.Thread(target=probe)
        thread.start()
        thread.join(3)

    monkeypatch.setattr(store_module, "_migrate_game_files", probing_migrate)

    store.adopt_legacy_game(make_game(game_id=NEW_ID), [OLD_ID])

    assert acquired == [True]


# ---------------------------------------------------------------------------
# 1.3 Tombstone adoption — the case that has to keep working
# ---------------------------------------------------------------------------


def test_tombstone_follows_the_id_and_stays_removed(store, make_game):
    """T1.17 A game the user deleted must not come back through a rename."""
    tomb = make_game(game_id=OLD_ID, removed=True, shortcut_path=LNK, shortcut_mtime=500)
    store.add_game(tomb, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()

    scanned = make_game(game_id=NEW_ID, shortcut_path=LNK, shortcut_mtime=500)
    assert store.add_game(scanned, {"legacy_game_ids": [OLD_ID]}) is None

    assert store.get(NEW_ID) is tomb
    assert tomb.removed is True
    assert NEW_ID in store.duplicate_game_ids


def test_adopted_tombstone_is_not_in_the_library(store, make_game):
    """T1.18 It stays in the store as a tombstone, never as a game."""
    tomb = make_game(game_id=OLD_ID, removed=True, shortcut_path=LNK, shortcut_mtime=1)
    store.add_game(tomb, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()

    store.add_game(
        make_game(game_id=NEW_ID, shortcut_path=LNK, shortcut_mtime=1),
        {"legacy_game_ids": [OLD_ID]},
    )

    assert [g for g in store if not g.removed] == []
    assert NEW_ID not in store.new_game_ids


def test_adopted_tombstone_with_a_newer_shortcut_is_a_reinstall(store, make_game):
    """T1.19 A rewritten shortcut is the signal that the game came back."""
    tomb = make_game(game_id=OLD_ID, removed=True, shortcut_path=LNK, shortcut_mtime=100)
    store.add_game(tomb, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()

    scanned = make_game(game_id=NEW_ID, shortcut_path=LNK, shortcut_mtime=999)
    pipeline = store.add_game(scanned, {"legacy_game_ids": [OLD_ID]})

    assert pipeline is not None
    assert NEW_ID in store.new_game_ids
    assert store.get(NEW_ID) is scanned


def test_an_unchanged_shortcut_at_a_tombstones_path_stays_removed(store, make_game):
    """The anchor is consulted before anything is indexed, so the first game to
    arrive at a tombstone's path adopts it — the poisoning in `_index_shortcut`
    cannot help here, because there is no contested key yet.

    What makes that safe is the mtime gate rather than the index. A shortcut
    file that has not changed is the same file the user deleted, so inheriting
    the tombstone is the right answer even though the ids differ.
    """
    tomb = make_game(
        game_id=OLD_ID, removed=True, shortcut_path=LNK, shortcut_mtime=500
    )
    store.add_game(tomb, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()

    arrival = make_game(game_id=NEW_ID, shortcut_path=LNK, shortcut_mtime=500)
    assert store.add_game(arrival, {"identity_anchor": LNK}) is None

    assert [game for game in store if not game.removed] == []


def test_a_recreated_shortcut_at_a_tombstones_path_comes_back(store, make_game):
    """The other half of the same gate: a newer mtime is a different file.

    Together these two are the whole containment argument for a tombstone
    keeping a stale `shortcut_path` on disk — so both directions are pinned.
    """
    tomb = make_game(
        game_id=OLD_ID, removed=True, shortcut_path=LNK, shortcut_mtime=500
    )
    store.add_game(tomb, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()

    arrival = make_game(game_id=NEW_ID, shortcut_path=LNK, shortcut_mtime=900)
    assert store.add_game(arrival, {"identity_anchor": LNK}) is not None

    assert NEW_ID in store.new_game_ids
    assert [game.game_id for game in store if not game.removed] == [NEW_ID]


def test_tombstone_adoption_leaves_the_resurrection_gate_alone(store, make_game):
    """T1.20 ``shortcut_mtime`` is what decides a reinstall; adoption must not move it."""
    tomb = make_game(game_id=OLD_ID, removed=True, shortcut_path=LNK, shortcut_mtime=100)
    store.add_game(tomb, {})

    store.adopt_legacy_game(
        make_game(game_id=NEW_ID, shortcut_path=LNK, shortcut_mtime=999), [OLD_ID]
    )

    assert tomb.shortcut_mtime == 100
