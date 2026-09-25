# relative_date.py
#
# Copyright 2022-2023 kramo
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

from datetime import datetime
from typing import Any

# Weekday/month names in pt-BR. GLib's %A/%B follow the C locale, which is
# English on Windows (gettext/locale aren't wired up here), so format them
# ourselves to match the rest of the hardcoded pt-BR UI. weekday() is
# 0=Monday..6=Sunday; month is 1=Jan..12=Dec.
WEEKDAYS = (
    "segunda-feira",
    "terça-feira",
    "quarta-feira",
    "quinta-feira",
    "sexta-feira",
    "sábado",
    "domingo",
)
MONTHS = (
    "janeiro",
    "fevereiro",
    "março",
    "abril",
    "maio",
    "junho",
    "julho",
    "agosto",
    "setembro",
    "outubro",
    "novembro",
    "dezembro",
)


def relative_date(timestamp: int) -> Any:  # pylint: disable=too-many-return-statements
    today = datetime.today()
    date = datetime.fromtimestamp(timestamp)
    # Calendar days apart, not elapsed 24-hour periods: a session that ended at
    # 23:50 yesterday read as "Hoje" until 23:50 today, because the subtraction
    # never crossed a whole day. Every branch below compares against weekday()
    # and day-of-month, which are calendar boundaries too, so this is the unit
    # they were written for. Negatives are clamped: a timestamp in the future
    # (a clock that was wrong when the game ran, a library copied from a machine
    # ahead of ours) used to fall through to the weekday branch and announce a
    # day of the week, which reads as a date in the past.
    days_no = max(0, (today.date() - date.date()).days)

    # Minúsculas: o valor sempre segue um rótulo com dois-pontos ("Jogado por
    # último: hoje"), nunca abre frase sozinho. Quem precisar de maiúscula
    # (um rótulo autônomo) capitaliza no próprio lugar de uso.
    if days_no == 0:
        return _("hoje")
    if days_no == 1:
        return _("ontem")
    if days_no <= (day_of_week := today.weekday()):
        return WEEKDAYS[date.weekday()]
    if days_no <= day_of_week + 7:
        return _("semana passada")
    # Mês e ano pelo calendário também, e não por dias contados: com 30 dias
    # fixos, 31/08 lido em 18/09 saía "este mês", e 31/12 de dois anos atrás,
    # lido no começo de janeiro, saía "ano passado".
    months_no = (today.year - date.year) * 12 + today.month - date.month
    if months_no <= 0:
        return _("este mês")
    if months_no == 1:
        return _("mês passado")
    if date.year == today.year:
        return MONTHS[date.month - 1]
    if date.year == today.year - 1:
        return _("ano passado")
    return str(date.year)


if __name__ == "__main__":
    # Guards against an off-by-one / misordering vs. weekday()/month conventions
    assert WEEKDAYS[0] == "segunda-feira" and WEEKDAYS[6] == "domingo"
    assert MONTHS[0] == "janeiro" and MONTHS[11] == "dezembro"
    assert len(WEEKDAYS) == 7 and len(MONTHS) == 12
    print("ok")
