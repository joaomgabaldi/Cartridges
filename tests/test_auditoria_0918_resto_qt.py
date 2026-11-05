# test_auditoria_0918_resto_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressões da auditoria de 18/09/2026: as varreduras de fundo. Cada teste falha sem o conserto do achado."""


import threading
from types import SimpleNamespace


class _ThreadEmLinha:
    """O `threading` do módulo, com a `Thread` rodando na hora; o resto (o `Timer` da passada) é o de verdade."""

    @staticmethod
    def Thread(target, args, daemon):  # noqa: N802 - o nome da classe que ela substitui
        return SimpleNamespace(start=lambda: target(*args))

    def __getattr__(self, nome):
        return getattr(threading, nome)


def _thread_em_linha(modulo, monkeypatch):
    # Trocar só o atributo do módulo: trocar `threading.Thread` quebraria o `Timer` (Python 3.15).
    monkeypatch.setattr(modulo, "threading", _ThreadEmLinha())


def test_b11_varredura_do_hltb_reiniciada_no_reset_para(monkeypatch, store, make_game):
    from cartridges.utils import hltb_backfill  # noqa: PLC0415

    for game_id in ("a", "b"):
        store.add_game(make_game(game_id=game_id, has_hltb_times=False, hltb_id=None), {})
    sweep = hltb_backfill.HLTBBackfill()
    buscas = []

    def buscar(*_args):
        buscas.append(1)
        sweep.stop()  # o reset no meio da varredura
        sweep.start()
        raise hltb_backfill.HLTBError("nada")

    monkeypatch.setattr(hltb_backfill, "fetch_times", buscar)
    monkeypatch.setattr(hltb_backfill, "shared_helper", lambda: None)
    _thread_em_linha(hltb_backfill, monkeypatch)
    try:
        sweep.run_async()
    finally:
        sweep.stop()

    assert len(buscas) == 1


def test_b11_varredura_de_tamanho_reiniciada_no_reset_para(monkeypatch, store, make_game):
    from cartridges.utils import install_size  # noqa: PLC0415

    for game_id in ("a", "b"):
        store.add_game(make_game(game_id=game_id, install_size=0, install_size_ts=0), {})
    sweep = install_size.InstallSizeSweep()
    medidas = []

    def medir(_pasta):
        medidas.append(1)
        sweep.stop()
        sweep.start()
        return 0

    monkeypatch.setattr(install_size, "install_size_folder", lambda _cmd: "C:/jogo")
    monkeypatch.setattr(install_size, "folder_size", medir)
    _thread_em_linha(install_size, monkeypatch)
    try:
        sweep.run_async()
    finally:
        sweep.stop()

    assert len(medidas) == 1


def test_b12_resultado_tardio_do_hltb_nao_sobrescreve_a_correcao(store, make_game):
    from cartridges.utils.hltb_backfill import HLTBBackfill  # noqa: PLC0415

    jogo = make_game(game_id="a", has_hltb_times=True)
    jogo.update_values = lambda valores: setattr(jogo, "sobrescrito", valores)
    store.add_game(jogo, {})

    HLTBBackfill()._apply(jogo, {"hltb_main": 1})

    assert not hasattr(jogo, "sobrescrito")


def test_b16_jogo_que_saiu_do_disco_perde_o_tamanho(
    monkeypatch, store, make_game, flush_idle
):
    from cartridges.utils import install_size  # noqa: PLC0415

    jogo = make_game(game_id="a", install_size=5000, install_size_ts=0)
    store.add_game(jogo, {})
    monkeypatch.setattr(install_size, "install_size_folder", lambda _cmd: "C:/sumiu")
    monkeypatch.setattr(install_size, "folder_size", lambda _pasta: 0)
    _thread_em_linha(install_size, monkeypatch)

    install_size.InstallSizeSweep().run_async()
    flush_idle()

    assert jogo.install_size == 0
    assert jogo.install_size_ts == 0
