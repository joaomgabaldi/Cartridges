"""O interruptor de conquistas e a correção de appID na edição do jogo."""

import pytest

from cartridges.conquistas import historico
from cartridges.conquistas.formatos import Desbloqueio
from tests.test_auditoria_0923_ligacao import _stub_sgdb
from tests.test_zerados import jogo


class _Varredura:
    def __init__(self):
        self.pedidos = []

    def varrer_jogo(self, game):
        self.pedidos.append(game.game_id)


@pytest.fixture
def varredura(real_window, monkeypatch):
    falsa = _Varredura()

    class _App:
        varredura_conquistas = falsa

    monkeypatch.setattr(real_window, "get_application", lambda: _App())
    return falsa


def _aplicar(game, **mudancas):
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    dialogo = DetailsDialog(game)
    for nome, valor in mudancas.items():
        if nome == "conquistas":
            dialogo.conquistas_switch.set_active(valor)
        else:
            setattr(dialogo, nome, valor)
    dialogo.apply_preferences()
    return dialogo


def test_interruptor_vem_ligado_e_e_gravado(store, real_window, varredura):
    _stub_sgdb(store)
    game = jogo(store, 20, executable="x.exe")
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    assert DetailsDialog(game).conquistas_switch.get_active()
    _aplicar(game, conquistas=False)
    assert game.conquistas is False


def test_religar_pede_varredura(store, real_window, varredura):
    _stub_sgdb(store)
    game = jogo(store, 21, executable="x.exe", steam_appid="570", conquistas=False)
    _aplicar(game, conquistas=True)
    assert varredura.pedidos == [game.game_id]


def test_corrigir_o_appid_descarta_o_historico(store, real_window, varredura):
    _stub_sgdb(store)
    game = jogo(store, 22, executable="x.exe", steam_appid="10")
    historico.registrar(game.game_id, [Desbloqueio("ERRADA", 1)])
    _aplicar(game, fetched_steam_appid="20")
    assert historico.ler(game.game_id) is None
    assert varredura.pedidos == [game.game_id]


def test_primeiro_appid_nao_descarta_nada(store, real_window, varredura):
    _stub_sgdb(store)
    game = jogo(store, 23, executable="x.exe")
    historico.registrar(game.game_id, [Desbloqueio("A", 1)])
    _aplicar(game, fetched_steam_appid="20")
    assert historico.ler(game.game_id) == {"A": 1}
    assert varredura.pedidos == [game.game_id]


def test_sem_mudanca_nao_varre(store, real_window, varredura):
    _stub_sgdb(store)
    game = jogo(store, 24, executable="x.exe", steam_appid="570")
    _aplicar(game)
    assert varredura.pedidos == []
