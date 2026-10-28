# desfoque.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O fundo desfocado da página de detalhes: só Pillow e bytes, para rodar numa thread."""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

# Luminância de quando não há capa legível (a página usa o fundo de reserva).
LUMINANCIA_RESERVA = (0.3, 0.5)


@dataclass(frozen=True)
class Desfoque:
    png: bytes
    # (para o tema escuro, para o claro): ver `opacidade_do_fundo`.
    luminancia: tuple[float, float]


def calcular(caminho: Path | None) -> Desfoque | None:
    """A capa em 100x150 borrada, em PNG, e a luminância dela. `None` sem capa ou ilegível."""
    if not caminho:
        return None
    try:
        with Image.open(caminho) as imagem:
            imagem = imagem.convert("RGB").resize((100, 150)).filter(ImageFilter.GaussianBlur(20))
            saida = BytesIO()
            imagem.save(saida, "png")
            estatistica = ImageStat.Stat(imagem.convert("L"))
            return Desfoque(
                saida.getvalue(),
                (
                    min((estatistica.mean[0] + estatistica.extrema[0][0]) / 510, 0.7),
                    max((estatistica.mean[0] + estatistica.extrema[0][1]) / 510, 0.3),
                ),
            )
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
