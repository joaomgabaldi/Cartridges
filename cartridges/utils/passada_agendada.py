# passada_agendada.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O agendamento das passadas de segundo plano da abertura (HowLongToBeat,
tamanho em disco, conquistas): esperar um pouco depois de abrir, esperar a
importação acabar, uma passada por vez, e parar de verdade no ``stop``.

Cada passada só escreve ``run_async`` (o retrato da store e a thread) e o
trabalhador, que confere ``_deve_parar`` entre um jogo e outro.
"""

import threading
from typing import Optional

from gi.repository import GLib

from cartridges import shared


class PassadaAgendada:
    """Uma passada por execução, armada por ``start`` e desligada por ``stop``."""

    # A abertura está ocupada (janela, disco e, em geral, uma importação logo depois).
    atraso_inicial = 20
    # A importação mexe no mesmo disco e na mesma rede: a passada espera ela acabar.
    espera_da_importacao = 30

    def __init__(self) -> None:
        # Id do GLib da partida pendente: cancelável no encerramento e nunca armada duas vezes.
        self._timeout_id: Optional[int] = None
        # Uma passada por vez: `run_async` é alcançável pelo temporizador e por quem pede.
        self._lock = threading.Lock()
        self._running = False
        # Marcado ao sair. O trabalhador confere entre um jogo e outro; o que já
        # está em curso não dá para cancelar, e o resultado dele é descartado.
        self._stopped = False
        # Sobe a cada `stop()`. O trabalhador leva o número com que nasceu e para
        # quando ele muda: o `start()` logo depois do `stop()` (o reset faz isso)
        # desfaz o `_stopped`, e o trabalhador antigo seguiria numa biblioteca que
        # já não existe.
        self._generation = 0

    def start(self) -> None:
        """Arma a passada. Chamada uma vez, no início do app."""
        self._stopped = False
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
        self._timeout_id = GLib.timeout_add_seconds(self.atraso_inicial, self._on_timer)

    def stop(self) -> None:
        """Cancela a passada pendente e desliga a que está em andamento."""
        self._stopped = True
        self._generation += 1
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def _on_timer(self) -> bool:
        self._timeout_id = None
        if self._stopped:
            return False
        app = shared.win.get_application() if shared.win is not None else None
        if app is not None and app.state == shared.AppState.IMPORT:
            self._timeout_id = GLib.timeout_add_seconds(self.espera_da_importacao, self._on_timer)
            return False
        self.run_async()
        return False

    def run_async(self) -> None:
        raise NotImplementedError

    def _deve_parar(self, geracao: int) -> bool:
        return self._stopped or geracao != self._generation

    def _reservar(self) -> bool:
        """Marca a passada como em andamento; False se já havia uma."""
        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def _liberar(self) -> None:
        with self._lock:
            self._running = False
