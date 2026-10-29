# updates_checker.py
#
# Copyright 2026 joaomgabaldi
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

"""Poll the repack feed and light up the "update available" notice per game.

The network half runs on a worker thread; the moment it lands, everything that
touches game state or the UI is bounced back onto the main thread, because the
save/update signals drive GTK widgets and those are not thread-safe.

The state model is deliberately tiny and lives on the games themselves (see
:class:`~cartridges.jogo.Jogo`), so this class holds no per-game memory and
caches no game lists — exactly the constraint the design calls for. Novelty is
decided per game by a single timestamp, ``update_dismissed_ts``: a digest is
"new to this game" when it is more recent than the last patch the user
dismissed. A freshly opted-in game has a dismissed timestamp of 0, so it is
caught up on the most recent digest that mentions it the first time the feed is
read, and everything after that is gated by what the user has acknowledged. The
feed only carries recent posts, so this can never surface an old back-catalogue.
"""

import logging
import threading
from typing import Optional

import requests

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.utils.thread_principal import na_thread_principal
from cartridges.utils.title_match import CONFIDENT_SCORE, compare_titles
from cartridges.utils.updates_feed import DigestEntry, UpdatePost, fetch_feed

_INTERVAL_KEY = "updates-check-interval"


class UpdatesChecker:
    """Owns the recurring repack-feed poll and applies its results."""

    def __init__(self) -> None:
        # Temporizador da próxima consulta: cancelável e nunca armado duas vezes.
        self._timer: Optional[threading.Timer] = None
        # Sobe a cada armação e a cada `stop()`: uma partida que já disparou mas ainda
        # espera na fila da thread principal confere o número e se descarta.
        self._armacao = 0
        # A single in-flight poll guard: a slow network request must not stack
        # up behind the timer firing again. Guarded by `_lock` because the
        # test-and-set is what keeps exactly one worker thread alive, and
        # `check_async` is reachable from the timer, from startup and from the
        # details dialog — an invariant worth enforcing rather than documenting.
        self._lock = threading.Lock()
        self._running = False
        # Set once the app is shutting down. A poll already on the worker thread
        # cannot be cancelled, so instead its result is dropped: `_apply` walks
        # the store, saves games and touches the UI, none of which is
        # legal once `do_shutdown` has run.
        self._stopped = False
        # The "you have updates" toast is a greeting, shown once per app run
        # after the first poll that produced results — not on every 12h re-poll.
        self._startup_toast_shown = False

    # -- scheduling -----------------------------------------------------------

    def start(self) -> None:
        """Kick off an immediate poll and arm the recurring timer.

        Safe to call once at startup. The interval comes from settings; 0 turns
        the whole feature off without touching any game.
        """
        self._stopped = False
        self.check_async()

        # Cancel before reading the setting, not after: returning early on a 0
        # interval used to leave a previously armed timer running, so turning
        # the feature off only took effect on the next launch.
        self._cancelar_timer()
        self._armar()

    def _armar(self) -> None:
        interval_hours = shared.schema.get_int(_INTERVAL_KEY)
        if interval_hours <= 0:
            return
        self._armacao += 1
        # O temporizador roda numa thread própria; a consulta volta à principal.
        self._timer = threading.Timer(
            interval_hours * 3600, na_thread_principal, (self._on_timer, self._armacao)
        )
        self._timer.daemon = True
        self._timer.start()

    def _cancelar_timer(self) -> None:
        self._armacao += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def stop(self) -> None:
        """Cancel the recurring timer and disown any poll still in flight."""
        self._stopped = True
        self._cancelar_timer()

    def _on_timer(self, armacao: int) -> None:
        if self._stopped or armacao != self._armacao:
            return
        self.check_async()
        self._armar()  # recorrente

    # -- the poll -------------------------------------------------------------

    def check_async(self) -> None:
        """Run one poll off the main thread, unless one is already running.

        The network request is skipped entirely when no game opted in: the
        feature costs nothing until at least one game asks to be watched.
        """
        if self._stopped:
            return
        # Over a snapshot, like every other walk of the store here: an import
        # adds games from its own worker thread while this runs.
        if not any(getattr(game, "track_updates", False) for game in list(shared.store)):
            return
        with self._lock:
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._poll_thread, daemon=True).start()

    def _poll_thread(self) -> None:
        posts: Optional[list[UpdatePost]] = None
        try:
            posts = fetch_feed()
        except requests.RequestException as error:
            # A failed poll is a non-event: the notices simply don't change this
            # round. Logged at info because a flaky network is expected.
            logging.info("Repack update feed poll failed: %s", error)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Unexpected error polling repack update feed", exc_info=True)
        finally:
            na_thread_principal(self._apply, posts)

    # -- applying results (main thread) --------------------------------------

    def _apply(self, posts: Optional[list[UpdatePost]]) -> None:
        """Fold a finished poll into game state. Runs on the main thread."""
        with self._lock:
            self._running = False
        # The window and the store may already be gone; a result that arrives
        # after shutdown is thrown away rather than written back.
        if self._stopped or not posts:
            return

        self._evaluate_all(posts)
        self._maybe_show_startup_toast()

    def _evaluate_all(self, posts: list[UpdatePost]) -> None:
        """Run every tracked game against a poll's results.

        Walks a snapshot rather than the store itself. This is a fuzzy title
        comparison per game and per digest entry over the whole library, which
        is far too long to hold the store still for — and it is reachable while
        an import is adding games from its own thread.
        """
        for game in list(shared.store):
            if getattr(game, "removed", False) or not getattr(
                game, "track_updates", False
            ):
                continue
            self._evaluate_game(game, posts)

    def _maybe_show_startup_toast(self) -> None:
        """Greet the user once with a toast naming games that have an update.

        Fires after the first poll that reached evaluation, so it lands just
        after the import toasts rather than on every background re-poll. Lists
        every tracked game whose notice is currently up, dismissed ones aside.
        """
        if self._startup_toast_shown:
            return
        self._startup_toast_shown = True

        names = [
            game.name
            for game in list(shared.store)
            if not getattr(game, "removed", False) and game.has_update
        ]
        if not names or shared.aplicativo is None:
            return

        if len(names) == 1:
            message = _("Atualização para {} disponível").format(names[0])
        else:
            joined = ", ".join(names[:-1]) + _(" e ") + names[-1]
            message = _("Atualizações para {} disponíveis").format(joined)

        # Texto puro: a fila de avisos não interpreta markup, então o "&" ou "<" de
        # um nome de jogo aparece como é. Ela também enfileira, sem furar a fila.
        shared.aplicativo.avisos.adicionar(message)

    def _evaluate_game(self, game: Jogo, posts: list[UpdatePost]) -> None:
        """Raise the notice for ``game`` if an undismissed patch mentions it.

        The newest matching digest wins, and its repack link rides along so the
        notice can open the right page. ``posts`` is newest-first, so the first
        match is the newest one and the loop can stop there.
        """
        best_ts = 0
        best_url = ""
        for post in posts:
            entry = self._match_in_post(game, post)
            if entry is not None:
                best_ts = post.timestamp
                best_url = entry.url
                break

        # A patch counts only when it is strictly newer than the last one the
        # user dismissed — that single comparison is the whole "don't nag about
        # a patch I already handled, but do speak up for an even newer one" rule.
        if best_ts <= game.update_dismissed_ts:
            return

        # Persist when *either* the advertised patch or its link changed. Keying
        # only off the timestamp would miss the case where the notice was already
        # raised (same digest) but its repack link is still missing — e.g. a
        # game flagged by an older build that predates the stored URL.
        if best_ts != game.update_available_ts or best_url != game.update_url:
            game.update_available_ts = best_ts
            game.update_url = best_url
            logging.info(
                "Update available for %s (%s) from digest at %d: %s",
                game.name,
                game.game_id,
                best_ts,
                best_url or "(no link)",
            )
            game.save()
            # A página de detalhes segue o `atualizado` do jogo.
            game.update()

    @staticmethod
    def _match_in_post(game: Jogo, post: UpdatePost) -> Optional[DigestEntry]:
        """Return the digest entry that confidently matches ``game``, or None.

        Confidence is the title matcher's own bar (``CONFIDENT_SCORE``): the
        numeric-signature gate keeps a sequel's patch from ever lighting up the
        base game, and the edition rules let "Game: Definitive Edition" in the
        library still match a plain "Game" in the digest.
        """
        for entry in post.entries:
            if compare_titles(game.name, entry.name).score >= CONFIDENT_SCORE:
                return entry
        return None
