"""Catálogo + histórico: o que a página do jogo e a lista mostram."""

from cartridges.conquistas import catalogo, historico, progresso
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio


def _info(nome):
    return ConquistaInfo(nome, nome.title(), "", "", "", False)


CAT = Catalogo((_info("A"), _info("B"), _info("C"), _info("D")), 0, False)


def test_sem_catalogo_nao_ha_progresso():
    assert progresso.montar(None, {"A": 1}) is None
    assert progresso.montar(Catalogo((), 0, False), {}) is None


def test_separa_e_ordena():
    p = progresso.montar(CAT, {"A": 100, "C": 300, "D": 0, "X": 5})
    # Mais recente primeiro; sem data por último. "X" não está no catálogo: não conta.
    assert [linha.info.nome for linha in p.desbloqueadas] == ["C", "A", "D"]
    assert [linha.info.nome for linha in p.bloqueadas] == ["B"]
    assert (p.total, p.feitas, p.fracao, p.completo) == (4, 3, 0.75, False)


def test_completo():
    p = progresso.montar(CAT, {"A": 1, "B": 2, "C": 3, "D": 4})
    assert p.completo and p.fracao == 1.0


def test_nunca_varrido_mostra_tudo_bloqueado():
    p = progresso.montar(CAT, None)
    assert p.feitas == 0 and len(p.bloqueadas) == 4


def test_do_jogo(make_game):
    catalogo._gravar_cache("570", CAT)
    historico.registrar("g1", [Desbloqueio("a", 10)])
    game = make_game(game_id="g1", steam_appid="570")
    assert progresso.do_jogo(game).feitas == 1

    game.conquistas = False
    assert progresso.do_jogo(game) is None

    sem_appid = make_game(game_id="g2")
    assert progresso.do_jogo(sem_appid) is None
