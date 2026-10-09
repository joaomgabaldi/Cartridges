# test_menu_do_card.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O menu de três pontinhos de cada card continua ligado ao jogo dele depois que
o jogo é atualizado.

O `DisplayManager.main` roda em toda atualização do jogo (fim de sessão, edição,
metadados). Até 09/10/2026 ele chamava `set_menu_model` toda vez, e o GTK cria um
popover novo a cada chamada; as conexões, feitas uma vez só, ficavam no popover
antigo. O menu novo não dizia qual era o jogo ativo, então "Editar" e "Remover"
agiam sobre o último jogo aberto, e "Restaurar save" não aparecia.
"""

from types import SimpleNamespace

import pytest

from cartridges import shared
from tests.test_zerados import jogo


@pytest.fixture
def display(real_window, monkeypatch):
    from cartridges.store.managers.display_manager import (  # noqa: PLC0415
        DisplayManager,
    )

    monkeypatch.setattr(
        real_window,
        "get_application",
        lambda: SimpleNamespace(state=shared.AppState.DEFAULT),
    )
    return DisplayManager()


def test_menu_continua_ligado_ao_jogo_depois_de_atualizado(real_window, store, display, monkeypatch):
    ativado = []
    monkeypatch.setattr(real_window, "set_active_game", lambda _w, _p, game: ativado.append(game))
    card = jogo(store, 1)
    display.main(card, {})
    display.main(card, {})  # uma atualização: fim de sessão, edição, metadados

    card.menu_button.get_popover().notify("visible")

    assert ativado == [card]


def test_atualizar_nao_troca_o_popover(real_window, store, display):
    card = jogo(store, 3)
    display.main(card, {})
    popover = card.menu_button.get_popover()
    display.main(card, {})
    assert card.menu_button.get_popover() is popover
