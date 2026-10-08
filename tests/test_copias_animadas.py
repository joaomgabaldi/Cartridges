# test_copias_animadas.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cópias reduzidas das capas animadas (`utils/copias_animadas.py`)."""

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import copias_animadas


def _animada(caminho, duracoes, formato="WEBP"):
    """Grava uma capa animada pequena, com um quadro por duração."""
    quadros = [
        Image.new("RGBA", (8, 12), (i * 30 % 256, 0, 0, 255))
        for i in range(len(duracoes))
    ]
    quadros[0].save(
        caminho, formato, save_all=True, append_images=quadros[1:],
        duration=duracoes, loop=0, lossless=True,
    )  # fmt: skip
    return caminho


def _duracoes(caminho):
    with Image.open(caminho) as image:
        resultado = []
        for i in range(image.n_frames):
            image.seek(i)
            image.load()  # no WebP a duração só aparece depois de decodificar
            resultado.append(image.info["duration"])
        return resultado


def test_quadros_curtos_sao_fundidos(tmp_path):
    origem = _animada(tmp_path / "a.webp", [16] * 6 + [100])
    destino = tmp_path / "copia.webp"

    assert copias_animadas.gerar(origem, destino, (200, 300)) is True

    assert _duracoes(destino) == [32, 32, 32, 100]
    with Image.open(destino) as image:
        assert image.n_frames == 4


def test_grade_e_detalhes_tem_a_mesma_contagem(tmp_path):
    origem = _animada(tmp_path / "a.webp", [16] * 6 + [100, 50])
    grade = tmp_path / "grade.webp"
    detalhes = tmp_path / "detalhes.webp"

    assert copias_animadas.gerar(origem, grade, (200, 300))
    assert copias_animadas.gerar(origem, detalhes, (280, 420))

    with Image.open(grade) as g, Image.open(detalhes) as d:
        assert g.n_frames == d.n_frames
        assert g.size == (200, 300)
        assert d.size == (280, 420)


def test_origem_de_um_quadro_nao_grava(tmp_path):
    origem = tmp_path / "a.png"
    Image.new("RGBA", (8, 12)).save(origem)
    destino = tmp_path / "copia.webp"

    assert copias_animadas.gerar(origem, destino, (200, 300)) is False
    assert not destino.exists()


def test_origem_so_com_quadros_curtos_nao_grava(tmp_path):
    # Dois quadros de 16 ms fundem num só: não há o que animar.
    origem = _animada(tmp_path / "a.webp", [16, 16])
    destino = tmp_path / "copia.webp"

    assert copias_animadas.gerar(origem, destino, (200, 300)) is False
    assert not destino.exists()


def test_origem_ilegivel_levanta(tmp_path):
    origem = tmp_path / "a.webp"
    origem.write_bytes(b"isto nao e uma imagem")

    with pytest.raises(OSError):
        copias_animadas.gerar(origem, tmp_path / "copia.webp", (200, 300))


def test_nao_vigente_nao_grava(tmp_path):
    origem = _animada(tmp_path / "a.webp", [100, 100])
    destino = tmp_path / "copia.webp"

    resultado = copias_animadas.gerar(
        origem, destino, (200, 300), vigente=lambda: False
    )

    assert resultado is False
    assert not destino.exists()
    assert not (tmp_path / "copia.webp.tmp").exists()


def test_caminho_para(tmp_path):
    assert copias_animadas.caminho_para(
        shared.covers_dir / "g1.webp", (200, 300)
    ) == shared.capas_animadas_dir / "g1_200x300.webp"
    assert copias_animadas.caminho_para(
        tmp_path / "prev" / "9.webp", (200, 300)
    ) == tmp_path / "prev" / "9_200x300.webp"


def test_tamanhos_sao_inteiros():
    assert copias_animadas.tamanhos() == (
        (int(shared.display_size[0]), int(shared.display_size[1])),
        (int(shared.details_size[0]), int(shared.details_size[1])),
    )
