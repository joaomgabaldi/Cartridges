# capa_video.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Capa a partir de um vídeo: o ffmpeg o converte num WebP animado do tamanho
das capas (``shared.image_size``), sem áudio.

Daí em diante é uma capa animada como as do SteamGridDB: ``save_cover`` a
guarda como está e ``copias_animadas`` gera as cópias da grade e dos detalhes.
O enquadramento é o das imagens escolhidas de um arquivo (``enquadramento``):
um vídeo largo vai inteiro no meio, sobre uma cópia esticada e borrada dele.

O ``ffmpeg.exe`` vai no instalador, ao lado do Python do app; fora dele (rodando
do código-fonte), vale o que estiver no PATH.
"""

import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable, Iterable, Optional

from PIL import Image, UnidentifiedImageError

from cartridges import shared
from cartridges.utils.enquadramento import escala_sobre_fundo

SUFIXOS = (".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi")

# Só o começo do vídeo vira capa: um WebP de minutos seria enorme e levaria
# minutos para codificar. 30 quadros por segundo é o que ``copias_animadas``
# mantém; um vídeo mais lento conserva a própria taxa.
DURACAO_MAXIMA_S = 15
QUADROS_POR_SEGUNDO = 30

# A conversão de 15 s leva uns 20 s num computador modesto; o limite só existe
# para um arquivo que trave o ffmpeg não deixar o diálogo carregando para sempre.
LIMITE_DE_TEMPO = 300


class VideoFalhou(Exception):
    """O vídeo não pôde virar capa. A mensagem vai para o usuário."""


def eh_video(caminho: Path) -> bool:
    return caminho.suffix.lower() in SUFIXOS


def executavel() -> Optional[Path]:
    exe = Path(sys.executable).parent / "ffmpeg.exe"
    if exe.is_file():
        return exe
    achado = shutil.which("ffmpeg")
    return Path(achado) if achado else None


# Pixel não quadrado (DVD, alguns celulares) vira quadrado antes de tudo, para o
# tamanho medido ser o que se vê. A rotação dos celulares o ffmpeg já aplica.
_PIXEL_QUADRADO = "scale=trunc(iw*sar/2)*2:ih,setsar=1"


def filtro(largura: int, altura: int, capa: tuple[int, int]) -> str:
    """O filtro do ffmpeg que leva quadros de ``largura`` x ``altura`` à capa."""
    largura_capa, altura_capa = capa
    inicio = f"{_PIXEL_QUADRADO},fps=fps='min(source_fps,{QUADROS_POR_SEGUNDO})',format=rgb24"
    escala = escala_sobre_fundo(largura, altura, capa)
    if escala is None:
        return f"{inicio},scale={largura_capa}:{altura_capa}:flags=bicubic"
    # O fundo de ``composite_cover`` é a imagem reduzida a 2x2 e ampliada de
    # volta com interpolação bilinear. O ``scale`` do ffmpeg não interpola a
    # partir de 2 pixels (sai em quatro blocos chapados), então o degradê vem de
    # um desfoque leve num 8x12 antes de ampliar: o mesmo resultado à vista.
    frente_l, frente_a = int(largura * escala), int(altura * escala)
    return (
        f"{inicio},split[origem][fundo_origem];"
        "[fundo_origem]scale=2:2:flags=area,scale=8:12:flags=neighbor,gblur=sigma=1.5,"
        f"scale={largura_capa}:{altura_capa}:flags=bicubic[fundo];"
        f"[origem]scale={frente_l}:{frente_a}:flags=bicubic[frente];"
        "[fundo][frente]overlay=(W-w)/2:(H-h)/2"
    )


def _rodar(argumentos: list[str]) -> bytes:
    exe = executavel()
    if exe is None:
        raise VideoFalhou(_("O ffmpeg não foi encontrado."))
    try:
        processo = subprocess.run(
            [str(exe), "-hide_banner", "-loglevel", "error", "-nostdin", *argumentos],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=LIMITE_DE_TEMPO,
            check=False,
        )
    except subprocess.TimeoutExpired as erro:
        raise VideoFalhou(_("A conversão do vídeo demorou demais e foi interrompida.")) from erro
    except OSError as erro:
        raise VideoFalhou(_("Não foi possível iniciar o ffmpeg.")) from erro
    if processo.returncode != 0:
        logging.warning(
            "ffmpeg saiu com o código %s: %s",
            processo.returncode,
            processo.stderr.decode(errors="replace").strip(),
        )
        raise VideoFalhou(_("O arquivo não pôde ser lido como vídeo."))
    return processo.stdout


def _tamanho(video: Path) -> tuple[int, int]:
    """Largura e altura do primeiro quadro, já com rotação e pixel quadrado."""
    png = _rodar(
        ["-i", str(video), "-map", "0:v:0", "-frames:v", "1", "-vf", _PIXEL_QUADRADO,
         "-f", "image2pipe", "-c:v", "png", "-"]
    )  # fmt: skip
    try:
        with Image.open(io.BytesIO(png)) as quadro:
            return quadro.size
    except (UnidentifiedImageError, OSError) as erro:
        raise VideoFalhou(_("O arquivo não pôde ser lido como vídeo.")) from erro


# Onde gravar as cópias reduzidas de uma capa e em que tamanho: o
# ``copias_animadas.caminho_para`` de cada ``copias_animadas.tamanhos()``.
# Chega por parâmetro para este módulo não depender do GTK.
Copias = Callable[[Path], Iterable[tuple[Path, tuple[int, int]]]]


def _saida_webp(rotulo: str, destino: Path, qualidade: int) -> list[str]:
    # Com perda, como as capas animadas do SteamGridDB; o nível 2 de compressão
    # custa ~10% a mais de arquivo que o 4 e codifica ~25% mais rápido, e é a
    # codificação que domina o tempo da conversão.
    return ["-map", f"[{rotulo}]", "-c:v", "libwebp_anim", "-lossless", "0",
            "-quality", str(qualidade), "-compression_level", "2", "-loop", "0",
            "-f", "webp", str(destino)]  # fmt: skip


def converter(video: Path, copias: Copias = lambda _capa: ()) -> Path:
    """Um WebP animado, em %TEMP%, com o começo de ``video`` como capa.

    As cópias reduzidas que ``copias`` pedir saem do mesmo ffmpeg, ao lado da
    capa: a prévia da edição toca assim que a capa aparece, em vez de esperar a
    geração delas pelo Pillow (dezenas de segundos para centenas de quadros), e
    o Aplicar as reaproveita (``copias_animadas.adotar``).

    Roda fora da thread principal: o ffmpeg leva segundos. Levanta
    ``VideoFalhou`` com uma mensagem para o usuário.
    """
    largura, altura = _tamanho(video)
    descritor, nome = tempfile.mkstemp(suffix=".webp")
    os.close(descritor)
    destino = Path(nome)
    reduzidas = list(copias(destino))
    # Um ramo do filtro por saída: a capa e cada cópia, reduzida da capa com o
    # mesmo Lanczos de ``copias_animadas``.
    grafo = f"[0:v:0]{filtro(largura, altura, shared.image_size)},split={1 + len(reduzidas)}[capa]"
    grafo += "".join(f"[r{indice}]" for indice in range(len(reduzidas)))
    saidas = _saida_webp("capa", destino, 85)
    for indice, (caminho, (largura_copia, altura_copia)) in enumerate(reduzidas):
        grafo += f";[r{indice}]scale={largura_copia}:{altura_copia}:flags=lanczos[c{indice}]"
        # A mesma qualidade das cópias do Pillow
        saidas += _saida_webp(f"c{indice}", caminho, 90)
    try:
        _rodar(
            ["-y", "-t", str(DURACAO_MAXIMA_S), "-i", str(video),
             "-filter_complex", grafo, *saidas]
        )  # fmt: skip
        if destino.stat().st_size == 0:
            raise VideoFalhou(_("O arquivo não pôde ser lido como vídeo."))
    except BaseException:
        destino.unlink(missing_ok=True)
        for caminho, _tamanho_copia in reduzidas:
            caminho.unlink(missing_ok=True)
        raise
    return destino
