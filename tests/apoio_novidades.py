# apoio_novidades.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes das Novidades. Não importa
 o `conftest` nem outro teste.

Nada de rede: o feed é o `fetch_news` trocado por quem usa; o checker falso não tem thread nem relógio.
"""

from PySide6.QtCore import QObject, Signal

from kyron.utils.news_feed import NewsPost


def post(timestamp=100, titulo="Título", resumo="Resumo", url="https://x/1", categoria="Repack"):
    return NewsPost(f"id-{timestamp}-{titulo}", timestamp, titulo, url, resumo, categoria)


class CheckerFalso(QObject):
    """O que a `Novidades` pede ao `NewsChecker`, sem thread: as chamadas ficam anotadas em `chamadas`."""

    postsMudaram = Signal()  # noqa: N815
    buscaTerminou = Signal(bool)  # noqa: N815
    naoVistasMudou = Signal(bool)  # noqa: N815

    def __init__(self):
        super().__init__()
        self.posts = ()
        self.loading = False
        self.has_unseen = False
        self.chamadas = []

    def start(self):
        self.chamadas.append("start")

    def stop(self):
        self.chamadas.append("stop")

    def check_async(self):
        self.chamadas.append("check_async")

    def mark_seen(self):
        self.chamadas.append("mark_seen")
