# test_restauracao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As pendências da restauração: os jogos restaurados cujo atalho ainda não
foi encontrado. Sem o arquivo, nada disto roda."""

import json

from cartridges import shared
from cartridges.utils import restauracao


def test_sem_arquivo_nao_ha_fluxo():
    assert restauracao.existe() is False
    assert restauracao.ids() == frozenset()
    assert restauracao.e_pendente("qualquer") is False


def test_gravar_e_ler():
    restauracao.gravar(["b", "a", "a"], 1_700_000_500)
    assert restauracao.existe() is True
    assert restauracao.ids() == frozenset({"a", "b"})
    assert restauracao.restaurado_em() == 1_700_000_500
    assert restauracao.e_pendente("a") is True
    dados = json.loads((shared.app_dir / "restauracao_pendente.json").read_text("utf-8"))
    assert dados == {"restaurado_em": 1_700_000_500, "jogos": ["a", "b"]}


def test_lista_vazia_apaga_o_arquivo():
    restauracao.gravar(["a"], 1)
    restauracao.gravar([], 1)
    assert restauracao.existe() is False
    assert restauracao.e_pendente("a") is False


def test_remover_o_ultimo_encerra_o_fluxo():
    restauracao.gravar(["a", "b"], 7)
    restauracao.remover("a")
    assert restauracao.ids() == frozenset({"b"})
    assert restauracao.restaurado_em() == 7
    restauracao.remover("b")
    assert restauracao.existe() is False


def test_arquivo_ilegivel_nao_derruba_nada():
    (shared.app_dir / "restauracao_pendente.json").write_text("{", encoding="utf-8")
    assert restauracao.existe() is True
    assert restauracao.ids() == frozenset()


def test_resolver_tira_o_encontrado_o_adotado_e_o_excluido(store, make_game):
    store.add_game(make_game(game_id="achado"), {}, run_pipeline=False)
    store.add_game(make_game(game_id="sem_atalho"), {}, run_pipeline=False)
    store.add_game(make_game(game_id="desinstalado", removed=True), {}, run_pipeline=False)
    # "adotado": a âncora o renomeou, o id antigo não está mais na store.
    restauracao.gravar(["achado", "sem_atalho", "desinstalado", "adotado"], 5)

    restauracao.resolver({"achado"})

    assert restauracao.ids() == frozenset({"sem_atalho"})


def test_pendentes_em_ordem_de_nome(store, make_game):
    store.add_game(make_game(game_id="z", name="Zelda"), {}, run_pipeline=False)
    store.add_game(make_game(game_id="a", name="alan wake"), {}, run_pipeline=False)
    restauracao.gravar(["z", "a", "sumiu"], 1)
    assert [j.game_id for j in restauracao.pendentes()] == ["a", "z"]


def test_ids_que_dependem_de_atalho(tmp_path):
    pasta = tmp_path / "extraido" / "games"
    pasta.mkdir(parents=True)

    def jogo(game_id, **campos):
        dados = {"game_id": game_id, "source": "shortcuts", "name": game_id, **campos}
        (pasta / f"{game_id}.json").write_text(json.dumps(dados), encoding="utf-8")

    jogo("vivo")
    jogo("manual", source="imported")
    jogo("zerado", removed=True, status="beaten")
    jogo("oculto", blacklisted=True)
    (pasta / "quebrado.json").write_text("{", encoding="utf-8")

    assert restauracao.ids_que_dependem_de_atalho(pasta) == ["vivo"]
