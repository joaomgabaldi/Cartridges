# hltb_backfill.py
#
# Copyright 2026 joaomgabaldi
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

"""Preenche os tempos do HowLongToBeat dos jogos que já estão na biblioteca.

A importação só busca os tempos de jogos novos; uma biblioteca antiga, ou uma busca que falhou, ficaria vazia.
Roda uma vez por abertura, numa thread, no ritmo do mesmo :class:`HLTBRateLimiter` da importação (o site não tem API).
Cada resultado é aplicado ao chegar, então sair no meio guarda o que já foi achado.
"""

import logging
import threading

from kyron import shared
from kyron.jogo import Jogo
from kyron.store.managers.hltb_manager import shared_helper
from kyron.modelos import tarefas
from kyron.utils.passada_agendada import PassadaAgendada
from kyron.utils.hltb import (
    HLTBError,
    HLTBGameNotFoundError,
    HLTBTimes,
    fetch_times,
    has_times,
)
from kyron.utils.thread_principal import na_thread_principal

# A abertura está ocupada e a importação automática divide o mesmo limitador: espera antes de entrar na fila.
_START_DELAY_SECONDS = 20
_IMPORT_RETRY_SECONDS = 30


class HLTBBackfill(PassadaAgendada):
    """Uma varredura em segundo plano atrás dos tempos que faltam."""

    atraso_inicial = _START_DELAY_SECONDS
    espera_da_importacao = _IMPORT_RETRY_SECONDS

    def run_async(self) -> None:
        if self._stopped or not shared.schema.get_boolean("hltb-metadata"):
            return

        # Retrato na thread principal: a importação muda os mapas da store durante a varredura.
        games = [
            game
            for game in shared.store
            if not game.removed
            and not game.blacklisted
            and not game.has_hltb_times
            and (game.name or "").strip()
        ]
        if not games:
            return

        if not self._reservar():
            return

        logging.info("HowLongToBeat backfill queued for %d games", len(games))
        threading.Thread(
            target=self._worker, args=(games, self._generation), daemon=True
        ).start()

    def _worker(self, games: list[Jogo], generation: int) -> None:
        found = 0
        # O jogo que o site não conhece volta a cada abertura, de propósito: é o sinal de que vale conferir o nome.
        tarefa = tarefas.comecar(_("HowLongToBeat"), len(games))
        try:
            for feitos, game in enumerate(games):
                tarefa.atualizar(feitos)
                if self._deve_parar(generation):
                    break
                # Conferido por jogo: a importação ou a edição pode tê-lo preenchido, ou a opção ter sido desligada.
                if game.removed or game.has_hltb_times:
                    continue
                if not shared.schema.get_boolean("hltb-metadata"):
                    break

                try:
                    times = fetch_times(shared_helper(), game.name, game.hltb_id)
                except HLTBGameNotFoundError:
                    # Resposta, não erro: sem traceback no log.
                    logging.debug("HowLongToBeat backfill missed %s", game.name)
                    continue
                except HLTBError as error:
                    # Falha de rede não merece diálogo: a próxima abertura varre de novo.
                    logging.debug(
                        "HowLongToBeat backfill missed %s", game.name, exc_info=error
                    )
                    continue
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.warning(
                        "Unexpected error in HowLongToBeat backfill for %s",
                        game.name,
                        exc_info=True,
                    )
                    continue

                if not has_times(times):
                    continue
                found += 1
                na_thread_principal(self._apply, game, times)
        finally:
            tarefa.terminar()
            self._liberar()
            logging.info(
                "HowLongToBeat backfill done: %d of %d games filled in",
                found,
                len(games),
            )

    def _apply(self, game: Jogo, times: HLTBTimes) -> None:
        # `has_hltb_times` de novo: o botão de buscar pode ter respondido antes, e a varredura não sobrescreve correção do usuário.
        if self._stopped or game.removed or game.has_hltb_times:
            return
        # Identidade na store: um reset apaga a biblioteca enquanto o worker anda, e o `save()` ressuscitaria o jogo apagado.
        store = getattr(shared, "store", None)
        if store is None or store.get(game.game_id) is not game:
            return

        # `update_values` leva só as chaves devolvidas: o que o site não trouxe fica como estava.
        game.update_values(dict(times))
        game.save()
        game.update()
