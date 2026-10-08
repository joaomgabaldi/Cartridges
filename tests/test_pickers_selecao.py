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
    monkeypatch.setattr(picker, "_select_thread", lambda _url, _animated=False: None)
    geracao_da_busca = picker._generation
    adicionar(picker, previa, geracao_da_busca)
    filho = picker.flowbox.get_child_at_index(0)

    picker._on_child_activated(picker.flowbox, filho)
    adicionar(picker, previa, geracao_da_busca)

    assert picker.stack.get_visible_child_name() == "downloading"
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


# region Limites de download do seletor de capas


class _ThreadNaHora:
    """Roda o alvo já no ``start``: o teste vê o download sem esperar thread."""

    def __init__(self, target, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def _anotar_limites(monkeypatch, erro=None, conteudo=b""):
    from cartridges import sgdb_picker as modulo  # noqa: PLC0415
    from cartridges.utils.download import MAX_IMAGE_BYTES  # noqa: PLC0415

    limites = []

    def baixar(_url, timeout=10, max_bytes=MAX_IMAGE_BYTES, ao_progredir=None):
        limites.append(max_bytes)
        if erro is not None:
            raise erro
        return conteudo

    monkeypatch.setattr(modulo, "download_bytes", baixar)
    return limites


@pytest.mark.parametrize("animated", [True, False])
def test_previa_usa_o_limite_do_tipo(busca_sgdb, monkeypatch, animated):
    from cartridges.utils.download import (  # noqa: PLC0415
        MAX_ANIMATED_IMAGE_BYTES,
        MAX_IMAGE_BYTES,
    )

    limites = _anotar_limites(monkeypatch, conteudo=_apng_bytes())

    busca_sgdb._search_thread("Jogo", animated, busca_sgdb._generation)

    assert limites == [MAX_ANIMATED_IMAGE_BYTES if animated else MAX_IMAGE_BYTES]


@pytest.mark.parametrize("ativo", [True, False])
def test_capa_escolhida_usa_o_limite_do_botao(previa, monkeypatch, ativo):
    import requests  # noqa: PLC0415

    from cartridges import sgdb_picker as modulo  # noqa: PLC0415
    from cartridges.utils.download import (  # noqa: PLC0415
        MAX_ANIMATED_IMAGE_BYTES,
        MAX_IMAGE_BYTES,
    )

    picker = sgdb_picker()
    picker.animated_button.set_active(ativo)  # sem chave da API: a busca nem sai
    picker._add_result(previa, "https://x/7.png", ativo, picker._generation)
    limites = _anotar_limites(monkeypatch, erro=requests.RequestException("x"))
    monkeypatch.setattr(modulo.threading, "Thread", _ThreadNaHora)
    monkeypatch.setattr(modulo, "entregar_na_tela", lambda *_a: None)

    picker._on_child_activated(picker.flowbox, picker.flowbox.get_child_at_index(0))

    assert limites == [MAX_ANIMATED_IMAGE_BYTES if ativo else MAX_IMAGE_BYTES]


def test_log_da_previa_traz_o_tipo_do_erro(busca_sgdb, monkeypatch, caplog):
    from cartridges.utils.download import ResponseTooLargeError  # noqa: PLC0415

    _anotar_limites(monkeypatch, erro=ResponseTooLargeError("https://x/7.png"))

    busca_sgdb._search_thread("Jogo", True, busca_sgdb._generation)

    assert "ResponseTooLargeError" in caplog.text


def test_log_da_capa_escolhida_traz_o_tipo_do_erro(monkeypatch, caplog):
    from cartridges import sgdb_picker as modulo  # noqa: PLC0415
    from cartridges.utils.download import ResponseTooLargeError  # noqa: PLC0415

    picker = sgdb_picker()
    _anotar_limites(monkeypatch, erro=ResponseTooLargeError("https://x/7.png"))
    monkeypatch.setattr(modulo, "entregar_na_tela", lambda *_a: None)

    picker._select_thread("https://x/7.png", True)

    assert "ResponseTooLargeError" in caplog.text


# endregion


# region Tela de download da escolha


def _modulo(picker):
    import sys  # noqa: PLC0415

    return sys.modules[type(picker).__module__]


def _baixar_falso(monkeypatch, picker, erro):
    """Troca o download do seletor: anota o ``ao_progredir`` e levanta ``erro``.
    Devolve a lista dos ``ao_progredir`` e a das entregas à thread principal."""
    modulo = _modulo(picker)
    recebidos, entregas = [], []

    def baixar(_url, timeout=10, max_bytes=0, ao_progredir=None):
        recebidos.append(ao_progredir)
        raise erro

    monkeypatch.setattr(modulo, "download_bytes", baixar)
    monkeypatch.setattr(
        modulo, "entregar_na_tela", lambda func, *args: entregas.append((func, args))
    )
    return recebidos, entregas


@pytest.mark.parametrize("criar", [logo_picker, sgdb_picker])
def test_escolha_baixa_com_progresso(criar, monkeypatch):
    import requests  # noqa: PLC0415

    picker = criar()
    recebidos, _entregas = _baixar_falso(monkeypatch, picker, requests.RequestException("x"))

    picker._select_thread("https://x/7.png")

    assert recebidos == [picker._ao_progredir]


@pytest.mark.parametrize("criar", [logo_picker, sgdb_picker])
def test_download_cancelado_encerra_em_silencio(criar, monkeypatch, caplog):
    from cartridges.utils.download import DownloadCancelado  # noqa: PLC0415

    picker = criar()
    _recebidos, entregas = _baixar_falso(monkeypatch, picker, DownloadCancelado())

    picker._select_thread("https://x/7.png")

    assert entregas == []
    assert "Could not" not in caplog.text


@pytest.mark.parametrize("criar", [logo_picker, sgdb_picker])
def test_progresso_cancela_depois_de_fechar(criar):
    from cartridges.utils.download import DownloadCancelado  # noqa: PLC0415

    picker = criar()
    picker._mostrar_download()
    assert picker.stack.get_visible_child_name() == "downloading"

    picker._on_closed()

    with pytest.raises(DownloadCancelado):
        picker._ao_progredir(1, 2)


def test_mostrar_download_de_novo_zera_a_tela():
    picker = logo_picker()
    picker._mostrar_download()
    picker._tela_de_download.atualizar(5, 10)

    picker._mostrar_download()

    assert picker._tela_de_download.barra.get_fraction() == 0.0


# endregion
