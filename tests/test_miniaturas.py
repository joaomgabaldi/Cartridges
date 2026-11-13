# test_miniaturas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Miniaturas das capas no tamanho da grade (`utils/miniaturas.py`)."""

import os
import time
from types import SimpleNamespace

import pytest
from PySide6.QtGui import QColor, QImage

from kyron import shared
from kyron.jogo import Jogo
from kyron.modelos.ordem import Linha
from kyron.utils import miniaturas


@pytest.fixture(autouse=True)
def _tamanho_e_estado(monkeypatch):
    monkeypatch.setattr(shared, "display_size", (20, 30), raising=False)
    monkeypatch.setattr(miniaturas, "_vistos", set())


def _capa(nome="imported_1.tiff", largura=60, altura=90):
    caminho = shared.covers_dir / nome
    imagem = QImage(largura, altura, QImage.Format.Format_RGB32)
    imagem.fill(QColor(200, 30, 30))
    assert imagem.save(str(caminho), "PNG")  # o Qt lê pelo conteúdo, não pela extensão
    return caminho


def _jogo(game_id="imported_1"):
    return Jogo({"game_id": game_id, "source": "imported", "name": "Alfa"})


def test_gerar_grava_png_no_tamanho_da_grade():
    destino = miniaturas.caminho_para("imported_1")
    assert miniaturas.gerar(_capa(), destino) is True
    imagem = QImage(str(destino))
    assert (imagem.width(), imagem.height()) == tuple(shared.display_size)
    assert destino.name == "imported_1-20x30.png"


def test_url_vazia_sem_miniatura_e_com_miniatura_velha():
    capa = _capa()
    assert miniaturas.url("imported_1", None) == ""
    assert miniaturas.url("imported_1", capa) == ""
    destino = miniaturas.caminho_para("imported_1")
    miniaturas.gerar(capa, destino)
    assert miniaturas.url("imported_1", capa).startswith("file:///")
    agora = destino.stat().st_mtime_ns
    os.utime(capa, ns=(agora + 10**9, agora + 10**9))
    assert miniaturas.url("imported_1", capa) == ""


def test_url_tem_a_versao_do_arquivo():
    capa = _capa()
    destino = miniaturas.caminho_para("imported_1")
    miniaturas.gerar(capa, destino)
    assert miniaturas.url("imported_1", capa).endswith(f"?v={destino.stat().st_mtime_ns}")


def test_capa_ilegivel_nao_gera_e_nao_e_tentada_de_novo(monkeypatch):
    capa = shared.covers_dir / "imported_1.tiff"
    capa.write_bytes(b"nao e uma imagem")
    destino = miniaturas.caminho_para("imported_1")
    assert miniaturas.gerar(capa, destino) is False
    assert not destino.exists()

    tentativas = []
    monkeypatch.setattr(miniaturas, "gerar", lambda c, d: tentativas.append(c) or False)
    for _ in range(2):
        miniaturas.preparar([("imported_1", capa)])
    # Espera a thread esvaziar a fila.
    for _ in range(200):
        if tentativas and miniaturas._fila.empty():
            break
        time.sleep(0.01)
    time.sleep(0.05)
    assert tentativas == [capa]
    # Capa que mudou (mtime novo) é tentada de novo.
    agora = capa.stat().st_mtime_ns
    os.utime(capa, ns=(agora + 10**9, agora + 10**9))
    miniaturas.preparar([("imported_1", capa)])
    for _ in range(200):
        if len(tentativas) == 2:
            break
        time.sleep(0.01)
    assert tentativas == [capa, capa]


def test_preparar_gera_na_ordem_dada():
    capas = [(f"imported_{i}", _capa(f"imported_{i}.tiff")) for i in (1, 2, 3)]
    miniaturas.preparar(capas)
    for _ in range(300):
        if all(miniaturas.url(game_id, capa) for game_id, capa in capas):
            break
        time.sleep(0.01)
    assert all(miniaturas.url(game_id, capa) for game_id, capa in capas)


def test_limpar_apaga_orfas_outros_tamanhos_e_tmp():
    pasta = shared.miniaturas_dir
    pasta.mkdir(parents=True)
    ficam = [pasta / "vivo-20x30.png", pasta / "com-hifen_1-20x30.png"]
    vao = [pasta / "morto-20x30.png", pasta / "vivo-40x60.png", pasta / "vivo-20x30.png.abc.tmp"]
    for arquivo in (*ficam, *vao):
        arquivo.write_bytes(b"x")
    miniaturas.limpar({"vivo", "com-hifen_1"})
    assert sorted(p.name for p in pasta.iterdir()) == sorted(p.name for p in ficam)


def test_apagar_tira_a_miniatura_do_jogo_e_nao_falha_sem_ela():
    destino = miniaturas.caminho_para("imported_1")
    miniaturas.gerar(_capa(), destino)
    miniaturas.apagar("imported_1")
    assert not destino.exists()
    miniaturas.apagar("imported_1")


def test_linha_traz_a_miniatura_em_dia():
    capa = _capa()
    assert Linha.de(_jogo()).miniatura == ""
    miniaturas.gerar(capa, miniaturas.caminho_para("imported_1"))
    assert Linha.de(_jogo()).miniatura == miniaturas.url("imported_1", capa) != ""


def test_capa_trocada_esvazia_a_miniatura_da_linha():
    capa = _capa()
    destino = miniaturas.caminho_para("imported_1")
    miniaturas.gerar(capa, destino)
    assert Linha.de(_jogo()).miniatura != ""
    agora = destino.stat().st_mtime_ns
    os.utime(capa, ns=(agora + 10**9, agora + 10**9))  # capa regravada
    assert Linha.de(_jogo()).miniatura == ""


def test_url_ignora_a_capa_de_fora_da_pasta_de_capas(tmp_path):
    de_sessao = tmp_path / "capa_da_sessao.png"
    imagem = QImage(60, 90, QImage.Format.Format_RGB32)
    imagem.save(str(de_sessao), "PNG")
    miniaturas.gerar(de_sessao, miniaturas.caminho_para("imported_1"))
    assert miniaturas.url("imported_1", de_sessao) == ""


def test_preparar_pula_a_capa_de_fora_da_pasta_de_capas(tmp_path, monkeypatch):
    de_sessao = tmp_path / "capa_da_sessao.png"
    QImage(60, 90, QImage.Format.Format_RGB32).save(str(de_sessao), "PNG")
    pedidos = []
    monkeypatch.setattr(miniaturas, "_fila", SimpleNamespace(put=pedidos.append))
    miniaturas.preparar([("imported_1", de_sessao)])
    assert pedidos == [] and miniaturas._vistos == set()


def test_preparar_registra_so_o_que_precisa_de_miniatura(monkeypatch):
    capa = _capa()
    miniaturas.gerar(capa, miniaturas.caminho_para("imported_1"))
    miniaturas.preparar([("imported_1", capa)])
    assert miniaturas._vistos == set()
