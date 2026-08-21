# test_importer.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When it is safe to mark a game as missing.

``remove_games`` is the only code in the app that can lose a user's library, and
it is licensed by exactly one thing: the source's id being in
``scanned_source_ids``. Everything here is about that licence being granted only
for a scan that actually ran to the end.

The trap this guards is subtle enough that it was written into the code twice
and got the wrong answer once. A generator that raises is closed, so the
``continue`` that follows cannot resume it: the next ``next()`` raises
``StopIteration`` — the same exception a clean finish raises — and the loop ends
looking successful. It cannot be inferred from how the loop ended; it needs its
own flag.
"""

import pytest

from cartridges import shared
from cartridges.importer.importer import Importer
from cartridges.importer.location import UnresolvableLocationError
from cartridges.importer.source import SourceScanError


class FakeSource:
    """A source whose scan behaviour each test dictates."""

    def __init__(
        self,
        source_id="shortcuts",
        games=(),
        raises=None,
        raise_after=0,
        available=True,
        iter_raises=None,
    ):
        self.source_id = source_id
        self.name = source_id
        self._games = list(games)
        self._raises = raises
        self._raise_after = raise_after
        self.is_available = available
        self._iter_raises = iter_raises

    def __iter__(self):
        if self._iter_raises is not None:
            raise self._iter_raises
        return self._generate()

    def _generate(self):
        # Yielded as ``(game, additional_data)`` tuples, which is the shape every
        # real source produces. The bare-Game branch of the importer is typed
        # against the actual ``Game`` class, so a duck-type would be rejected as
        # an invalid return type and silently skipped.
        for index, game in enumerate(self._games):
            if self._raises is not None and index == self._raise_after:
                raise self._raises
            yield (game, {})
        if self._raises is not None and self._raise_after >= len(self._games):
            raise self._raises


@pytest.fixture
def importer(store):
    """An Importer wired to a clean store.

    ``Importer.__init__`` resets the store's id bookkeeping, which is why the
    store fixture has to come first.
    """
    return Importer()


def scan(importer_, source):
    importer_.source_task_thread_func((source,))


# ---------------------------------------------------------------------------
# Granting the licence to remove
# ---------------------------------------------------------------------------


def test_clean_scan_marks_the_source(importer, make_game):
    """T2.1"""
    scan(importer, FakeSource(games=[make_game(game_id="shortcuts_1")]))
    assert "shortcuts" in importer.scanned_source_ids


def test_generic_exception_does_not_mark_the_source(importer, make_game):
    """T2.2 The regression: a failed scan reaching the same StopIteration."""
    source = FakeSource(
        games=[make_game(game_id="shortcuts_1")],
        raises=OSError("drive went away mid-scan"),
        raise_after=1,
    )
    scan(importer, source)

    assert "shortcuts" not in importer.scanned_source_ids
    assert any(isinstance(error, OSError) for error in importer.errors)


def test_source_scan_error_does_not_mark_and_reaches_the_user(importer):
    """T2.3 A scan that quietly produces half a library is worse than one that says so."""
    source = FakeSource(raises=SourceScanError("could not resolve any .lnk"))
    scan(importer, source)

    assert "shortcuts" not in importer.scanned_source_ids
    assert any(isinstance(error, SourceScanError) for error in importer.errors)


def test_unavailable_source_does_not_mark(importer):
    """T2.4 A disconnected drive is not "every game was uninstalled"."""
    scan(importer, FakeSource(available=False))
    assert importer.scanned_source_ids == set()


def test_unresolvable_location_does_not_mark(importer):
    """T2.4"""
    scan(importer, FakeSource(iter_raises=UnresolvableLocationError()))
    assert importer.scanned_source_ids == set()


def test_partial_scan_keeps_its_games_but_not_the_licence(importer, make_game, store):
    """T2.5 Progress is kept; the authority to delete is not."""
    games = [make_game(game_id=f"shortcuts_{i}") for i in range(3)]
    source = FakeSource(games=games, raises=RuntimeError("boom"), raise_after=3)

    scan(importer, source)

    assert len(store) == 3
    assert "shortcuts" not in importer.scanned_source_ids


# ---------------------------------------------------------------------------
# remove_games filters
# ---------------------------------------------------------------------------


def test_remove_games_skips_an_unscanned_source(importer, make_game, store):
    """T2.6"""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()

    importer.remove_games()

    assert game.removed is False


def test_remove_games_removes_a_missing_game_of_a_scanned_source(
    importer, make_game, store
):
    """The positive control for every skip below."""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    importer.scanned_source_ids.add("shortcuts")

    importer.remove_games()

    assert game.removed is True
    assert "shortcuts_1" in importer.removed_game_ids


@pytest.mark.parametrize("bucket", ["duplicate_game_ids", "new_game_ids"])
def test_remove_games_skips_games_seen_this_run(importer, make_game, store, bucket):
    """T2.7 A game the scan just saw is not missing."""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()
    getattr(store, bucket).add("shortcuts_1")
    importer.scanned_source_ids.add("shortcuts")

    importer.remove_games()

    assert game.removed is False


def test_remove_games_skips_manually_added_games(importer, make_game, store):
    """T2.8 "imported" games have no source to go missing from."""
    game = make_game(game_id="imported_1", source="imported")
    store.add_game(game, {})
    store.new_game_ids = set()
    importer.scanned_source_ids.add("imported")

    importer.remove_games()

    assert game.removed is False


def test_remove_games_skips_a_source_disabled_in_the_schema(
    importer, make_game, store, schema
):
    """T2.8 A source the user turned off did not scan, whatever the ids say."""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    importer.scanned_source_ids.add("shortcuts")
    schema["shortcuts"] = False

    importer.remove_games()

    assert game.removed is False


def test_remove_missing_disabled_removes_nothing(importer, make_game, store, schema):
    """T2.9"""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    importer.scanned_source_ids.add("shortcuts")
    schema["remove-missing"] = False

    importer.remove_games()

    assert game.removed is False


def test_a_successful_empty_scan_still_removes(importer, make_game, store):
    """T2.10 An emptied folder is a real answer, not a failure.

    This is the line between the two: a source that *failed* produces nothing
    and must not remove, but a source that scanned an empty folder produces
    nothing and must. Only the completion flag tells them apart.
    """
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()

    scan(importer, FakeSource(games=[]))
    assert "shortcuts" in importer.scanned_source_ids

    importer.remove_games()

    assert game.removed is True


def test_a_tombstone_is_not_removed_again(importer, make_game, store):
    """Already-removed games are skipped, so undo history stays meaningful."""
    game = make_game(game_id="shortcuts_1", removed=True)
    store.add_game(game, {})
    importer.scanned_source_ids.add("shortcuts")

    importer.remove_games()

    assert importer.removed_game_ids == set()
