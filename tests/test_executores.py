# test_executores.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os dois executores dos managers: rede (daemon, descartável) e gravação (drenada)."""

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication

from kyron import shared
from kyron.jogo import Jogo
from kyron.store.managers import async_manager
from kyron.store.managers.file_manager import FileManager

_RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def executores_novos(monkeypatch):
    """Cada teste encerra os seus; os do processo ficam intactos."""
    rede, gravacao = async_manager._PoolDaemon(2, "teste"), ThreadPoolExecutor(max_workers=2)  # noqa: SLF001
    monkeypatch.setattr(async_manager, "_rede", rede)
    monkeypatch.setattr(async_manager, "_gravacao", gravacao)
    yield
    rede.encerrar()
    gravacao.shutdown(wait=True)


def _jogo(i):
    return Jogo({"game_id": f"imported_{i}", "source": "imported", "name": f"J{i}", "executable": "x.exe"})


def test_encerrar_espera_as_gravacoes(monkeypatch):
    principal = FileManager.main

    def lento(self, game, dados):
        time.sleep(0.2)
        principal(self, game, dados)

    monkeypatch.setattr(FileManager, "main", lento)
    gerente = FileManager()
    for i in range(3):
        gerente.process_game(_jogo(i), {}, lambda _m: None)
    async_manager.encerrar()
    for i in range(3):
        ficha = shared.games_dir / f"imported_{i}.json"
        assert json.loads(ficha.read_text(encoding="utf-8"))["game_id"] == f"imported_{i}"


def test_gravacao_depois_de_encerrar_roda_na_hora():
    async_manager.encerrar()
    FileManager().process_game(_jogo(9), {}, lambda _m: None)
    assert (shared.games_dir / "imported_9.json").is_file()


def test_rede_nao_segura_a_saida():
    codigo = (
        "import time\n"
        "from kyron.store.managers import async_manager\n"
        "class G(async_manager.AsyncManager):\n"
        "    def main(self, game, dados):\n"
        "        time.sleep(30)\n"
        "G().process_game(None, {}, lambda m: None)\n"
        "time.sleep(0.3)\n"
        "async_manager.encerrar()\n"
    )
    ambiente = {
        **os.environ,
        "KYRON_DADOS": os.environ["KYRON_DADOS"],
        "KYRON_REGISTRO": os.environ["KYRON_REGISTRO"],
    }
    inicio = time.monotonic()
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=_RAIZ, env=ambiente, timeout=20, check=False, capture_output=True
    )
    assert resultado.returncode == 0, resultado.stderr.decode(errors="replace")
    assert time.monotonic() - inicio < 15


def test_tarefa_que_levanta_nao_mata_a_thread():
    pool = async_manager._PoolDaemon(1, "um")  # noqa: SLF001
    feito = threading.Event()
    pool.submit(lambda: 1 / 0)
    pool.submit(feito.set)
    assert feito.wait(5)
    pool.encerrar()


def test_tarefa_e_solta_na_thread_principal_sem_esperar_a_proxima(app_qt):
    """A thread do pool não guarda a tarefa até a próxima chegar nem é a última dona dela: é o que evita o deadlock com o mutex de sinais do Qt."""
    pool = async_manager._PoolDaemon(1, "um")  # noqa: SLF001
    soltou_em = []

    class Marca:
        def __del__(self):
            soltou_em.append(threading.current_thread().name)

    def enviar():
        marca = Marca()
        pool.submit(lambda _marca: None, marca)

    enviar()
    fim = time.monotonic() + 5
    while not soltou_em and time.monotonic() < fim:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    pool.encerrar()
    assert soltou_em == [threading.main_thread().name]
