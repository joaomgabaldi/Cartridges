"""Catálogo + histórico: o que a página do jogo e a lista mostram."""

import pytest

from cartridges.conquistas import catalogo, historico, progresso
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.progresso import Linha, aparencia, dica, montar
from cartridges.conquistas.xbox import conta
from tests.apoio_conquistas import com_fonte


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


@pytest.mark.parametrize(
    ("feitas", "total", "esperado"),
    [(0, 4, 0), (2, 3, 66), (999, 1000, 99), (29, 100, 29), (7, 100, 7), (4, 4, 100), (1, 200, 0)],
)
def test_porcentagem_arredonda_para_baixo(feitas, total, esperado):
    catalogo_grande = Catalogo(tuple(_info(f"N{n}") for n in range(total)), 0, False)
    p = progresso.montar(catalogo_grande, {f"N{n}": 1 for n in range(feitas)})
    assert p.porcentagem == esperado


def test_nunca_varrido_mostra_tudo_bloqueado():
    p = progresso.montar(CAT, None)
    assert p.feitas == 0 and len(p.bloqueadas) == 4


def test_do_jogo(make_game):
    catalogo.guardar("570", CAT)
    historico.registrar("g1", [Desbloqueio("a", 10)])
    game = make_game(game_id="g1", steam_appid="570")
    com_fonte(game, "steam:570")
    assert progresso.do_jogo(game).feitas == 1

    game.conquistas = False
    assert progresso.do_jogo(game) is None

    sem_appid = make_game(game_id="g2")
    assert progresso.do_jogo(sem_appid) is None


def test_historico_antigo_sem_fonte_fica_oculto_ate_a_varredura(make_game):
    catalogo.guardar("570", CAT)
    game = make_game(steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("A", 1)])
    assert progresso.do_jogo(game) is None
    com_fonte(game, "steam:570")
    assert progresso.do_jogo(game) is not None


def test_xbox_some_ao_sair_da_conta(make_game, monkeypatch):
    catalogo.guardar("xbox-7", CAT)
    game = make_game()
    com_fonte(game, "xbox:7")
    monkeypatch.setattr(conta, "conectada", lambda: True)
    assert progresso.do_jogo(game) is not None
    monkeypatch.setattr(conta, "conectada", lambda: False)
    assert progresso.do_jogo(game) is None


def test_fonte_gravada_manda_mais_que_o_appid_atual(make_game):
    catalogo.guardar("570", CAT)
    game = make_game(steam_appid="999")
    com_fonte(game, "steam:570")
    assert progresso.do_jogo(game) is not None


def test_cartao_da_epic_some_sem_conta(make_game, monkeypatch):
    from cartridges.conquistas.epic import conta as conta_epic  # noqa: PLC0415

    game = make_game()
    catalogo.guardar("epic-ns1", Catalogo((ConquistaInfo("EPIC:1", "T", "", "", "", False),), 0, False))
    historico.registrar(game.game_id, [Desbloqueio("EPIC:1", 5)], fonte="epic:ns1", conta="c1")
    monkeypatch.setattr(conta_epic, "conectada", lambda: True)
    assert progresso.do_jogo(game).feitas == 1
    monkeypatch.setattr(conta_epic, "conectada", lambda: False)
    assert progresso.do_jogo(game) is None



def _conquista(nome="A", titulo="Primeira", descricao="Faça algo.", icone="a.png", cinza="", oculta=False, pct=55.0):
    return ConquistaInfo(nome, titulo, descricao, icone, cinza, oculta, pct)


def test_todas_na_ordem_do_catalogo():
    cat = Catalogo((_conquista("A"), _conquista("B"), _conquista("C")), 0, True)
    prog = montar(cat, {"C": 10, "A": 20})
    assert [l.info.nome for l in prog.todas] == ["A", "B", "C"]
    assert [l.desbloqueada for l in prog.todas] == [True, False, True]


def test_aparencia_desbloqueada_colorida():
    assert aparencia(Linha(_conquista(), 5), False) == ("a.png", False, False)


def test_aparencia_bloqueada_com_icone_cinza_proprio():
    assert aparencia(Linha(_conquista(cinza="a-cinza.png"), None), False) == ("a-cinza.png", False, False)


def test_aparencia_bloqueada_sem_icone_cinza_usa_filtro():
    assert aparencia(Linha(_conquista(), None), False) == ("a.png", True, False)


def test_aparencia_oculta_bloqueada_depende_da_opcao():
    linha = Linha(_conquista(oculta=True), None)
    assert aparencia(linha, False) == ("", False, True)
    assert aparencia(linha, True) == ("a.png", True, False)
    assert aparencia(Linha(_conquista(oculta=True), 5), False) == ("a.png", False, False)


def test_dica_com_nome_descricao_e_porcentagem():
    assert dica(Linha(_conquista(pct=3.8), None), False) == "<b>Primeira</b>\nFaça algo.\n3,8% dos jogadores"


def test_dica_sem_porcentagem_e_sem_descricao():
    assert dica(Linha(_conquista(descricao="", pct=None), None), False) == "<b>Primeira</b>"


def test_dica_escapa_o_texto():
    assert dica(Linha(_conquista(titulo="A & <B>", descricao="x<y", pct=None), 1), False) == (
        "<b>A &amp; &lt;B&gt;</b>\nx&lt;y"
    )


def test_dica_da_oculta():
    assert dica(Linha(_conquista(oculta=True), None), False) == (
        "<b>Conquista oculta</b>\nOs detalhes aparecem depois do desbloqueio."
    )
