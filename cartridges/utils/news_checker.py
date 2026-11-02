# news_checker.py
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

"""Vigia o feed do repack atrás de posts legíveis e acende o selo do botão Novidades (D83).

A thread de trabalho só faz a rede; tudo o que toca a tela volta à thread principal por `na_thread_principal`. O
checker guarda os posts buscados, então abrir a página é instantâneo e reabri-la não custa uma requisição.

A novidade é um número só: `news-last-seen-ts` guarda a data do post mais novo que a pessoa já viu, e o selo acende
quando o feed traz algo mais novo. Abrir a página reconhece tudo o que há nela.

A primeira busca bem-sucedida depois da instalação é a linha de base, não novidade: sem registro do que a pessoa viu,
todo post do feed seria "não visto", e acender o selo por um acervo que ninguém perdeu o esvaziaria de sentido.
"""

import logging
import threading
from typing import Optional

import requests
from PySide6.QtCore import QObject, QTimer, Signal

from cartridges import shared
from cartridges.utils.news_feed import NewsPost, fetch_news
from cartridges.utils.thread_principal import na_thread_principal

# Horas entre as buscas em segundo plano. 0 desliga a busca recorrente (a página ainda busca ao abrir).
_INTERVAL_KEY = "news-check-interval"

# O post mais novo já visto, no schema de estado: é estado da janela, não preferência.
_LAST_SEEN_KEY = "news-last-seen-ts"


class NewsChecker(QObject):
    """Dono da busca recorrente, dos posts em cache e da marca de não vistos."""

    # A lista de posts foi trocada por uma diferente.
    postsMudaram = Signal()  # noqa: N815
    # Uma busca terminou; `True` se trouxe posts, `False` se a rede (ou o feed) falhou.
    buscaTerminou = Signal(bool)  # noqa: N815
    # A marca de não vistos virou; o argumento é o novo estado.
    naoVistasMudou = Signal(bool)  # noqa: N815

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_async)
        # Uma busca por vez: o teste e a troca são travados porque o botão de atualizar pode apertar a qualquer hora.
        self._lock = threading.Lock()
        self._running = False
        # Depois do `stop()` (fim do app, ou a chave desligada) o resultado de uma busca em voo só solta a trava.
        self._stopped = False
        self._posts: tuple[NewsPost, ...] = ()
        self._has_unseen = False

    @property
    def posts(self) -> tuple[NewsPost, ...]:
        """Os posts da última busca bem-sucedida, do mais novo ao mais antigo."""
        return self._posts

    @property
    def loading(self) -> bool:
        return self._running

    @property
    def has_unseen(self) -> bool:
        return self._has_unseen

    def start(self) -> None:
        """Busca já e arma o relógio. Não espera nenhum jogo: as novidades são globais."""
        self._stopped = False
        self.check_async()
        self._timer.stop()
        interval_hours = shared.schema.get_int(_INTERVAL_KEY)
        if interval_hours > 0:
            # O QTimer guarda int32: a chave aceita mais horas do que cabem em milissegundos.
            self._timer.start(min(interval_hours * 3600 * 1000, 2**31 - 1))

    def stop(self) -> None:
        """Para o relógio e abandona a busca em voo."""
        self._stopped = True
        self._timer.stop()

    def check_async(self) -> None:
        """Uma busca fora da thread principal, a menos que já haja uma."""
        if self._stopped:
            # Parado (chave desligada, fim do app): quem pediu a busca (o "Atualizar") não espera um fim que não vem.
            self.buscaTerminou.emit(False)
            return
        with self._lock:
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._poll_thread, daemon=True).start()

    def _poll_thread(self) -> None:
        posts: Optional[list[NewsPost]] = None
        try:
            posts = fetch_news()
        except requests.RequestException as error:
            # Busca que falha não é evento: o cache fica e o selo não muda.
            logging.info("Repack news feed poll failed: %s", error)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Unexpected error polling repack news feed", exc_info=True)
        finally:
            na_thread_principal(self._apply, posts)

    def _apply(self, posts: Optional[list[NewsPost]]) -> None:
        """Entrega uma busca terminada ao estado. Roda na thread principal."""
        with self._lock:
            self._running = False
        if self._stopped:
            return
        if not posts:
            # O cache fica: uma conexão caída não esvazia a página que a pessoa lê. Mas é falha.
            self.buscaTerminou.emit(False)
            return
        fetched = tuple(posts)
        # Os posts são imutáveis, então a igualdade é de verdade: a lista só é refeita (e a rolagem volta ao topo)
        # quando mudou, não a cada busca de seis horas.
        if fetched != self._posts:
            self._posts = fetched
            self.postsMudaram.emit()
        self._refresh_unseen()
        self.buscaTerminou.emit(True)

    def _newest_timestamp(self) -> int:
        return max((post.timestamp for post in self._posts), default=0)

    def _refresh_unseen(self) -> None:
        newest = self._newest_timestamp()
        last_seen = shared.state_schema.get_int64(_LAST_SEEN_KEY)
        # Primeira vez: o feed de hoje é a linha de base (ver a docstring do módulo).
        if last_seen == 0 and newest:
            shared.state_schema.set_int64(_LAST_SEEN_KEY, newest)
            last_seen = newest
        self._set_unseen(newest > last_seen)

    def _set_unseen(self, unseen: bool) -> None:
        if unseen == self._has_unseen:
            return
        self._has_unseen = unseen
        logging.debug("News badge %s", "raised" if unseen else "cleared")
        self.naoVistasMudou.emit(unseen)

    def mark_seen(self) -> None:
        """Reconhece todos os posts em cache; chamado ao abrir a página."""
        newest = self._newest_timestamp()
        if newest > shared.state_schema.get_int64(_LAST_SEEN_KEY):
            shared.state_schema.set_int64(_LAST_SEEN_KEY, newest)
        self._set_unseen(False)
