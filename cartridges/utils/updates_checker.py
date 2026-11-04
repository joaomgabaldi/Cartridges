# updates_checker.py
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

"""Consulta o feed de repacks e acende o aviso de "atualização disponível" por jogo.

A rede roda numa thread de trabalho; o que toca jogos ou tela volta à principal. O estado vive nos jogos (:class:`~cartridges.jogo.Jogo`): um digest é novo para o jogo se for mais recente que o último patch dispensado (``update_dismissed_ts``). Um jogo recém-ativado (0) é posto em dia com o digest mais recente que o cita, e o feed só traz posts recentes.
"""

import logging
import threading
from typing import Optional

import requests

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.utils.thread_principal import na_thread_principal
from cartridges.utils.title_match import CONFIDENT_SCORE, compare_titles
from cartridges.utils.updates_feed import DigestEntry, UpdatePost, fetch_feed

_INTERVAL_KEY = "updates-check-interval"


class UpdatesChecker:
    """Dono da consulta recorrente ao feed e da aplicação dos resultados."""

    def __init__(self) -> None:
        self._timer: Optional[threading.Timer] = None
        # Sobe a cada armação e a cada `stop()`: a partida já disparada que espera na fila confere o número e se descarta.
        self._armacao = 0
        # Uma consulta por vez: `check_async` é chamada pelo timer, pela abertura e pela edição.
        self._lock = threading.Lock()
        self._running = False
        # No encerramento: a consulta em voo não se cancela, então o resultado é descartado (`_apply` mexe na store e na tela).
        self._stopped = False
        # O aviso "há atualizações" sai uma vez por execução, não a cada consulta.
        self._startup_toast_shown = False

    def start(self) -> None:
        """Consulta já e arma o timer recorrente. O intervalo vem das preferências; 0 desliga tudo sem tocar nos jogos."""
        self._stopped = False
        self.check_async()

        # Cancela antes de ler a opção: com intervalo 0, o timer já armado seguiria rodando.
        self._cancelar_timer()
        self._armar()

    def _armar(self) -> None:
        interval_hours = shared.schema.get_int(_INTERVAL_KEY)
        if interval_hours <= 0:
            return
        self._armacao += 1
        self._timer = threading.Timer(
            min(interval_hours * 3600, threading.TIMEOUT_MAX),
            na_thread_principal, (self._on_timer, self._armacao)
        )
        self._timer.daemon = True
        self._timer.start()

    def _cancelar_timer(self) -> None:
        self._armacao += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def stop(self) -> None:
        self._stopped = True
        self._cancelar_timer()

    def _on_timer(self, armacao: int) -> None:
        if self._stopped or armacao != self._armacao:
            return
        self.check_async()
        self._armar()  # recorrente

    def check_async(self) -> None:
        """Uma consulta fora da principal, se não houver uma. Sem jogo ativado, nem faz a requisição."""
        if self._stopped:
            return
        # Sobre um retrato: a importação adiciona jogos de outra thread.
        if not any(getattr(game, "track_updates", False) for game in list(shared.store)):
            return
        with self._lock:
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._poll_thread, daemon=True).start()

    def _poll_thread(self) -> None:
        posts: Optional[list[UpdatePost]] = None
        try:
            posts = fetch_feed()
        except requests.RequestException as error:
            # Consulta que falha não é evento: os avisos não mudam.
            logging.info("Repack update feed poll failed: %s", error)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Unexpected error polling repack update feed", exc_info=True)
        finally:
            na_thread_principal(self._apply, posts)

    def _apply(self, posts: Optional[list[UpdatePost]]) -> None:
        with self._lock:
            self._running = False
        # Resultado que chega depois do encerramento é descartado.
        if self._stopped or not posts:
            return

        self._evaluate_all(posts)
        self._maybe_show_startup_toast()

    def _evaluate_all(self, posts: list[UpdatePost]) -> None:
        """Confere cada jogo acompanhado com o resultado. Sobre um retrato: a comparação difusa é longa demais para segurar a store, e a importação adiciona jogos."""
        for game in list(shared.store):
            if getattr(game, "removed", False) or not getattr(
                game, "track_updates", False
            ):
                continue
            self._evaluate_game(game, posts)

    def _maybe_show_startup_toast(self) -> None:
        """Avisa uma vez, após a primeira consulta avaliada, os jogos com atualização pendente (os dispensados ficam de fora)."""
        if self._startup_toast_shown:
            return
        self._startup_toast_shown = True

        names = [
            game.name
            for game in list(shared.store)
            if not getattr(game, "removed", False) and game.has_update
        ]
        if not names or shared.aplicativo is None:
            return

        if len(names) == 1:
            message = _("Atualização para {} disponível").format(names[0])
        else:
            joined = ", ".join(names[:-1]) + _(" e ") + names[-1]
            message = _("Atualizações para {} disponíveis").format(joined)

        # Texto puro: a fila de avisos não interpreta markup.
        shared.aplicativo.avisos.adicionar(message)

    def _evaluate_game(self, game: Jogo, posts: list[UpdatePost]) -> None:
        """Acende o aviso de ``game`` se um patch não dispensado o cita. Vence o digest mais novo (``posts`` vem do mais novo), com o link do repack."""
        best_ts = 0
        best_url = ""
        for post in posts:
            entry = self._match_in_post(game, post)
            if entry is not None:
                best_ts = post.timestamp
                best_url = entry.url
                break

        # Só conta patch estritamente mais novo que o último dispensado.
        if best_ts <= game.update_dismissed_ts:
            return

        # Grava se o patch *ou* o link mudou: só pelo timestamp perderia o aviso já aceso sem link (versão antiga).
        if best_ts != game.update_available_ts or best_url != game.update_url:
            game.update_available_ts = best_ts
            game.update_url = best_url
            logging.info(
                "Update available for %s (%s) from digest at %d: %s",
                game.name,
                game.game_id,
                best_ts,
                best_url or "(no link)",
            )
            game.save()
            game.update()

    @staticmethod
    def _match_in_post(game: Jogo, post: UpdatePost) -> Optional[DigestEntry]:
        """A entrada do digest que casa com ``game`` com confiança (``CONFIDENT_SCORE``), ou None.

        A assinatura numérica impede que o patch de uma sequência acenda o jogo base, e as regras de edição
        deixam "Game: Definitive Edition" casar com "Game".
        """
        for entry in post.entries:
            if compare_titles(game.name, entry.name).score >= CONFIDENT_SCORE:
                return entry
        return None
