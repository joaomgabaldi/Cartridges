"""A varredura de abertura: grava o histórico e avisa do que é novo."""

import json

import pytest

from cartridges.conquistas import catalogo, historico, varredura
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.varredura import VarreduraConquistas
from tests.apoio_conquistas import criar, pastas  # noqa: F401


@pytest.fixture(autouse=True)
def sem_catalogo(monkeypatch):
    monkeypatch.setattr(catalogo, "obter", lambda _appid, _exe: catalogo.Renovacao(None))


def _goldberg(pastas, appid, conquistas):  # noqa: F811
    criar(
        pastas.appdata / "GSE Saves" / appid / "achievements.json",
        json.dumps({nome: {"earned": True, "earned_time": hora} for nome, hora in conquistas}),
    )


def _rodar(games, flush_idle):
    instancia = VarreduraConquistas()
    instancia._worker(games, instancia._generation)
    flush_idle()
    return instancia


def _avisos(win):
    return [toast.get_title() for toast in win.toast_queue.added]


def _registrado(store, make_game, numero, **campos):
    game = make_game(game_id=f"shortcuts_{numero}", name=f"Jogo {numero}", executable="", **campos)
    store.add_game(game, {}, run_pipeline=False)
    return game


def test_primeira_varredura_grava_sem_avisar(store, make_game, pastas, win, flush_idle):
    _goldberg(pastas, "570", [("ACH_A", 100)])
    game = _registrado(store, make_game, 1, steam_appid="570")
    _rodar([game], flush_idle)
    assert historico.ler(game.game_id) == {"ACH_A": 100}
    assert _avisos(win) == []


def test_conquista_nova_desde_a_ultima_abertura(store, make_game, pastas, win, flush_idle):
    game = _registrado(store, make_game, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("ACH_A", 100)])
    _goldberg(pastas, "570", [("ACH_A", 100), ("ACH_B", 200)])
    _rodar([game], flush_idle)
    assert historico.ler(game.game_id) == {"ACH_A": 100, "ACH_B": 200}
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]


def test_aviso_soma_os_jogos(store, make_game, pastas, win, flush_idle):
    um = _registrado(store, make_game, 1, steam_appid="570")
    dois = _registrado(store, make_game, 2, steam_appid="620")
    historico.registrar(um.game_id, [])
    historico.registrar(dois.game_id, [])
    _goldberg(pastas, "570", [("A", 1), ("B", 2)])
    _goldberg(pastas, "620", [("C", 3)])
    _rodar([um, dois], flush_idle)
    assert _avisos(win) == ["3 novas conquistas em 2 jogos"]


def test_mesmo_appid_em_dois_jogos(store, make_game, pastas, flush_idle):
    zerado = _registrado(store, make_game, 1, steam_appid="570", removed=True, status="beaten")
    vivo = _registrado(store, make_game, 2, steam_appid="570")
    _goldberg(pastas, "570", [("ACH_A", 100)])
    _rodar([zerado, vivo], flush_idle)
    assert historico.ler(zerado.game_id) == historico.ler(vivo.game_id) == {"ACH_A": 100}


def test_jogo_que_saiu_durante_a_leitura_nao_ganha_arquivo(store, make_game, pastas, flush_idle):
    _goldberg(pastas, "570", [("ACH_A", 100)])
    game = _registrado(store, make_game, 1, steam_appid="570")
    leitura = varredura.ler_jogo(game)
    store.excluir(game)
    instancia = VarreduraConquistas()
    assert instancia._gravar(leitura) == 0
    flush_idle()
    assert historico.ler(game.game_id) is None


def test_chave_recusada_avisa_uma_vez(store, make_game, pastas, win, flush_idle, monkeypatch):
    monkeypatch.setattr(
        catalogo, "obter", lambda _appid, _exe: catalogo.Renovacao(None, chave_recusada=True)
    )
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert _avisos(win).count(
        "A chave da Steam Web API foi recusada. Verifique-a nas Preferências."
    ) == 1


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"steam_appid": "570"}, True),
        ({"steam_appid": "570", "conquistas": False}, False),
        ({}, False),
        ({"steam_appid": "570", "removed": True}, False),  # removido, não zerado
        ({"steam_appid": "570", "removed": True, "status": "beaten"}, True),  # zerado
        ({"steam_appid": "570", "removed": True, "status": "beaten", "blacklisted": True}, False),
    ],
)
def test_quem_participa(make_game, campos, esperado):
    assert varredura.participa(make_game(**campos)) is esperado


def test_mensagem():
    assert varredura.mensagem([]) is None
    assert varredura.mensagem([("A", 0)]) is None
    assert varredura.mensagem([("Hollow Knight", 2)]) == "2 novas conquistas em Hollow Knight"
    assert varredura.mensagem([("A", 1), ("B", 0), ("C", 2)]) == "3 novas conquistas em 2 jogos"


def test_entregar_nao_levanta_no_laco_principal(store, make_game, pastas, flush_idle, monkeypatch):
    game = _registrado(store, make_game, 1, steam_appid="570")
    leitura = varredura.ler_jogo(game)

    def estoura(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(historico, "registrar", estoura)
    assert VarreduraConquistas()._entregar(leitura) is False


def test_concluir_nao_levanta_e_zera_a_lista(monkeypatch):
    instancia = VarreduraConquistas()
    instancia._novas = [("Jogo 1", 2)]

    def estoura(_texto):
        raise RuntimeError("sem janela")

    monkeypatch.setattr(varredura, "_aviso", estoura)
    assert instancia._concluir() is False
    assert instancia._novas == []


def test_varredura_de_um_jogo_fica_calada(store, make_game, pastas, win, flush_idle, monkeypatch):
    monkeypatch.setattr(
        catalogo, "obter", lambda _appid, _exe: catalogo.Renovacao(None, chave_recusada=True)
    )
    game = _registrado(store, make_game, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("ACH_A", 100)])
    _goldberg(pastas, "570", [("ACH_A", 100), ("ACH_B", 200)])
    instancia = VarreduraConquistas()
    instancia._worker([game], instancia._generation, avisar=False)
    flush_idle()
    assert historico.ler(game.game_id) == {"ACH_A": 100, "ACH_B": 200}
    assert _avisos(win) == []
    assert instancia._novas == []
    # A passada completa que vem depois, sem nada novo, também não avisa do que
    # a varredura de um jogo só já guardou.
    instancia._worker([game], instancia._generation)
    flush_idle()
    assert [aviso for aviso in _avisos(win) if "conquista" in aviso] == []


def _janela_com_jogo_aberto(win, game):
    chamadas = []
    win.active_game = game
    win.update_conquistas_block = chamadas.append
    return chamadas


def test_pagina_aberta_atualiza_quando_so_o_catalogo_chegou(
    store, make_game, pastas, win, flush_idle, monkeypatch
):
    monkeypatch.setattr(
        catalogo,
        "obter",
        lambda _appid, _exe: catalogo.Renovacao(catalogo.Catalogo((), 1, False)),
    )
    game = _registrado(store, make_game, 1, steam_appid="570")
    chamadas = _janela_com_jogo_aberto(win, game)
    _rodar([game], flush_idle)
    assert chamadas == [game]


def test_pagina_aberta_nao_atualiza_sem_novidade(store, make_game, pastas, win, flush_idle):
    game = _registrado(store, make_game, 1, steam_appid="570")
    chamadas = _janela_com_jogo_aberto(win, game)
    _rodar([game], flush_idle)
    assert chamadas == []


def test_pagina_de_outro_jogo_nao_atualiza(store, make_game, pastas, win, flush_idle, monkeypatch):
    monkeypatch.setattr(
        catalogo,
        "obter",
        lambda _appid, _exe: catalogo.Renovacao(catalogo.Catalogo((), 1, False)),
    )
    game = _registrado(store, make_game, 1, steam_appid="570")
    outro = _registrado(store, make_game, 2, steam_appid="620")
    chamadas = _janela_com_jogo_aberto(win, outro)
    _rodar([game], flush_idle)
    assert chamadas == []
