# steam_applist.py
#
# Copyright 2026 kramo
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

"""Look up appids in Steam's full application list.

The store search endpoint only returns what the storefront currently promotes.
When a game is superseded by a re-release, the original stops appearing: a
search for "The Outer Worlds" returns the sequel and the Spacer's Choice
Edition, but not appid 578650 — even though that appid still resolves fine and
is the game the user actually owns.

``ISteamApps/GetAppList`` is the way around that. It lists every app on Steam,
delisted ones included, so it can find what the storefront hides. The tradeoffs
are that it is a large download, carries no metadata to rank or filter by, and
includes a great deal of junk (test builds, dedicated servers, videos). So it
is a *fallback*: consulted only when the store search fails to identify the
game, cached on disk, and its hits are confirmed against the appdetails
endpoint before being trusted.
"""

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Optional

import requests
from requests.exceptions import RequestException

from cartridges.utils.title_match import TitleMatch, core_words, rank_candidates, tokenize

APPLIST_URL = "https://api.steampowered.com/ISteamApps/GetAppList/v2/"

# Steam adds apps constantly but the games we fail to find are old ones, so a
# stale list costs nothing. Refetching weekly keeps a many-megabyte download
# off the user's connection.
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# Downloading the list takes a while on a slow connection; the request runs in
# a worker thread, so a generous timeout is safe.
DOWNLOAD_TIMEOUT_SECONDS = 120

# Cap what a lookup hands back: the list holds many same-named apps and each
# one the caller confirms costs an API request.
MAX_RESULTS = 12

# How long a failed download is believed before another one is attempted, per
# consecutive failure. The whole load runs under `_lock` with a 120 s timeout,
# so without this a Steam outage during the import of a large library meant
# every single game waiting out its own two-minute download — with every other
# worker queued behind it — for an answer that had just failed. The window
# escalates so a long outage is asked about less and less often, and is capped
# in the minutes so a service that comes back is noticed in the same session.
FAILURE_BACKOFF_SECONDS = (60, 300, 900)

_SQUASH_RE = re.compile(r"[^a-z0-9]+")


class SteamAppListError(Exception):
    """The app list could not be fetched or read."""


def _squash(text: str) -> str:
    """Reduce a title to bare alphanumerics for cheap substring filtering."""
    return _SQUASH_RE.sub("", "".join(tokenize(text)))


class SteamAppList:
    """The full Steam app list, cached on disk and indexed on first use."""

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        # ``cartridges.shared`` pulls in GTK, so it is imported here rather
        # than at module level: that keeps this module usable (and testable)
        # on its own, and lets callers point it at any cache file.
        if cache_path is None:
            from cartridges import shared  # pylint: disable=import-outside-toplevel

            cache_path = shared.cache_dir / "steam_applist.json"
        self.cache_path = cache_path
        # `_entries` and `_squashed` are strictly parallel: `lookup` zips them
        # to map a squashed title back to its appid. They are therefore only
        # ever published together, as one tuple, under `_lock` — see
        # `_entries_or_load`.
        self._lock = threading.Lock()
        self._index: Optional[tuple[list[dict], list[str]]] = None
        # Negative cache for a download that failed, read and written only
        # under `_lock` — the same lock the load itself holds, so the failure
        # is recorded and consulted by exactly the threads it has to stop.
        self._failure_count = 0
        self._failure_time = 0.0

    # region Fetching

    def _is_cache_fresh(self) -> bool:
        try:
            age = time.time() - self.cache_path.stat().st_mtime
        except OSError:
            return False
        return age < CACHE_TTL_SECONDS

    def _backoff_remaining(self) -> float:
        """Seconds left before a failed download may be attempted again.

        Only meaningful while `_lock` is held, like the counters it reads.
        """
        if not self._failure_count:
            return 0.0
        window = FAILURE_BACKOFF_SECONDS[
            min(self._failure_count, len(FAILURE_BACKOFF_SECONDS)) - 1
        ]
        return self._failure_time + window - time.time()

    def _download(self) -> list[dict]:
        logging.info("Downloading the Steam app list")
        try:
            with requests.get(APPLIST_URL, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                response.raise_for_status()
                payload = response.json()
        except (RequestException, ValueError) as error:
            raise SteamAppListError("could not download the app list") from error

        apps = payload.get("applist", {}).get("apps") if isinstance(payload, dict) else None
        if not isinstance(apps, list) or not apps:
            raise SteamAppListError("unexpected app list format")

        # Cache before returning, but never let a write failure (read-only or
        # full disk) cost us a list we already have in hand.
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.cache_path.with_suffix(".json.tmp")
            tmp_path.write_text(json.dumps(apps), encoding="utf-8")
            tmp_path.replace(self.cache_path)
        except OSError as error:
            logging.warning("Could not cache the Steam app list", exc_info=error)

        return apps

    def _read_cache(self) -> Optional[list[dict]]:
        try:
            apps = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return apps if isinstance(apps, list) and apps else None

    def _entries_or_load(self) -> tuple[list[dict], list[str]]:
        """Return the (entries, squashed titles) index, loading it if needed.

        This object is a process-wide singleton reached from the importer's
        worker threads, the Steam picker's search thread and the details dialog
        at once. The whole load is serialised: two threads racing here used to
        run two multi-megabyte downloads, and — worse — one could publish a new
        `_entries` while `_squashed` still held the old list, so `lookup` zipped
        titles against the wrong appids and confidently returned a wrong match.
        Publishing both halves as a single tuple makes that impossible to
        express.
        """
        with self._lock:
            if self._index is not None:
                return self._index

            # Refusing here is what makes the failure cost one download instead
            # of one per game. Checked, never waited on: this runs on the
            # caller's thread with the lock held, so sleeping would stall every
            # other lookup for the length of the backoff.
            if (remaining := self._backoff_remaining()) > 0:
                raise SteamAppListError(
                    f"the app list download failed, retrying in {int(remaining)}s"
                )

            apps = self._read_cache() if self._is_cache_fresh() else None
            if apps is None:
                try:
                    apps = self._download()
                except SteamAppListError:
                    # A stale cache still beats no list at all when the network
                    # is down or Steam is having a bad day.
                    apps = self._read_cache()
                    if apps is None:
                        self._failure_count += 1
                        self._failure_time = time.time()
                        raise

            # The appid is stored under "id" so entries are shaped like store
            # search results and both sources can flow through the same code.
            entries = [
                {"name": str(app.get("name", "")), "id": app.get("appid")}
                for app in apps
                if isinstance(app, dict) and app.get("name") and app.get("appid")
            ]
            # Built once and kept: recomputing it per keystroke in the picker
            # would mean re-normalizing a few hundred thousand titles each time.
            squashed = [_squash(entry["name"]) for entry in entries]
            self._index = (entries, squashed)
            logging.info("Steam app list ready (%d apps)", len(entries))
            return self._index

    # endregion

    def lookup(self, name: str, limit: int = MAX_RESULTS) -> list[tuple[dict, TitleMatch]]:
        """Return app list entries that could be ``name``, best match first.

        :raises SteamAppListError: if the list is unavailable
        """
        # Answered before the list is touched: a name with nothing to match on
        # ("7", "The") can never produce a hit, and finding that out is not
        # worth a multi-megabyte download.
        wanted_words = core_words(tokenize(name))
        if not wanted_words:
            return []

        entries, squashed_titles = self._entries_or_load()

        # Scoring every title would mean tokenizing the whole list on each
        # lookup. Requiring the longest word of the query to appear first cuts
        # it to a handful of entries, and cannot drop a real match: every word
        # of the query must be present in a match by definition.
        anchor = _squash(max(wanted_words, key=len))
        shortlist = [
            entry
            for entry, squashed in zip(entries, squashed_titles)
            if anchor in squashed
        ]
        logging.debug(
            "App list: %d of %d entries shortlisted for %s",
            len(shortlist),
            len(entries),
            name,
        )
        return rank_candidates(name, shortlist)[:limit]


# One instance per process: the parsed list is large and the picker, the
# importer and the details dialog all want the same copy.
_app_list: Optional[SteamAppList] = None
_app_list_lock = threading.Lock()


def get_app_list() -> SteamAppList:
    """Return the shared :class:`SteamAppList`.

    Locked because "one instance per process" is the point: two instances mean
    two copies of a few hundred thousand parsed entries and two downloads, and
    the callers reaching this are on different threads by design.
    """
    global _app_list  # pylint: disable=global-statement
    with _app_list_lock:
        if _app_list is None:
            _app_list = SteamAppList()
        return _app_list
