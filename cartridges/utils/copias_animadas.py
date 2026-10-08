# copias_animadas.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Cópias reduzidas das capas animadas, no tamanho em que são exibidas.

Tocar o GIF/WebP original na biblioteca decodificaria e redimensionaria
centenas de quadros grandes a cada volta. A cópia já sai no tamanho da tela e
com os quadros curtos fundidos, então o player só decodifica o que mostra.
"""

from pathlib import Path
from typing import Callable

from PIL import Image, ImageSequence

from cartridges import shared

# Abaixo disto o quadro é fundido ao anterior: nenhuma tela mostra mais de
# ~30 quadros por segundo, e os quadros a mais só custariam decodificação.
QUADRO_MINIMO_MS = 30


def tamanhos() -> tuple[tuple[int, int], tuple[int, int]]:
    """(grade, detalhes): os dois tamanhos em que a capa é exibida."""
    return (
        (int(shared.display_size[0]), int(shared.display_size[1])),
        (int(shared.details_size[0]), int(shared.details_size[1])),
    )


def caminho_para(origem: Path, tamanho: tuple[int, int]) -> Path:
    """Onde fica a cópia de ``origem`` no ``tamanho`` pedido.

    As capas da biblioteca vão para o cache do app. As prévias dos seletores
    moram numa pasta temporária que o próprio seletor limpa: a cópia fica ao
    lado delas e some junto. O tamanho no nome faz uma mudança de escala gerar
    cópias novas, sem confundir com as do tamanho anterior.
    """
    nome = f"{origem.stem}_{tamanho[0]}x{tamanho[1]}.webp"
    if origem.parent == shared.covers_dir:
        return shared.capas_animadas_dir / nome
    return origem.with_name(nome)


def gerar(
    origem: Path,
    destino: Path,
    tamanho: tuple[int, int],
    vigente: Callable[[], bool] = lambda: True,
) -> bool:
    """Grava em ``destino`` a cópia de ``origem`` reduzida a ``tamanho``.

    Devolve False, sem gravar nada, se a origem não é animada (menos de 2
    quadros, contados depois da fusão) ou se ``vigente()`` diz, no fim, que a
    capa mudou no meio da geração. Se a origem não abre, o erro de leitura
    (``OSError``, ``ValueError``, ``Image.DecompressionBombError``) sobe para
    quem chamou decidir o que mostrar.

    A fusão acima depende só da origem, mas o libwebp também funde quadros
    repetidos ou quase iguais ao gravar, e com perda isso depende dos pixels,
    ou seja, do tamanho. A contagem de quadros das cópias da grade e dos
    detalhes pode divergir; a duração total, que a fusão preserva, não. Quem
    troca de uma cópia para a outra continua pelo tempo, não pelo quadro.
    """
    quadros: list[Image.Image] = []
    duracoes: list[int] = []
    # ponytail: todos os quadros reduzidos ficam em RAM até o save (pico de
    # ~216 MB na capa de 901 quadros, uma vez por capa); o Pillow só grava WebP
    # animado a partir de uma lista. Alimentar o _webp.WebPAnimEncoder direto,
    # um quadro por vez, se o pico incomodar.
    with Image.open(origem) as imagem:
        for quadro in ImageSequence.Iterator(imagem):
            # No WebP o Pillow só preenche info["duration"] ao decodificar o
            # quadro; lida antes, sai vazia e todo quadro valeria 100 ms.
            quadro.load()
            duracao = int(quadro.info.get("duration", 100)) or 100
            if duracoes and duracoes[-1] < QUADRO_MINIMO_MS:
                duracoes[-1] += duracao
                continue
            quadros.append(quadro.convert("RGBA").resize(tamanho, Image.LANCZOS))
            duracoes.append(duracao)
    if len(quadros) < 2:
        return False

    destino.parent.mkdir(parents=True, exist_ok=True)
    # Grava ao lado e troca de nome no fim: quem vê o destino nunca pega uma
    # cópia pela metade.
    temporario = destino.with_name(destino.name + ".tmp")
    quadros[0].save(
        temporario, "WEBP", save_all=True, append_images=quadros[1:],
        duration=duracoes, loop=0, quality=90, method=4,
    )  # fmt: skip
    if not vigente():
        temporario.unlink(missing_ok=True)
        return False
    temporario.replace(destino)
    return True
