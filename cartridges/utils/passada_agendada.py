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

from cartridges import shared
from cartridges.utils.thread_principal import na_thread_principal


class PassadaAgendada:
    """Uma passada por execução, armada por ``start`` e desligada por ``stop``."""

    # A abertura está ocupada (janela, disco e, em geral, uma importação logo depois).
    atraso_inicial = 20
    # A importação mexe no mesmo disco e na mesma rede: a passada espera ela acabar.
    espera_da_importacao = 30

    def __init__(self) -> None:
        # Temporizador da partida pendente: cancelável no encerramento e nunca armado duas vezes.
        self._timer: Optional[threading.Timer] = None
        # Sobe a cada armação e a cada `stop()`: a partida que já disparou mas ainda
        # espera na fila da thread principal confere o número e se descarta.
        self._armacao = 0
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
        self._armar(self.atraso_inicial)

    def _armar(self, segundos: float) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._armacao += 1
        # O temporizador roda numa thread própria; a partida volta à principal, onde
        # `run_async` tira o retrato da store.
        self._timer = threading.Timer(
            segundos, na_thread_principal, (self._on_timer, self._armacao)
        )
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        """Cancela a passada pendente e desliga a que está em andamento."""
        self._stopped = True
        self._generation += 1
        self._armacao += 1
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    @staticmethod
    def _importando() -> bool:
        # shortcut: lê o estado da janela (duplo nos testes); a importação do plano 2 passa a
        # marcá-lo no Aplicativo, e este teste muda junto com ela.
        app = shared.win.get_application() if shared.win is not None else None
        return app is not None and app.state == shared.AppState.IMPORT

    def _on_timer(self, armacao: int) -> None:
        if self._stopped or armacao != self._armacao:
            return
        self._timer = None
        if self._importando():
            self._armar(self.espera_da_importacao)
            return
        self.run_async()

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
