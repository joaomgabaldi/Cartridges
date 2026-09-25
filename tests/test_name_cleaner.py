# test_name_cleaner.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks for shortcut name cleaning::

    python3 tests/test_name_cleaner.py

Cleaning happens before any Steam lookup, so leftover clutter here becomes a
failed match later: an extra word in the local name has to be present on
Steam's side too, and "(PC)" never is.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cartridges.utils.name_cleaner import (  # noqa: E402
    clean_for_search,
    clean_game_name,
)


class TestBracketedNoise(unittest.TestCase):
    def test_platform_tags_are_dropped(self) -> None:
        for raw in (
            "Hades (PC)",
            "Hades [PC]",
            "Hades (pc)",
            "Hades (Steam)",
            "Hades (GOG)",
            "Hades (Epic)",
        ):
            with self.subTest(raw=raw):
                self.assertEqual("Hades", clean_game_name(raw))

    def test_existing_technical_tags_still_dropped(self) -> None:
        self.assertEqual("Hades", clean_game_name("Hades (DX12)"))
        self.assertEqual("Hades", clean_game_name("Hades (Windows)"))
        self.assertEqual("Hades", clean_game_name("Hades (x64)"))

    def test_a_real_word_in_brackets_is_kept(self) -> None:
        # Only whole-bracket noise goes; a subtitle must survive.
        self.assertEqual(
            "Hades (Director's Cut)", clean_game_name("Hades (Director's Cut)")
        )


class TestUnbracketedWords(unittest.TestCase):
    def test_pc_is_kept_when_part_of_the_title(self) -> None:
        # The reason "pc" is bracket-only noise: stripping it everywhere would
        # mangle titles that legitimately start with it.
        self.assertEqual(
            "PC Building Simulator", clean_game_name("PC Building Simulator")
        )
        self.assertEqual("Steam World Dig", clean_game_name("Steam World Dig"))

    def test_standalone_technical_tokens_still_dropped(self) -> None:
        self.assertEqual("Hades", clean_game_name("Hades Windows"))


class TestSearchVariant(unittest.TestCase):
    def test_separators_become_spaces(self) -> None:
        self.assertEqual("Black Myth Wukong", clean_for_search("Black Myth - Wukong"))

    def test_platform_tag_dropped_for_search_too(self) -> None:
        self.assertEqual("Hades", clean_for_search("Hades (PC)"))

    def test_curly_apostrophe_becomes_the_plain_one(self) -> None:
        """Shortcuts carry "’"; catalogues index "'", and the query must match.

        This is not cosmetic: HowLongToBeat found "Assassin's Creed Mirage" and
        returned nothing at all for "Assassin’s Creed Shadows" from the same
        library, purely because of this character.
        """
        self.assertEqual(
            "Assassin's Creed Shadows", clean_for_search("Assassin’s Creed Shadows")
        )

    def test_display_name_keeps_its_typography(self) -> None:
        """Only the query is folded — the game keeps how it is written."""
        self.assertEqual(
            "Assassin’s Creed Shadows", clean_game_name("Assassin’s Creed Shadows")
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
