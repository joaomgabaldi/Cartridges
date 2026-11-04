# process_session.py
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

"""Acompanha o tempo de jogo observando o processo do jogo."""

import logging
from time import monotonic
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import QTimer

from cartridges import shared
from cartridges.utils import session_log
from cartridges.utils.process_monitor import (
    install_dir_from_command,
    is_package_running,
    is_process_running,
    is_process_running_under,
)
from cartridges.utils.run_executable import aumid_from_command

if TYPE_CHECKING:
    from cartridges.jogo import Jogo


class ProcessSession:
    """Sessão automática de um jogo, observando o processo."""

    active: "Optional[ProcessSession]" = None

    POLL_INTERVAL = 2
    STARTUP_GRACE = 300
    PACKAGE_STARTUP_GRACE = 90
    # Com que frequência gravar o tempo acumulado no disco (rede de segurança contra queda ou falta de luz).
    PERSIST_INTERVAL = 60
    # Um intervalo entre duas consultas maior que isto não é jogo: o relógio monotônico continua contando com o PC
    # dormindo, e um jogo pausado de noite renderia a noite inteira.
    MAX_GAP = POLL_INTERVAL + 30

    def __init__(self, game: "Jogo") -> None:
        self.game = game
        # Só quando o usuário pediu.
        self.exe_name = game.process_executable.strip() if game.track_process else ""
        aumid = aumid_from_command(game.executable)
        self.package_family = aumid.split("!", 1)[0] if aumid else ""
        self.install_dir = install_dir_from_command(game.executable)
        self.grace = max(0, shared.schema.get_int("process-tracking-grace"))
        self.session_seconds = 0
        self.started = False
        self.counting = False
        # Todas monotônicas, nunca de parede: medem intervalos (ver `_accumulate`).
        self.last_tick: Optional[float] = None
        self.last_persist = 0.0
        self.waited = 0
        self.startup_grace = (
            self.PACKAGE_STARTUP_GRACE if self.package_family else self.STARTUP_GRACE
        )
        self.missing_since: Optional[float] = None
        self.timer: Optional[QTimer] = None

    @property
    def elapsed(self) -> int:
        """Segundos contados até agora, incluindo o trecho ainda não gravado."""
        if self.counting and self.last_tick is not None:
            return self.session_seconds + int(monotonic() - self.last_tick)
        return self.session_seconds

    def _is_running(self) -> bool:
        if self.package_family and is_package_running(self.package_family):
            return True
        if self.exe_name and is_process_running(self.exe_name):
            return True
        return bool(self.install_dir) and is_process_running_under(self.install_dir)

    def start(self) -> None:
        ProcessSession.active = self
        self.last_persist = monotonic()
        shared.sessao.show_session_blocker(self.game)
        self.timer = QTimer()
        self.timer.timeout.connect(self._poll)
        self.timer.start(self.POLL_INTERVAL * 1000)

    def _parar_timer(self) -> None:
        if self.timer is not None:
            self.timer.stop()
            self.timer.deleteLater()
            self.timer = None

    def _poll(self) -> None:
        running = self._is_running()

        if not self.started:
            if running:
                self.started = True
                self.counting = True
                self.last_tick = monotonic()
                self.missing_since = None
                # O instante que separa uma sessão que conta de uma que não conta: sem esta linha as duas deixam o mesmo
                # rastro no log.
                logging.debug(
                    "%s seen running after %ss; counting playtime",
                    self.game.name,
                    self.waited,
                )
            else:
                self.waited += self.POLL_INTERVAL
                if self.waited >= self.startup_grace:
                    self._parar_timer()
                    if self.package_family:
                        # Um jogo empacotado que nunca mostrou um processo da família não iniciou: a ativação chegou ao
                        # shell e o que subiu foi o app Xbox avisando de atualização, novo login ou jogo desinstalado
                        # (outro pacote).
                        logging.info(
                            "No process of %s ever appeared; %s never started, "
                            "ending the session without a record",
                            self.package_family,
                            self.game.name,
                        )
                        self.stop(record=False, never_launched=True)
                    else:
                        # Aqui "nunca visto" pode ser "perdi de vista": um launcher passou a outro executável, ou o jogo
                        # se instalou fora da pasta do comando.
                        logging.info(
                            "%s never appeared; falling back to the manual "
                            "session window for %s",
                            self.exe_name or self.install_dir,
                            self.game.name,
                        )
                        self.stop(record=False, fall_back=True)
                    return
            return

        if running:
            self.missing_since = None
            if not self.counting:
                self.counting = True
                self.last_tick = monotonic()
            self._accumulate()
            self._maybe_persist()
        else:
            if self.counting:
                # Acabou de sumir: grava o tempo até agora e pausa a contagem, para a espera abaixo nunca contar.
                self._accumulate()
                self.counting = False
            if self.missing_since is None:
                self.missing_since = monotonic()
            if monotonic() - self.missing_since >= self.grace:
                self._parar_timer()
                self.stop(record=True)

    def _accumulate(self) -> None:
        now = monotonic()
        if self.counting and self.last_tick is not None:
            elapsed = int(now - self.last_tick)
            if elapsed > self.MAX_GAP:
                logging.info(
                    "%ss gap while tracking %s (sleep?); counting %ss",
                    elapsed,
                    self.game.name,
                    self.POLL_INTERVAL,
                )
                self.last_tick = now - self.POLL_INTERVAL
                elapsed = self.POLL_INTERVAL
            if elapsed > 0:
                self.game.playtime += elapsed
                self.session_seconds += elapsed
                # Carrega o resto de menos de um segundo, senão truncar cada consulta de dois segundos perderia tempo
                # numa sessão longa.
                now = self.last_tick + elapsed
        self.last_tick = now

    def _maybe_persist(self) -> None:
        now = monotonic()
        if now - self.last_persist >= self.PERSIST_INTERVAL:
            self.game.save()
            self.last_persist = now

    def flush(self) -> None:
        if self.started:
            self._accumulate()
            self.game.save()

    def stop(
        self,
        record: bool = True,
        fall_back: bool = False,
        never_launched: bool = False,
    ) -> None:
        self._parar_timer()

        if ProcessSession.active is self:
            ProcessSession.active = None

        if fall_back:
            from cartridges.session_window import SessionWindow

            SessionWindow(self.game).present()
            return

        shared.sessao.hide_session_blocker()

        if never_launched:
            # A variável é o título do jogo; o aviso mostra texto puro.
            shared.sessao.avisar(_("Não foi possível detectar {} em execução").format(self.game.name))

        if record and self.started:
            self._accumulate()
            session_log.record(self.game.game_id, self.session_seconds)
            self.game.save()
            self.game.update()
            shared.sessao.session_toast(self.game, self.session_seconds)
        elif record:
            # Pediu-se para registrar, mas o processo nunca apareceu (encerrar pelo botão da janela bloqueada durante a
            # espera cai aqui): nada foi medido, e o silêncio era indistinguível de uma sessão gravada.
            logging.info(
                "Session for %s ended before %s was ever seen; nothing recorded",
                self.game.name,
                self.exe_name
                or self.package_family
                or self.install_dir
                or "the game",
            )

        shared.sessao.present()

    def close(self, *_args: Any) -> None:
        self.stop(record=True)
