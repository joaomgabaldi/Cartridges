# format_playtime.py
#
# Copyright 2024 kramo
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


def format_playtime(seconds: int) -> str:
    """Human-readable playtime, capped at hours (never days/weeks).

    Under an hour it shows whole minutes ("45 min"); from an hour on it shows
    fractional hours with a comma decimal ("10,5 horas").
    """
    if seconds < 60:
        return _("menos de 1 min")
    if seconds < 3600:
        # ponytail: 3599s rounds to "60 min" instead of "1 hora" — cosmetic, rare
        return _("{} min").format(round(seconds / 60))

    hours = round(seconds / 3600, 1)
    if hours == 1:
        return _("1 hora")
    text = str(int(hours)) if hours.is_integer() else str(hours).replace(".", ",")
    return _("{} horas").format(text)


if __name__ == "__main__":
    import builtins

    builtins._ = lambda s: s  # type: ignore  # stand in for gettext

    assert format_playtime(0) == "menos de 1 min"
    assert format_playtime(59) == "menos de 1 min"
    assert format_playtime(60) == "1 min"
    assert format_playtime(1800) == "30 min"
    assert format_playtime(3600) == "1 hora"
    assert format_playtime(5400) == "1,5 horas"
    assert format_playtime(37800) == "10,5 horas"
    assert format_playtime(90000) == "25 horas"  # stays in hours, never days
    print("ok")
