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
