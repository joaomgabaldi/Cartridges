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


def test_zerar_limpa_barra_e_texto():
    tela = TelaDeDownload()
    tela.atualizar(5 * MB, 20 * MB)
    tela.zerar()
    assert tela.barra.get_fraction() == 0.0
    assert tela.texto.get_label() == ""


def test_kb_arredonda_para_cima():
    assert tamanho_baixado(300, None) == "1 KB"
    assert tamanho_baixado(1536, 4096) == "2 KB de 4 KB"


def test_corpo_maior_que_o_total_pulsa_e_mostra_so_o_recebido(monkeypatch):
    # O servidor informou menos do que mandou: o total real não é conhecido.
    tela = TelaDeDownload()
    pulsos = []
    monkeypatch.setattr(tela.barra, "pulse", lambda: pulsos.append(1))
    tela.atualizar(30 * MB, 20 * MB)
    assert tela.texto.get_label() == "30,0 MB"
    assert pulsos == [1]


def test_pulsa_do_clique_ate_o_primeiro_dado(monkeypatch):
    tela = TelaDeDownload()
    pulsos = []
    monkeypatch.setattr(tela.barra, "pulse", lambda: pulsos.append(1))
    monkeypatch.setattr(tela, "get_mapped", lambda: True)
    tela.zerar()

    # Tempos do frame clock, em microssegundos: um pulso a cada 0,1 s.
    for agora in (0, 50_000, 100_000):
        assert tela._tique(agora) is True
    assert len(pulsos) == 2

    # O primeiro dado desliga o tick: o relógio de quadros para.
    tela.atualizar(MB, 20 * MB)
    assert tela._tique(300_000) is False
    assert len(pulsos) == 2

    tela.zerar()
    assert tela._tique(400_000) is True
    assert len(pulsos) == 3


def test_tela_escondida_para_de_pulsar(monkeypatch):
    # O download falhou antes do primeiro dado e a página de erro tomou o lugar.
    tela = TelaDeDownload()
    pulsos = []
    monkeypatch.setattr(tela.barra, "pulse", lambda: pulsos.append(1))
    monkeypatch.setattr(tela, "get_mapped", lambda: False)
    tela.zerar()

    assert tela._tique(0) is False
    assert pulsos == []


def test_zerar_registra_o_tick_uma_vez_por_download(monkeypatch):
    tela = TelaDeDownload()
    registros = []
    monkeypatch.setattr(tela, "add_tick_callback", lambda cb: registros.append(cb) or 7)
    monkeypatch.setattr(tela, "get_mapped", lambda: True)

    tela.zerar()
    tela.zerar()
    assert len(registros) == 1

    tela.atualizar(1, 2)
    tela._tique(0)  # desligou
    tela.zerar()
    assert len(registros) == 2


def test_tela_nao_fica_presa_na_memoria():
    import gc  # noqa: PLC0415
    import weakref  # noqa: PLC0415

    tela = TelaDeDownload()
    tela.zerar()
    ref = weakref.ref(tela)
    del tela
    gc.collect()
    assert ref() is None


def test_quase_um_mega_ja_e_mb():
    assert tamanho_baixado(1_048_000, None) == "1,0 MB"


def test_recebido_igual_ao_total_enche_a_barra():
    tela = TelaDeDownload()
    tela.atualizar(20 * MB, 20 * MB)
    assert tela.barra.get_fraction() == 1.0
    assert tela.texto.get_label() == "20,0 MB de 20,0 MB"
