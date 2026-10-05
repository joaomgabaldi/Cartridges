"""O vigia da sessão da Epic: o vigia da conta com a loja da Epic."""

from cartridges.conquistas import historico
from cartridges.conquistas.epic import api, conta
from cartridges.conquistas.epic import vigia as vigia_epic
from cartridges.conquistas.formatos import Desbloqueio


def _sincrono(trabalho, entregar):
    entregar(trabalho())


def test_base_silenciosa_e_depois_pulso(make_game, monkeypatch):
    lidos = [[Desbloqueio("EPIC:1", 0)], [Desbloqueio("EPIC:1", 0), Desbloqueio("EPIC:2", 0)]]
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(api, "desbloqueadas", lambda ns: lidos.pop(0))
    game = make_game()
    historico.registrar(game.game_id, [], fonte="epic:ns1", conta="c1")
    avisos = []
    v = vigia_epic.Vigia(game, avisos.append, em_thread=_sincrono)
    v.iniciar()
    assert v.ativo and avisos == []
    v._olhar()
    assert [d.nome for d in avisos[0]] == ["EPIC:2"]
    v.parar()


def test_nao_inicia_em_jogo_do_xbox(make_game, monkeypatch):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    game = make_game()
    historico.registrar(game.game_id, [], fonte="xbox:7", conta="1")
    v = vigia_epic.Vigia(game, lambda _a: None, em_thread=_sincrono)
    v.iniciar()
    assert not v.ativo
