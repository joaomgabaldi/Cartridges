# test_copias_animadas_boot.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Limpeza e preparo das cópias animadas na abertura e no fechamento do app."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import cartridges.main as main_module
from cartridges import shared
from cartridges.utils import copias_animadas


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
def abertura(monkeypatch, store):
    """Registra, na ordem, o que a abertura chamou."""
    eventos = []
    _ThreadFalsa.criadas = []
    monkeypatch.setattr(main_module.threading, "Thread", _ThreadFalsa)
    monkeypatch.setattr(
        main_module, "entregar_na_tela", lambda funcao, *args: funcao(*args)
    )
    monkeypatch.setattr(
        copias_animadas, "limpar", lambda ids: eventos.append(("limpar", ids))
    )
    monkeypatch.setattr(
        copias_animadas, "preparar", lambda capas: eventos.append(("preparar", capas))
    )
    capas = [("g1", Path("g1.gif"))]
    monkeypatch.setattr(
        shared, "win", SimpleNamespace(capas_na_ordem=lambda: capas), raising=False
    )
    return SimpleNamespace(eventos=eventos, capas=capas)


def _jogos(store, *ids):
    for game_id in ids:
        store.source_games.setdefault("imported", {})[game_id] = SimpleNamespace(
            game_id=game_id
        )


def test_limpa_numa_thread_de_fundo_e_depois_prepara(abertura, store, schema):
    _jogos(store, "g1", "g2")

    main_module.limpar_e_preparar_capas_animadas()

    (thread,) = _ThreadFalsa.criadas
    assert thread.daemon is True
    assert abertura.eventos == [], "nada roda na thread principal"

    thread.target()

    assert abertura.eventos == [
        ("limpar", {"g1", "g2"}),
        ("preparar", abertura.capas),
    ]


def test_os_ids_sao_coletados_antes_da_thread_comecar(abertura, store, schema):
    _jogos(store, "g1")

    main_module.limpar_e_preparar_capas_animadas()
    _jogos(store, "g2")  # chega depois: a loja não é lida de dentro da thread
    _ThreadFalsa.criadas[0].target()

    assert abertura.eventos[0] == ("limpar", {"g1"})


def test_sem_janela_nao_prepara_nem_levanta(abertura, store, schema, monkeypatch):
    monkeypatch.setattr(shared, "win", None)

    main_module.limpar_e_preparar_capas_animadas()
    _ThreadFalsa.criadas[0].target()

    assert abertura.eventos == [("limpar", set())]


def test_o_fechamento_do_app_encerra_as_copias(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        main_module.copias_animadas, "encerrar", lambda: chamadas.append("encerrar")
    )
    monkeypatch.setattr(main_module.session_fita, "fechar", lambda: None)
    monkeypatch.setattr(shared, "win", None)
    monkeypatch.setattr(shared, "store", shared.store)

    main_module.CartridgesApplication().do_shutdown()

    assert chamadas == ["encerrar"]
