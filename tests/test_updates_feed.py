# test_updates_feed.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checks for the repack update-feed reader.

Runnable without the GTK stack — ``cartridges.utils.updates_feed`` imports only
the standard library and ``requests`` — so a regression is caught with a plain::

    python3 tests/test_updates_feed.py

The markup here is the real thing: each updated game is a ``su-spoiler-title``
div whose text is the bare title, surrounded by download links (``Repack page``,
file-host URLs) and ``.rar`` list items that must NOT be read as games. Those
cases pin the exact failure that shipped first — reading the anchors/list items
instead of the spoiler header, which found no titles at all.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cartridges.utils.title_match import CONFIDENT_SCORE, compare_titles  # noqa: E402
from cartridges.utils.updates_feed import (  # noqa: E402
    extract_entries,
    is_update_digest,
    parse_feed,
)

def extract_game_names(content_html):
    return [entry.name for entry in extract_entries(content_html)]


# One spoiler block, verbatim in shape from fitgirl-repacks.site: the title is
# the div text, and every <a>/<li> around it is download plumbing.
_SPOILER_BLOCK = """
<div class="su-spoiler su-spoiler-style-fancy su-spoiler-icon-plus su-spoiler-closed">
<div class="su-spoiler-title" tabindex="0" role="button"><span class="su-spoiler-icon"></span>{name}</div>
<div class="su-spoiler-content su-u-clearfix su-u-trim">
<a href="https://fitgirl-repacks.site/{slug}/">Repack page</a></p>
<ol>
<li><a href="https://filecrypt.cc/Container/ABC.html" rel="noopener">{name_dotted}.Update.v100.19.15437-RUNE.rar</a> (Source: scene)
</ol>
</div></div>
"""


def _digest_body(*games):
    intro = "<p>Updates for the following games have been added today.</p>"
    blocks = "".join(
        _SPOILER_BLOCK.format(
            name=name, slug=name.lower().replace(" ", "-"), name_dotted=name.replace(" ", ".")
        )
        for name in games
    )
    return intro + blocks


SAMPLE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>FitGirl Repacks</title>
    <item>
      <title>Some Cool Game (v1.2) Repack</title>
      <guid>https://fitgirl-repacks.site/?p=1</guid>
      <pubDate>Mon, 20 Jul 2026 10:00:00 +0000</pubDate>
      <content:encoded><![CDATA[<p>A brand new repack, not a digest.</p>]]></content:encoded>
    </item>
    <item>
      <title>Updates Digest for July 21, 2026</title>
      <guid>https://fitgirl-repacks.site/?p=2</guid>
      <pubDate>Wed, 22 Jul 2026 12:56:33 +0000</pubDate>
      <content:encoded><![CDATA[__DIGEST_A__]]></content:encoded>
    </item>
    <item>
      <title>Updates Digest for July 22, 2026</title>
      <guid>https://fitgirl-repacks.site/?p=3</guid>
      <pubDate>Thu, 23 Jul 2026 00:16:36 +0000</pubDate>
      <content:encoded><![CDATA[__DIGEST_B__]]></content:encoded>
    </item>
  </channel>
</rss>""".replace(
    "__DIGEST_A__", _digest_body("Flotsam", "Forza Horizon 6")
).replace(
    "__DIGEST_B__", _digest_body("Age of Mythology: Retold", "The Crew 2")
)


class TestIsUpdateDigest(unittest.TestCase):
    def test_recognises_digest_titles(self):
        self.assertTrue(is_update_digest("Updates Digest for July 22, 2026"))
        self.assertTrue(is_update_digest("  updates digest  "))

    def test_rejects_other_posts(self):
        self.assertFalse(is_update_digest("Some Cool Game Repack"))
        self.assertFalse(is_update_digest(""))
        self.assertFalse(is_update_digest(None))


class TestExtractGameNames(unittest.TestCase):
    def test_extracts_spoiler_title_text(self):
        html = _digest_body("Age of Mythology: Retold")
        self.assertEqual(extract_game_names(html), ["Age of Mythology: Retold"])

    def test_ignores_download_anchors_and_rar_items(self):
        # "Repack page" and the .rar filename must never be treated as a game.
        names = extract_game_names(_digest_body("Northgard"))
        self.assertEqual(names, ["Northgard"])

    def test_multiple_games_in_order(self):
        names = extract_game_names(_digest_body("Panzer Corps 2", "Phonopolis"))
        self.assertEqual(names, ["Panzer Corps 2", "Phonopolis"])

    def test_titles_with_punctuation_preserved(self):
        html = _digest_body("Warhammer 40,000: Battlesector")
        self.assertEqual(extract_game_names(html), ["Warhammer 40,000: Battlesector"])

    def test_deduplicates_case_insensitively(self):
        html = _digest_body("Northgard", "NORTHGARD")
        self.assertEqual(extract_game_names(html), ["Northgard"])

    def test_no_spoilers_yields_nothing(self):
        self.assertEqual(extract_game_names("<p>Just prose, no spoilers.</p>"), [])


class TestExtractEntries(unittest.TestCase):
    def test_captures_repack_url_with_name(self):
        (entry,) = extract_entries(_digest_body("Northgard"))
        self.assertEqual(entry.name, "Northgard")
        self.assertEqual(entry.url, "https://fitgirl-repacks.site/northgard/")

    def test_download_link_is_not_taken_as_url(self):
        # The first "Repack page" link wins; the file-host .rar anchor is ignored.
        (entry,) = extract_entries(_digest_body("Panzer Corps 2"))
        self.assertTrue(entry.url.endswith("/panzer-corps-2/"))
        self.assertNotIn("filecrypt", entry.url)

    def test_missing_link_yields_empty_url_not_dropped(self):
        html = (
            '<div class="su-spoiler">'
            '<div class="su-spoiler-title">Linkless Game</div>'
            '<div class="su-spoiler-content"><p>no repack link here</p></div>'
            "</div>"
        )
        (entry,) = extract_entries(html)
        self.assertEqual(entry.name, "Linkless Game")
        self.assertEqual(entry.url, "")


class TestParseFeed(unittest.TestCase):
    def setUp(self):
        self.posts = parse_feed(SAMPLE_FEED)

    def test_only_digests_are_returned(self):
        self.assertEqual(len(self.posts), 2)
        for post in self.posts:
            self.assertTrue(post.title.lower().startswith("updates digest"))

    def test_sorted_newest_first(self):
        self.assertGreater(self.posts[0].timestamp, self.posts[1].timestamp)
        self.assertIn("July 22", self.posts[0].title)

    def test_names_extracted_per_digest(self):
        newest, older = self.posts
        self.assertEqual(
            [e.name for e in newest.entries], ["Age of Mythology: Retold", "The Crew 2"]
        )
        self.assertEqual([e.name for e in older.entries], ["Flotsam", "Forza Horizon 6"])

    def test_malformed_xml_is_swallowed(self):
        self.assertEqual(parse_feed("<not xml"), [])


class TestExtractionFeedsMatcher(unittest.TestCase):
    """The extracted title must match the library entry it stands for."""

    def test_exact_title_matches(self):
        (name,) = extract_game_names(_digest_body("Age of Mythology: Retold"))
        match = compare_titles("Age of Mythology: Retold", name)
        self.assertGreaterEqual(match.score, CONFIDENT_SCORE)

    def test_roman_numeral_edition_still_matches(self):
        (name,) = extract_game_names(_digest_body("Civilization VI"))
        match = compare_titles("Civilization 6", name)
        self.assertGreaterEqual(match.score, CONFIDENT_SCORE)

    def test_sequel_digest_does_not_match_base_game(self):
        (name,) = extract_game_names(_digest_body("The Crew 2"))
        match = compare_titles("The Crew", name)
        self.assertLess(match.score, CONFIDENT_SCORE)


class TestDoctypeGuard(unittest.TestCase):
    """Auditoria 26/08, B6: a janela do guard terminava no primeiro `<`+letra,
    inclusive dentro de um comentário — `<!-- <a -->` escondia o DOCTYPE."""

    def test_a_doctype_hidden_behind_a_comment_is_refused(self):
        from cartridges.utils.updates_feed import parse_xml

        doc = (
            '<?xml version="1.0"?><!-- <a -->'
            '<!DOCTYPE rss [<!ENTITY a "x">]><rss><channel/></rss>'
        )
        self.assertIsNone(parse_xml(doc))

    def test_a_plain_doctype_is_still_refused(self):
        from cartridges.utils.updates_feed import parse_xml

        doc = '<?xml version="1.0"?><!DOCTYPE rss><rss><channel/></rss>'
        self.assertIsNone(parse_xml(doc))

    def test_a_doctype_string_inside_the_body_is_harmless(self):
        from cartridges.utils.updates_feed import parse_xml

        doc = "<rss><channel><title>&lt;!DOCTYPE&gt; no texto</title></channel></rss>"
        self.assertIsNotNone(parse_xml(doc))

    def test_an_ordinary_commented_feed_still_parses(self):
        from cartridges.utils.updates_feed import parse_xml

        doc = '<?xml version="1.0"?><!-- gerado às 3h --><rss><channel/></rss>'
        self.assertIsNotNone(parse_xml(doc))


if __name__ == "__main__":
    unittest.main()
