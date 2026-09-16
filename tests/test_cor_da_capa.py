# test_cor_da_capa.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A cor que resume uma capa: matiz e saturação, sem brilho."""

from PIL import Image

from cartridges.utils.cor_da_capa import dominante


def _capa(tmp_path, cor, detalhe=None):
    imagem = Image.new("RGB", (120, 180), cor)
    if detalhe:
        imagem.paste(Image.new("RGB", (40, 40), detalhe), (20, 20))
    caminho = tmp_path / "capa.png"
    imagem.save(caminho)
    return caminho


def test_capa_vermelha_da_matiz_vermelha(tmp_path):
    matiz, saturacao = dominante(_capa(tmp_path, (220, 20, 20)))
    assert matiz < 10 or matiz > 350
    assert saturacao > 800


def test_detalhe_vivo_vence_o_fundo_apagado(tmp_path):
    # Fundo cinza ocupa quase tudo, mas cinza não diz nada sobre o jogo.
    matiz, _ = dominante(_capa(tmp_path, (60, 60, 62), detalhe=(0, 200, 200)))
    assert 165 < matiz < 195


def test_capa_sem_cor_nenhuma_nao_chuta(tmp_path):
    assert dominante(_capa(tmp_path, (12, 12, 12))) is None


def test_arquivo_que_nao_abre_nao_levanta(tmp_path):
    quebrado = tmp_path / "quebrado.png"
    quebrado.write_text("nao sou uma imagem", encoding="utf-8")
    assert dominante(quebrado) is None
