# test_pickers_selecao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Escolher uma capa ou um logo encerra a busca que ainda baixa miniaturas, e como o download corre.

Os seletores de capa e de logo do SteamGridDB (`cartridges.modelos.seletores`). O seletor de papel de
parede (wallhaven) ainda é do GTK e entra com a tarefa 10 do plano 3.
"""

import logging

import pytest
import requests

from cartridges.modelos import seletores
from cartridges.utils.download import (
    MAX_ANIMATED_IMAGE_BYTES,
    MAX_IMAGE_BYTES,
    DownloadCancelado,
    ResponseTooLargeError,
)
from tests.apoio_seletores import (  # noqa: F401  (as fixtures vêm junto)
    DownloadFalso,
    SgdbFalso,
    baixar,
    chave,
    criar,
    esperar,
    lista_de_grades,
    prontos,
    temp,
    vazio_de,
)


@pytest.fixture(params=[seletores.SeletorDoSgdb, seletores.SeletorDeLogo], ids=["capa", "logo"])
def classe(request):
    return request.param


def _miniatura(seletor, linha):
    return seletor.data(seletor.index(linha, 0), seletor.Papel.Miniatura)


def test_previa_atrasada_nao_tira_o_carregamento_da_escolha(classe, monkeypatch, temp):
    class DepoisDaPrimeira(DownloadFalso):
        def __call__(self, url, **kwargs):
            if len(self.urls) == 1:  # a segunda miniatura fica presa: é a "atrasada"
                self.soltar.clear()
            return super().__call__(url, **kwargs)

    baixar = DepoisDaPrimeira()
    monkeypatch.setattr(seletores, "download_bytes", baixar)
    seletor, destino = criar(classe)
    seletor.abrir("Jogo")
    assert esperar(lambda: _miniatura(seletor, 0) != "")
    assert baixar.comecou.is_set()

    seletor.escolher(0)
    assert esperar(lambda: baixar.cancelado.is_set()), "a busca das miniaturas é encerrada pela escolha"
    assert esperar(lambda: len(baixar.urls) == 3)  # o download da escolha, preso como o resto
    # A miniatura atrasada não chega: a grade segue em "baixando", sem nada novo.
    assert seletor.baixando is True and _miniatura(seletor, 1) == "" and _miniatura(seletor, 2) == ""
    baixar.soltar.set()
    assert esperar(lambda: destino.capas or destino.logos)
    (entregue,) = destino.capas or destino.logos
    assert vazio_de(temp) == [entregue.name]


def test_previa_png_de_busca_animada_vira_apng_e_a_parada_segue_png(baixar, temp):
    seletor, _ = criar(seletores.SeletorDoSgdb)
    seletor.abrir("Jogo")
    assert esperar(lambda: prontos(seletor, 3))
    assert [_miniatura(seletor, i).rsplit(".", 1)[1] for i in range(3)] == ["png"] * 3
    seletor.animadas = True
    assert esperar(lambda: prontos(seletor, 3) and _miniatura(seletor, 0).endswith(".apng"))
    assert [_miniatura(seletor, i).rsplit(".", 1)[1] for i in range(3)] == ["apng"] * 3
    seletor.fechar()


@pytest.mark.parametrize("animadas", [True, False])
def test_previa_usa_o_limite_do_tipo(animadas, baixar, temp):
    seletor, _ = criar(seletores.SeletorDoSgdb)
    seletor.abrir("Jogo")
    assert esperar(lambda: prontos(seletor, 3))
    if animadas:
        baixar.limites.clear()
        seletor.animadas = True
        assert esperar(lambda: prontos(seletor, 3) and len(baixar.limites) >= 3)
    assert set(baixar.limites) == {MAX_ANIMATED_IMAGE_BYTES if animadas else MAX_IMAGE_BYTES}
    seletor.fechar()


@pytest.mark.parametrize("animadas", [True, False])
def test_capa_escolhida_usa_o_limite_do_botao(animadas, baixar, temp):
    seletor, _ = criar(seletores.SeletorDoSgdb)
    seletor.abrir("Jogo")
    assert esperar(lambda: prontos(seletor, 3))
    if animadas:
        seletor.animadas = True
        assert esperar(lambda: prontos(seletor, 3) and _miniatura(seletor, 0).endswith(".apng"))
    baixar.falhar = requests.RequestException("x")
    baixar.limites.clear()
    seletor.escolher(0)
    assert esperar(lambda: seletor.erro)
    assert baixar.limites == [MAX_ANIMATED_IMAGE_BYTES if animadas else MAX_IMAGE_BYTES]
    seletor.fechar()


def test_log_da_previa_traz_o_tipo_do_erro(baixar, temp, caplog):
    baixar.falhar = ResponseTooLargeError("https://x/7.png")
    seletor, _ = criar(seletores.SeletorDoSgdb)
    with caplog.at_level(logging.WARNING):
        seletor.abrir("Jogo")
        # Toda miniatura falhando não deixa o seletor carregando para sempre.
        assert esperar(lambda: seletor.vazio)
    assert "ResponseTooLargeError" in caplog.text
    assert seletor.tituloDoEstado == "Não foi possível carregar as pré-visualizações"
    assert seletor.descricaoDoEstado == "Tente novamente." and seletor.erro is True
    seletor.fechar()


def test_log_da_capa_escolhida_traz_o_tipo_do_erro(baixar, temp, caplog):
    seletor, _ = criar(seletores.SeletorDoSgdb)
    seletor.abrir("Jogo")
    assert esperar(lambda: prontos(seletor, 3))
    baixar.falhar = ResponseTooLargeError("https://x/7.png")
    with caplog.at_level(logging.WARNING):
        seletor.escolher(0)
        assert esperar(lambda: seletor.erro)
    assert "ResponseTooLargeError" in caplog.text
    seletor.fechar()


def test_escolha_baixa_com_progresso(classe, baixar, temp):
    seletor, _ = criar(classe)
    seletor.abrir("Jogo")
    assert esperar(lambda: prontos(seletor, 3))
    baixar.soltar.clear()
    baixar.comecou.clear()
    seletor.escolher(0)
    assert esperar(lambda: seletor.baixando and seletor.textoDoProgresso != "")
    # 1 de 10 bytes: "1 KB de 1 KB", uma barra em 10%.
    assert seletor.textoDoProgresso == "1 KB de 1 KB" and seletor.progresso == pytest.approx(0.1)
    baixar.soltar.set()
    assert esperar(lambda: not seletor.aberto)


def test_download_cancelado_encerra_em_silencio(classe, baixar, temp, caplog):
    seletor, destino = criar(classe)
    seletor.abrir("Jogo")
    assert esperar(lambda: prontos(seletor, 3))
    baixar.falhar = DownloadCancelado()
    with caplog.at_level(logging.INFO):
        seletor.escolher(0)
        assert esperar(lambda: baixar.comecou.is_set())
        assert esperar(lambda: False, 0.3) is False
    assert seletor.erro is False and destino.capas == [] and destino.logos == []
    assert "Could not" not in caplog.text
    seletor.fechar()


def test_progresso_cancela_depois_de_fechar(classe, baixar, temp):
    seletor, _ = criar(classe)
    seletor.abrir("Jogo")
    assert esperar(lambda: prontos(seletor, 3))
    seletor.fechar()
    with pytest.raises(DownloadCancelado):
        seletor._ao_progredir(1, 2)  # noqa: SLF001


def test_escolher_de_novo_zera_o_progresso(classe, baixar, temp):
    seletor, _ = criar(classe, SgdbFalso(grids=lista_de_grades(3)))
    seletor.abrir("Jogo")
    assert esperar(lambda: prontos(seletor, 3))
    baixar.soltar.clear()
    seletor.escolher(0)
    assert esperar(lambda: seletor.textoDoProgresso != "")
    seletor.fechar()
    seletor.abrir("Jogo")
    assert seletor.textoDoProgresso == "" and seletor.baixando is False
    seletor.fechar()
    baixar.soltar.set()


# -- o texto e a barra de "Baixando…" (eram os testes da `TelaDeDownload` GTK) -----------------------


def _recebido(seletor, recebido, total):
    """Entrega o progresso na thread principal, como a `na_thread_principal` do download faria."""
    seletor._baixando = True  # noqa: SLF001
    seletor._progresso_recebido(seletor._generation, recebido, total)  # noqa: SLF001


def test_sem_total_mostra_so_o_recebido(classe, temp):
    seletor, _ = criar(classe)
    _recebido(seletor, 512 * 1024, None)
    # Sem total, a barra fica indeterminada (-1) e o texto traz só o que chegou.
    assert seletor.textoDoProgresso == "512 KB" and seletor.progresso == -1.0


def test_corpo_maior_que_o_total_pulsa_e_mostra_so_o_recebido(classe, temp):
    # O servidor informou menos do que mandou: o total real não é conhecido, e "30,0 MB de 20,0 MB"
    # pareceria erro do aplicativo.
    seletor, _ = criar(classe)
    _recebido(seletor, 30 * 1024 * 1024, 20 * 1024 * 1024)
    assert seletor.textoDoProgresso == "30,0 MB" and seletor.progresso == -1.0


def test_recebido_igual_ao_total_enche_a_barra(classe, temp):
    seletor, _ = criar(classe)
    _recebido(seletor, 20 * 1024 * 1024, 20 * 1024 * 1024)
    assert seletor.textoDoProgresso == "20,0 MB de 20,0 MB" and seletor.progresso == 1.0
