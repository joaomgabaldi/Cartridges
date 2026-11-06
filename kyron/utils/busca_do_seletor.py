# busca_do_seletor.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que os seletores com busca fazem igual: esperar a pessoa parar de digitar e interromper o download da imagem escolhida.

Quem usa é um ``QObject`` com ``busca``, ``search()``, ``_generation``, ``_last_query`` e ``_closed``.
O atraso corre numa ``threading.Timer``; quem dispara é sempre a thread principal.
"""

import threading
from typing import Any, Optional

from kyron.utils.download import DownloadCancelado
from kyron.utils.thread_principal import na_thread_principal


_MB = 1024 * 1024


def _tamanho(n: int) -> str:
    # KB para cima, como o Explorador de Arquivos: nunca "0 KB" com algo baixado. MB de 1024².
    kb = -(-n // 1024)
    if kb < 1024:
        return f"{kb} KB"
    return f"{n / _MB:.1f} MB".replace(".", ",")


def tamanho_baixado(recebido: int, total: Optional[int]) -> str:
    """ "4,4 MB de 21,0 MB", ou só "4,4 MB" quando o total não é conhecido."""
    if total is None:
        return _tamanho(recebido)
    return _("{recebido} de {total}").format(recebido=_tamanho(recebido), total=_tamanho(total))


class BuscaDoSeletor:
    atraso_da_busca_ms = 500

    _debounce_timer: Optional[threading.Timer] = None
    # Cada tecla invalida o disparo anterior, mesmo que o ``Timer`` dele já tenha saído.
    _debounce_id = 0

    def _on_search_changed(self, *_args: Any) -> None:
        self._cancelar_debounce()
        token = self._debounce_id
        self._debounce_timer = threading.Timer(
            self.atraso_da_busca_ms / 1000, na_thread_principal, (self._debounce_fire, token)
        )
        self._debounce_timer.daemon = True
        self._debounce_timer.start()

    def _cancelar_debounce(self) -> None:
        """Na thread principal: o disparo pendente não acontece."""
        self._debounce_id += 1
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
            self._debounce_timer = None

    def _debounce_fire(self, token: int) -> None:
        if token != self._debounce_id or self._closed:
            return
        self._debounce_timer = None
        # O texto programático do ``abrir`` já foi buscado; Enter repete a busca por outro caminho (``buscarAgora``).
        if self.busca.strip() == self._last_query:
            return
        self.search()

    def _ao_progredir(self, recebido: int, total: Optional[int]) -> None:
        """Roda na thread do download; com o seletor fechado, interrompe (uma capa animada de 200 MB seguia baixando)."""
        if self._closed:
            raise DownloadCancelado
