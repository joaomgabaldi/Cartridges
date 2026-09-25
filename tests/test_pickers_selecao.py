# test_pickers_selecao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Escolher um logo ou uma capa encerra a busca que ainda baixa prévias."""

import pytest
from gi.repository import GdkPixbuf


@pytest.fixture
def previa(tmp_path):
    caminho = tmp_path / "previa.png"
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, 4, 4)
    pixbuf.fill(0xFFFFFFFF)
    pixbuf.savev(str(caminho), "png", [], [])
    return caminho


def logo_picker():
    from cartridges.logo_picker import LogoPicker  # noqa: PLC0415

    return LogoPicker("Jogo", lambda _p: None, lambda: None)


def sgdb_picker():
    from cartridges.sgdb_picker import SgdbPicker  # noqa: PLC0415

    return SgdbPicker("Jogo", lambda _p: None)


def adicionar(picker, previa, geracao):
    if hasattr(picker, "animated_button"):
        return picker._add_result(previa, "https://x/y.png", False, geracao)
    return picker._add_result(previa, "https://x/y.png", geracao)


@pytest.mark.parametrize("criar", [logo_picker, sgdb_picker])
def test_previa_atrasada_nao_tira_o_carregamento_da_escolha(criar, previa, monkeypatch):
    picker = criar()
    # O download do escolhido não sai: o teste é sobre o que acontece enquanto ele corre.
    monkeypatch.setattr(picker, "_select_thread", lambda _url: None)
    geracao_da_busca = picker._generation
    adicionar(picker, previa, geracao_da_busca)
    filho = picker.flowbox.get_child_at_index(0)

    picker._on_child_activated(picker.flowbox, filho)
    adicionar(picker, previa, geracao_da_busca)

    assert picker.stack.get_visible_child_name() == "loading"
    assert picker.flowbox.get_child_at_index(1) is None
