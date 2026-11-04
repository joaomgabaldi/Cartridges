# cor_da_capa.py
#
# Copyright 2026 joaomgabaldi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A cor que resume uma imagem (a capa ou a tela do jogo), para vestir as fitas de LED.

Dominante não é a que ocupa mais pixels (costuma ser o preto do fundo): vence a mais viva entre as
frequentes (frequência vezes saturação); cinzas, pretos e brancos não entram. Só matiz e saturação saem
daqui; o brilho é do usuário.
"""

import colorsys
import logging
from pathlib import Path
from typing import Optional

from PIL import Image

# Abaixo disto a cor é cinza (pouca saturação) ou quase preta (pouco valor).
MIN_SATURACAO = 0.25
MIN_VALOR = 0.15

# 64x64 e oito cores bastam para separar o fundo do que salta aos olhos.
AMOSTRA = (64, 64)
CORES = 8


def dominante(capa: Path) -> Optional[tuple[int, int]]:
    """Matiz (0–359) e saturação (0–1000) da capa, ou ``None`` sem cor útil. Nunca levanta (thread de UI)."""
    try:
        with Image.open(capa) as imagem:
            return dominante_da_imagem(imagem)
    # Captura larga de propósito: o Pillow reclama de cada defeito de um jeito (``DecompressionBombError`` nem é ``OSError``).
    except Exception as erro:
        logging.info("Capa sem cor legível (%s): %s", capa.name, erro)
        return None


def dominante_da_imagem(
    imagem: Image.Image, cores: int = CORES, min_valor: float = MIN_VALOR
) -> Optional[tuple[int, int]]:
    """A conta de ``dominante`` para uma imagem já aberta (o print da tela do jogo).

    A tela pede mais cores e um valor mínimo menor que a capa, para o amarelo forte não se fundir ao branco vizinho.
    """
    amostra = imagem.convert("RGB").resize(AMOSTRA)
    paleta = amostra.quantize(colors=cores, method=Image.Quantize.FASTOCTREE)
    contagens = paleta.convert("RGB").getcolors(AMOSTRA[0] * AMOSTRA[1]) or []

    melhor: Optional[tuple[float, float]] = None
    melhor_peso = 0.0
    for quantidade, (vermelho, verde, azul) in contagens:
        matiz, saturacao, valor = colorsys.rgb_to_hsv(
            vermelho / 255, verde / 255, azul / 255
        )
        if saturacao < MIN_SATURACAO or valor < min_valor:
            continue
        peso = quantidade * saturacao
        if peso > melhor_peso:
            melhor, melhor_peso = (matiz, saturacao), peso

    if melhor is None:
        return None
    return round(melhor[0] * 360) % 360, round(melhor[1] * 1000)
