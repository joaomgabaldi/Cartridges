# test_ponte.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A `Ponte` entre os sinais dos jogos e o QML."""

import gc
import threading
import time
import weakref

from PySide6.QtCore import QEventLoop, QTimer

from cartridges.jogo import Jogo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.ponte import Ponte
from cartridges.store.managers.exibicao_manager import ExibicaoManager


def _jogo(game_id="a"):
    return Jogo({"game_id": game_id, "source": "imported", "name": "Alfa"})


def _rodar_ate(condicao, limite=5.0):
    fim = time.monotonic() + limite
    while not condicao() and time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
    return condicao()


def test_ligar_duas_vezes_avisa_uma(app_qt):
    ponte, jogo, avisos = Ponte(), _jogo(), []
    ponte.avisoRecebido.connect(avisos.append)
    ponte.ligar(jogo)
    ponte.ligar(jogo)
    jogo.aviso.emit("oi", "")
    assert avisos == ["oi"]


def test_ponte_nao_prende_o_jogo(app_qt):
    ponte, jogo = Ponte(), _jogo()
    ref = weakref.ref(jogo)
    ponte.ligar(jogo)
    del jogo
    gc.collect()
    assert ref() is None


def test_ligar_fora_da_principal_levanta(app_qt):
    erros = []

    def ligar():
        try:
            Ponte().ligar(_jogo())
        except RuntimeError as erro:
            erros.append(erro)

    thread = threading.Thread(target=ligar)
    thread.start()
    thread.join()
    assert len(erros) == 1


def test_jogo_importado_depois_fica_ligado(app_qt):
    ponte, jogo, avisos = Ponte(), _jogo(), []
    ponte.avisoRecebido.connect(avisos.append)
    gerente = ExibicaoManager(ModeloDaBiblioteca(), ponte.ligar)
    thread = threading.Thread(target=gerente.main, args=(jogo, {}))
    thread.start()
    thread.join()
    assert _rodar_ate(lambda: jogo.game_id in ponte._ligados)  # noqa: SLF001
    jogo.aviso.emit("x", "")
    assert avisos == ["x"]
