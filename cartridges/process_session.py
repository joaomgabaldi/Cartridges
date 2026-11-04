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

"""Acompanha o tempo de jogo observando o processo do jogo.

Depois de lançado, espera o processo aparecer, conta o tempo em que ele roda e encerra a sessão sozinha quando ele
sai. O tempo vai para ``game.playtime`` a cada consulta, então uma queda só perde o último intervalo.

O jogo é reconhecido por qualquer um de três sinais: o nome do executável configurado, a pasta de instalação lida do
comando e, nos jogos da Microsoft Store e do Game Pass, o nome de família do pacote (ver :meth:`_is_running`). O que
nenhum vê (Steam e Epic, que passam por um launcher) cai na :class:`~cartridges.session_window.SessionWindow` manual.
A exceção é um jogo empacotado cujo pacote nunca aparece: a sessão termina sem registro e avisa, pois aí "nunca visto"
significa que o jogo não iniciou.
"""

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

    # Uma sessão acompanhada por vez, como a SessionWindow; a referência aqui também impede a coleta do objeto enquanto
    # o timer roda.
    active: "Optional[ProcessSession]" = None

    # Segundos entre consultas à lista de processos; curto para que a tolerância configurada pelo usuário seja o que
    # governa a espera.
    POLL_INTERVAL = 2
    # Quanto esperar o processo aparecer antes de desistir: launchers, compilação de shaders e anti-cheats atrasam o exe
    # de verdade.
    STARTUP_GRACE = 300
    # Menor para jogo empacotado: a ativação pelo shell produz um processo do pacote em segundos ou falhou; esperar os
    # cinco minutos abriria a janela manual por cima de um jogo já rodando.
    PACKAGE_STARTUP_GRACE = 90
    # Com que frequência gravar o tempo acumulado no disco (rede de segurança contra queda ou falta de luz).
    PERSIST_INTERVAL = 60
    # Um intervalo entre duas consultas maior que isto não é jogo: o relógio monotônico continua contando com o PC
    # dormindo, e um jogo pausado de noite renderia a noite inteira. Esse intervalo é creditado como uma consulta só.
    MAX_GAP = POLL_INTERVAL + 30

    def __init__(self, game: "Jogo") -> None:
        self.game = game
        # Só quando o usuário pediu. O campo mantém o valor com a chave desligada (o diálogo o pré-preenche do comando),
        # e um jogo que chega aqui pela pasta não pode ressuscitar um nome que o dono desligou.
        self.exe_name = game.process_executable.strip() if game.track_process else ""
        # Nome de família do pacote que vale como "o jogo está rodando", vazio fora da Store/Game Pass. Um nome basta:
        # pacotes irmãos eram a preocupação (Call of Duty tem um pacote por título e um "COREBase" compartilhado), mas
        # todo processo de um título, launcher ou jogo, reporta a família do próprio título.
        aumid = aumid_from_command(game.executable)
        self.package_family = aumid.split("!", 1)[0] if aumid else ""
        # Pasta de instalação tirada do comando, vazia se ele não tem caminho de executável seguro. Vigiada além de
        # `exe_name`, não no lugar: a pasta pega o jogo que passa a outro executável, e o nome pega o jogo cujo comando
        # aponta para uma subpasta (Battlefield 6 lança `SP\bf6.exe` mas guarda o multiplayer um nível acima). Nenhum
        # cobre o outro.
        self.install_dir = install_dir_from_command(game.executable)
        # Segundos a esperar depois que o processo some antes de encerrar, para o jogo que se reinicia não ser cortado.
        # Ajustável pelo usuário.
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
        self.timer: Optional[QTimer] = None  # criado em `start`, parado uma vez só

    @property
    def elapsed(self) -> int:
        """Segundos contados até agora, incluindo o trecho ainda não gravado.

        `session_seconds` só se move numa consulta, e o relógio ficaria parado dois segundos e saltaria dois. Somar o
        trecho atual também faz o relógio bater com o total que a sessão grava: fica em zero enquanto se espera o jogo
        aparecer e para quando o jogo some durante a espera, tempo que nunca chega a `game.playtime`.
        """
        if self.counting and self.last_tick is not None:
            return self.session_seconds + int(monotonic() - self.last_tick)
        return self.session_seconds

    def _is_running(self) -> bool:
        """O jogo está rodando agora?

        Aceita qualquer um dos três sinais. O pacote é perguntado primeiro por ser o mais revelador: sobrevive ao jogo
        se relançar com outro executável (a campanha de Call of Duty troca ``cod23-cod.exe`` por
        ``sp23\\sp23-cod.exe``, mesmo pacote) e é o único que distingue dois títulos do Game Pass. Mas não no lugar
        dos outros: só responde onde ``OpenProcess`` consegue, e um handle recusado volta como o mesmo "sem pacote" de
        um processo comum; assim, um pacote mudo não prova que o jogo não roda, e o nome de processo configurado para
        um jogo da Store é respeitado.

        O nome vem antes da pasta por ser mais barato: lê a lista de processos, enquanto a pasta abre cada processo
        para ver de onde foi carregado.
        """
        if self.package_family and is_package_running(self.package_family):
            return True
        if self.exe_name and is_process_running(self.exe_name):
            return True
        return bool(self.install_dir) and is_process_running_under(self.install_dir)

    def start(self) -> None:
        """Begin watching for the game's process."""
        ProcessSession.active = self
        self.last_persist = monotonic()
        # Bloqueia a janela principal para não iniciar uma segunda sessão por ela.
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
                        # (outro pacote). A janela manual poria um contador na tela até alguém fechá-lo, e `do_shutdown`
                        # gravaria horas de jogo que não existiram.
                        logging.info(
                            "No process of %s ever appeared; %s never started, "
                            "ending the session without a record",
                            self.package_family,
                            self.game.name,
                        )
                        self.stop(record=False, never_launched=True)
                    else:
                        # Aqui "nunca visto" pode ser "perdi de vista": um launcher passou a outro executável, ou o jogo
                        # se instalou fora da pasta do comando. Pedir ao usuário para encerrar é melhor que descartar
                        # uma sessão que pode estar rodando.
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
                # Retomada depois de um sumiço breve (o jogo se relançou): novo trecho, sem contar o intervalo.
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
        """Soma o tempo desde o último tick aos totais.

        Medido no relógio monotônico, não no de parede: `time()` pula (NTP, mudança manual, volta do repouso com RTC
        desajustado), e um salto para a frente era creditado como jogo que não houve (o para trás caía no teste ``>
        0``, e a assimetria passava despercebida).
        """
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
        """Save accumulated time at most once per PERSIST_INTERVAL."""
        now = monotonic()
        if now - self.last_persist >= self.PERSIST_INTERVAL:
            self.game.save()
            self.last_persist = now

    def flush(self) -> None:
        """Grava o tempo acumulado sem mexer na interface: usado no desligamento do app, quando os widgets já podem
        ter sumido.
        """
        if self.started:
            self._accumulate()
            self.game.save()

    def stop(
        self,
        record: bool = True,
        fall_back: bool = False,
        never_launched: bool = False,
    ) -> None:
        """Encerra a sessão, gravando o tempo se pedido.

        ``fall_back`` entrega a sessão à janela manual em vez de descartá-la: nunca vimos o jogo, e a escolha é entre
        pedir ao usuário que encerre e perder a sessão em silêncio.

        ``never_launched``: para um jogo empacotado, "nenhum processo do pacote visto" significa que o jogo não
        iniciou; a sessão termina sem registro e o usuário é avisado. Os dois são mutuamente exclusivos.
        """
        self._parar_timer()

        if ProcessSession.active is self:
            ProcessSession.active = None

        if fall_back:
            # avoid import cycles
            from cartridges.session_window import SessionWindow

            # Só o rastreador muda de mãos: o jogo continua rodando, então o bloqueador, o papel de parede, as fitas, a
            # janela estacionada e o controle suspenso ficam como estão (`show_session_blocker` reconhece o mesmo jogo).
            # Sem `shared.sessao.present()`: a principal está fora do caminho e o jogo pode estar em primeiro plano.
            SessionWindow(self.game).present()
            return

        shared.sessao.hide_session_blocker()

        if never_launched:
            # A variável é o título do jogo; o aviso mostra texto puro.
            shared.sessao.avisar(_("Não foi possível detectar {} em execução").format(self.game.name))

        if record and self.started:
            self._accumulate()
            # Anotada depois do accumulate e antes do save, para que a linha do
            # histórico e o total do jogo contem os mesmos segundos.
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
        """Alias so callers can treat this like a SessionWindow."""
        self.stop(record=True)
