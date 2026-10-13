# enquadramento.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Como uma imagem (ou um vídeo) escolhida de um arquivo vira o retrato da capa.

Mais alta que a capa, ou mais larga em até ``MAX_STRETCH``, ela é só esticada.
Mais larga que isso, vai inteira no meio, sobre uma cópia esticada e borrada
dela mesma. A regra mora aqui, sem GTK, porque a capa de imagem
(``save_cover.composite_cover``) e a de vídeo (``capa_video``) a seguem igual.
"""

from typing import Optional

# Quanto um esticão pode distorcer a imagem antes de ela ganhar o fundo borrado.
MAX_STRETCH = 0.12


def escala_sobre_fundo(largura: float, altura: float, capa: tuple[int, int]) -> Optional[float]:
    """A escala da imagem inteira sobre o fundo borrado, ou None se basta esticá-la."""
    largura_capa, altura_capa = capa
    mais_alta = largura / altura < largura_capa / altura_capa
    if mais_alta or 1 - (altura / largura * largura_capa) / altura_capa <= MAX_STRETCH:
        return None
    return min(largura_capa / largura, altura_capa / altura)
