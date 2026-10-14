# test_tela_do_jogo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A cor predominante do monitor do jogo, e os casos em que não há cor a tirar."""

import os

import pytest
from PIL import Image

from cartridges.utils import tela_do_jogo
from cartridges.utils.tela_do_jogo import Amostra

MONITOR = (1920, 0, 3840, 1080)


@pytest.fixture
def tela(monkeypatch):
    """Uma janela de outro processo na frente, num monitor conhecido, e o print
    trocável pelo teste."""
    estado = {"imagem": Image.new("RGB", (64, 36), (220, 20, 20)), "bbox": None}

    def capturar(bbox):
        estado["bbox"] = bbox
        if isinstance(estado["imagem"], Exception):
            raise estado["imagem"]
        return estado["imagem"]

    monkeypatch.setattr(tela_do_jogo, "_janela_da_frente", lambda: 1234)
    monkeypatch.setattr(tela_do_jogo, "_processo_da", lambda _hwnd: os.getpid() + 1)
    monkeypatch.setattr(tela_do_jogo, "_retangulo_do_monitor", lambda: MONITOR)
    monkeypatch.setattr(tela_do_jogo, "_capturar", capturar)
    return estado


def test_sem_janela_na_frente_e_ignorada(tela, monkeypatch):
    monkeypatch.setattr(tela_do_jogo, "_janela_da_frente", lambda: 0)
    assert tela_do_jogo.cor_da_tela() == Amostra("ignorada")
    assert tela["bbox"] is None


def test_janela_do_proprio_app_e_ignorada(tela, monkeypatch):
    monkeypatch.setattr(tela_do_jogo, "_processo_da", lambda _hwnd: os.getpid())
    assert tela_do_jogo.cor_da_tela() == Amostra("ignorada")
    assert tela["bbox"] is None


def test_imagem_colorida_da_a_cor(tela):
    amostra = tela_do_jogo.cor_da_tela()
    assert amostra.tipo == "cor"
    assert amostra.cor[0] <= 5 or amostra.cor[0] >= 355


def test_imagem_cinza_e_sem_cor(tela):
    tela["imagem"] = Image.new("RGB", (64, 36), (90, 90, 90))
    assert tela_do_jogo.cor_da_tela() == Amostra("sem_cor")


def test_imagem_toda_preta_e_bloqueada(tela):
    tela["imagem"] = Image.new("RGB", (64, 36), (0, 0, 0))
    assert tela_do_jogo.cor_da_tela() == Amostra("bloqueada")


def test_quase_preta_nao_e_bloqueio(tela):
    imagem = Image.new("RGB", (64, 36), (0, 0, 0))
    imagem.putpixel((10, 10), (3, 3, 3))
    tela["imagem"] = imagem
    assert tela_do_jogo.cor_da_tela() == Amostra("sem_cor")


def test_captura_que_levanta_e_bloqueada(tela):
    tela["imagem"] = OSError("screen grab failed")
    assert tela_do_jogo.cor_da_tela() == Amostra("bloqueada")


def test_monitor_que_nao_responde_e_bloqueada(tela, monkeypatch):
    def falhar():
        raise OSError("GetMonitorInfoW falhou")

    monkeypatch.setattr(tela_do_jogo, "_retangulo_do_monitor", falhar)
    assert tela_do_jogo.cor_da_tela() == Amostra("bloqueada")


def test_a_captura_recorta_o_monitor_da_janela(tela):
    tela_do_jogo.cor_da_tela()
    assert tela["bbox"] == MONITOR
