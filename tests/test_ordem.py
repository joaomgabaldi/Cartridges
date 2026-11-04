# test_ordem.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regras puras de ordenação, filtro e opções da biblioteca (sem Qt)."""

from cartridges.jogo import Jogo
from cartridges.modelos import ordem
from cartridges.modelos.ordem import Linha


def _linha(jogo_id, nome="X", **campos):
    base = {
        "jogo_id": jogo_id, "nome": nome, "capa": "", "zerado": False, "removido": False,
        "status": "", "genero": "", "desenvolvedora": "", "publicadora": "", "anotacoes": "",
        "lancamento": "", "adicionado": 0, "jogado_em": 0, "tempo_de_jogo": 0, "tamanho": 0,
        "estrelas": 0, "carregando": False,
    }  # fmt: skip
    return Linha(**{**base, **campos})


def _ordenar(linhas, modo):
    return [linha.jogo_id for linha in sorted(linhas, key=lambda x: ordem.chave(x, modo))]


def _jogo(game_id, nome, **extra):
    return Jogo({"game_id": game_id, "source": "imported", "name": nome, **extra})


def test_linha_le_o_jogo():
    jogo = _jogo("a", "Alfa", genre="RPG", developer="D", publisher="P", notes="n", rating=3, playtime=7)
    jogo.loading = 2
    linha = Linha.de(jogo)
    assert (linha.jogo_id, linha.nome, linha.genero, linha.desenvolvedora) == ("a", "Alfa", "RPG", "D")
    assert (linha.publicadora, linha.anotacoes, linha.estrelas, linha.tempo_de_jogo) == ("P", "n", 3, 7)
    assert linha.carregando is True
    assert linha.capa == ""


def test_jogados_recentemente_primeiro():
    linhas = [_linha("a", jogado_em=1), _linha("b", jogado_em=30), _linha("c", jogado_em=2)]
    assert _ordenar(linhas, "last_played") == ["b", "c", "a"]


def test_az_e_za_com_desempate_por_id():
    linhas = [_linha("2", "Halo"), _linha("1", "Halo"), _linha("3", "alien")]
    assert _ordenar(linhas, "a-z") == ["3", "1", "2"]
    assert _ordenar(linhas, "z-a") == ["2", "1", "3"]


def test_az_ignora_a_caixa():
    assert _ordenar([_linha("1", "halo"), _linha("2", "Alien")], "a-z") == ["2", "1"]


def test_ordem_e_total_e_estavel():
    linhas = [_linha("1", "Halo"), _linha("2", "Halo"), _linha("3", "halo")]
    for modo in ordem.MODOS:
        assert _ordenar(linhas, modo) == _ordenar(list(reversed(linhas)), modo)


def test_identical_records_compare_equal():
    """O mesmo jogo não vem antes nem depois de si mesmo, em nenhum modo (o z-a também)."""
    linha = _linha("1", "Halo", lancamento="2012", estrelas=3)
    for modo in ordem.MODOS:
        assert ordem.chave(linha, modo) == ordem.chave(linha, modo)


def test_the_order_is_antisymmetric_and_transitive():
    """As três propriedades de uma ordem, em todos os modos: sem elas a grade troca jogos de lugar."""
    linhas = [
        _linha("1", "Alien", lancamento="2010", estrelas=4),
        _linha("2", "Halo", lancamento="2012"),
        _linha("3", "Halo", estrelas=4),
        _linha("4", "halo", lancamento="2012", tamanho=5),
        _linha("5", "Zelda", estrelas=2, tamanho=5),
    ]

    for modo in ordem.MODOS:
        def comparar(a, b):
            ka, kb = ordem.chave(a, modo), ordem.chave(b, modo)
            return -1 if ka < kb else (1 if kb < ka else 0)

        for a in linhas:
            assert comparar(a, a) == 0
            for b in linhas:
                assert comparar(a, b) == -comparar(b, a)
                for c in linhas:
                    if comparar(a, b) <= 0 and comparar(b, c) <= 0:
                        assert comparar(a, c) <= 0


def test_ties_on_rating_fall_back_to_the_title():
    """Sem desempate a grade trocaria os dois de lugar a cada reordenação."""
    linhas = [_linha("1", "Beta", estrelas=4), _linha("2", "Alfa", estrelas=4)]
    assert _ordenar(linhas, "rating") == _ordenar(list(reversed(linhas)), "rating") == ["2", "1"]


def test_sem_data_vai_para_o_fim_nos_dois_sentidos():
    linhas = [_linha("n", "A"), _linha("v", lancamento="2020"), _linha("o", lancamento="2010")]
    assert _ordenar(linhas, "released_newest") == ["v", "o", "n"]
    assert _ordenar(linhas, "released_oldest") == ["o", "v", "n"]


def test_data_parcial_ordena():
    linhas = [_linha("c", lancamento="2/set./2012"), _linha("p", lancamento="2012")]
    assert _ordenar(linhas, "released_oldest") == ["p", "c"]
    assert _ordenar(linhas, "released_newest") == ["c", "p"]


def test_mesma_data_desempata_pelo_nome():
    linhas = [_linha("1", "B", lancamento="2012"), _linha("2", "A", lancamento="2012")]
    assert _ordenar(linhas, "released_newest") == ["2", "1"]


def test_sem_nota_vai_para_o_fim():
    linhas = [
        Linha.de(_jogo("a", "A", rating=9)),
        Linha.de(_jogo("b", "B", rating="ótimo")),
        Linha.de(_jogo("c", "C", rating=2)),
    ]
    assert [x.estrelas for x in linhas] == [5, 0, 2]
    assert _ordenar(linhas, "rating") == ["a", "c", "b"]


def test_newest_e_oldest():
    linhas = [_linha("a", adicionado=5), _linha("b", adicionado=100), _linha("c", adicionado=7)]
    assert _ordenar(linhas, "newest") == ["b", "c", "a"]
    assert _ordenar(linhas, "oldest") == ["a", "c", "b"]


def test_tempo_de_jogo_numerico_e_nao_textual():
    linhas = [_linha("a", tempo_de_jogo=9), _linha("b", tempo_de_jogo=100)]
    assert _ordenar(linhas, "playtime") == ["b", "a"]


def test_tamanho_zero_no_fim():
    linhas = [_linha("z", tamanho=0), _linha("g", tamanho=5), _linha("m", tamanho=2)]
    assert _ordenar(linhas, "install_size") == ["g", "m", "z"]


def test_modo_desconhecido_vale_last_played():
    linhas = [_linha("a", jogado_em=1), _linha("b", jogado_em=9)]
    assert _ordenar(linhas, "inventado") == _ordenar(linhas, "last_played") == ["b", "a"]


def test_busca_acha_anotacao_e_publicadora():
    linha = _linha("a", "Hollow", publicadora="Team Cherry", anotacoes="senha do cofre: 8815")
    assert ordem.passa(linha, "cherry", "", "", "")
    assert ordem.passa(linha, "8815", "", "", "")
    assert ordem.passa(linha, "hollow", "", "", "")
    assert not ordem.passa(linha, "zelda", "", "", "")


def test_busca_acha_desenvolvedora():
    assert ordem.passa(_linha("a", desenvolvedora="Nintendo"), "ninten", "", "", "")


def test_busca_ignora_caixa():
    assert ordem.passa(_linha("a", "Zelda"), "ZELDA", "", "", "")


def test_genero_ausente_so_em_todos():
    sem = _linha("a")
    assert ordem.passa(sem, "", "", "", "")
    assert not ordem.passa(sem, "", "RPG", "", "")
    assert not ordem.passa(sem, "", "", "2020", "")
    assert not ordem.passa(sem, "", "", "", "beaten")


def test_filtros_somam():
    linha = _linha("a", "Zelda", genero="RPG", lancamento="2020", status="beaten")
    assert ordem.passa(linha, "zel", "RPG", "2020", "beaten")
    assert not ordem.passa(linha, "zel", "RPG", "2019", "beaten")
    assert not ordem.passa(linha, "zel", "RPG", "2020", "playing")
    assert not ordem.passa(linha, "mario", "RPG", "2020", "beaten")


def test_opcoes_ordenam_acentos():
    generos, _ = ordem.opcoes([_linha("a", genero="Aventura"), _linha("b", genero="Ação"), _linha("c")])
    assert generos == ["Ação", "Aventura"]


def test_generos_que_so_diferem_no_acento_tem_ordem_fixa(monkeypatch):
    # O `set` do módulo vira uma lista em ordem de chegada: sem desempate, a ordem de entrada
    # decidiria (na prática, o hash das strings).
    class EmOrdem(list):
        add = list.append

    monkeypatch.setattr(ordem, "set", EmOrdem, raising=False)
    sem, com = _linha("a", genero="Acao"), _linha("b", genero="Ação")
    assert ordem.opcoes([sem, com])[0] == ["Acao", "Ação"]
    assert ordem.opcoes([com, sem])[0] == ["Acao", "Ação"]


def test_anos_decrescentes():
    linhas = [_linha("a", lancamento="2010"), _linha("b", lancamento="17/set./2020"), _linha("c", lancamento="Em breve")]
    assert ordem.opcoes(linhas)[1] == ["2020", "2010"]



def test_copia_mais_velha_que_a_capa_nao_e_usada():
    import os  # noqa: PLC0415

    from cartridges import shared  # noqa: PLC0415
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    shared.covers_dir.mkdir(parents=True, exist_ok=True)
    shared.capas_animadas_dir.mkdir(parents=True, exist_ok=True)
    capa = shared.covers_dir / "a.webp"
    capa.write_bytes(b"x")
    os.utime(capa, ns=(2_000_000_000, 2_000_000_000))
    for indice in (0, 1):
        copia = copias_animadas.caminho_para(capa, copias_animadas.tamanhos()[indice])
        copia.write_bytes(b"x")
        os.utime(copia, ns=(1_000_000_000, 1_000_000_000))
        assert ordem.url_da_copia(capa, indice) == "", "mais velha: a tela a larga e o preparar a refaz"
        os.utime(copia, ns=(2_000_000_000, 2_000_000_000))
        assert ordem.url_da_copia(capa, indice).startswith("file:///"), "igual passa"
    assert ordem.url_da_copia(None) == ""


def test_a_z_poe_os_acentos_junto_da_letra():
    linhas = [_linha(str(i), nome) for i, nome in enumerate(["Zelda", "Éden", "Árvore", "Banana", "Fable"])]
    nomes = {linha.jogo_id: linha.nome for linha in linhas}
    assert [nomes[i] for i in _ordenar(linhas, "a-z")] == ["Árvore", "Banana", "Éden", "Fable", "Zelda"]
    assert [nomes[i] for i in _ordenar(linhas, "z-a")] == ["Zelda", "Fable", "Éden", "Banana", "Árvore"]


def test_a_z_acento_junto_da_mesma_inicial():
    linhas = [_linha(str(i), nome) for i, nome in enumerate(["Epic", "Éden", "Ábaco", "Azul"])]
    nomes = {linha.jogo_id: linha.nome for linha in linhas}
    assert [nomes[i] for i in _ordenar(linhas, "a-z")] == ["Ábaco", "Azul", "Éden", "Epic"]


def test_chave_nao_refaz_a_data_a_cada_comparacao(monkeypatch):
    ordem.chave.cache_clear()
    chamadas = []
    original = ordem.parse_release_date
    monkeypatch.setattr(ordem, "parse_release_date", lambda texto: chamadas.append(texto) or original(texto))
    linhas = [_linha(str(i), f"J{i}", lancamento=f"20{i:02d}") for i in range(10)]
    try:
        _ordenar(linhas, "released_newest")
        _ordenar(linhas, "released_newest")
        assert len(chamadas) == len(linhas)
    finally:
        ordem.chave.cache_clear()


def test_linha_le_a_capa_uma_vez(monkeypatch):
    jogo = _jogo("a", "Alfa")
    chamadas = []
    monkeypatch.setattr(jogo, "get_cover_path", lambda: chamadas.append(1))
    Linha.de(jogo)
    assert len(chamadas) == 1
