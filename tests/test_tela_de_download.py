# test_tela_de_download.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tela "Baixando…" dos seletores: barra e tamanho baixado."""

import pytest

from cartridges.utils.tela_de_download import TelaDeDownload, tamanho_baixado

MB = 1024 * 1024


def test_formata_mb_com_virgula():
    assert tamanho_baixado(4_582_277, 21 * MB) == "4,4 MB de 21,0 MB"


def test_formata_kb_abaixo_de_um_mega():
    assert tamanho_baixado(40 * 1024, 512 * 1024) == "40 KB de 512 KB"
    assert tamanho_baixado(MB, None) == "1,0 MB"


def test_sem_total_mostra_so_o_recebido():
    tela = TelaDeDownload()
    tela.atualizar(512 * 1024, None)
    assert tela.texto.get_label() == "512 KB"


def test_barra_acompanha_o_total():
    tela = TelaDeDownload()
    assert tela.atualizar(5 * MB, 20 * MB) is False
    assert tela.barra.get_fraction() == pytest.approx(0.25)


def test_fracao_nao_passa_de_um():
    tela = TelaDeDownload()
    tela.atualizar(30 * MB, 20 * MB)
    assert tela.barra.get_fraction() == 1.0


def test_zerar_limpa_barra_e_texto():
    tela = TelaDeDownload()
    tela.atualizar(5 * MB, 20 * MB)
    tela.zerar()
    assert tela.barra.get_fraction() == 0.0
    assert tela.texto.get_label() == ""
