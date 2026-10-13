# test_capa_video.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Um vídeo escolhido como capa vira um WebP animado do tamanho das capas,
enquadrado como as imagens escolhidas de um arquivo."""

import subprocess
from pathlib import Path

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import capa_video

precisa_do_ffmpeg = pytest.mark.skipif(
    capa_video.executavel() is None, reason="ffmpeg não instalado (pacman -S mingw-w64-ucrt-x86_64-ffmpeg)"
)


def fazer_video(caminho: Path, tamanho: str, segundos: float = 1, taxa: int = 10) -> Path:
    subprocess.run(
        [str(capa_video.executavel()), "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         f"testsrc2=size={tamanho}:rate={taxa}", "-t", str(segundos), "-c:v", "mpeg4", str(caminho)],
        check=True,
    )  # fmt: skip
    return caminho


def quadros_e_duracao(caminho: Path) -> tuple[int, int]:
    with Image.open(caminho) as imagem:
        assert imagem.is_animated
        assert imagem.size == shared.image_size
        duracao = 0
        for indice in range(imagem.n_frames):
            imagem.seek(indice)
            imagem.load()
            duracao += imagem.info.get("duration", 0)
        return imagem.n_frames, duracao


def test_eh_video_pelo_sufixo():
    assert capa_video.eh_video(Path("trailer.MP4"))
    assert capa_video.eh_video(Path("clipe.webm"))
    assert not capa_video.eh_video(Path("capa.gif"))


def test_video_alto_e_so_esticado():
    assert "overlay" not in capa_video.filtro(1080, 1920, (600, 900))


def test_video_pouco_mais_largo_ainda_e_esticado():
    # 600x800: esticar para 600x900 distorce 11 %, dentro dos 12 % tolerados.
    assert "overlay" not in capa_video.filtro(600, 800, (600, 900))


def test_video_largo_vai_ao_centro_sobre_o_proprio_desfoque():
    filtro = capa_video.filtro(1920, 1080, (600, 900))

    assert "overlay=(W-w)/2:(H-h)/2" in filtro
    assert "[origem]scale=600:337:" in filtro


def test_sem_ffmpeg_a_falha_tem_mensagem(tmp_path, monkeypatch):
    monkeypatch.setattr(capa_video, "executavel", lambda: None)

    with pytest.raises(capa_video.VideoFalhou):
        capa_video.converter(tmp_path / "trailer.mp4")


@precisa_do_ffmpeg
def test_arquivo_que_nao_e_video_levanta(tmp_path):
    falso = tmp_path / "falso.mp4"
    falso.write_bytes(b"nada")

    with pytest.raises(capa_video.VideoFalhou):
        capa_video.converter(falso)


@precisa_do_ffmpeg
def test_video_largo_vira_capa_animada_com_fundo_desfocado(tmp_path):
    capa = capa_video.converter(fazer_video(tmp_path / "largo.mp4", "320x180"))
    try:
        quadros, duracao = quadros_e_duracao(capa)
        assert quadros == 10
        assert duracao == pytest.approx(1000, abs=50)
        with Image.open(capa) as imagem:
            # O fundo é um degradê, sem os blocos chapados de ampliar um 2x2.
            linha = [imagem.convert("RGB").getpixel((x, 20)) for x in range(0, 600, 60)]
            assert len(set(linha)) > 4, linha
    finally:
        capa.unlink()


@precisa_do_ffmpeg
def test_so_o_comeco_do_video_vira_capa_a_no_maximo_30_quadros(tmp_path):
    capa = capa_video.converter(
        fazer_video(tmp_path / "longo.mp4", "64x96", segundos=capa_video.DURACAO_MAXIMA_S + 2, taxa=60)
    )
    try:
        quadros, duracao = quadros_e_duracao(capa)
        assert duracao == pytest.approx(capa_video.DURACAO_MAXIMA_S * 1000, abs=100)
        assert quadros <= capa_video.DURACAO_MAXIMA_S * capa_video.QUADROS_POR_SEGUNDO + 1
    finally:
        capa.unlink()


@precisa_do_ffmpeg
def test_as_copias_reduzidas_saem_junto_com_a_capa(tmp_path):
    tamanhos = [(200, 300), (420, 630)]

    def copias(capa):
        return [(capa.with_name(f"{capa.stem}_{l}x{a}.webp"), (l, a)) for l, a in tamanhos]

    capa = capa_video.converter(fazer_video(tmp_path / "largo.mp4", "320x180"), copias)
    reduzidas = [caminho for caminho, _tamanho in copias(capa)]
    try:
        for caminho, tamanho in zip(reduzidas, tamanhos):
            with Image.open(caminho) as imagem:
                assert imagem.is_animated and imagem.size == tamanho
        assert all(quadros_e_duracao(capa)[1] == _duracao(caminho) for caminho in reduzidas)
    finally:
        for caminho in (capa, *reduzidas):
            caminho.unlink(missing_ok=True)


def _duracao(caminho: Path) -> int:
    with Image.open(caminho) as imagem:
        total = 0
        for indice in range(imagem.n_frames):
            imagem.seek(indice)
            imagem.load()
            total += imagem.info.get("duration", 0)
        return total
