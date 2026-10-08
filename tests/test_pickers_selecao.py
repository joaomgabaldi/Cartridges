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


# region Prévias do seletor de capas


def _apng_bytes(quadros=2):
    import io  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    imagens = [Image.new("RGB", (60, 90), cor) for cor in ("red", "blue")[:quadros]]
    saida = io.BytesIO()
    imagens[0].save(
        saida, "PNG", save_all=True, append_images=imagens[1:], duration=100
    )
    return saida.getvalue()


@pytest.fixture
def busca_sgdb(monkeypatch):
    """O seletor de capas com a rede trocada: uma grade ``.png`` cujo download
    é um APNG, e as entregas à thread principal anotadas em vez de rodadas."""
    from cartridges import sgdb_picker as modulo  # noqa: PLC0415

    picker = sgdb_picker()
    entregas = []
    monkeypatch.setattr(picker.sgdb, "search_games", lambda _q: [{"id": 1}])
    monkeypatch.setattr(
        picker.sgdb,
        "get_grids",
        lambda *_a, **_k: [{"id": 7, "url": "https://x/7.png", "thumb": "https://x/t7.png"}],
    )
    monkeypatch.setattr(modulo, "download_bytes", lambda *_a, **_k: _apng_bytes())
    monkeypatch.setattr(
        modulo, "entregar_na_tela", lambda func, *args: entregas.append((func, args))
    )
    picker.entregas = entregas
    return picker


def _previas(picker):
    return [args[0] for func, args in picker.entregas if func == picker._add_result]


def test_previa_png_de_busca_animada_vira_apng(busca_sgdb):
    busca_sgdb._search_thread("Jogo", True, busca_sgdb._generation)

    assert [p.name for p in _previas(busca_sgdb)] == ["7.apng"]


def test_previa_png_de_busca_parada_segue_png(busca_sgdb):
    busca_sgdb._search_thread("Jogo", False, busca_sgdb._generation)

    assert [p.suffix for p in _previas(busca_sgdb)] == [".png"]


def test_apng_de_um_quadro_termina_parado(tmp_path, capas_falsas):
    picker = sgdb_picker()
    previa = tmp_path / "7.apng"
    previa.write_bytes(_apng_bytes(quadros=1))

    picker._add_result(previa, "https://x/7.png", True, picker._generation)
    (cover,) = picker._covers
    for pedido in capas_falsas.pedidos:
        pedido.pronto("estatica")

    assert not cover.animada
    assert picker.stack.get_visible_child_name() == "results"


# endregion
