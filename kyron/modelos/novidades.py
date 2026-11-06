# novidades.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A lógica de tela das Novidades: o selo do botão, a página com os posts do feed e o "Atualizar".

O `NewsChecker` busca e guarda os posts; aqui viram dicionários para o QML e os avisos saem pela fila do app. Tudo na thread principal.
"""

import weakref
from typing import Any

from PySide6.QtCore import Property, QObject, Signal, Slot

from kyron import shared
from kyron.modelos.avisos import FilaDeAvisos
from kyron.utils.news_checker import NewsChecker
from kyron.utils.open_uri import abrir_url
from kyron.utils.relative_date import relative_date

_CHAVE = "show-news-button"


def _como_dicionario(post: Any) -> dict:
    subtitulo = " · ".join(
        parte for parte in (relative_date(post.timestamp) if post.timestamp else "", post.category) if parte
    )
    return {"titulo": post.title, "subtitulo": subtitulo, "resumo": post.summary, "url": post.url}


class Novidades(QObject):
    alterado = Signal()
    # A lista foi trocada por outra: a página volta ao topo.
    listaRefeita = Signal()  # noqa: N815

    def __init__(self, avisos: FilaDeAvisos, checker: NewsChecker, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._checker = checker
        self._posts: list[dict] = []
        self._pagina_a_vista = False
        # As linhas expandidas, fora do delegate: a página é destruída ao voltar, e as linhas se mantêm até os posts mudarem.
        self._abertas: set[str] = set()
        # O "Atualizar" apertado: quem responde é o fim da busca. O aviso "Atualizando…" não some sozinho.
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
        """Posts em cache sempre vencem: uma busca que falhou não tira a lista de quem a lê."""
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
        """Guarda a linha expandida: reabrir a página a mostra como estava; só posts novos zeram."""
        if aberta:
            self._abertas.add(chave)
        else:
            self._abertas.discard(chave)

    def acompanhar_a_chave(self) -> None:
        """Passa a ligar e desligar o feed quando `show-news-button` muda (referência fraca: o schema é do app)."""
        if self._ligacao is not None:
            return
        fraco = weakref.ref(self)

        def mudou(*_args: Any) -> None:
            if (novidades := fraco()) is not None:
                novidades.ligar()

        self._ligacao = shared.schema.connect(f"changed::{_CHAVE}", mudou)

    def ligar(self) -> None:
        """Oculto, o feed também não é consultado."""
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
        """Abrir a página reconhece tudo o que há nela; sem nada em cache (primeira vez, ou só falhas), busca agora."""
        self._checker.mark_seen()
        self._refazer()
        if not self._checker.posts:
            self._checker.check_async()
        self.alterado.emit()

    @Slot(bool)
    def paginaVisivel(self, visivel: bool) -> None:  # noqa: N802
        self._pagina_a_vista = visivel
        if visivel:
            # Só os posts novos refazem a lista (`_ao_mudar_os_posts`): refazê-la aqui recolheria as linhas abertas.
            self._checker.mark_seen()

    @Slot()
    def atualizar(self) -> None:
        """Força uma busca e responde por aviso. Uma busca em voo não recomeça: o fim dela responde do mesmo jeito."""
        self._avisos_sem_pedido()
        self._pedido = True
        self._aviso = self._avisos.adicionar("Atualizando novidades…", segundos=0)
        # Chave desligada: o checker está parado e a busca em voo foi abandonada; `check_async` responde "falha" na hora.
        if not self._checker.loading or not self.visivel:
            self._checker.check_async()
        self.alterado.emit()

    @Slot(str)
    def abrirNoNavegador(self, url: str) -> None:  # noqa: N802
        """Só um endereço da lista atual: o QML não escolhe o que o navegador abre."""
        if url and any(post["url"] == url for post in self._posts):
            abrir_url(url)

    def _refazer(self) -> bool:
        """Refaz a lista (as datas relativas mudam com o tempo); `True` se ela mudou."""
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
        # Posts que chegam com a página aberta já foram vistos: o selo não acende pelas costas de quem lê.
        if self._pagina_a_vista:
            self._checker.mark_seen()

    def _ao_terminar_a_busca(self, deu_certo: bool) -> None:
        self.alterado.emit()
        # A busca de seis em seis horas termina em silêncio: o selo é todo o vocabulário dela.
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
