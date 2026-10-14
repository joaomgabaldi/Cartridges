# test_cor_da_capa.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A cor que resume uma capa: matiz e saturação, sem brilho."""

from PIL import Image

from cartridges.utils.cor_da_capa import dominante, dominante_da_imagem


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


def test_imagem_que_explode_ao_abrir_nao_levanta(tmp_path, monkeypatch):
    from PIL import Image as ImagemPIL

    def explodir(*_args, **_kwargs):
        raise ImagemPIL.DecompressionBombError("grande demais")

    monkeypatch.setattr(ImagemPIL, "open", explodir)
    assert dominante(tmp_path / "qualquer.png") is None


# region Imagem já aberta (o print da tela)


def test_imagem_vermelha_da_matiz_vermelha():
    matiz, saturacao = dominante_da_imagem(Image.new("RGB", (200, 100), (220, 20, 20)))
    assert matiz <= 5 or matiz >= 355
    assert saturacao > 800


def test_imagem_cinza_nao_tem_cor():
    assert dominante_da_imagem(Image.new("RGB", (200, 100), (128, 128, 128))) is None


def test_imagem_rgba_tambem_serve():
    assert dominante_da_imagem(Image.new("RGBA", (50, 50), (20, 20, 220, 255))) is not None



def test_cor_escura_so_conta_com_o_valor_minimo_baixo():
    escura = Image.new("RGB", (64, 64), (8, 8, 30))
    assert dominante_da_imagem(escura) is None
    assert dominante_da_imagem(escura, min_valor=0.06) is not None


def test_amarelo_forte_nao_se_mistura_ao_branco_com_mais_cores():
    """Degradê de amarelo a branco com uma mancha azul: em 8 cores o amarelo
    se funde ao branco e sai lavado (saturação ~0,63, que na fita parece
    branco); em 16 ele se mantém."""
    imagem = Image.new("RGB", (160, 90))
    for x in range(160):
        t = x / 159
        cor = (255, round(190 + 65 * t), round(255 * t))
        imagem.paste(Image.new("RGB", (1, 90), cor), (x, 0))
    imagem.paste(Image.new("RGB", (30, 30), (30, 60, 200)), (10, 10))
    matiz, saturacao = dominante_da_imagem(imagem, cores=16)
    assert 40 <= matiz <= 50
    assert saturacao > 800

# endregion
