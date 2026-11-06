# test_ponte.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A `Ponte` entre os sinais dos jogos e o QML."""

import gc
import threading
import time
import weakref

from PySide6.QtCore import QEventLoop, QTimer

from kyron.jogo import Jogo
from kyron.modelos.biblioteca import ModeloDaBiblioteca
from kyron.ponte import Ponte
from kyron.store.managers.exibicao_manager import ExibicaoManager


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
    ponte.fila.adicionar = lambda texto, *_a, **_k: avisos.append(texto)
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
    ponte.fila.adicionar = lambda texto, *_a, **_k: avisos.append(texto)
    gerente = ExibicaoManager(ModeloDaBiblioteca(), ponte.ligar)
    thread = threading.Thread(target=gerente.main, args=(jogo, {}))
    thread.start()
    thread.join()
    assert _rodar_ate(lambda: jogo in ponte._ligados)  # noqa: SLF001
    jogo.aviso.emit("x", "")
    assert avisos == ["x"]


def test_jogo_nao_prende_a_ponte(app_qt):
    jogo, ponte = _jogo(), Ponte()
    ref = weakref.ref(ponte)
    ponte.ligar(jogo)
    del ponte
    gc.collect()
    assert ref() is None
    jogo.aviso.emit("oi", "")  # a ponte já se foi: nada acontece


def test_ligar_depois_da_adocao_nao_duplica_os_sinais(app_qt):
    """A adoção troca o `game_id` do mesmo objeto: ligar de novo não conecta os sinais outra vez."""
    ponte, jogo, avisos = Ponte(), _jogo(), []
    ponte.fila.adicionar = lambda texto, *_a, **_k: avisos.append(texto)
    ponte.ligar(jogo)
    jogo.game_id = "outro"
    ponte.ligar(jogo)
    jogo.aviso.emit("oi", "")
    assert avisos == ["oi"]
