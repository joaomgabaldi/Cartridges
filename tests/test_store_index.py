# test_store_index.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The anchor index, the duplicate branch, and the store's thread safety.

The anchor authorises moving one game's save file onto another id, so an
ambiguous answer has to be no answer — that is what the poisoning below is for.
The duplicate branch is the other half: it is where a rescan of a game we
already have lands, and therefore the only place a stale launch command or a
renamed shortcut can ever be corrected.
"""

import threading

import pytest

from cartridges.store.store import Store, _is_derived_command, _path_key

A_ID = "shortcuts_aaaaaaaaaaaaaaaa"
B_ID = "shortcuts_bbbbbbbbbbbbbbbb"
C_ID = "shortcuts_cccccccccccccccc"
PATH = "D:\\Atalhos\\Halo.lnk"


def key_for(path, source="shortcuts"):
    """The index key for a path, derived the way the store derives it.

    Deliberately not a hardcoded tuple: the key's shape is an internal decision
    that has already changed once (separator and case folding were added when a
    library written by one interpreter stopped matching itself), and a test that
    restates it by hand breaks for the wrong reason when it changes again.
    """
    return (source, _path_key(path))


KEY = key_for(PATH)


@pytest.fixture
def seed(store):
    def seeder(game):
        store.add_game(game, {})
        store.new_game_ids = set()
        store.duplicate_game_ids = set()
        return game

    return seeder


# ---------------------------------------------------------------------------
# 1.4 The anchor index
# ---------------------------------------------------------------------------


def test_new_game_with_a_shortcut_is_indexed(store, make_game, seed):
    """T1.21"""
    game = seed(make_game(game_id=A_ID, shortcut_path=PATH))
    assert store._games_by_shortcut[KEY] is game


def test_empty_shortcut_path_is_never_indexed(store, make_game, seed):
    """T1.22 A game with no shortcut has no anchor to be found by."""
    seed(make_game(game_id=A_ID, shortcut_path=""))
    assert store._games_by_shortcut == {}


def test_a_second_claimant_poisons_the_key(store, make_game, seed):
    """T1.23 Two records naming one path is ambiguous, and ambiguity is not a match."""
    seed(make_game(game_id=A_ID, shortcut_path=PATH))
    seed(make_game(game_id=B_ID, shortcut_path=PATH))

    assert store._games_by_shortcut[KEY] is None


def test_a_poisoned_key_produces_no_adoption(store, make_game, seed):
    """T1.24 The whole point: a guess here costs a game's save file."""
    seed(make_game(game_id=A_ID, shortcut_path=PATH))
    seed(make_game(game_id=B_ID, shortcut_path=PATH))

    scanned = make_game(game_id=C_ID, shortcut_path=PATH)
    assert store.adopt_legacy_game(scanned, [], anchor=True) is None


def test_a_third_claimant_does_not_settle_a_poisoned_key(store, make_game, seed):
    """T1.25 Arriving later is not evidence of being right."""
    seed(make_game(game_id=A_ID, shortcut_path=PATH))
    seed(make_game(game_id=B_ID, shortcut_path=PATH))
    seed(make_game(game_id=C_ID, shortcut_path=PATH))

    assert store._games_by_shortcut[KEY] is None


def test_same_game_id_reclaims_the_key(store, make_game, seed):
    """T1.26 The reinstall path swaps a tombstone for the game that came back."""
    seed(make_game(game_id=A_ID, shortcut_path=PATH, removed=True))
    returned = make_game(game_id=A_ID, shortcut_path=PATH)

    with store._lock:
        store._index_shortcut(returned)

    assert store._games_by_shortcut[KEY] is returned


def test_reindex_retires_the_old_key_and_claims_the_new(store, make_game, seed):
    """T1.27 Leaving the old key behind is what let a freed name steal a record."""
    game = seed(make_game(game_id=A_ID, shortcut_path=PATH))
    new_path = "D:\\Atalhos\\Halo Infinite.lnk"

    with store._lock:
        store._reindex_shortcut(game, new_path)

    assert KEY not in store._games_by_shortcut
    assert store._games_by_shortcut[key_for(new_path)] is game
    assert game.shortcut_path == new_path


def test_reindex_into_a_claimed_path_poisons_rather_than_steals(
    store, make_game, seed
):
    """T1.28 Moving in on another record's path is still ambiguous."""
    seed(make_game(game_id=A_ID, shortcut_path=PATH))
    mover = seed(make_game(game_id=B_ID, shortcut_path="D:\\Atalhos\\Other.lnk"))

    with store._lock:
        store._reindex_shortcut(mover, PATH)

    assert store._games_by_shortcut[KEY] is None


def test_a_freed_key_is_reclaimed_without_waiting_for_a_restart(
    store, make_game, seed, tmp_path
):
    """T1.29 A contested path that stops being contested must become usable again.

    Indexing only happened for genuinely new games, so once a poisoned key was
    popped by a rename the record still sitting on that path never re-indexed:
    the anchor stayed dead for that path until the next boot rebuilt the index
    from disk. The anchor is the last line of defence against losing a game, so
    it going quiet is exactly the wrong failure.
    """
    lnk = tmp_path / "Halo.lnk"
    lnk.write_text("x", encoding="utf-8")
    key = key_for(str(lnk))

    stayer = seed(make_game(game_id=A_ID, shortcut_path=str(lnk)))
    leaver = seed(make_game(game_id=B_ID, shortcut_path=str(lnk)))
    assert store._games_by_shortcut[key] is None  # contested

    # The leaver moves off the path, which pops the key.
    with store._lock:
        store._reindex_shortcut(leaver, str(tmp_path / "Elsewhere.lnk"))
    assert key not in store._games_by_shortcut

    # A rescan of the game that stayed goes through the duplicate branch.
    store.add_game(make_game(game_id=A_ID, shortcut_path=str(lnk)), {})

    assert store._games_by_shortcut[key] is stayer


def test_the_duplicate_branch_does_not_cure_a_still_contested_key(
    store, make_game, seed, tmp_path
):
    """T1.30 Reclaiming a freed key must not be confused with resolving ambiguity."""
    lnk = tmp_path / "Halo.lnk"
    lnk.write_text("x", encoding="utf-8")
    key = key_for(str(lnk))

    seed(make_game(game_id=A_ID, shortcut_path=str(lnk)))
    seed(make_game(game_id=B_ID, shortcut_path=str(lnk)))
    assert store._games_by_shortcut[key] is None

    store.add_game(make_game(game_id=A_ID, shortcut_path=str(lnk)), {})

    assert store._games_by_shortcut[key] is None


def test_a_live_record_takes_the_key_from_a_tombstone(store, make_game, seed):
    """A dead record beside a live one is not an ambiguity.

    This pair is the wreckage of the retarget bug: the game was imported again
    under a new id while its old record was marked removed, and both name the
    shortcut they came from. Poisoning it disarmed the anchor for exactly the
    games that had already been bitten once.
    """
    seed(make_game(game_id=A_ID, shortcut_path=PATH, removed=True))
    live = seed(make_game(game_id=B_ID, shortcut_path=PATH))

    assert store._games_by_shortcut[KEY] is live


def test_a_tombstone_does_not_take_the_key_from_a_live_record(store, make_game, seed):
    """The other arrival order must reach the same answer.

    The disk is read in whatever order the directory hands over, and that must
    not decide which record an anchor authorises a save file to move onto.
    """
    live = seed(make_game(game_id=A_ID, shortcut_path=PATH))
    seed(make_game(game_id=B_ID, shortcut_path=PATH, removed=True))

    assert store._games_by_shortcut[KEY] is live


def test_a_lone_tombstone_stays_indexed(store, make_game, seed):
    """Without this, a game removed on purpose resurrects itself on a patch.

    Its shortcut is still in the folder — that is what the tombstone is for —
    so a retarget gives it a new id, finds no anchor, and imports it as new.
    """
    tombstone = seed(make_game(game_id=A_ID, shortcut_path=PATH, removed=True))

    assert store._games_by_shortcut[KEY] is tombstone


def test_two_tombstones_still_poison_the_key(store, make_game, seed):
    """Nothing to prefer between two dead records, so there is no answer to give."""
    seed(make_game(game_id=A_ID, shortcut_path=PATH, removed=True))
    seed(make_game(game_id=B_ID, shortcut_path=PATH, removed=True))

    assert store._games_by_shortcut[KEY] is None


def test_removal_in_place_is_seen_by_the_tie_break(store, make_game, seed):
    """``remove_games`` flips the flag on records already in the index.

    The rule reads the stored object, not a snapshot taken when it was indexed,
    so a record that dies after indexing loses the key to a live claimant just
    the same. Reversed, this is the whole scenario: the tombstone below is
    created exactly the way the importer creates one.
    """
    dying = seed(make_game(game_id=A_ID, shortcut_path=PATH))
    assert store._games_by_shortcut[KEY] is dying

    dying.removed = True  # what remove_games does
    live = seed(make_game(game_id=B_ID, shortcut_path=PATH))

    assert store._games_by_shortcut[KEY] is live


def test_a_poisoned_key_is_not_settled_by_a_tombstone(store, make_game, seed):
    """The live-vs-live contest stays unresolved whoever shows up next."""
    seed(make_game(game_id=A_ID, shortcut_path=PATH))
    seed(make_game(game_id=B_ID, shortcut_path=PATH))
    seed(make_game(game_id=C_ID, shortcut_path=PATH, removed=True))

    assert store._games_by_shortcut[KEY] is None


def test_the_tie_break_restores_adoption_for_a_wrecked_library(store, make_game, seed):
    """The end-to-end point of the tie-break, on the state a real library holds.

    A tombstone from the first retarget sits beside the record that replaced it.
    Before the tie-break the key was poisoned, so the *second* patch lost the
    record too — the fix installed and the bug reproducing anyway.
    """
    seed(make_game(game_id=A_ID, shortcut_path=PATH, removed=True))
    live = seed(make_game(game_id=B_ID, shortcut_path=PATH, playtime=9000))

    repatched = make_game(game_id=C_ID, shortcut_path=PATH)
    assert store.add_game(repatched, {"identity_anchor": PATH}) is None

    assert store.get(C_ID) is live
    assert live.playtime == 9000
    assert C_ID in store.duplicate_game_ids


def test_the_anchor_matches_across_a_separator_difference(store, make_game, seed):
    """One side of this key comes from the JSON, the other from the live scan.

    A library written by one interpreter and rescanned by another has one of
    each convention, and the anchor is keyed by exactly this value — so a miss
    here is not a cosmetic mismatch, it is the game being imported again and its
    old record removed with everything on it. This is the data-loss route the
    anchor exists to cover, failing through the door it was built to guard.
    """
    stored = seed(make_game(game_id=A_ID, shortcut_path="D:\\Atalhos\\Halo.lnk"))

    found = store.adopt_legacy_game(
        make_game(game_id=B_ID, shortcut_path="D:/Atalhos/Halo.lnk"), [], anchor=True
    )

    assert found is stored


def test_the_anchor_matches_across_a_case_difference(store, make_game, seed):
    """Windows paths are case-insensitive; Python strings are not.

    Re-picking the shortcuts folder with a different capitalisation is enough to
    produce this.
    """
    stored = seed(make_game(game_id=A_ID, shortcut_path="D:\\Atalhos\\Halo.lnk"))

    found = store.adopt_legacy_game(
        make_game(game_id=B_ID, shortcut_path="d:\\atalhos\\halo.lnk"), [], anchor=True
    )

    assert found is stored


def test_one_path_in_two_conventions_is_not_two_claimants(store, make_game, seed):
    """...and must not poison the key either.

    Poisoning is the right answer to a genuinely ambiguous path. Two spellings
    of one path are not ambiguous, and treating them as such would silently
    disarm the anchor for that shortcut.
    """
    stored = seed(make_game(game_id=A_ID, shortcut_path="D:\\Atalhos\\Halo.lnk"))

    store.add_game(make_game(game_id=A_ID, shortcut_path="D:/Atalhos/Halo.lnk"), {})

    assert store._games_by_shortcut[key_for("D:\\Atalhos\\Halo.lnk")] is stored


# ---------------------------------------------------------------------------
# 1.5 The duplicate branch
# ---------------------------------------------------------------------------


def test_shortcut_mtime_advances_but_never_goes_back(store, make_game, seed):
    """T1.31 The tombstone must reflect the real file, and only ever move forward."""
    stored = seed(make_game(game_id=A_ID, shortcut_mtime=100))

    store.add_game(make_game(game_id=A_ID, shortcut_mtime=200), {})
    assert stored.shortcut_mtime == 200

    store.add_game(make_game(game_id=A_ID, shortcut_mtime=150), {})
    assert stored.shortcut_mtime == 200


def test_packaged_command_is_refreshed_when_the_aumid_changes(store, make_game, seed):
    """T1.32 A title update can re-issue the app id; nothing else would fix it."""
    stored = seed(
        make_game(game_id=A_ID, executable="explorer.exe shell:AppsFolder\\Old_h!App")
    )

    store.add_game(
        make_game(game_id=A_ID, executable="explorer.exe shell:AppsFolder\\New_h!App"),
        {},
    )

    assert stored.executable == "explorer.exe shell:AppsFolder\\New_h!App"
    assert stored.saves == 1


def test_packaged_command_may_degrade_to_the_shortcut_fallback(store, make_game, seed):
    """T1.33 An unresolvable AUMID falls back to launching the .lnk itself."""
    stored = seed(
        make_game(
            game_id=A_ID,
            shortcut_path=PATH,
            executable="explorer.exe shell:AppsFolder\\Old_h!App",
        )
    )

    store.add_game(
        make_game(game_id=A_ID, shortcut_path=PATH, executable=f'start "" "{PATH}"'),
        {},
    )

    assert stored.executable == f'start "" "{PATH}"'


def test_the_shortcut_fallback_is_not_absorbing(store, make_game, seed):
    """T1.34 The way back has to be recognised as derived, or degradation is permanent.

    Testing only for an AUMID made the fallback a one-way door: one incomplete
    ``Get-StartApps`` degraded a working command forever, because the command
    that would fix it was not recognised as ours to replace.
    """
    stored = seed(
        make_game(
            game_id=A_ID,
            shortcut_path=PATH,
            executable=f'start "" "{PATH}"',
        )
    )

    store.add_game(
        make_game(
            game_id=A_ID,
            shortcut_path=PATH,
            executable="explorer.exe shell:AppsFolder\\Real_h!App",
        ),
        {},
    )

    assert stored.executable == "explorer.exe shell:AppsFolder\\Real_h!App"


def test_classic_command_is_never_refreshed(store, make_game, seed):
    """T1.35 For a classic game the command *is* the identity."""
    stored = seed(
        make_game(game_id=A_ID, executable='start "" "C:\\Games\\halo.exe"')
    )

    store.add_game(
        make_game(game_id=A_ID, executable='start "" "D:\\Elsewhere\\halo.exe"'), {}
    )

    assert stored.executable == 'start "" "C:\\Games\\halo.exe"'
    assert stored.saves == 0


def test_url_command_is_never_refreshed(store, make_game, seed):
    """T1.36 A .url hashes its URL, so a changed command is a different game."""
    stored = seed(make_game(game_id=A_ID, executable='start "" "steam://rungameid/1"'))

    store.add_game(
        make_game(game_id=A_ID, executable='start "" "steam://rungameid/2"'), {}
    )

    assert stored.executable == 'start "" "steam://rungameid/1"'


def test_an_identical_command_writes_nothing(store, make_game, seed):
    """T1.37 The equality guard is the strongest lock, and it runs first."""
    command = "explorer.exe shell:AppsFolder\\Same_h!App"
    stored = seed(make_game(game_id=A_ID, executable=command))

    store.add_game(make_game(game_id=A_ID, executable=command), {})

    assert stored.saves == 0


def test_classic_shortcut_with_appsfolder_in_arguments_is_held_by_equality(
    store, make_game
):
    """T1.38 Two locks in series: the shape test passes, the equality test stops it.

    A classic .lnk can carry ``shell:AppsFolder`` in its arguments, which makes
    it look derived. It is safe anyway, because its identity is
    ``target|arguments`` — so a rescan rebuilds a byte-identical command and the
    equality guard returns before anything is written.
    """
    command = 'start "" "C:\\Games\\launch.exe" --open shell:AppsFolder\\Foo!Bar'
    stored = make_game(game_id=A_ID, executable=command)
    rescanned = make_game(game_id=A_ID, executable=command)

    assert _is_derived_command(stored) is True, "first lock: it does look derived"
    assert Store._refresh_derived_executable(stored, rescanned) is False


def test_the_fallback_is_recognised_across_a_separator_difference(store, make_game):
    """The two sides of this comparison age differently.

    ``executable`` is rewritten by a rescan while ``shortcut_path`` is not, so a
    library that changed interpreters has one in each convention. Compared as
    plain strings, a game sitting on the fallback stopped looking derived — and
    the absorbing fallback came back in through the separator door, with a
    degraded command that could never be lifted back onto its AUMID.
    """
    stored = make_game(
        game_id=A_ID,
        shortcut_path="D:\\Atalhos\\Halo.lnk",
        executable='start "" "D:/Atalhos/Halo.lnk"',
    )

    assert _is_derived_command(stored) is True


def test_the_fallback_is_recognised_across_a_case_difference(store, make_game):
    stored = make_game(
        game_id=A_ID,
        shortcut_path="D:\\Atalhos\\Halo.lnk",
        executable='start "" "d:\\atalhos\\halo.lnk"',
    )

    assert _is_derived_command(stored) is True


def test_a_command_naming_another_file_is_not_derived(store, make_game):
    """The normalisation must not turn the test into "anything goes"."""
    stored = make_game(
        game_id=A_ID,
        shortcut_path="D:\\Atalhos\\Halo.lnk",
        executable='start "" "D:\\Atalhos\\Doom.lnk"',
    )

    assert _is_derived_command(stored) is False


def test_rename_is_followed_only_when_the_stored_path_is_gone(
    store, make_game, seed, tmp_path
):
    """T1.39"""
    gone = tmp_path / "Halo.lnk"
    present = tmp_path / "Halo Infinite.lnk"
    present.write_text("x", encoding="utf-8")

    stored = seed(make_game(game_id=A_ID, shortcut_path=str(gone)))
    store.add_game(make_game(game_id=A_ID, shortcut_path=str(present)), {})
    assert stored.shortcut_path == str(present)

    # Now the stored path exists, so a third file is a duplicate, not a rename.
    other = tmp_path / "Halo Copy.lnk"
    other.write_text("x", encoding="utf-8")
    store.add_game(make_game(game_id=A_ID, shortcut_path=str(other)), {})
    assert stored.shortcut_path == str(present)


def test_two_shortcuts_for_one_game_save_once_and_settle(
    store, make_game, seed, tmp_path
):
    """T1.40 They are duplicates of each other, not a rename.

    Without the existence test they took turns claiming the record, saving it
    twice per scan and leaving which path it named up to iteration order.
    """
    first = tmp_path / "Halo.lnk"
    second = tmp_path / "Halo (2).lnk"
    for path in (first, second):
        path.write_text("x", encoding="utf-8")

    stored = seed(make_game(game_id=A_ID, shortcut_path=str(first)))

    for _ in range(2):  # two scans
        store.add_game(make_game(game_id=A_ID, shortcut_path=str(first)), {})
        store.add_game(make_game(game_id=A_ID, shortcut_path=str(second)), {})

    assert stored.saves == 0
    assert stored.shortcut_path == str(first)


def test_one_save_when_mtime_and_command_both_change(store, make_game, seed):
    """T1.41 The branch batches its writes into a single save."""
    stored = seed(
        make_game(
            game_id=A_ID,
            shortcut_mtime=1,
            executable="explorer.exe shell:AppsFolder\\Old_h!App",
        )
    )

    store.add_game(
        make_game(
            game_id=A_ID,
            shortcut_mtime=2,
            executable="explorer.exe shell:AppsFolder\\New_h!App",
        ),
        {},
    )

    assert stored.saves == 1


def test_nothing_changed_means_no_save(store, make_game, seed):
    """T1.42 A rescan of an unchanged library must not rewrite it."""
    stored = seed(make_game(game_id=A_ID, shortcut_mtime=5, shortcut_path=PATH))

    store.add_game(make_game(game_id=A_ID, shortcut_mtime=5, shortcut_path=PATH), {})

    assert stored.saves == 0


# ---------------------------------------------------------------------------
# 1.6 Concurrency
# ---------------------------------------------------------------------------


def test_iteration_is_a_snapshot(store, make_game, seed):
    """T1.43 ``for game in store`` used to die partway through an import."""
    for index in range(5):
        seed(make_game(game_id=f"shortcuts_{index:016d}"))

    seen = []
    for game in store:
        seen.append(game)
        if len(seen) == 1:
            store.add_game(make_game(game_id="shortcuts_9999999999999999"), {})

    assert len(seen) == 5


def test_concurrent_add_game_while_iterating(store, make_game):
    """T1.44 Import workers add while the main thread lays out the library."""
    errors: list = []
    total = 60

    def adder(start: int) -> None:
        try:
            for index in range(start, start + 20):
                store.add_game(make_game(game_id=f"shortcuts_{index:016d}"), {})
        except Exception as error:  # pylint: disable=broad-exception-caught
            errors.append(error)

    threads = [threading.Thread(target=adder, args=(base,)) for base in (0, 20, 40)]
    for thread in threads:
        thread.start()
    for _ in range(200):
        try:
            list(store)
        except Exception as error:  # pylint: disable=broad-exception-caught
            errors.append(error)
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(store) == total


def test_clear_empties_all_three_indexes(store, make_game, seed):
    """T1.45 A library reset must not leave an anchor pointing at a dropped game."""
    seed(make_game(game_id=A_ID, shortcut_path=PATH))

    store.clear()

    assert store.games_by_id == {}
    assert store.source_games == {}
    assert store._games_by_shortcut == {}


def test_cleanup_game_dismisses_toasts_on_the_idle(
    store, make_game, seed, win, flush_idle
):
    """T1.46 Toasts are libadwaita widgets and this runs on an import worker."""
    game = seed(make_game(game_id=A_ID))
    toast = object()
    win.toasts[(game, "remove")] = toast

    store.cleanup_game(game)

    assert win.toast_queue.dismissed == [], "must not touch widgets inline"
    flush_idle()
    assert win.toast_queue.dismissed == [toast]
