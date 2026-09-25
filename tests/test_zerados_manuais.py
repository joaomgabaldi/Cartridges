# test_zerados_manuais.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Jogos Zerados adicionados à mão: jogos que nunca passaram pelo app."""

from cartridges import shared


def jogo(store, numero, **campos):
    """Um ``Game`` de verdade, já registrado na store (sem pipeline)."""
    from cartridges.game import Game  # noqa: PLC0415

    game = Game(
        {
            "source": "shortcuts",
            "game_id": f"shortcuts_m{numero}",
            "name": f"Jogo {numero}",
            "executable": "x",
            "added": 0,
            **campos,
        }
    )
    if store is not None:
        store.source_games.setdefault("shortcuts", {})[game.game_id] = game
        store.games_by_id[game.game_id] = game
    return game


# -- Managers ------------------------------------------------------------------


def test_steam_so_processa_removido_com_a_marca(store, monkeypatch):
    from cartridges.store.managers import steam_api_manager  # noqa: PLC0415

    gerente = steam_api_manager.SteamAPIManager()
    monkeypatch.setattr(gerente, "resolve_tags", lambda *_a: ([], False))
    monkeypatch.setattr(
        gerente.steam_api_helper,
        "get_api_data",
        lambda **_k: {"developer": "Supergiant Games"},
    )
    zerado = jogo(store, 1, removed=True, status="beaten", steam_appid="1145360")

    gerente.main(zerado, {})
    assert zerado.developer is None

    gerente.main(zerado, {"zerado_manual": True, "sem_ligacao": True})
    assert zerado.developer == "Supergiant Games"


def test_hltb_so_processa_removido_com_a_marca(store, monkeypatch):
    from cartridges.store.managers import hltb_manager  # noqa: PLC0415

    gerente = hltb_manager.HLTBManager()
    monkeypatch.setattr(gerente, "_fetch", lambda _g: {"hltb_id": 42})
    zerado = jogo(store, 2, removed=True, status="beaten")

    gerente.main(zerado, {})
    assert zerado.hltb_id is None

    gerente.main(zerado, {"zerado_manual": True})
    assert zerado.hltb_id == 42


def test_blacklisted_continua_pulado_mesmo_com_a_marca(store, monkeypatch):
    from cartridges.store.managers import hltb_manager  # noqa: PLC0415

    gerente = hltb_manager.HLTBManager()
    monkeypatch.setattr(gerente, "_fetch", lambda _g: {"hltb_id": 42})
    excluido = jogo(store, 3, removed=True, blacklisted=True)

    gerente.main(excluido, {"zerado_manual": True})
    assert excluido.hltb_id is None


# -- Situação ------------------------------------------------------------------


def test_zerado_com_o_mesmo_appid_ou_nome_bloqueia(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    dota = jogo(store, 10, name="Dota 2", removed=True, status="beaten", steam_appid="570")

    assert zerado_manual.situacao("Outro nome", "570") == ("zerado", dota)
    assert zerado_manual.situacao("DOTA 2") == ("zerado", dota)


def test_nome_compara_sem_pontuacao_e_sem_maiusculas(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    wukong = jogo(store, 11, name="Black Myth: Wukong", removed=True, status="beaten")

    assert zerado_manual.situacao("black myth - wukong") == ("zerado", wukong)


def test_jogo_da_biblioteca_bloqueia(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    celeste = jogo(store, 12, name="Celeste")

    assert zerado_manual.situacao("celeste") == ("biblioteca", celeste)


def test_blacklisted_nao_conta(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    jogo(store, 13, name="Celeste", blacklisted=True)

    assert zerado_manual.situacao("Celeste") == ("novo", None)


def test_desinstalado_mais_recente_e_o_escolhido(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    jogo(store, 14, name="Icarus", removed=True, last_played=10)
    recente = jogo(store, 15, name="Icarus", removed=True, last_played=20)

    assert zerado_manual.situacao("ICARUS") == ("desinstalado", recente)


# -- Adicionar -----------------------------------------------------------------


class ManagerFalso:
    signals = ()

    def __init__(self, nome, chamados):
        self.nome = nome
        self.chamados = chamados

    def process_game(self, game, dados, callback):
        self.chamados.append((self.nome, dados.get("zerado_manual")))
        callback(self)


def managers_falsos(store):
    from cartridges.store.managers.hltb_manager import HLTBManager  # noqa: PLC0415
    from cartridges.store.managers.sgdb_manager import SgdbManager  # noqa: PLC0415
    from cartridges.store.managers.steam_api_manager import (  # noqa: PLC0415
        SteamAPIManager,
    )

    chamados = []
    store.managers = {
        SteamAPIManager: ManagerFalso("steam", chamados),
        HLTBManager: ManagerFalso("hltb", chamados),
        SgdbManager: ManagerFalso("sgdb", chamados),
    }
    return chamados


def test_adicionar_pela_steam_cria_zerado_e_busca_os_dados(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    chamados = managers_falsos(store)

    novo = zerado_manual.adicionar("Hades", "1145360")

    assert store.get("imported_1") is novo
    assert novo.zerado is True
    assert novo.executable == ""
    assert novo.playtime == 0
    assert novo.steam_appid == "1145360"
    assert novo.name == "Hades"
    assert chamados == [("steam", True), ("hltb", True), ("sgdb", True)]
    assert novo.loading == 0


def test_adicionar_so_pelo_nome_nao_busca_nada(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    chamados = managers_falsos(store)

    novo = zerado_manual.adicionar("Chrono Trigger")

    assert novo.zerado is True
    assert not novo.steam_appid
    assert chamados == []


def test_adicionar_repetido_nao_cria(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    jogo(store, 16, name="Hades", removed=True, status="beaten")

    assert zerado_manual.adicionar("hades") is None
    assert store.get("imported_1") is None


def test_adicionar_desinstalado_marca_em_vez_de_criar(store):
    from cartridges.utils import zerado_manual  # noqa: PLC0415

    antigo = jogo(store, 17, name="Hades", removed=True, playtime=3600)

    assert zerado_manual.adicionar("Hades") is antigo
    assert antigo.zerado is True
    assert antigo.playtime == 3600
    assert store.get("imported_1") is None
