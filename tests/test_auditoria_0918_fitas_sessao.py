# test_auditoria_0918_fitas_sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressões da auditoria de 18/09/2026 sobre as fitas na sessão. Cada teste falha sem o conserto do achado."""


import json
import threading
import time

from kyron import shared
from kyron.utils import session_fita
from tests.apoio_fita import FitaFalsa, cor_mandada, estado_mandado, falsas, pastas, sem_fade
from tests.apoio_session_fita import _jogo


def test_a3_fechamento_devolve_a_fita_suspensa(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita._guardar_e_vestir()
    session_fita._suspensas.add("eb0")

    session_fita.fechar()

    assert estado_mandado(modulos["eb0"]) is False
    assert schema.get_string(session_fita.CHAVE_ESTADO) == ""


def test_a3_fita_que_nao_respondeu_a_leitura_nao_e_pintada(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, False)
    modulos["eb1"].status = lambda nowait=False: {"Error": "sem resposta"}

    session_fita._arrancar()

    assert list(json.loads(schema.get_string(session_fita.CHAVE_ESTADO))) == ["eb0"]
    assert modulos["eb1"].recebidos == []

    # Nenhuma lida: a chave fica vazia, e não "{}".
    schema.set_string(session_fita.CHAVE_ESTADO, "")
    session_fita.fechar_conexoes()
    modulos["eb0"].status = lambda nowait=False: {"Error": "sem resposta"}
    session_fita._falhas.clear()
    session_fita._guardar_e_vestir()
    assert schema.get_string(session_fita.CHAVE_ESTADO) == ""


def test_a3_fechamento_espera_o_arranque_em_curso(falsas, monkeypatch, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita._guardar_e_vestir()
    monkeypatch.setattr(session_fita, "PRAZO_FECHAMENTO", 3)

    # O arranque segura a trava enquanto veste as fitas.
    session_fita._TRAVA_ARRANQUE.acquire()
    fechamento = threading.Thread(target=session_fita.fechar)
    fechamento.start()
    try:
        time.sleep(0.2)
        assert schema.get_string(session_fita.CHAVE_ESTADO)
        assert estado_mandado(modulos["eb0"]) is True
    finally:
        session_fita._TRAVA_ARRANQUE.release()
    fechamento.join(5)

    assert schema.get_string(session_fita.CHAVE_ESTADO) == ""
    assert estado_mandado(modulos["eb0"]) is False


def test_b2_ja_terminei_rapido_vence_a_cor_do_jogo(falsas, tmp_path, monkeypatch, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita._guardar_e_vestir()
    jogo = _jogo(tmp_path)
    tarefas = []
    monkeypatch.setattr(session_fita, "_em_thread", tarefas.append)

    session_fita.comecar(jogo)
    session_fita.voltar()
    # A cor do app fica pronta antes da do jogo, que ainda lia a capa.
    tarefas[1]()
    tarefas[0]()

    assert cor_mandada(modulos["eb0"]) == session_fita.hsv_hex(session_fita.cor_do_app())


def test_b3_descarte_nao_derruba_a_conexao_que_tomou_o_lugar():
    fita = session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")
    velha, nova = FitaFalsa(), FitaFalsa()
    session_fita._conexoes[fita.id] = (fita.ip, nova)

    session_fita._descartar(fita, velha)

    assert session_fita._conexoes[fita.id][1] is nova
    assert getattr(velha, "fechada", False)
    assert not getattr(nova, "fechada", False)


def test_b15_sidecar_com_tipo_errado_vale_o_automatico(tmp_path, schema):
    jogo = _jogo(tmp_path)
    shared.fitas_dir.mkdir(parents=True, exist_ok=True)
    (shared.fitas_dir / f"{jogo.game_id}.json").write_text(
        json.dumps({"locked": True, "matiz": None}), encoding="utf-8"
    )

    assert session_fita.cor_do_jogo(jogo) == session_fita.cor_da_capa(
        jogo.get_cover_path()
    )
