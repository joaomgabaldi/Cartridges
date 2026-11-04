# novidades.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A lógica de tela das Novidades: o selo do botão, a página com os posts do feed e o "Atualizar"."""

import weakref
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from cartridges import shared
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.utils.news_checker import NewsChecker
from cartridges.utils.open_uri import abrir_url
from cartridges.utils.relative_date import relative_date

_CHAVE = "show-news-button"


def _como_dicionario(post: Any) -> dict:
    subtitulo = " · ".join(
        parte for parte in (relative_date(post.timestamp) if post.timestamp else "", post.category) if parte
    )
    return {"titulo": post.title, "subtitulo": subtitulo, "resumo": post.summary, "url": post.url}


class Novidades(QObject):
    alterado = Signal()
    listaRefeita = Signal()  # noqa: N815

    def __init__(self, avisos: FilaDeAvisos, checker: NewsChecker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._checker = checker
        self._posts: list[dict] = []
        self._pagina_a_vista = False
        self._abertas: set[str] = set()
        self._pedido = False
        self._aviso: int | None = None
        self._ligacao: int | None = None
        checker.postsMudaram.connect(self._ao_mudar_os_posts)
        checker.buscaTerminou.connect(self._ao_terminar_a_busca)
        checker.naoVistasMudou.connect(self.alterado)
        self._refazer()

    @Property(bool, notify=alterado)
    def visivel(self) -> bool:
        return shared.schema.get_boolean(_CHAVE)

    @Property(bool, notify=alterado)
    def naoVistas(self) -> bool:  # noqa: N802
        return self._checker.has_unseen

    @Property(str, notify=alterado)
    def estado(self) -> str:
        if self._checker.posts:
            return "lista"
        return "carregando" if self._checker.loading else "vazio"

    @Property("QVariantList", notify=alterado)
    def posts(self) -> list:
        return self._posts

    @Slot(str, result=bool)
    def estaAberta(self, chave: str) -> bool:  # noqa: N802
        return chave in self._abertas

    @Slot(str, bool)
    def definirAberta(self, chave: str, aberta: bool) -> None:  # noqa: N802
        if aberta:
            self._abertas.add(chave)
        else:
            self._abertas.discard(chave)

    def acompanhar_a_chave(self) -> None:
        if self._ligacao is not None:
            return
        fraco = weakref.ref(self)

        def mudou(*_args: Any) -> None:
            if (novidades := fraco()) is not None:
                novidades.ligar()

        self._ligacao = shared.schema.connect(f"changed::{_CHAVE}", mudou)

    def ligar(self) -> None:
        if self.visivel:
            self._checker.start()
        else:
            self._checker.stop()
            self._largar_o_pedido()
        self.alterado.emit()

    def parar(self) -> None:
        if self._ligacao is not None:
            shared.schema.disconnect(self._ligacao)
            self._ligacao = None
        self._checker.stop()
        self._largar_o_pedido()

    @Slot()
    def abrir(self) -> None:
        self._checker.mark_seen()
        self._refazer()
        if not self._checker.posts:
            self._checker.check_async()
        self.alterado.emit()

    @Slot(bool)
    def paginaVisivel(self, visivel: bool) -> None:  # noqa: N802
        self._pagina_a_vista = visivel
        if visivel:
            self._checker.mark_seen()

    @Slot()
    def atualizar(self) -> None:
        self._avisos_sem_pedido()
        self._pedido = True
        self._aviso = self._avisos.adicionar("Atualizando novidades…", segundos=0)
        if not self._checker.loading or not self.visivel:
            self._checker.check_async()
        self.alterado.emit()

    @Slot(str)
    def abrirNoNavegador(self, url: str) -> None:  # noqa: N802
        if url and any(post["url"] == url for post in self._posts):
            abrir_url(url)

    def _refazer(self) -> bool:
        novos = [_como_dicionario(post) for post in self._checker.posts]
        mudou = novos != self._posts
        if mudou:
            self._posts = novos
        return mudou

    def _ao_mudar_os_posts(self) -> None:
        self._abertas.clear()
        self._refazer()
        self.alterado.emit()
        self.listaRefeita.emit()
        if self._pagina_a_vista:
            self._checker.mark_seen()

    def _ao_terminar_a_busca(self, deu_certo: bool) -> None:
        self.alterado.emit()
        if not self._pedido:
            return
        self._largar_o_pedido()
        self._avisos.adicionar("Novidades atualizadas" if deu_certo else "Não foi possível atualizar as novidades")

    def _avisos_sem_pedido(self) -> None:
        if self._aviso is not None:
            self._avisos.dispensar(self._aviso)
            self._aviso = None

    def _largar_o_pedido(self) -> None:
        self._pedido = False
        self._avisos_sem_pedido()
