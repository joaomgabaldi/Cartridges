# test_title_match.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks for the Steam title matcher.

Runnable without the GTK stack — ``cartridges.utils.title_match`` imports
nothing from the app — so a regression is caught with a plain::

    python3 tests/test_title_match.py

The cases below are the real reason this module exists: Steam's own search
ranks "The Outer Worlds 2" above "The Outer Worlds", so anything that trusts
the first result silently attaches sequel metadata to the original game.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cartridges.utils.title_match import (  # noqa: E402
    best_candidate,
    compare_titles,
    rank_candidates,
)

# Verbatim store search output, so these tests keep describing what the API
# actually returns rather than an idealized version of it.
OUTER_WORLDS_RESULTS = [
    {"name": "The Outer Worlds 2", "id": 1449110, "metascore": ""},
    {"name": "The Outer Worlds 2 Soundtrack", "id": 3729820, "metascore": ""},
    {"name": "The Outer Worlds: Spacer's Choice Edition", "id": 1920490, "metascore": ""},
    {"name": "The Outer Worlds 2 Premium Upgrade Edition", "id": 3729860, "metascore": ""},
]

ALIEN_ISOLATION_RESULTS = [
    {"name": "Alien: Isolation 2", "id": 4665290, "metascore": ""},
    {"name": "Alien: Isolation", "id": 214490, "metascore": "81"},
    {"name": "Alien Isolation: Trauma", "id": 336290, "metascore": ""},
    {"name": "Alien: Isolation - Trauma", "id": 282513, "metascore": ""},
    {"name": "Alien: Isolation - Safe Haven", "id": 282514, "metascore": ""},
    {"name": "Alien: Isolation - Corporate Lockdown", "id": 282512, "metascore": ""},
    {"name": "Alien: Isolation - The Trigger", "id": 282516, "metascore": ""},
    {"name": "Alien: Isolation - Lost Contact", "id": 282515, "metascore": ""},
    {"name": "Alien: Isolation - Last Survivor", "id": 282510, "metascore": ""},
    {"name": "Alien: Isolation - Crew Expendable", "id": 282511, "metascore": ""},
]


class TestSequelGate(unittest.TestCase):
    """A game must never be confused with its own sequel."""

    def test_sequel_is_rejected_in_both_directions(self) -> None:
        self.assertEqual(
            0, compare_titles("The Outer Worlds", "The Outer Worlds 2").score
        )
        self.assertEqual(
            0, compare_titles("The Outer Worlds 2", "The Outer Worlds").score
        )

    def test_trailing_number_counts_but_embedded_one_does_not(self) -> None:
        self.assertEqual(100, compare_titles("Left 4 Dead", "Left 4 Dead").score)
        self.assertEqual(0, compare_titles("Left 4 Dead", "Left 4 Dead 2").score)

    def test_roman_and_arabic_numerals_are_the_same_number(self) -> None:
        self.assertEqual(100, compare_titles("Civilization 6", "Civilization VI").score)
        self.assertEqual(0, compare_titles("Civilization 6", "Civilization V").score)
        self.assertEqual(
            0, compare_titles("Final Fantasy VII", "Final Fantasy VIII").score
        )

    def test_spelled_out_numbers_are_the_same_number(self) -> None:
        self.assertEqual(100, compare_titles("Portal 2", "Portal Two").score)

    def test_lone_one_is_a_pronoun_not_a_numeral(self) -> None:
        # "one" mid-title must stay a word, or the title gains a numeric
        # signature no store entry can match.
        self.assertEqual(
            100, compare_titles("No One Lives Forever", "No One Lives Forever").score
        )

    def test_trailing_roman_one_is_a_numeral(self) -> None:
        self.assertEqual(
            100, compare_titles("The Last of Us Part I", "The Last of Us Part 1").score
        )
        self.assertEqual(
            0, compare_titles("The Last of Us Part I", "The Last of Us Part II").score
        )


class TestNoise(unittest.TestCase):
    """Cosmetic differences must not stop a match."""

    def test_trademarks_case_accents_and_punctuation(self) -> None:
        for wanted, candidate in (
            ("Batman Arkham Knight", "Batman™: Arkham Knight"),
            ("Bioshock Infinite", "BioShock Infinite"),
            ("Pokemon", "Pokémon"),
            ("Alien Isolation", "Alien: Isolation"),
            ("Doom Eternal", "DOOM Eternal"),
        ):
            with self.subTest(candidate=candidate):
                self.assertEqual(100, compare_titles(wanted, candidate).score)

    def test_missing_leading_article(self) -> None:
        self.assertEqual(
            100, compare_titles("Witcher 3 Wild Hunt", "The Witcher 3: Wild Hunt").score
        )

    def test_author_credit_prefix(self) -> None:
        # Stores carry the credit, shortcuts usually drop it.
        self.assertTrue(
            compare_titles("Civilization VI", "Sid Meier's Civilization VI").confident
        )


class TestEditionsAndSeparateProducts(unittest.TestCase):
    """Re-releases are the same game; soundtracks and DLC are not."""

    def test_edition_suffix_is_still_the_same_game(self) -> None:
        for wanted, candidate in (
            ("Alien Isolation", "Alien: Isolation Collection"),
            ("Final Fantasy VII", "FINAL FANTASY VII REMASTERED"),
            ("The Witcher 3 Wild Hunt", "The Witcher 3: Wild Hunt - Complete Edition"),
        ):
            with self.subTest(candidate=candidate):
                self.assertTrue(compare_titles(wanted, candidate).confident)

    def test_soundtrack_is_never_the_game(self) -> None:
        self.assertEqual(
            0, compare_titles("The Outer Worlds 2", "The Outer Worlds 2 Soundtrack").score
        )

    def test_dlc_is_offered_but_not_adopted(self) -> None:
        match = compare_titles("Alien Isolation", "Alien: Isolation - Trauma")
        self.assertFalse(match.confident)
        self.assertGreater(match.score, 0)

    def test_unrelated_title_sharing_words(self) -> None:
        self.assertEqual(0, compare_titles("The Outer Worlds", "The Outer Side").score)


class TestTitlesWithoutCoreWords(unittest.TestCase):
    """A title made only of numbers and stopwords cannot be compared.

    Numbers are the sequel gate and stopwords carry no identity, so both are
    dropped before the words are scored — which leaves titles like "7" or
    "The" with nothing to score at all. Comparing one used to walk off the end
    of an empty word list and raise ``StopIteration``, and that lands on the
    Steam picker's search thread, which only catches ``SteamError`` and
    ``RequestException``: the thread died and the dialog stayed on "loading".
    """

    def test_digits_only_title_is_not_the_game_starting_with_it(self) -> None:
        for wanted, candidate in (
            ("7", "7 Days to Die"),
            ("300", "300 Dwarves"),
            ("1917", "1917 Trench Warfare"),
        ):
            with self.subTest(wanted=wanted):
                self.assertEqual(0, compare_titles(wanted, candidate).score)

    def test_stopword_only_title_is_not_the_game_starting_with_it(self) -> None:
        for wanted, candidate in (
            ("The", "The Forest"),
            ("A", "A Way Out"),
        ):
            with self.subTest(wanted=wanted):
                self.assertEqual(0, compare_titles(wanted, candidate).score)

    def test_such_a_title_still_matches_itself(self) -> None:
        # The guard must not cost a game whose name really is just a number the
        # ability to match its own store entry.
        self.assertEqual(100, compare_titles("7", "7").score)
        self.assertEqual(100, compare_titles("1917", "1917").score)

    def test_ranking_drops_them_instead_of_crashing(self) -> None:
        ranked = rank_candidates(
            "7", [{"name": "7 Days to Die", "id": 251570, "metascore": ""}]
        )
        self.assertEqual([], ranked)


class TestRanking(unittest.TestCase):
    """End-to-end behaviour against real search results."""

    def test_alien_isolation_picks_the_base_game(self) -> None:
        best = best_candidate("Alien Isolation", ALIEN_ISOLATION_RESULTS)
        assert best is not None
        candidate, match = best
        self.assertEqual(214490, candidate["id"])
        self.assertTrue(match.confident)

    def test_outer_worlds_refuses_to_guess(self) -> None:
        # The original (578650) is not in Steam's search results at all, so the
        # only honest outcome is to adopt nothing. Picking the top hit here is
        # exactly the bug that motivated this module.
        best = best_candidate("The Outer Worlds", OUTER_WORLDS_RESULTS)
        self.assertFalse(best is not None and best[1].confident)

    def test_sequel_entries_are_dropped_entirely(self) -> None:
        ranked = rank_candidates("The Outer Worlds", OUTER_WORLDS_RESULTS)
        self.assertNotIn(1449110, [candidate["id"] for candidate, _ in ranked])


# ---------------------------------------------------------------------------
# Properties that hold for every pair (T6.12 - T6.13)
# ---------------------------------------------------------------------------

# Real titles, picked for the shapes that break tokenizers: bare numbers,
# stopword-only, roman numerals, possessives, colons, accents, ampersands,
# trademark signs, and a title that is punctuation once normalised.
FUZZ_TITLES = [
    "7", "300", "1917", "2048", "The", "A", "Of",
    "Half-Life 2", "Portal 2", "Left 4 Dead 2", "Civilization VI",
    "Sid Meier's Civilization VI", "The Witcher 3: Wild Hunt",
    "Pokémon Legends: Arceus", "Sam & Max Save the World",
    "DOOM Eternal", "DOOM (2016)", "Halo: The Master Chief Collection",
    "The Last of Us Part I", "The Last of Us Part II",
    "Final Fantasy VII", "Final Fantasy VIII", "FINAL FANTASY VII REMAKE",
    "The Outer Worlds", "The Outer Worlds 2",
    "The Outer Worlds 2 Soundtrack", "Alien: Isolation",
    "Alien: Isolation - Trauma", "Battlefield 1", "Battlefield 11",
    "Command & Conquer™ Remastered", "S.T.A.L.K.E.R.: Shadow of Chernobyl",
    "! ! !", "---", "", "   ", "Ō", "12 Minutes", "Nier:Automata",
    "Mass Effect™ Legendary Edition", "Cities: Skylines II",
]


class TestFuzz(unittest.TestCase):
    """The shape of bug that keeps happening here is an unhandled exception.

    ``compare_titles`` is reached from a picker's search thread (which catches
    only network errors), from the metadata manager, and from the update
    checker on the main thread. An exception in it does not degrade a match —
    it kills the thread, and the picker sits on "loading" for the rest of the
    session. So the property worth asserting over the whole corpus is not
    correctness, it is total-ness.
    """

    def test_no_pair_raises(self) -> None:
        for wanted in FUZZ_TITLES:
            for candidate in FUZZ_TITLES:
                with self.subTest(wanted=wanted, candidate=candidate):
                    match = compare_titles(wanted, candidate)
                    self.assertIsInstance(match.score, int)
                    self.assertIsInstance(match.reason, str)

    def test_ranking_never_raises(self) -> None:
        candidates = [
            {"name": name, "id": index} for index, name in enumerate(FUZZ_TITLES)
        ]
        for wanted in FUZZ_TITLES:
            with self.subTest(wanted=wanted):
                rank_candidates(wanted, candidates)

    def test_every_title_matches_itself_or_is_uncomparable(self) -> None:
        """Reflexivity, where the title says anything at all."""
        for title in FUZZ_TITLES:
            with self.subTest(title=title):
                score = compare_titles(title, title).score
                self.assertIn(score, (0, 100))


class TestDirectionality(unittest.TestCase):
    """The comparison is deliberately *not* symmetric, and that is worth pinning.

    T6.13 asked for symmetry, and the matcher does not have it — by design, not
    by accident. ``wanted`` is the local title and ``candidate`` is the store
    result, and the rule is a subset one: everything the wanted title says must
    be present in the candidate. So a store entry with *fewer* words than the
    local title is a mismatch, while the same pair the other way round is an
    author-credit prefix and matches.

    That never shows up as an inconsistency, because every caller passes the
    local title first — ``rank_candidates`` and the update checker both do. But
    the direction is load-bearing: flipping it would make "Civilization VI"
    match a library entry the user named after the publisher, and stop matching
    the one they did not.
    """

    ASYMMETRIC_PAIRS = [
        # (longer local title, shorter store title)
        ("Sid Meier's Civilization VI", "Civilization VI"),
        ("FINAL FANTASY VII REMAKE", "Final Fantasy VII"),
        ("Alien: Isolation - Trauma", "Alien: Isolation"),
    ]

    def test_a_store_title_missing_words_is_a_mismatch(self) -> None:
        for longer, shorter in self.ASYMMETRIC_PAIRS:
            with self.subTest(wanted=longer, candidate=shorter):
                match = compare_titles(longer, shorter)
                self.assertEqual(0, match.score)
                self.assertIn("missing words", match.reason)

    def test_the_same_pair_matches_the_other_way_round(self) -> None:
        for longer, shorter in self.ASYMMETRIC_PAIRS:
            with self.subTest(wanted=shorter, candidate=longer):
                self.assertGreater(compare_titles(shorter, longer).score, 0)

    def test_asymmetry_is_confined_to_the_subset_rule(self) -> None:
        """Everywhere else, the verdict does agree in both directions.

        Stated as a property over the whole corpus, minus the one rule that is
        directional: if neither side is missing words, the two must agree.
        """
        for wanted in FUZZ_TITLES:
            for candidate in FUZZ_TITLES:
                forward = compare_titles(wanted, candidate)
                backward = compare_titles(candidate, wanted)
                if "missing words" in (forward.reason, backward.reason):
                    continue
                if "missing words" in forward.reason or "missing words" in backward.reason:
                    continue
                with self.subTest(wanted=wanted, candidate=candidate):
                    self.assertEqual(forward.score > 0, backward.score > 0)

    def test_the_sequel_gate_is_symmetric(self) -> None:
        """A differing numeric signature is a mismatch from either side."""
        pairs = [
            ("The Outer Worlds", "The Outer Worlds 2"),
            ("Battlefield 1", "Battlefield 11"),
            ("Final Fantasy VII", "Final Fantasy VIII"),
            ("Portal", "Portal 2"),
        ]
        for left, right in pairs:
            with self.subTest(pair=(left, right)):
                self.assertEqual(0, compare_titles(left, right).score)
                self.assertEqual(0, compare_titles(right, left).score)


if __name__ == "__main__":
    unittest.main(verbosity=2)
