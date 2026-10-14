# test_tela_do_jogo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A cor predominante do monitor do jogo, e os casos em que não há cor a tirar."""

import os

import pytest
from PIL import Image

from cartridges.utils import tela_do_jogo
from cartridges.utils.tela_do_jogo import Amostra


@pytest.fixture
def tela(monkeypatch):
    """Uma janela de outro processo na frente, e o print trocável pelo teste."""
    estado = {"imagem": Image.new("RGB", (64, 36), (220, 20, 20)), "capturas": 0}

    def capturar():
        estado["capturas"] += 1
        if isinstance(estado["imagem"], Exception):
            raise estado["imagem"]
        return estado["imagem"]

    monkeypatch.setattr(tela_do_jogo, "_janela_da_frente", lambda: 1234)
    monkeypatch.setattr(tela_do_jogo, "_processo_da", lambda _hwnd: os.getpid() + 1)
    monkeypatch.setattr(tela_do_jogo, "_capturar", capturar)
    return estado


def test_sem_janela_na_frente_e_ignorada(tela, monkeypatch):
    monkeypatch.setattr(tela_do_jogo, "_janela_da_frente", lambda: 0)
    assert tela_do_jogo.cor_da_tela() == Amostra("ignorada")
    assert tela["capturas"] == 0


def test_janela_do_proprio_app_e_ignorada(tela, monkeypatch):
    monkeypatch.setattr(tela_do_jogo, "_processo_da", lambda _hwnd: os.getpid())
    assert tela_do_jogo.cor_da_tela() == Amostra("ignorada")
    assert tela["capturas"] == 0


def test_imagem_colorida_da_a_cor(tela):
    amostra = tela_do_jogo.cor_da_tela()
    assert amostra.tipo == "cor"
    assert amostra.cor[0] <= 5 or amostra.cor[0] >= 355


def test_imagem_cinza_e_sem_cor(tela):
    tela["imagem"] = Image.new("RGB", (64, 36), (90, 90, 90))
    assert tela_do_jogo.cor_da_tela().tipo == "sem_cor"


def test_imagem_toda_preta_e_bloqueada(tela):
    tela["imagem"] = Image.new("RGB", (64, 36), (0, 0, 0))
    assert tela_do_jogo.cor_da_tela() == Amostra("bloqueada")


def test_quase_preta_nao_e_bloqueio(tela):
    imagem = Image.new("RGB", (64, 36), (0, 0, 0))
    imagem.putpixel((10, 10), (3, 3, 3))
    tela["imagem"] = imagem
    assert tela_do_jogo.cor_da_tela().tipo == "sem_cor"


def test_captura_que_levanta_e_bloqueada(tela):
    tela["imagem"] = OSError("screen grab failed")
    assert tela_do_jogo.cor_da_tela() == Amostra("bloqueada")


def test_captura_so_o_monitor_principal(monkeypatch):
    """O jogo roda no monitor principal: os outros não entram no print, e o
    custo da captura é o de uma tela só."""
    pedidos = []
    monkeypatch.setattr(
        tela_do_jogo.ImageGrab,
        "grab",
        lambda **kwargs: pedidos.append(kwargs) or Image.new("RGB", (8, 8)),
    )
    tela_do_jogo._capturar()
    assert pedidos == [{}]


def test_a_amostra_traz_a_luz_da_cena(tela):
    tela["imagem"] = Image.new("RGB", (64, 36), (255, 255, 255))
    assert tela_do_jogo.cor_da_tela().luz > 0.9
    tela["imagem"] = Image.new("RGB", (64, 36), (60, 60, 60))
    assert abs(tela_do_jogo.cor_da_tela().luz - 60 / 255) < 0.02


def test_a_amostra_traz_o_tempo_da_captura(tela):
    ms = tela_do_jogo.cor_da_tela().ms
    assert isinstance(ms, int) and ms >= 0


def test_cena_escura_com_cor_ainda_da_cor(tela):
    tela["imagem"] = Image.new("RGB", (64, 36), (8, 8, 30))
    amostra = tela_do_jogo.cor_da_tela()
    assert amostra.tipo == "cor"
    assert 225 < amostra.cor[0] < 255
