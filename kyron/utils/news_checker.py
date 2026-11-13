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

"""Vigia o feed da FitGirl e a página do ElAmigos atrás de posts legíveis e acende o selo do botão Novidades.

A thread de trabalho só faz a rede; o que toca a tela volta à principal. O checker guarda os posts buscados.
`news-last-seen-ts` guarda a data do post mais novo já visto; o selo acende quando o feed traz algo mais novo,
e abrir a página reconhece tudo. A primeira busca bem-sucedida depois da instalação é a linha de base, não novidade.
"""

import logging
import threading
from typing import Optional

lazy import requests
from PySide6.QtCore import QObject, QTimer, Signal

from kyron import shared
from kyron.utils.elamigos_feed import fetch_elamigos
from kyron.utils.news_feed import NewsPost, fetch_news
from kyron.utils.thread_principal import na_thread_principal

# Horas entre as buscas em segundo plano; 0 desliga (a página ainda busca ao abrir).
_INTERVAL_KEY = "news-check-interval"

_LAST_SEEN_KEY = "news-last-seen-ts"


class NewsChecker(QObject):
    """Dono da busca recorrente, dos posts em cache e da marca de não vistos."""

    postsMudaram = Signal()  # noqa: N815
    # `True` se a busca trouxe posts, `False` se a rede (ou o feed) falhou.
    buscaTerminou = Signal(bool)  # noqa: N815
    naoVistasMudou = Signal(bool)  # noqa: N815

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.check_async)
        # Uma busca por vez: o botão de atualizar pode apertar a qualquer hora.
        self._lock = threading.Lock()
        self._running = False
        # Depois do `stop()` (fim do app, ou a chave desligada) o resultado de uma busca em voo só solta a trava.
        self._stopped = False
        self._posts: tuple[NewsPost, ...] = ()
        self._has_unseen = False

    @property
    def posts(self) -> tuple[NewsPost, ...]:
        return self._posts

    @property
    def loading(self) -> bool:
        return self._running

    @property
    def has_unseen(self) -> bool:
        return self._has_unseen

    def start(self) -> None:
        self._stopped = False
        self.check_async()
        self._timer.stop()
        interval_hours = shared.schema.get_int(_INTERVAL_KEY)
        if interval_hours > 0:
            # O QTimer guarda int32: a chave aceita mais horas do que cabem em milissegundos.
            self._timer.start(min(interval_hours * 3600 * 1000, 2**31 - 1))

    def stop(self) -> None:
        self._stopped = True
        self._timer.stop()

    def check_async(self) -> None:
        if self._stopped:
            # Parado: quem pediu a busca (o "Atualizar") não espera um fim que não vem.
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
            # Cada fonte falha sozinha: a outra ainda aparece. Só as duas caídas contam como falha.
            for fetch in (fetch_news, fetch_elamigos):
                try:
                    fetched = fetch()
                except requests.RequestException as error:
                    # Busca que falha não é evento: o cache fica e o selo não muda.
                    logging.info("News source poll failed: %s", error)
                    continue
                except Exception:  # pylint: disable=broad-exception-caught
                    # Defeito de leitura numa fonte não derruba a outra.
                    logging.warning("Unexpected error polling a news source", exc_info=True)
                    continue
                posts = (posts or []) + fetched
            if posts:
                posts.sort(key=lambda post: post.timestamp, reverse=True)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Unexpected error polling news sources", exc_info=True)
            posts = None
        finally:
            na_thread_principal(self._apply, posts)

    def _apply(self, posts: Optional[list[NewsPost]]) -> None:
        with self._lock:
            self._running = False
        if self._stopped:
            return
        if not posts:
            # O cache fica: uma conexão caída não esvazia a página que a pessoa lê. Mas é falha.
            self.buscaTerminou.emit(False)
            return
        fetched = tuple(posts)
        # A lista só é refeita (e a rolagem volta ao topo) quando mudou.
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
        # Primeira vez: o feed de hoje é a linha de base.
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
        newest = self._newest_timestamp()
        if newest > shared.state_schema.get_int64(_LAST_SEEN_KEY):
            shared.state_schema.set_int64(_LAST_SEEN_KEY, newest)
        self._set_unseen(False)
