# test_copias_animadas_boot.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Limpeza das cópias animadas na abertura, antes de o modelo poder pedir as que faltam."""

from types import SimpleNamespace

import pytest

from kyron import app as app_modulo
from kyron.utils import copias_animadas


class _ThreadFalsa:
    """Guarda o alvo; o teste decide quando rodá-lo."""

    criadas: list = []

    def __init__(self, target, daemon=False):
        self.target = target
        self.daemon = daemon
        _ThreadFalsa.criadas.append(self)

    def start(self):
        pass


@pytest.fixture
def abertura(monkeypatch):
    """Registra, na ordem, o que a abertura chamou."""
    eventos = []
    _ThreadFalsa.criadas = []
    monkeypatch.setattr(app_modulo.threading, "Thread", _ThreadFalsa)
    monkeypatch.setattr(app_modulo, "na_thread_principal", lambda funcao, *args: funcao(*args))
    monkeypatch.setattr(copias_animadas, "limpar", lambda ids: eventos.append(("limpar", ids)))
    modelo = SimpleNamespace(ativar_copias=lambda: eventos.append(("ativar",)))
    return SimpleNamespace(eventos=eventos, modelo=modelo)


def test_limpa_numa_thread_de_fundo_e_depois_libera_o_modelo(abertura, store):
    store.source_games.setdefault("imported", {})["g1"] = SimpleNamespace(game_id="g1")

    app_modulo._limpar_e_ativar_copias(abertura.modelo)

    (thread,) = _ThreadFalsa.criadas
    assert thread.daemon is True
    assert abertura.eventos == [], "nada roda na thread principal"
    thread.target()
    assert abertura.eventos == [("limpar", {"g1"}), ("ativar",)]


def test_os_ids_sao_coletados_antes_da_thread_comecar(abertura, store):
    store.source_games.setdefault("imported", {})["g1"] = SimpleNamespace(game_id="g1")

    app_modulo._limpar_e_ativar_copias(abertura.modelo)
    store.source_games["imported"]["g2"] = SimpleNamespace(game_id="g2")  # chega depois
    _ThreadFalsa.criadas[0].target()

    assert abertura.eventos[0] == ("limpar", {"g1"})
