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
    """Minutos inteiros abaixo de uma hora ("45 min"); depois, horas com vírgula ("10,5 horas"), nunca dias."""
    if seconds < 60:
        return _("menos de 1 min")
    minutes = round(seconds / 60)
    if minutes < 60:
        return _("{} min").format(minutes)

    hours = round(seconds / 3600, 1)
    if hours == 1:
        return _("1 hora")
    text = str(int(hours)) if hours.is_integer() else str(hours).replace(".", ",")
    return _("{} horas").format(text)


def format_stopwatch(seconds: int) -> str:
    """O relógio do jogo aberto (``0:05:12``): sem arredondar, e as horas não são limitadas nem preenchidas."""
    seconds = max(0, seconds)
    return f"{seconds // 3600}:{seconds // 60 % 60:02}:{seconds % 60:02}"


# Base 1024 com rótulos curtos, como o Explorer: em base 1000 mostraria 94 GB onde o Windows mostra 87.
_UNITS = ("B", "KB", "MB", "GB", "TB")


def format_size(size: int) -> str:
    """Tamanho legível, com vírgula decimal ("87,4 GB")."""
    if size <= 0:
        return ""

    value = float(size)
    unit = 0
    while value >= 1024 and unit < len(_UNITS) - 1:
        value /= 1024
        unit += 1

    # Casa decimal só a partir de MB.
    if unit < 2:
        return f"{round(value)} {_UNITS[unit]}"

    rounded = round(value, 1)
    text = str(int(rounded)) if rounded.is_integer() else str(rounded).replace(".", ",")
    return f"{text} {_UNITS[unit]}"


if __name__ == "__main__":
    import builtins

    builtins._ = lambda s: s  # type: ignore  # stand in for gettext

    assert format_playtime(0) == "menos de 1 min"
    assert format_playtime(59) == "menos de 1 min"
    assert format_playtime(60) == "1 min"
    assert format_playtime(1800) == "30 min"
    assert format_playtime(3599) == "1 hora"  # arredonda para 1 hora, não "60 min"
    assert format_playtime(3600) == "1 hora"
    assert format_playtime(5400) == "1,5 horas"
    assert format_playtime(37800) == "10,5 horas"
    assert format_playtime(90000) == "25 horas"  # fica em horas, nunca dias

    assert format_stopwatch(0) == "0:00:00"
    assert format_stopwatch(-1) == "0:00:00"  # nunca negativo
    assert format_stopwatch(9) == "0:00:09"
    assert format_stopwatch(312) == "0:05:12"
    assert format_stopwatch(3600) == "1:00:00"
    assert format_stopwatch(45296) == "12:34:56"
    assert format_stopwatch(360000) == "100:00:00"  # as horas não têm limite
    print("ok")
