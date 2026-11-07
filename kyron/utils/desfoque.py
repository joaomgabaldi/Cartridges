# desfoque.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os fundos desfocados da página de detalhes e do Big Picture: só Pillow e bytes, para rodar numa thread."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageStat

# Luminância de quando não há capa legível (a página usa o fundo de reserva).
LUMINANCIA_RESERVA = 0.3
# O Big Picture ocupa a tela inteira: o desfoque da página vira uma média cinza, então o dele borra menos e satura.
RAIO_DO_FUNDO_VIVO = 6
SATURACAO_DO_FUNDO_VIVO = 1.8
# De 0 a 255. Capa clara demais ofuscaria o logo branco e o texto.
BRILHO_MAXIMO_DO_FUNDO_VIVO = 80


@dataclass(frozen=True)
class Desfoque:
    png: bytes
    # Ver `opacidade_do_fundo`.
    luminancia: float
    png_vivo: bytes


def _fundo_vivo(imagem: Image.Image) -> bytes:
    """A capa em 100x150 com as manchas de cor à vista, sem passar de `BRILHO_MAXIMO_DO_FUNDO_VIVO`."""
    vivo = ImageEnhance.Color(imagem.filter(ImageFilter.GaussianBlur(RAIO_DO_FUNDO_VIVO))).enhance(SATURACAO_DO_FUNDO_VIVO)
    brilho = ImageStat.Stat(vivo.convert("L")).mean[0]
    if brilho > BRILHO_MAXIMO_DO_FUNDO_VIVO:
        vivo = ImageEnhance.Brightness(vivo).enhance(BRILHO_MAXIMO_DO_FUNDO_VIVO / brilho)
    saida = BytesIO()
    vivo.save(saida, "png")
    return saida.getvalue()


def calcular(caminho: Path | None) -> Desfoque | None:
    """A capa em 100x150 borrada, em PNG, e a luminância dela. `None` sem capa ou ilegível."""
    if not caminho:
        return None
    try:
        with Image.open(caminho) as imagem:
            pequena = imagem.convert("RGB").resize((100, 150))
            imagem = pequena.filter(ImageFilter.GaussianBlur(20))
            saida = BytesIO()
            imagem.save(saida, "png")
            estatistica = ImageStat.Stat(imagem.convert("L"))
            return Desfoque(
                saida.getvalue(),
                min((estatistica.mean[0] + estatistica.extrema[0][0]) / 510, 0.7),
                _fundo_vivo(pequena),
            )
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
