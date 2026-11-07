# test_coleta_de_lixo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A coleta de lixo fica na thread principal: em outra, ela destruiria objetos do Qt fora da thread deles."""

import gc
import threading
import weakref
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QTimer

from kyron import app as modulo_app
from kyron.jogo import Jogo
from kyron.utils.coleta_de_lixo import coletar_o_que_passou_do_limite
from tests.apoio_abertura import preparar_main


class _Ciclo:
    def __init__(self, destruida_em):
        self.eu = self
        self.destruida_em = destruida_em

    def __del__(self):
        self.destruida_em.append(threading.current_thread().name)


def test_lixo_feito_em_outra_thread_so_e_coletado_na_principal(app_qt):  # noqa: ARG001
    assert gc.isenabled() is False  # o `app_qt` liga o mesmo que o app
    gc.collect()
    destruida_em, guardados = [], []

    def trabalho():
        _Ciclo(destruida_em)
        guardados.extend([] for _ in range(gc.get_threshold()[0] * 5))  # passa do limite: ligada, a coleta rodaria aqui

    thread = threading.Thread(target=trabalho)
    thread.start()
    thread.join()
    assert destruida_em == []

    coletar_o_que_passou_do_limite()
    assert destruida_em == [threading.main_thread().name]


def test_a_coleta_escolhe_a_geracao_mais_velha_que_passou_do_limite(monkeypatch):
    coletadas = []
    monkeypatch.setattr(gc, "collect", coletadas.append)
    monkeypatch.setattr(gc, "get_threshold", lambda: (10, 10, 10))
    for contagem, esperado in (((0, 0, 0), []), ((11, 0, 0), [0]), ((11, 11, 0), [1]), ((11, 11, 11), [2])):
        coletadas.clear()
        monkeypatch.setattr(gc, "get_count", lambda c=contagem: c)
        coletar_o_que_passou_do_limite()
        assert coletadas == esperado


def test_o_temporizador_coleta_sozinho_no_laco_de_eventos(app_qt):
    gc.collect()
    destruida_em, guardados = [], []  # o temporizador é o que o `app_qt` ligou
    _Ciclo(destruida_em)
    guardados.extend([] for _ in range(gc.get_threshold()[0] * 5))
    laco = QEventLoop()
    QTimer.singleShot(1200, laco.quit)
    laco.exec()
    assert destruida_em == [threading.main_thread().name]


def test_o_main_liga_a_coleta(monkeypatch):
    ligada, eventos = [], []
    preparar_main(monkeypatch, lambda _app, _argv, abertura: setattr(abertura, "aplicativo", SimpleNamespace(reiniciar=False)), eventos)
    monkeypatch.setattr(modulo_app, "coletar_so_na_principal", ligada.append)
    assert modulo_app.main(["kyron"]) == 0
    assert len(ligada) == 1


def test_jogo_solto_em_outra_thread_e_destruido_na_principal(app_qt):  # noqa: ARG001
    """Vale para toda thread do app: a reinstalação na Store, as varreduras e a gravação também podem soltar a última referência."""
    destruido_em = []
    caixa = [Jogo({"game_id": "imported_1", "source": "imported", "name": "A"})]
    caixa[0].atualizado.connect(lambda: None)
    fraca = weakref.ref(caixa[0], lambda _r: destruido_em.append(threading.current_thread().name))
    thread = threading.Thread(target=caixa.clear)
    thread.start()
    thread.join()
    laco = QEventLoop()
    QTimer.singleShot(100, laco.quit)
    laco.exec()
    assert fraca() is None
    assert destruido_em == [threading.main_thread().name]
