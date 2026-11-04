# test_session_window.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A sessão manual: o relógio de um minuto, sem janela (a janela é do `ModeloDaSessao`)."""

import pytest

from cartridges import session_window as sw
from cartridges import shared
from cartridges.session_window import SessionWindow
from cartridges.utils import session_log
from tests.apoio_sessao import SessaoFalsa


@pytest.fixture
def clock(monkeypatch):
    class Clock:
        now = 1000.0

        def __call__(self):
            return self.now

    instancia = Clock()
    monkeypatch.setattr(sw, "monotonic", instancia)
    return instancia


@pytest.fixture
def sessao(monkeypatch):
    falsa = SessaoFalsa()
    monkeypatch.setattr(shared, "sessao", falsa, raising=False)
    return falsa


def test_flush_grava_os_segundos_inteiros(make_game, clock, sessao):
    janela = SessionWindow(make_game())
    clock.now += 61.7

    janela.flush()

    assert (janela.game.playtime, janela.session_seconds, janela.game.saves) == (61, 61, 1)
    clock.now += 0.3  # o resto de 0,7 s não se perdeu: 62 inteiros no total
    janela.flush()
    assert janela.game.playtime == 62
    janela.close()


def test_manual_dormindo_conta_um_intervalo(make_game, clock, sessao):
    """Review Focus 3: o PC dormiu a noite toda; só um intervalo de gravação conta."""
    janela = SessionWindow(make_game())
    clock.now += 8 * 3600

    janela.flush()

    assert janela.game.playtime == SessionWindow.TICK_INTERVAL
    clock.now += 10  # e o relógio de parede, que nem é lido, não muda nada
    janela.flush()
    assert janela.game.playtime == SessionWindow.TICK_INTERVAL + 10
    janela.close()


def test_o_relogio_sobrevive_a_gravacao_do_minuto(make_game, clock, sessao):
    """O relógio não volta a zero quando o minuto é gravado."""
    janela = SessionWindow(make_game())
    clock.now += 65
    janela.flush()  # o tique de um minuto
    clock.now += 5

    assert janela.elapsed == 70
    janela.close()


def test_fechar_grava_registra_avisa_e_traz_de_volta(make_game, clock, sessao):
    janela = SessionWindow(make_game(game_id="shortcuts_7"))
    clock.now += 80

    janela.close()
    janela.close()  # a segunda não registra de novo

    assert janela.game.playtime == 80
    assert [linha["seconds"] for linha in session_log.load("shortcuts_7")] == [80]
    assert sessao.blocker == [None]
    assert [seg for _jogo, seg in sessao.toasts] == [80]
    assert sessao.presented == 1
    assert janela.game.updates == 1
    assert SessionWindow.active is None


def test_present_poe_a_camada_e_pede_a_janela(make_game, clock, sessao):
    janela = SessionWindow(make_game())

    janela.present()

    assert sessao.blocker == [janela.game] and sessao.janelas == [janela]
    janela.close()
