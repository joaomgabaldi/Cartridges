# test_zerados.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A página Jogos Zerados: os desinstalados marcados como Zerado."""

from types import SimpleNamespace

import pytest
from gi.repository import Gio, GLib, Gtk

from cartridges import shared


def jogo(store, numero, **campos):
    """Um ``Game`` de verdade, já registrado na store (sem pipeline)."""
    from cartridges.game import Game  # noqa: PLC0415

    game = Game(
        {
            "source": "shortcuts",
            "game_id": f"shortcuts_z{numero}",
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


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"removed": True, "status": "beaten"}, True),
        ({"removed": False, "status": "beaten"}, False),
        ({"removed": True, "status": "playing"}, False),
        ({"removed": True, "status": ""}, False),
        ({"removed": True, "status": "beaten", "blacklisted": True}, False),
    ],
)
def test_zerado_e_desinstalado_com_a_marca(campos, esperado):
    assert jogo(None, 1, **campos).zerado is esperado


def test_ficha_antiga_com_hidden_carrega_normal(store, write_record):
    from cartridges import main as main_module  # noqa: PLC0415
    from cartridges.game import PERSISTED_ATTRS  # noqa: PLC0415

    write_record("shortcuts_h", executable="x", hidden=True)
    main_module.CartridgesApplication.load_games_from_disk(None)

    assert store.get("shortcuts_h") is not None
    assert "hidden" not in PERSISTED_ATTRS


@pytest.fixture
def display(real_window, monkeypatch):
    """O DisplayManager de verdade sobre a janela de verdade.

    ``main`` lê o estado do app, e a janela dos testes não tem app.
    """
    from cartridges.store.managers.display_manager import (  # noqa: PLC0415
        DisplayManager,
    )

    monkeypatch.setattr(
        real_window,
        "get_application",
        lambda: SimpleNamespace(state=shared.AppState.DEFAULT),
    )
    return DisplayManager()


def grade_de(game):
    child = game.get_parent()
    return child.get_parent() if child else None


def test_zerado_vai_para_a_grade_de_zerados(real_window, store, display):
    zerado = jogo(store, 1, removed=True, status="beaten")
    display.main(zerado, {})
    assert grade_de(zerado) is real_window.zerados_library


def test_desinstalado_sem_marca_nao_aparece(real_window, store, display):
    comum = jogo(store, 2, removed=True)
    display.main(comum, {})
    assert grade_de(comum) is None


def test_jogo_instalado_zerado_fica_na_biblioteca(real_window, store, display):
    vivo = jogo(store, 3, status="beaten")
    display.main(vivo, {})
    assert grade_de(vivo) is real_window.library


def test_desinstalar_um_zerado_move_para_a_pagina(real_window, store, display):
    game = jogo(store, 4, status="beaten")
    display.main(game, {})
    game.removed = True
    display.main(game, {})
    assert grade_de(game) is real_window.zerados_library


def test_a_busca_da_biblioteca_nao_filtra_os_zerados(real_window, store):
    """A página de zerados não tem busca: a caixa da biblioteca não vale lá."""
    real_window.search_entry.set_text("zelda")
    zerado = jogo(store, 5, removed=True, status="beaten", name="Halo")
    real_window.zerados_library.append(zerado)
    assert real_window.filter_func(zerado.get_parent()) is True

    # Sem pai ainda (o GTK chama o filtro no meio do append): decide pela regra.
    outro = jogo(store, 6, removed=True, status="beaten", name="Halo")
    solto = Gtk.FlowBoxChild()
    solto.set_child(outro)
    assert real_window.filter_func(solto) is True
    real_window.search_entry.set_text("")


def test_pagina_vazia_mostra_o_aviso(real_window, store):
    real_window.set_library_child()
    assert real_window.zerados_notice_empty.get_parent() is not None

    jogo(store, 7, removed=True, status="beaten")
    real_window.set_library_child()
    assert real_window.zerados_notice_empty.get_parent() is None


def test_item_do_menu_so_com_desinstalados_e_na_tela_principal(
    real_window, store, monkeypatch
):
    acao = Gio.SimpleAction.new("show_zerados", None)
    real_window.add_action(acao)

    real_window.set_show_zerados()
    assert acao.get_enabled() is False, "nada a mostrar nem a oferecer"

    jogo(store, 8, removed=True)
    real_window.set_show_zerados()
    assert acao.get_enabled() is True

    monkeypatch.setattr(
        real_window.navigation_view,
        "get_visible_page",
        lambda: real_window.zerados_library_page,
    )
    real_window.set_show_zerados()
    assert acao.get_enabled() is False, "só na tela principal"


# -- Store ---------------------------------------------------------------------


@pytest.fixture
def espiao(store):
    """Um manager que só escuta os dois sinais, como File/DisplayManager."""
    from cartridges.store.managers.manager import Manager  # noqa: PLC0415

    class Espiao(Manager):
        signals = {"update-ready", "save-ready"}

        def main(self, game, additional_data):
            pass

    store.add_manager(Espiao())


def test_tumbas_carregadas_ficam_conectadas(store, espiao, make_game):
    zerado = make_game(game_id="shortcuts_z", removed=True, status="beaten")
    comum = make_game(game_id="shortcuts_c", removed=True)
    store.add_game(zerado, {"skip_save": True})
    store.add_game(comum, {"skip_save": True})

    assert {sinal for sinal, _ in zerado.signals} == {"update-ready", "save-ready"}
    assert {sinal for sinal, _ in comum.signals} == {"update-ready", "save-ready"}
    assert zerado.updates == 1, "o zerado vai para a tela na carga"
    assert comum.updates == 0, "o desinstalado comum continua fora de tela"


def test_reinstalar_um_zerado_mantem_a_ficha(store, make_game):
    tumba = make_game(
        game_id="shortcuts_z",
        removed=True,
        status="beaten",
        playtime=3600,
        executable="velho",
        shortcut_path="C:\velho.lnk",
        shortcut_mtime=100,
    )
    store.add_game(tumba, {"skip_save": True})

    novo = make_game(
        game_id="shortcuts_z",
        executable="novo",
        shortcut_path="C:\novo.lnk",
        shortcut_mtime=200,
    )
    assert store.add_game(novo, {}) is None

    assert store.get("shortcuts_z") is tumba
    assert tumba.removed is True
    assert tumba.status == "beaten"
    assert tumba.playtime == 3600
    assert tumba.executable == "novo"
    assert tumba.shortcut_path == "C:\novo.lnk"
    assert tumba.shortcut_mtime == 200
    assert tumba.saves == 1
    assert "shortcuts_z" in store.duplicate_game_ids


def test_o_mesmo_atalho_de_sempre_nao_mexe_no_zerado(store, make_game):
    tumba = make_game(game_id="shortcuts_z", removed=True, status="beaten", shortcut_mtime=100)
    store.add_game(tumba, {"skip_save": True})

    store.add_game(make_game(game_id="shortcuts_z", shortcut_mtime=100), {})

    assert store.get("shortcuts_z") is tumba
    assert tumba.saves == 0


def test_reinstalar_um_desinstalado_comum_segue_como_antes(
    store, make_game, app_dirs, flush_idle
):
    tumba = make_game(game_id="shortcuts_c", removed=True, shortcut_mtime=100)
    store.add_game(tumba, {"skip_save": True})
    (app_dirs.games / "shortcuts_c.json").write_text("{}", encoding="utf-8")

    novo = make_game(game_id="shortcuts_c", shortcut_mtime=200)
    store.add_game(novo, {}, run_pipeline=False)

    assert store.get("shortcuts_c") is novo
    assert not (app_dirs.games / "shortcuts_c.json").exists()


def test_tumba_sem_executavel_carrega_e_jogo_vivo_nao(store, write_record):
    from cartridges import main as main_module  # noqa: PLC0415

    write_record(
        "imported_1", source="imported", executable="", removed=True, status="beaten"
    )
    write_record("imported_2", source="imported", executable="")
    main_module.CartridgesApplication.load_games_from_disk(None)

    assert store.get("imported_1") is not None
    assert store.get("imported_2") is None
