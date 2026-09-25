# test_rate_limiter.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The token bucket, and the history it restores across restarts.

Persisting a pick history achieves nothing unless restoring it costs tokens. The
Steam limiter reloads up to 200 timestamps at startup; with a bucket created
full on top of that, a restart ten seconds after a big import could issue
another 100 requests immediately — 300 inside a period the service documents as
allowing 200.
"""

import time

import pytest

from cartridges.utils.rate_limiter import PickHistory, RateLimiter


class Limiter(RateLimiter):
    """A limiter with small, legible numbers."""

    refill_period_seconds = 60
    refill_period_tokens = 20
    burst_tokens = 10

    def __init__(self, seeded=()):
        self._seeded = list(seeded)
        super().__init__()

    def _init_pick_history(self):
        super()._init_pick_history()
        if self._seeded:
            self.pick_history.add(*self._seeded)


def test_a_fresh_limiter_starts_full():
    """The control: nothing restored, nothing consumed."""
    limiter = Limiter()
    assert limiter.n_tokens == limiter.burst_tokens


def test_restored_history_consumes_tokens():
    """T6.14 The bucket has to reflect what was already spent."""
    now = time.time()
    limiter = Limiter(seeded=[now - 5] * 4)

    assert limiter.n_tokens == limiter.burst_tokens - 4


def test_expired_history_consumes_nothing():
    """T6.15 Picks older than the period are not owed anything."""
    now = time.time()
    limiter = Limiter(seeded=[now - 600] * 8)

    assert limiter.n_tokens == limiter.burst_tokens


def test_history_larger_than_the_bucket_is_clamped():
    """T6.16 Consuming more than the bucket holds would go negative."""
    now = time.time()
    limiter = Limiter(seeded=[now - 1] * 50)

    assert limiter.n_tokens == 0


def test_seed_history_reports_what_it_consumed():
    now = time.time()
    limiter = Limiter()
    limiter.pick_history.add(*[now - 1] * 3)

    assert limiter.seed_history() == 3


def test_seed_history_never_blocks():
    """It runs inside __init__, before the refill thread exists.

    Anything that waited for a token here would deadlock at startup rather than
    fail, which is the worst shape this bug could take.
    """
    now = time.time()
    limiter = Limiter(seeded=[now - 1] * 10)
    assert limiter.n_tokens == 0

    # A second seeding has nothing left to take and must still return.
    limiter.pick_history.add(now)
    assert limiter.seed_history() == 0


def test_pick_history_drops_entries_outside_the_period():
    """The window is what makes the restored count meaningful."""
    now = time.time()
    history = PickHistory(60)
    history.add(now - 120, now - 90, now - 5, now - 1)

    assert len(history) == 2


def test_spacing_respects_the_documented_limit():
    """T6.17 The empirical check, formalised.

    Not a timing assertion on wall-clock duration — that is flaky by
    construction — but on the refill spacing the limiter derives, which is what
    actually governs the rate.
    """
    limiter = Limiter()
    period = limiter.refill_period_seconds / limiter.refill_period_tokens

    assert limiter.refill_spacing >= period
