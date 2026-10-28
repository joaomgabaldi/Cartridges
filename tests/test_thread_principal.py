# test_thread_principal.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`na_thread_principal`, o `AsyncManager` e o `Pipeline` sem GLib/GObject."""

import threading
import types
import time

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from cartridges.store.managers.async_manager import AsyncManager
from cartridges.store.pipeline import Pipeline
from cartridges.utils.thread_principal import eh_thread_principal, na_thread_principal


def _rodar_ate(condicao, limite=5.0):
    fim = time.monotonic() + limite
    while not condicao() and time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
    return condicao()


def test_executa_na_thread_principal(app_qt):
    visto = []
    thread = threading.Thread(
        target=lambda: na_thread_principal(lambda: visto.append(eh_thread_principal()))
    )
    thread.start()
    thread.join()
    assert visto == []  # enfileirada, nunca síncrona
    assert _rodar_ate(lambda: visto)
    assert visto == [True]


def test_chamada_da_principal_tambem_e_adiada(app_qt):
    visto = []
    na_thread_principal(visto.append, 1)
    assert visto == []
    assert _rodar_ate(lambda: visto)
    assert visto == [1]


def test_ordem_preservada(app_qt):
    visto = []
    for i in range(3):
        na_thread_principal(visto.append, i)
    assert _rodar_ate(lambda: len(visto) == 3)
    assert visto == [0, 1, 2]


class _Gerente(AsyncManager):
    def __init__(self):
        super().__init__()
        self.rodou = []

    def main(self, game, additional_data):
        self.rodou.append(game)


def test_async_manager_entrega_o_callback_na_principal(app_qt):
    gerente = _Gerente()
    entregas = []
    gerente.process_game("jogo", {}, lambda m: entregas.append((m, eh_thread_principal())))
    assert _rodar_ate(lambda: entregas)
    assert entregas == [(gerente, True)]
    assert gerente.rodou == ["jogo"]


def test_cancelamento_impede_o_trabalho_e_reset_libera(app_qt):
    gerente = _Gerente()
    gerente.cancel_tasks()
    entregas = []
    gerente.process_game("a", {}, entregas.append)
    # Como o Gio.Task: cancelada, a tarefa não roda mas a conclusão ainda chega,
    # senão o pipeline (e a importação) nunca terminaria.
    assert _rodar_ate(lambda: entregas)
    assert gerente.rodou == []
    gerente.reset_cancellable()
    gerente.process_game("b", {}, entregas.append)
    assert _rodar_ate(lambda: len(entregas) == 2)
    assert gerente.rodou == ["b"]


def test_pipeline_emite_advanced(app_qt):
    class Bloqueante:
        blocking = True
        run_after = ()
        name = "X"

        def process_game(self, game, data, callback):
            callback(self)

    pipeline = Pipeline(types.SimpleNamespace(game_id="x"), {}, [Bloqueante()])
    emissoes = []
    pipeline.advanced.connect(lambda: emissoes.append(1))
    pipeline.advance()
    assert emissoes == [1]
    assert pipeline.is_done


def test_conexao_direta_feita_em_worker_roda_no_emit_da_principal(app_qt):
    from PySide6.QtCore import Qt  # noqa: PLC0415

    pipeline = Pipeline(types.SimpleNamespace(game_id="x"), {}, [])
    chamadas = []

    def conectar():
        pipeline.advanced.connect(
            lambda: chamadas.append(eh_thread_principal()), Qt.ConnectionType.DirectConnection
        )

    thread = threading.Thread(target=conectar)
    thread.start()
    thread.join()
    pipeline.advanced.emit()
    assert chamadas == [True]


def test_excecao_na_tarefa_e_registrada_e_callback_chega(app_qt, caplog):
    gerente = _Gerente()
    gerente.run = lambda *_: 1 / 0
    entregas = []
    gerente.process_game("a", {}, entregas.append)
    assert _rodar_ate(lambda: entregas)
    assert "Erro inesperado" in caplog.text


def test_encerrar_descarta_sem_quebrar_quem_chama(app_qt):
    from cartridges.store.managers import async_manager  # noqa: PLC0415

    async_manager.encerrar()
    try:
        entregas = []
        _Gerente().process_game("a", {}, entregas.append)  # não levanta
        assert entregas == []
    finally:
        async_manager._executor = async_manager.ThreadPoolExecutor(  # noqa: SLF001
            thread_name_prefix="manager"
        )
