# test_steam_genre.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks for genre selection and controller support.

Runs entirely offline against tag lists captured from the real endpoints, so
what is pinned here is the *selection rule*, not whatever Steam's voters happen
to be doing today::

    python3 tests/test_steam_genre.py

The cases that matter are the ones where the top-voted tag is the wrong answer:
"Ação" outranks "Tiro em Primeira Pessoa (FPS)" on Call of Duty, and
"Simulador Automobilístico" outranks "Tiro em Terceira Pessoa" on GTA V.
"""

import contextlib
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path

import pytest
from requests.exceptions import RequestException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cartridges.store.managers.steam_api_manager import SteamAPIManager  # noqa: E402
from cartridges.utils.steam import (  # noqa: E402
    STEAM_METADATA_VERSION,
    SteamAPIHelper,
    SteamGameNotFoundError,
    format_release_date,
)
from cartridges.utils.steam_genre import (  # noqa: E402
    GENRE_NAMES,
    GENRE_TAGS,
    VAGUE_GENRE_TAGS,
    WEAK_GENRES,
    pick_genre,
)

# Real tag ids, in the order the store returns them (descending votes).
COD_TAGS = [19, 1663, 4182, 3859, 1774, 4168, 3839, 1678]
GTA_TAGS = [1695, 19, 3859, 6378, 1100687, 1697, 3839, 1774, 21, 4182, 3814]
SPIDER_MAN_TAGS = [1695, 1671, 19, 4182, 1742, 21, 3993, 4106, 1697, 4036, 1687]
ASSETTO_TAGS = [699, 4175, 1100687, 3859, 1755, 4182]
STARDEW_TAGS = [87918, 3964, 3859, 10235, 122, 1654, 599, 22602]


class TestPickGenre(unittest.TestCase):
    def test_specific_tag_beats_the_broad_one_above_it(self) -> None:
        """"Ação" has more votes than "FPS" on Call of Duty and must lose.

        This is the whole reason the broad tags are left out of the table: the
        genre a player would name is almost never the top-voted one.
        """
        self.assertEqual(pick_genre(["1"], COD_TAGS), "Tiro em Primeira Pessoa (FPS)")

    def test_vague_tag_yields_to_a_better_one_below_it(self) -> None:
        """GTA V is tagged as a driving sim, and is not one."""
        self.assertEqual(pick_genre(["1", "25"], GTA_TAGS), "Tiro em Terceira Pessoa")
        self.assertEqual(pick_genre(["1", "25"], SPIDER_MAN_TAGS), "Ação / Aventura")

    def test_vague_tag_is_still_used_when_nothing_else_applies(self) -> None:
        """Demoting "Simulador Automobilístico" must not lose actual racing sims."""
        self.assertEqual(pick_genre(["9"], ASSETTO_TAGS), "Simulador Automobilístico")

    def test_first_listed_tag_wins(self) -> None:
        self.assertEqual(pick_genre(["23", "3", "28"], STARDEW_TAGS), "Simulador Rural")

    def test_falls_back_to_the_genres_field(self) -> None:
        """No listed tag: the coarse genre is vague but never wrong."""
        self.assertEqual(pick_genre(["2", "1"], [1695, 4172, 3859]), "Estratégia")

    def test_weak_genres_are_a_last_resort(self) -> None:
        """"Indie" and "Free to Play" say nothing, but beat an empty line."""
        self.assertEqual(pick_genre(["23", "1"], []), "Ação")
        self.assertEqual(pick_genre(["23", "37"], []), "Indie")

    def test_returns_none_when_there_is_nothing_to_show(self) -> None:
        self.assertIsNone(pick_genre([], []))
        self.assertIsNone(pick_genre(["999"], [4166, 1654]))

    def test_unknown_ids_are_skipped_rather_than_shown_raw(self) -> None:
        """A genre id we have no translation for must not leak English through."""
        self.assertEqual(pick_genre(["999", "1"], []), "Ação")


class TestTables(unittest.TestCase):
    def test_every_vague_tag_is_listed(self) -> None:
        """A demoted tag that is not in the table can never be picked at all."""
        self.assertEqual(VAGUE_GENRE_TAGS - set(GENRE_TAGS), set())

    def test_every_weak_genre_is_named(self) -> None:
        self.assertEqual(WEAK_GENRES - set(GENRE_NAMES), set())

    def test_the_broad_tags_are_left_out(self) -> None:
        """Ação, Aventura, RPG, Estratégia, Simulação, Casual, Indie.

        Each duplicates a value of the `genres` field, which is already the
        fallback, and each sits at the top of nearly every game's tag list.
        """
        for tag_id in (19, 21, 122, 9, 599, 597, 492):
            self.assertNotIn(tag_id, GENRE_TAGS)


class TestControllerSupport(unittest.TestCase):
    parse = staticmethod(SteamAPIHelper.parse_controller_support)

    def test_full_and_partial(self) -> None:
        self.assertEqual(self.parse({"categories": [{"id": 2}, {"id": 28}]}), "full")
        self.assertEqual(self.parse({"categories": [{"id": 2}, {"id": 18}]}), "partial")

    def test_full_wins_when_both_are_present(self) -> None:
        self.assertEqual(self.parse({"categories": [{"id": 18}, {"id": 28}]}), "full")

    def test_other_controller_categories_are_ignored(self) -> None:
        """DualShock, DualSense, Tracked Controller and Steam Input all carry
        "Controller" in their name and say nothing about gamepad playability —
        No Man's Sky lists four of them. Matching on the text instead of the id
        would report support for a game that never claimed it."""
        categories = [{"id": 2}, {"id": 44}, {"id": 43}, {"id": 52}, {"id": 53}]
        self.assertIsNone(self.parse({"categories": categories}))

    def test_absent_and_malformed(self) -> None:
        self.assertIsNone(self.parse({"categories": []}))
        self.assertIsNone(self.parse({}))
        self.assertIsNone(self.parse({"categories": None}))
        self.assertIsNone(self.parse({"categories": ["Full controller support"]}))


class TestGamepadRecommended(unittest.TestCase):
    """Category 60, a separate claim from 18 and 28."""

    parse = staticmethod(SteamAPIHelper.parse_gamepad_recommended)

    def test_present_and_absent(self) -> None:
        self.assertTrue(self.parse({"categories": [{"id": 2}, {"id": 60}]}))
        self.assertFalse(self.parse({"categories": [{"id": 2}, {"id": 28}]}))

    def test_full_support_does_not_imply_a_recommendation(self) -> None:
        """Elden Ring and God of War are id 28 without id 60. Inferring one
        from the other would put the sentence on most of the library."""
        self.assertFalse(self.parse({"categories": [{"id": 28}]}))

    def test_it_can_stand_without_full_support(self) -> None:
        """Nothing in the API ties them together, so neither does this."""
        self.assertTrue(self.parse({"categories": [{"id": 18}, {"id": 60}]}))

    def test_malformed(self) -> None:
        self.assertFalse(self.parse({}))
        self.assertFalse(self.parse({"categories": None}))
        self.assertFalse(self.parse({"categories": ["Gamepad Recommended"]}))

    def test_it_is_always_written_so_it_can_be_taken_away(self) -> None:
        """Unlike the string fields, the payload is the whole answer: a game
        that loses the category must lose the line, not keep a stale True."""
        values = SteamAPIHelper.parse_app_data({"categories": [{"id": 28}]})
        self.assertIn("gamepad_recommended", values)
        self.assertFalse(values["gamepad_recommended"])


class FakeResponse:
    """Stand-in for a `requests` response used as a context manager."""

    def __init__(self, payload, error=None) -> None:
        self._payload = payload
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def iter_content(self, chunk_size=1):  # read by download.get_capped
        return iter(())

    def raise_for_status(self) -> None:
        if self._error:
            raise self._error

    def json(self):
        return self._payload


def _helper_returning(monkeypatch, payload, error=None) -> SteamAPIHelper:
    monkeypatch.setattr(
        "cartridges.utils.download.requests.get",
        lambda *_a, **_k: FakeResponse(payload, error),
    )
    return SteamAPIHelper(contextlib.nullcontext())


def test_store_tags_are_returned_in_order(monkeypatch) -> None:
    payload = {
        "response": {
            "store_items": [
                {
                    "appid": 2519060,
                    "tags": [
                        {"tagid": 19, "weight": 1073},
                        {"tagid": 1663, "weight": 1009},
                    ],
                }
            ]
        }
    }
    helper = _helper_returning(monkeypatch, payload)

    assert helper.get_store_tags("2519060") == [19, 1663]


def test_bulk_tags_are_keyed_by_appid(monkeypatch) -> None:
    """Matched on the appid in the reply, never on its position.

    A bulk reply is not guaranteed to come back in the order asked for, and
    mapping by position would hand one game another game's genre.
    """
    payload = {
        "response": {
            "store_items": [
                {"appid": 367520, "tags": [{"tagid": 1628}]},
                {"appid": 2519060, "tags": [{"tagid": 1663}]},
            ]
        }
    }
    helper = _helper_returning(monkeypatch, payload)

    assert helper.get_store_tags_bulk(["2519060", "367520"]) == {
        "2519060": [1663],
        "367520": [1628],
    }


def test_bulk_omits_games_with_no_tags_in_the_reply(monkeypatch) -> None:
    """Absent must stay absent, not become an empty list.

    An empty list means "this game has no tags", which sends the genre back to
    the coarse store value — so a game the bulk call simply did not answer for
    would have its "Metroidvania" quietly rewritten as "Ação".
    """
    payload = {
        "response": {
            "store_items": [
                {"appid": 2519060, "tags": [{"tagid": 1663}]},
                {"appid": 999999999},  # unknown appid: comes back without tags
            ]
        }
    }
    helper = _helper_returning(monkeypatch, payload)

    result = helper.get_store_tags_bulk(["2519060", "999999999", "413150"])

    assert result == {"2519060": [1663]}
    assert "999999999" not in result
    assert "413150" not in result


def test_bulk_skips_non_numeric_appids(monkeypatch) -> None:
    helper = _helper_returning(monkeypatch, {"response": {"store_items": []}})

    assert helper.get_store_tags_bulk(["not-an-appid", ""]) == {}


@pytest.mark.parametrize(
    "payload",
    [
        {"response": {}},  # game has no tags
        {"response": {"store_items": [{}]}},
        {"response": {"store_items": [{"tags": None}]}},
        {"response": {"store_items": [{"tags": [{"tagid": "19"}, {}, None]}]}},
        {},  # not the shape we expect at all
        # A proxy or captive portal answering 200 with a `response` that is not
        # a dict. The `.get` for `store_items` then raises AttributeError, and
        # that one escaping used to kill the refresh's prefetch thread — which
        # is the only thing that schedules the queue, so the whole run stayed
        # stuck as "running" for the rest of the process.
        {"response": None},
        {"response": "maintenance"},
        {"response": []},
    ],
)
def test_store_tags_survive_an_unexpected_payload(monkeypatch, payload) -> None:
    """The genre falls back to the `genres` field, which is already in hand —
    a hiccup here must never fail the whole lookup."""
    helper = _helper_returning(monkeypatch, payload)

    assert helper.get_store_tags("2519060") == []


def test_bulk_stops_between_batches_when_asked(monkeypatch) -> None:
    """A cancelled refresh must not sit through every request it was going to
    make: a big library is several batches, each able to hit a 30 s timeout."""
    from cartridges.utils import steam as steam_module  # noqa: PLC0415

    calls: list = []

    def record(*_a, **kwargs):
        calls.append(kwargs["params"])
        return FakeResponse({"response": {"store_items": []}})

    monkeypatch.setattr("cartridges.utils.download.requests.get", record)
    monkeypatch.setattr(steam_module, "TAG_BATCH_SIZE", 2)
    helper = SteamAPIHelper(contextlib.nullcontext())

    helper.get_store_tags_bulk(["1", "2", "3", "4", "5", "6"])
    assert len(calls) == 3

    calls.clear()
    helper.get_store_tags_bulk(["1", "2", "3", "4", "5", "6"], should_stop=lambda: True)
    assert calls == []

    calls.clear()
    stop = iter([False, True, True])
    helper.get_store_tags_bulk(
        ["1", "2", "3", "4", "5", "6"], should_stop=lambda: next(stop)
    )
    assert len(calls) == 1


def test_store_tags_survive_a_network_failure(monkeypatch) -> None:
    helper = _helper_returning(monkeypatch, {}, error=RequestException("boom"))

    assert helper.get_store_tags("2519060") == []


def test_store_tags_reject_a_non_numeric_appid(monkeypatch) -> None:
    """`steam_appid` is a string in the game's record and can be hand-edited."""
    helper = _helper_returning(monkeypatch, {"response": {"store_items": []}})

    assert helper.get_store_tags("not-an-appid") == []


class TestResolveTags(unittest.TestCase):
    """Where SteamAPIManager gets a game's tags from."""

    resolve = staticmethod(SteamAPIManager.resolve_tags)

    def test_ordinary_import_fetches_per_game(self) -> None:
        self.assertEqual(self.resolve("2519060", {}), (None, False))

    def test_bulk_hit_is_used_without_a_request(self) -> None:
        data = {"steam_tags": {"2519060": [19, 1663]}}
        self.assertEqual(self.resolve("2519060", data), ([19, 1663], False))

    def test_bulk_miss_leaves_the_genre_alone(self) -> None:
        """The refresh answered for other games but not this one.

        Recomputing without tags would replace a specific genre with the coarse
        store one, so the field is skipped entirely instead.
        """
        tag_ids, skip_genre = self.resolve("413150", {"steam_tags": {"2519060": [19]}})
        self.assertIsNone(tag_ids)
        self.assertTrue(skip_genre)

    def test_a_game_genuinely_without_tags_still_resolves(self) -> None:
        """An empty list is an answer: fall back to the coarse genre."""
        self.assertEqual(self.resolve("413150", {"steam_tags": {"413150": []}}), ([], False))


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestSteamCheckedStamp(unittest.TestCase):
    """The marker that makes "only what is missing" mean anything.

    Without it every game looks unchecked forever and the partial refresh costs
    exactly what the full one costs.
    """

    @staticmethod
    def _game(**overrides):
        game = SimpleNamespace(
            name="Probe", steam_appid="367520", blacklisted=False, removed=False,
            steam_checked=0, genre=None,
        )
        def update_values(data, target=game):
            for key, value in data.items():
                setattr(target, key, value)

        game.update_values = update_values
        for key, value in overrides.items():
            setattr(game, key, value)
        return game

    def _run(self, manager, game, helper_result):
        manager.steam_api_helper = SimpleNamespace(
            get_api_data=helper_result,
            get_store_tags=lambda _a: [],
            get_store_tags_bulk=lambda *_a, **_k: {},
        )
        manager.main(game, {})

    def test_a_successful_lookup_stamps_the_game(self) -> None:
        manager = SteamAPIManager.__new__(SteamAPIManager)
        game = self._game()

        self._run(manager, game, lambda **_k: {"name": "Hollow Knight"})

        self.assertEqual(game.steam_checked, STEAM_METADATA_VERSION)

    def test_a_failed_lookup_leaves_the_game_unchecked(self) -> None:
        """A network blip must not read as "up to date": the game would stop
        being offered the fields it never received."""
        manager = SteamAPIManager.__new__(SteamAPIManager)
        game = self._game()

        def boom(**_kwargs):
            raise SteamGameNotFoundError()

        self._run(manager, game, boom)

        self.assertEqual(game.steam_checked, 0)


class TestDescription(unittest.TestCase):
    """Steam's short pitch, which is what the details page shows."""

    parse = staticmethod(SteamAPIHelper.parse_app_data)

    def test_it_is_taken_from_short_description(self) -> None:
        """`about_the_game` is the long one, and it is HTML with images and
        autoplay video — Cyberpunk 2077's holds 3665 characters and no text at
        all. This one is plain, always present and translated."""
        values = self.parse({"short_description": "Um RPG de ação.", "about_the_game": "<p><video/></p>"})
        self.assertEqual(values["description"], "Um RPG de ação.")

    def test_surrounding_whitespace_is_dropped(self) -> None:
        self.assertEqual(self.parse({"short_description": "  Um RPG.\n"})["description"], "Um RPG.")

    def test_an_empty_description_is_left_out(self) -> None:
        """Absent means the record keeps whatever it already had, rather than
        being blanked by a payload that simply did not carry one."""
        self.assertNotIn("description", self.parse({"short_description": ""}))
        self.assertNotIn("description", self.parse({}))


class TestPortugueseDates(unittest.TestCase):
    """The appdetails request asks for Portuguese, for the description's sake.

    The date changes shape with it, and every other field we read does not —
    that was checked against both languages over 25 games before the switch.
    """

    def test_the_portuguese_shape_parses(self) -> None:
        self.assertEqual(format_release_date("5/dez./2019"), "Dez 2019")
        self.assertEqual(format_release_date("23/set./2026"), "Set 2026")
        self.assertEqual(format_release_date("10/nov./2023"), "Nov 2023")

    def test_it_agrees_with_the_english_shape(self) -> None:
        """Same game, same output, whichever language answered."""
        for english, portuguese in (
            ("5 Dec, 2019", "5/dez./2019"),
            ("26 Feb, 2016", "26/fev./2016"),
            ("21 Aug, 2012", "21/ago./2012"),
            ("20 Oct, 2016", "20/out./2016"),
            ("16 May, 2011", "16/mai./2011"),
            ("13 Apr, 2015", "13/abr./2015"),
        ):
            self.assertEqual(format_release_date(english), format_release_date(portuguese))

    def test_a_year_only_date_is_unchanged(self) -> None:
        self.assertEqual(format_release_date("2027"), "2027")
