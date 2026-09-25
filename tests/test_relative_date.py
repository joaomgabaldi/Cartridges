# test_relative_date.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How "last played" is phrased.

The unit is calendar days, not elapsed 24-hour periods. Subtracting two
``datetime`` objects measures the latter, so a session that ended at 23:50
yesterday read as "hoje" until 23:50 today — and the error propagated into every
branch below it, because they all compare against ``weekday()`` and day-of-month,
which are calendar boundaries.
"""

from datetime import datetime, timedelta

import pytest

from cartridges.utils import relative_date as rd


@pytest.fixture
def at(monkeypatch):
    """Freeze "today" so the branches can be reached deterministically."""

    def freeze(year, month, day, hour=12, minute=0):
        frozen = datetime(year, month, day, hour, minute)

        class FrozenDatetime(datetime):
            @classmethod
            def today(cls):
                return frozen

        monkeypatch.setattr(rd, "datetime", FrozenDatetime)
        return frozen

    return freeze


def stamp(year, month, day, hour=12, minute=0):
    return int(datetime(year, month, day, hour, minute).timestamp())


def test_late_last_night_is_yesterday(at):
    """T6.1 23:50 yesterday, read at 00:10 today, is not "hoje"."""
    at(2026, 6, 15, hour=0, minute=10)
    assert rd.relative_date(stamp(2026, 6, 14, 23, 50)) == "ontem"


def test_early_this_morning_is_today(at):
    """T6.2 00:30 today, read at 23:00, is still "hoje"."""
    at(2026, 6, 15, hour=23, minute=0)
    assert rd.relative_date(stamp(2026, 6, 15, 0, 30)) == "hoje"


def test_a_future_timestamp_is_today(at):
    """T6.3 A clock that was wrong must not announce a weekday.

    A negative day count fell through to the weekday branch and printed a day
    of the week, which reads as a date in the past.
    """
    at(2026, 6, 15)
    assert rd.relative_date(stamp(2026, 8, 1)) == "hoje"
    assert rd.relative_date(stamp(2027, 1, 1)) == "hoje"


def test_earlier_this_week_is_a_weekday_name(at):
    """T6.4 Wednesday, read on Friday."""
    at(2026, 6, 19)  # a Friday
    assert datetime(2026, 6, 19).weekday() == 4
    assert rd.relative_date(stamp(2026, 6, 17)) == "quarta-feira"


def test_last_week(at):
    """T6.4"""
    at(2026, 6, 19)
    assert rd.relative_date(stamp(2026, 6, 10)) == "semana passada"


def test_this_month(at):
    """T6.4 Far enough back to clear the week branches, still in the month."""
    at(2026, 6, 25)
    assert rd.relative_date(stamp(2026, 6, 2)) == "este mês"


def test_last_month(at):
    """T6.4"""
    at(2026, 6, 15)
    assert rd.relative_date(stamp(2026, 5, 20)) == "mês passado"


def test_earlier_this_year_is_a_month_name(at):
    """T6.4"""
    at(2026, 11, 15)
    assert rd.relative_date(stamp(2026, 2, 10)) == "fevereiro"


def test_last_year(at):
    """T6.4"""
    at(2026, 6, 15)
    assert rd.relative_date(stamp(2025, 8, 1)) == "ano passado"


def test_older_than_last_year_is_the_year(at):
    """T6.4"""
    at(2026, 6, 15)
    assert rd.relative_date(stamp(2019, 3, 1)) == "2019"


def test_the_day_and_month_tables_line_up_with_python():
    """The tables are indexed by weekday()/month, so their order is load-bearing."""
    assert rd.WEEKDAYS[datetime(2026, 6, 15).weekday()] == "segunda-feira"
    assert rd.WEEKDAYS[datetime(2026, 6, 21).weekday()] == "domingo"
    assert rd.MONTHS[datetime(2026, 1, 1).month - 1] == "janeiro"
    assert rd.MONTHS[datetime(2026, 12, 1).month - 1] == "dezembro"
    assert len(rd.WEEKDAYS) == 7 and len(rd.MONTHS) == 12


def test_every_hour_of_yesterday_reads_as_yesterday(at):
    """The bug was time-of-day dependent, so sweep it."""
    at(2026, 6, 15, hour=0, minute=5)
    yesterday = datetime(2026, 6, 14)
    for hour in range(24):
        moment = yesterday + timedelta(hours=hour)
        assert rd.relative_date(int(moment.timestamp())) == "ontem", moment
