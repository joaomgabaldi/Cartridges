# session_window.py
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

from time import monotonic
from typing import Any, Optional

from PySide6.QtCore import QObject, QTimer

from cartridges import shared
from cartridges.utils import session_log


class SessionWindow(QObject):
    """O relógio da sessão manual, mostrada na janela "Jogando {nome}" (QML)."""

    active: "Optional[SessionWindow]" = None

    TICK_INTERVAL = 60
    # Um intervalo maior que isto entre duas gravações é o PC dormindo, não jogo: o relógio monotônico conta o sono.
    MAX_GAP = TICK_INTERVAL + 30

    def __init__(self, game: Any) -> None:
        super().__init__()
        SessionWindow.active = self
        self.game = game
        # Monotônico, não de parede: mede um intervalo, e `time()` se move com NTP, mudança manual e volta do repouso.
        self.session_start = monotonic()
        self.session_seconds = 0
        self._fechada = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.flush)
        self.timer.start(self.TICK_INTERVAL * 1000)

    @property
    def elapsed(self) -> int:
        """Os segundos da sessão, inclusive os ainda não gravados."""
        return self.session_seconds + int(monotonic() - self.session_start)

    def flush(self) -> None:
        now = monotonic()
        elapsed = int(now - self.session_start)
        if elapsed > self.MAX_GAP:
            self.session_start = now - self.TICK_INTERVAL
            elapsed = self.TICK_INTERVAL
        if elapsed > 0:
            self.game.playtime += elapsed
            self.session_seconds += elapsed
            self.session_start += elapsed
            self.game.save()

    def present(self) -> None:
        shared.sessao.show_session_blocker(self.game)
        shared.sessao.abrir_janela_manual(self)

    def close(self, *_args: Any) -> None:
        if self._fechada:
            return
        self._fechada = True
        self.timer.stop()

        if SessionWindow.active is self:
            SessionWindow.active = None

        shared.sessao.hide_session_blocker()

        self.flush()
        session_log.record(self.game.game_id, self.session_seconds)
        self.game.update()

        shared.sessao.session_toast(self.game, self.session_seconds)

        shared.sessao.present()
