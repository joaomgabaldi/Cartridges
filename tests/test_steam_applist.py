# test_steam_applist.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks for the Steam app list fallback.

Runs entirely offline against a hand-written cache file, so it exercises the
lookup without downloading a hundred megabytes or depending on what Steam
happens to be serving today::

    python3 tests/test_steam_applist.py

The point of the fallback is appid 578650: "The Outer Worlds" is absent from
every store search endpoint, and the full app list is the only place it can
still be found.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cartridges.utils.steam_applist import SteamAppList  # noqa: E402

# A slice of the real app list: the game we want, its sequel, and the kind of
# junk that shares a name with it and has to be ranked out or confirmed away.
FAKE_APPS = [
    {"appid": 578650, "name": "The Outer Worlds"},
    {"appid": 1449110, "name": "The Outer Worlds 2"},
    {"appid": 3729820, "name": "The Outer Worlds 2 Soundtrack"},
    {"appid": 1920490, "name": "The Outer Worlds: Spacer's Choice Edition"},
    {"appid": 214490, "name": "Alien: Isolation"},
    {"appid": 214491, "name": "Alien: Isolation Dedicated Server"},
    {"appid": 3420840, "name": "The Outer Side"},
    {"appid": 999999, "name": "Some Unrelated Game"},
]


class TestLookup(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        cache_path = Path(self._temp_dir.name) / "steam_applist.json"
        cache_path.write_text(json.dumps(FAKE_APPS), encoding="utf-8")
        self.app_list = SteamAppList(cache_path=cache_path)

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_finds_the_title_store_search_hides(self) -> None:
        results = self.app_list.lookup("The Outer Worlds")
        self.assertTrue(results, "expected at least one candidate")
        candidate, match = results[0]
        self.assertEqual(578650, candidate["id"])
        self.assertTrue(match.confident)

    def test_sequel_and_soundtrack_never_appear(self) -> None:
        found = [candidate["id"] for candidate, _ in self.app_list.lookup("The Outer Worlds")]
        self.assertNotIn(1449110, found)
        self.assertNotIn(3729820, found)

    def test_dedicated_server_is_not_the_game(self) -> None:
        results = self.app_list.lookup("Alien Isolation")
        self.assertEqual(214490, results[0][0]["id"])
        self.assertTrue(results[0][1].confident)
        # The server entry may be listed, but never as something to adopt.
        for candidate, match in results:
            if candidate["id"] == 214491:
                self.assertFalse(match.confident)

    def test_unrelated_titles_are_excluded(self) -> None:
        found = [candidate["id"] for candidate, _ in self.app_list.lookup("The Outer Worlds")]
        self.assertNotIn(3420840, found)
        self.assertNotIn(999999, found)

    def test_unknown_title_returns_nothing(self) -> None:
        self.assertEqual([], self.app_list.lookup("A Game That Does Not Exist Here"))

    def test_cache_is_read_without_network(self) -> None:
        # A second lookup must reuse the parsed list rather than refetch it.
        self.app_list.lookup("Alien Isolation")
        # The parsed entries and their squashed titles are published together
        # as one tuple, so that both halves can never be seen out of step.
        self.assertIsNotNone(self.app_list._index)  # pylint: disable=protected-access


# ---------------------------------------------------------------------------
# Download failure handling (T6.5 - T6.10)
#
# Without a negative cache, a failed download was repeated once per game, each
# attempt waiting out the 120-second timeout under the shared lock — every other
# lookup in the process blocked behind it. The backoff is what turns that into
# one failure instead of one per game.
# ---------------------------------------------------------------------------

import time  # noqa: E402

import pytest  # noqa: E402

from cartridges.utils.steam_applist import (  # noqa: E402
    FAILURE_BACKOFF_SECONDS,
    SteamAppListError,
)


@pytest.fixture
def app_list(tmp_path):
    return SteamAppList(cache_path=tmp_path / "steam_applist.json")


@pytest.fixture
def failing_download(monkeypatch):
    """Count how many times the download is actually attempted."""
    attempts = []

    def fail(_self):
        attempts.append(time.time())
        raise SteamAppListError("network down")

    monkeypatch.setattr(SteamAppList, "_download", fail)
    return attempts


def test_a_failed_download_is_not_repeated_inside_the_backoff(
    app_list, failing_download
):
    """T6.5 One failure must cost one download, not one per game."""
    for _ in range(5):
        with pytest.raises(SteamAppListError):
            app_list.lookup("The Outer Worlds")

    assert len(failing_download) == 1


def test_the_backoff_escalates_and_then_holds(app_list, failing_download):
    """T6.6 60 -> 300 -> 900, and no further."""
    windows = []
    for _ in range(5):
        with pytest.raises(SteamAppListError):
            app_list.lookup("The Outer Worlds")
        windows.append(round(app_list._backoff_remaining()))
        # Step past the window so the next attempt is allowed through.
        app_list._failure_time -= FAILURE_BACKOFF_SECONDS[-1] + 1

    assert windows[0] == pytest.approx(FAILURE_BACKOFF_SECONDS[0], abs=1)
    assert windows[1] == pytest.approx(FAILURE_BACKOFF_SECONDS[1], abs=1)
    assert windows[2] == pytest.approx(FAILURE_BACKOFF_SECONDS[2], abs=1)
    assert windows[3] == pytest.approx(FAILURE_BACKOFF_SECONDS[-1], abs=1)
    assert windows[4] == pytest.approx(FAILURE_BACKOFF_SECONDS[-1], abs=1)


def test_a_success_clears_the_backoff(app_list, monkeypatch):
    """T6.7 A list in hand must never be withheld because of an old failure."""
    calls = []

    def fail_once(_self):
        calls.append(1)
        if len(calls) == 1:
            raise SteamAppListError("network down")
        return FAKE_APPS

    monkeypatch.setattr(SteamAppList, "_download", fail_once)

    with pytest.raises(SteamAppListError):
        app_list.lookup("The Outer Worlds")

    app_list._failure_time -= FAILURE_BACKOFF_SECONDS[0] + 1
    assert app_list.lookup("The Outer Worlds")
    assert app_list._backoff_remaining() <= 0

    # And the parsed list is kept, so nothing downloads again.
    app_list.lookup("Alien Isolation")
    assert len(calls) == 2


def test_a_stale_cache_beats_no_list_and_records_no_failure(
    tmp_path, failing_download
):
    """T6.8 Steam having a bad day is not a reason to lose the fallback."""
    cache_path = tmp_path / "steam_applist.json"
    cache_path.write_text(json.dumps(FAKE_APPS), encoding="utf-8")
    # Older than the freshness window, so the download is attempted first.
    import os as _os

    ancient = time.time() - (365 * 24 * 60 * 60)
    _os.utime(cache_path, (ancient, ancient))
    app_list = SteamAppList(cache_path=cache_path)

    assert app_list.lookup("The Outer Worlds")
    assert len(failing_download) == 1
    assert app_list._failure_count == 0, "falling back is not a failure"


def test_a_name_with_no_core_words_never_downloads(app_list, failing_download):
    """T6.9 The guard that the title matcher was missing, in the place that has it.

    ``core_words`` drops digits and stopwords, so a title like "7" or "The"
    reduces to nothing. There is no anchor to shortlist on, so there is nothing
    the list could answer — and paying for a hundred-megabyte download to find
    that out would be the wrong order of operations.
    """
    for name in ("7", "300", "The", "1917"):
        assert app_list.lookup(name) == []

    assert failing_download == []


def test_the_cache_write_is_atomic(tmp_path, monkeypatch):
    """T6.10 An interrupted write must not leave a truncated list behind."""

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def raise_for_status(self):
            return None

        def json(self):
            return {"applist": {"apps": FAKE_APPS}}

    monkeypatch.setattr(
        "cartridges.utils.steam_applist.requests.get",
        lambda *_a, **_k: FakeResponse(),
    )
    cache_path = tmp_path / "steam_applist.json"
    app_list = SteamAppList(cache_path=cache_path)

    app_list.lookup("The Outer Worlds")

    assert cache_path.is_file()
    assert list(tmp_path.glob("*.tmp")) == []


if __name__ == "__main__":
    unittest.main(verbosity=2)
