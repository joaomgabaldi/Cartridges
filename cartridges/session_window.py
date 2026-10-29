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
    """O relógio da sessão manual, mostrada na janela "Jogando {nome}" (QML).

    We can't detect when the game itself exits (Steam/Epic/UWP just hand off to
    another process), so the user clicks "Já terminei de jogar" to end the
    session. Elapsed time is flushed into ``game.playtime`` every minute, so a
    crash, freeze or power loss only ever loses the last partial minute.
    A janela em si é do `ModeloDaSessao` (`abrir_janela_manual`).
    """

    # Only one session is tracked at a time. Also keeps this object alive.
    active: "Optional[SessionWindow]" = None

    # Seconds between the periodic flushes.
    TICK_INTERVAL = 60
    # A gap longer than this between two flushes is the PC having slept, not
    # play: the monotonic clock counts the time asleep. It is credited as one
    # tick interval instead of as the whole night.
    MAX_GAP = TICK_INTERVAL + 30

    def __init__(self, game: Any) -> None:
        super().__init__()
        SessionWindow.active = self
        self.game = game
        # Monotonic, not wall clock: this measures an interval, and `time()`
        # moves under NTP corrections, manual clock changes and resume-from-sleep.
        self.session_start = monotonic()
        self.session_seconds = 0  # this session's running total, for the toast
        self._fechada = False
        # Save accumulated time every minute (crash/power-loss safety net)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.flush)
        self.timer.start(self.TICK_INTERVAL * 1000)

    @property
    def elapsed(self) -> int:
        """Os segundos da sessão, inclusive os ainda não gravados.

        `flush` grava a cada minuto adiantando `session_start`; sem somar o que
        já foi gravado, o relógio voltava a zero a cada gravação.
        """
        return self.session_seconds + int(monotonic() - self.session_start)

    def flush(self) -> None:
        """Add elapsed time to the game's total and persist it."""
        now = monotonic()
        elapsed = int(now - self.session_start)
        if elapsed > self.MAX_GAP:
            self.session_start = now - self.TICK_INTERVAL
            elapsed = self.TICK_INTERVAL
        if elapsed > 0:
            self.game.playtime += elapsed
            self.session_seconds += elapsed
            # Advance by the whole seconds actually banked, not to `now`: the
            # discarded remainder would otherwise be lost on every minute tick.
            self.session_start += elapsed  # makes flush idempotent if called again
            self.game.save()

    def present(self) -> None:
        """Põe a camada da sessão e pede a janela "Jogando {nome}"."""
        shared.sessao.show_session_blocker(self.game)
        shared.sessao.abrir_janela_manual(self)

    def close(self, *_args: Any) -> None:
        """Encerra a sessão (o `on_close` da `main`). Chamar de novo não faz nada."""
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

        # Bring the main window back now that the session is over
        shared.sessao.present()
