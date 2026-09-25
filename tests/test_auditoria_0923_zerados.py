# tests/test_auditoria_0923_zerados.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auditoria de 23/09: Jogos Zerados (B12–B16, Q1)."""

from types import SimpleNamespace

import pytest

from cartridges import shared
from tests.test_zerados import jogo  # helper que registra um Game de verdade


@pytest.fixture
def display(real_window, monkeypatch):
    from cartridges.store.managers.display_manager import DisplayManager  # noqa: PLC0415

    monkeypatch.setattr(
        real_window, "get_application",
        lambda: SimpleNamespace(state=shared.AppState.DEFAULT),
    )
    return DisplayManager()


def test_zerado_com_patch_pendente_nao_brilha(store, display):
    g = jogo(store, 1, removed=True, status="beaten", track_updates=True,
             update_available_ts=123)
    display.main(g, {})
    assert not g.cover_button.has_css_class("update-available")


def test_revealers_de_zerado_ficam_escondidos(store):
    g = jogo(store, 2)
    g.toggle_play(None, None, None, False)  # entrou o ponteiro
    g.removed, g.status = True, "beaten"
    g.toggle_play(None, None, None, None)  # saiu
    g.toggle_play(None, None, None, False)  # entrou de novo
    assert not g.play_revealer.get_reveal_child()
    assert not g.menu_revealer.get_reveal_child()


def test_remover_nao_age_num_zerado(store, real_window):
    from cartridges.main import CartridgesApplication  # noqa: PLC0415

    g = jogo(store, 3, removed=True, status="beaten")
    real_window.active_game = g
    CartridgesApplication.on_remove_game_action(None)
    assert g.removed is True
    assert not real_window.toasts


def test_atalho_renomeado_de_zerado_e_seguido(store, make_game, tmp_path):
    antigo = tmp_path / "antigo.lnk"
    novo = tmp_path / "novo.lnk"
    novo.write_text("x")
    zerado = make_game(game_id="shortcuts_a", removed=True, status="beaten",
                       shortcut_path=str(antigo), shortcut_mtime=100)
    store.add_game(zerado, {}, run_pipeline=False)
    chegando = make_game(game_id="shortcuts_a", shortcut_path=str(novo), shortcut_mtime=100)
    store.add_game(chegando, {}, run_pipeline=False)
    assert zerado.shortcut_path == str(novo)


def test_icone_de_jogar_e_refeito_para_removidos(store, real_window):
    g = jogo(store, 4, removed=True, status="beaten")
    chamadas = []
    g.set_play_icon = lambda: chamadas.append(g)
    real_window.update_play_icons()
    assert chamadas == [g]


def test_remover_jogo_zerado_instalado_avisa_ida_para_zerados(store, real_window):
    g = jogo(store, 5, status="beaten")
    real_window.active_game = g
    g.remove_game()
    assert g.zerado
    toast = real_window.toasts[(g, "remove")]
    assert toast.get_title() == "Jogo 5 movido para Jogos Zerados"


def test_remover_jogo_comum_continua_removido(store, real_window):
    g = jogo(store, 6)
    real_window.active_game = g
    g.remove_game()
    assert real_window.toasts[(g, "remove")].get_title() == "Jogo 6 removido"
