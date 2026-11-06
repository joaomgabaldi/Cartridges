"""A varredura do HowLongToBeat e o agendamento das passadas de segundo plano."""

import logging
import threading
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from kyron.modelos import tarefas
from kyron.utils import hltb, hltb_backfill
from kyron.utils.passada_agendada import PassadaAgendada


def _rodar(limite=0.15):
    """Gira o laço de eventos por um instante: o que foi enfileirado chega."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()


def _rodar_ate(condicao, limite=5.0):
    fim = time.monotonic() + limite
    while not condicao() and time.monotonic() < fim:
        _rodar(0.02)
    return condicao()


def _thread_em_linha(monkeypatch):
    monkeypatch.setattr(
        hltb_backfill.threading,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
    )


def _jogos(store, make_game, *ids):
    for game_id in ids:
        store.add_game(make_game(game_id=game_id, name=game_id, has_hltb_times=False, hltb_id=None), {})


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    monkeypatch.setattr(hltb_backfill, "shared_helper", lambda: None)


def test_hltb_vira_tarefa_com_a_fila_e_termina(monkeypatch, store, make_game):
    _jogos(store, make_game, "a", "b", "c")
    vistas = []
    comecar = tarefas.comecar
    monkeypatch.setattr(tarefas, "comecar", lambda nome, total: (vistas.append((nome, total)), comecar(nome, total))[1])

    def nao_acha(*_args):
        raise hltb.HLTBGameNotFoundError("x")

    monkeypatch.setattr(hltb_backfill, "fetch_times", nao_acha)
    _thread_em_linha(monkeypatch)

    sweep = hltb_backfill.HLTBBackfill()
    try:
        sweep.run_async()
    finally:
        sweep.stop()
    _rodar()

    assert vistas == [("HowLongToBeat", 3)]
    assert tarefas.lista.rowCount() == 0


def test_resultado_e_aplicado_na_principal(monkeypatch, store, make_game):
    _jogos(store, make_game, "a")
    jogo = store["a"]
    monkeypatch.setattr(hltb_backfill, "fetch_times", lambda *_a: {"hltb_main": 3600})
    visto = []
    aplicar = hltb_backfill.HLTBBackfill._apply
    monkeypatch.setattr(
        hltb_backfill.HLTBBackfill,
        "_apply",
        lambda self, *a: (visto.append(threading.current_thread() is threading.main_thread()), aplicar(self, *a))[1],
    )

    sweep = hltb_backfill.HLTBBackfill()
    try:
        sweep.run_async()
        assert _rodar_ate(lambda: visto)
    finally:
        sweep.stop()

    assert visto == [True]
    assert (jogo.hltb_main, jogo.saves, jogo.updates) == (3600, 1, 1)


def test_jogo_que_o_hltb_nao_conhece_nao_deixa_rastro_de_erro(monkeypatch, store, make_game, caplog):
    # "Não encontrado" é resposta, não erro: eram 6 tracebacks por abertura no log.
    caplog.set_level(logging.DEBUG)
    _jogos(store, make_game, "a", "b")
    erros = {"a": hltb.HLTBGameNotFoundError(), "b": hltb.HLTBUnavailableError("fora")}

    def buscar(_helper, nome, _hltb_id):
        raise erros[nome]

    monkeypatch.setattr(hltb_backfill, "fetch_times", buscar)
    _thread_em_linha(monkeypatch)
    sweep = hltb_backfill.HLTBBackfill()
    try:
        sweep.run_async()
    finally:
        sweep.stop()

    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert any(r.exc_info for r in caplog.records if "missed b" in r.getMessage())
    assert not any(r.exc_info for r in caplog.records if "missed a" in r.getMessage())


def test_varredura_reiniciada_no_reset_para(monkeypatch, store, make_game):
    _jogos(store, make_game, "a", "b")
    sweep = hltb_backfill.HLTBBackfill()
    buscas = []

    def buscar(*_args):
        buscas.append(1)
        sweep.stop()  # o reset no meio da varredura
        sweep.start()
        raise hltb.HLTBError("nada")

    monkeypatch.setattr(hltb_backfill, "fetch_times", buscar)
    _thread_em_linha(monkeypatch)
    try:
        sweep.run_async()
    finally:
        sweep.stop()

    assert len(buscas) == 1


def test_resultado_tardio_nao_sobrescreve_a_correcao(store, make_game):
    jogo = make_game(game_id="a", has_hltb_times=True)
    jogo.update_values = lambda valores: setattr(jogo, "sobrescrito", valores)
    store.add_game(jogo, {})

    hltb_backfill.HLTBBackfill()._apply(jogo, {"hltb_main": 1})

    assert not hasattr(jogo, "sobrescrito")


def test_backfill_para_no_stop(monkeypatch, store, make_game):
    """O ``stop()`` não espera a busca em curso: volta na hora, e o resultado dela é descartado."""
    _jogos(store, make_game, "a", "b")
    jogo = store["a"]
    entrou, solta = threading.Event(), threading.Event()

    def travada(*_args):
        entrou.set()
        solta.wait(10)
        return {"hltb_main": 60}

    monkeypatch.setattr(hltb_backfill, "fetch_times", travada)
    sweep = hltb_backfill.HLTBBackfill()
    sweep.run_async()
    assert entrou.wait(5)

    inicio = time.monotonic()
    sweep.stop()
    assert time.monotonic() - inicio < 1

    solta.set()
    assert _rodar_ate(lambda: not sweep._running)  # noqa: SLF001
    _rodar()
    assert (jogo.updates, store["b"].updates) == (0, 0)  # nada aplicado depois do stop


class _Passada(PassadaAgendada):
    atraso_inicial = 0.05
    espera_da_importacao = 0.05

    def __init__(self):
        super().__init__()
        self.rodou = []

    def run_async(self):
        self.rodou.append(threading.current_thread() is threading.main_thread())


def test_passada_dispara_na_principal_depois_do_atraso():
    passada = _Passada()
    passada.start()
    assert passada.rodou == []
    assert _rodar_ate(lambda: passada.rodou)
    assert passada.rodou == [True]


def test_passada_parada_antes_do_atraso_nao_dispara():
    passada = _Passada()
    passada.start()
    passada.stop()
    _rodar(0.3)
    assert passada.rodou == []


def test_passada_espera_a_importacao_acabar(monkeypatch):
    passada = _Passada()
    importando = [True]
    monkeypatch.setattr(PassadaAgendada, "_importando", staticmethod(lambda: importando[0]))
    passada.start()
    _rodar(0.3)
    assert passada.rodou == []
    importando[0] = False
    assert _rodar_ate(lambda: passada.rodou)


def test_partida_ja_na_fila_nao_sobrevive_ao_stop():
    passada = _Passada()
    passada.start()
    armacao = passada._armacao  # noqa: SLF001
    passada.stop()
    passada._on_timer(armacao)  # noqa: SLF001  # a que disparou antes do stop e chegou depois
    assert passada.rodou == []


def test_start_depois_de_start_arma_uma_vez_so():
    passada = _Passada()
    passada.start()
    passada.start()
    _rodar(0.3)
    assert passada.rodou == [True]

