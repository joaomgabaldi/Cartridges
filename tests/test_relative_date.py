# test_relative_date.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How "last played" is phrased: calendar days, not elapsed 24-hour periods (a session ended 23:50 yesterday must not read "hoje" at 23:50 today)."""

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
    """23:50 yesterday, read at 00:10 today, is not "hoje"."""
    at(2026, 6, 15, hour=0, minute=10)
    assert rd.relative_date(stamp(2026, 6, 14, 23, 50)) == "ontem"


def test_early_this_morning_is_today(at):
    """00:30 today, read at 23:00, is still "hoje"."""
    at(2026, 6, 15, hour=23, minute=0)
    assert rd.relative_date(stamp(2026, 6, 15, 0, 30)) == "hoje"


def test_a_future_timestamp_is_today(at):
    """A clock that was wrong must not announce a weekday (a negative day count fell through to the weekday branch)."""
    at(2026, 6, 15)
    assert rd.relative_date(stamp(2026, 8, 1)) == "hoje"
    assert rd.relative_date(stamp(2027, 1, 1)) == "hoje"


def test_earlier_this_week_is_a_weekday_name(at):
    at(2026, 6, 19)  # a Friday
    assert datetime(2026, 6, 19).weekday() == 4
    assert rd.relative_date(stamp(2026, 6, 17)) == "quarta-feira"


def test_last_week(at):
    at(2026, 6, 19)
    assert rd.relative_date(stamp(2026, 6, 10)) == "semana passada"


def test_this_month(at):
    at(2026, 6, 25)
    assert rd.relative_date(stamp(2026, 6, 2)) == "este mês"


def test_last_month(at):
    at(2026, 6, 15)
    assert rd.relative_date(stamp(2026, 5, 20)) == "mês passado"


def test_earlier_this_year_is_a_month_name(at):
    at(2026, 11, 15)
    assert rd.relative_date(stamp(2026, 2, 10)) == "fevereiro"


def test_last_year(at):
    at(2026, 6, 15)
    assert rd.relative_date(stamp(2025, 8, 1)) == "ano passado"


def test_older_than_last_year_is_the_year(at):
    at(2026, 6, 15)
    assert rd.relative_date(stamp(2019, 3, 1)) == "2019"


@pytest.mark.parametrize(
    ("hoje", "data", "esperado"),
    [
        ((2026, 9, 18), (2026, 8, 31), "mês passado"),
        ((2026, 1, 5), (2024, 12, 31), "2024"),
        ((2026, 3, 31), (2026, 1, 31), "janeiro"),
    ],
)
def test_b27_mes_e_ano_pelo_calendario(at, hoje, data, esperado):
    """Mês e ano contam pelo calendário, não por blocos de 30 e 365 dias."""
    at(*hoje)
    assert rd.relative_date(stamp(*data)) == esperado


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
