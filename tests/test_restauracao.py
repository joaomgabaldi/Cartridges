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


def _importer_com(store, game_ids_varridos):
    from cartridges.importer.importer import Importer  # noqa: PLC0415

    importer = Importer()
    importer.scanned_source_ids = {"shortcuts"}
    store.duplicate_game_ids = set(game_ids_varridos)
    return importer


def test_pendente_nao_vira_desinstalado(store, make_game):
    store.add_game(make_game(game_id="pendente"), {}, run_pipeline=False)
    store.add_game(make_game(game_id="sumiu"), {}, run_pipeline=False)
    restauracao.gravar(["pendente"], 1)

    _importer_com(store, []).remove_games()

    assert store.get("pendente").removed is False
    assert store.get("sumiu").removed is True


def test_resolver_pendencias_so_depois_de_varrer_os_atalhos(store, make_game):
    from cartridges.importer.importer import Importer  # noqa: PLC0415

    store.add_game(make_game(game_id="achado"), {}, run_pipeline=False)
    restauracao.gravar(["achado"], 1)

    importer = Importer()
    store.duplicate_game_ids = {"achado"}
    importer.resolver_pendencias()  # nada foi varrido
    assert restauracao.ids() == frozenset({"achado"})

    importer.scanned_source_ids = {"shortcuts"}
    importer.resolver_pendencias()
    assert restauracao.existe() is False


def test_biblioteca_esconde_pendente(real_window, store):
    from cartridges.game import Game  # noqa: PLC0415

    jogos = {}
    for game_id in ("pendente", "normal"):
        jogo = Game(
            {"source": "shortcuts", "game_id": game_id, "name": game_id,
             "executable": "x", "added": 0}
        )
        real_window.library.append(jogo)
        jogos[game_id] = jogo
    restauracao.gravar(["pendente"], 1)

    assert real_window.filter_func(jogos["pendente"].get_parent()) is False
    assert real_window.filter_func(jogos["normal"].get_parent()) is True


# --------------------------------------------------------------------------
# Escolher atalho
# --------------------------------------------------------------------------

import pytest  # noqa: E402

from cartridges.utils import session_log  # noqa: E402


@pytest.fixture
def pasta_de_atalhos(tmp_path, schema):
    pasta = tmp_path / "Atalhos"
    pasta.mkdir()
    schema["shortcuts-location"] = str(pasta)
    schema["shortcuts-recursive"] = False
    return pasta


@pytest.fixture
def retirados(win):
    lista = []
    win.retirar_da_grade = lista.append
    return lista


def test_candidatos_sem_os_do_backup_e_por_nome(store, make_game, pasta_de_atalhos):
    for nome in ("Hades.lnk", "Gran Turismo 7.lnk", "GT7.url", "Leia-me.txt"):
        (pasta_de_atalhos / nome).write_text("x", encoding="utf-8")
    restauracao.gravar(["gt"], 100)
    store.add_game(make_game(game_id="gt", name="Gran Turismo 7", added=10), {}, run_pipeline=False)
    # Do backup (added < restaurado_em): o atalho dele não é candidato.
    store.add_game(
        make_game(game_id="h", name="Hades", added=10,
                  shortcut_path=str(pasta_de_atalhos / "Hades.lnk")),
        {}, run_pipeline=False,
    )
    # Novo, criado pela importação depois da restauração: o atalho dele é.
    store.add_game(
        make_game(game_id="n", name="GT7", added=200,
                  shortcut_path=str(pasta_de_atalhos / "GT7.url")),
        {}, run_pipeline=False,
    )

    nomes = [p.name for p in restauracao.candidatos(store.get("gt"))]

    assert nomes == ["Gran Turismo 7.lnk", "GT7.url"]


def test_copiar_de_fora_da_pasta(pasta_de_atalhos, tmp_path):
    origem = tmp_path / "Desktop" / "Jogo X.lnk"
    origem.parent.mkdir()
    origem.write_text("atalho", encoding="utf-8")

    destino = restauracao.copiar_para_a_pasta(origem)

    assert destino == pasta_de_atalhos / "Jogo X.lnk"
    assert destino.read_text("utf-8") == "atalho"
    assert origem.is_file()


def test_copiar_com_nome_repetido_avisa_e_nao_copia(pasta_de_atalhos, tmp_path):
    (pasta_de_atalhos / "Jogo X.lnk").write_text("antigo", encoding="utf-8")
    origem = tmp_path / "Desktop" / "Jogo X.lnk"
    origem.parent.mkdir()
    origem.write_text("novo", encoding="utf-8")

    with pytest.raises(restauracao.AtalhoJaExiste):
        restauracao.copiar_para_a_pasta(origem)
    assert (pasta_de_atalhos / "Jogo X.lnk").read_text("utf-8") == "antigo"


def test_atalho_ja_na_pasta_nao_e_copiado(pasta_de_atalhos):
    dentro = pasta_de_atalhos / "Jogo.lnk"
    dentro.write_text("x", encoding="utf-8")
    assert restauracao.copiar_para_a_pasta(dentro) == dentro


def test_subpasta_so_conta_como_dentro_se_a_busca_for_recursiva(pasta_de_atalhos, schema):
    (pasta_de_atalhos / "sub").mkdir()
    fundo = pasta_de_atalhos / "sub" / "Jogo.lnk"
    fundo.write_text("x", encoding="utf-8")
    schema["shortcuts-recursive"] = True
    assert restauracao.copiar_para_a_pasta(fundo) == fundo
    schema["shortcuts-recursive"] = False
    assert restauracao.copiar_para_a_pasta(fundo) == pasta_de_atalhos / "Jogo.lnk"


def _cenario_conflito(store, make_game, pasta_de_atalhos):
    caminho = pasta_de_atalhos / "GT7.lnk"
    caminho.write_text("x", encoding="utf-8")
    restauracao.gravar(["gt"], 100)
    restaurado = make_game(game_id="gt", name="Gran Turismo 7", added=10,
                           playtime=36000, last_played=1_700_000_050,
                           shortcut_path="C:/Antigo/GT7.lnk")
    novo = make_game(game_id="shortcuts_novo", name="GT7", added=200,
                     playtime=6000, last_played=1_700_000_090, shortcut_path=str(caminho))
    store.add_game(restaurado, {}, run_pipeline=False)
    store.add_game(novo, {}, run_pipeline=False)
    session_log.record("gt", 36000, 1_700_000_050)
    session_log.record("shortcuts_novo", 6000, 1_700_000_090)
    return caminho, restaurado, novo


def test_jogo_do_atalho_e_resumo(store, make_game, pasta_de_atalhos):
    caminho, _restaurado, novo = _cenario_conflito(store, make_game, pasta_de_atalhos)
    assert restauracao.jogo_do_atalho(caminho) is novo
    assert restauracao.tem_historico(novo) is True
    assert restauracao.resumo(novo) == (6000, 1, 1_700_000_090)


def test_manter_backup(store, make_game, pasta_de_atalhos, retirados):
    caminho, restaurado, novo = _cenario_conflito(store, make_game, pasta_de_atalhos)
    restauracao.decidir(restaurado, caminho, novo, "backup")
    assert store.get("shortcuts_novo") is None
    assert retirados == [novo]
    assert restaurado.shortcut_path == str(caminho)
    assert restaurado.playtime == 36000
    # Continua pendente até a importação adotá-lo pelo atalho novo.
    assert restauracao.e_pendente("gt") is True


def test_mesclar_dados(store, make_game, pasta_de_atalhos, retirados):
    caminho, restaurado, novo = _cenario_conflito(store, make_game, pasta_de_atalhos)
    restauracao.decidir(restaurado, caminho, novo, "mesclar")
    assert store.get("shortcuts_novo") is None
    assert restaurado.playtime == 42000
    assert restaurado.last_played == 1_700_000_090
    assert len(session_log.load("gt")) == 2
    assert restaurado.shortcut_path == str(caminho)


def test_manter_este_pc(store, make_game, pasta_de_atalhos, retirados):
    caminho, restaurado, novo = _cenario_conflito(store, make_game, pasta_de_atalhos)
    restauracao.decidir(restaurado, caminho, novo, "este_pc")
    assert store.get("gt") is None
    assert store.get("shortcuts_novo") is novo
    assert session_log.load("gt") == []
    assert restauracao.existe() is False


def test_sem_jogo_novo_so_aponta(store, make_game, pasta_de_atalhos, retirados):
    caminho = pasta_de_atalhos / "GT7.lnk"
    restauracao.gravar(["gt"], 100)
    restaurado = make_game(game_id="gt", added=10)
    store.add_game(restaurado, {}, run_pipeline=False)
    restauracao.decidir(restaurado, caminho, None, "backup")
    assert restaurado.shortcut_path == str(caminho)
    assert retirados == []


def test_excluir_pendente_apaga_de_vez(store, make_game, retirados):
    restauracao.gravar(["gt", "outro"], 1)
    jogo = make_game(game_id="gt")
    store.add_game(jogo, {}, run_pipeline=False)
    session_log.record("gt", 60, 1_700_000_005)
    restauracao.excluir(jogo)
    assert store.get("gt") is None
    assert session_log.load("gt") == []
    assert restauracao.ids() == frozenset({"outro"})


def test_importacao_da_restauracao_varre_atalhos_mesmo_com_a_fonte_desligada(schema, monkeypatch):
    from cartridges import main as main_module  # noqa: PLC0415

    fontes = []

    class ImporterFalso:
        ao_terminar = None

        def add_source(self, fonte):
            fontes.append(type(fonte).__name__)

        def run(self):
            pass

    monkeypatch.setattr(main_module, "Importer", ImporterFalso)
    schema["shortcuts"] = False
    app = main_module.CartridgesApplication.__new__(main_module.CartridgesApplication)

    main_module.CartridgesApplication.on_import_action(app)
    assert fontes == []

    main_module.CartridgesApplication.on_import_action(app, varrer_atalhos=True)
    assert fontes == ["ShortcutsSource"]


def test_tempo_sem_sessao_tambem_e_historico(make_game):
    """O tempo jogado é gravado a cada minuto; a sessão só entra no histórico
    quando termina bem. Um jogo que caiu no meio tem horas e nenhuma sessão."""
    assert restauracao.tem_historico(make_game(game_id="caiu", playtime=600)) is True
    assert restauracao.tem_historico(make_game(game_id="virgem", playtime=0)) is False
