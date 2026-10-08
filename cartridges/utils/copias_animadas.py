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

import contextlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from PIL import Image, ImageSequence

from cartridges import shared
from cartridges.utils.na_tela import entregar_na_tela

# Como terminou um pedido. ``ilegivel`` é só a origem que não abre; ``falhou``
# é a cópia que não pôde ser gravada (disco cheio, permissão negada): nada foi
# gravado, a capa segue animada e o pedido pode ser repetido depois.
Resultado = Literal["pronta", "estatica", "ilegivel", "falhou"]

# Abaixo disto o quadro é fundido ao anterior: nenhuma tela mostra mais de
# ~30 quadros por segundo, e os quadros a mais só custariam decodificação.
QUADRO_MINIMO_MS = 30


class GravacaoFalhou(Exception):
    """Não foi possível gravar a cópia em ``destino``.

    Não herda de ``OSError`` de propósito: a origem ilegível sobe como
    ``OSError``, e quem chama precisa distinguir as duas falhas.
    """


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
    capa mudou ou o app fechou no meio da geração (``vigente`` é consultada a
    cada quadro lido e antes da troca final). Se a origem não abre, o erro de leitura
    (``OSError``, ``ValueError``, ``Image.DecompressionBombError``) sobe para
    quem chamou decidir o que mostrar. Se é a gravação que falha, sobe
    ``GravacaoFalhou``, sem deixar ``.tmp`` para trás.

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
            # Uma capa com centenas de quadros leva segundos: se a capa mudou
            # ou o app está fechando, para já em vez de ler o resto.
            if not vigente():
                return False
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

    # Grava ao lado e troca de nome no fim: quem vê o destino nunca pega uma
    # cópia pela metade. O nome leva um sufixo único porque, quando a capa
    # troca, o trabalho velho e o novo podem gravar o mesmo destino juntos.
    temporario = destino.with_name(f"{destino.name}.{uuid4().hex}.tmp")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        quadros[0].save(
            temporario, "WEBP", save_all=True, append_images=quadros[1:],
            duration=duracoes, loop=0, quality=90, method=4,
        )  # fmt: skip
        # A checagem e a troca formam um passo só em relação ao ``apagar``,
        # que invalida e apaga com a mesma trava: o rename cai antes da
        # invalidação (e o glob do ``apagar`` o remove) ou depois (e é pulado).
        # Sem isto a cópia da capa velha podia aparecer depois da troca.
        # ``vigente`` não pode pegar a trava, ou travaria aqui.
        with _trava:
            if not vigente():
                return False
            temporario.replace(destino)
        return True
    except OSError as erro:
        raise GravacaoFalhou(destino) from erro
    finally:
        with contextlib.suppress(OSError):
            temporario.unlink(missing_ok=True)


@dataclass
class _Trabalho:
    chave: str  # game_id: o que ``apagar`` usa para invalidar
    prontos: list[Callable[[Resultado], None]] = field(default_factory=list)
    iniciado: bool = False
    # Vira True quando a capa muda ou o pedido é cancelado; o trabalho que já
    # rodava vê isso em ``vigente`` e descarta o resultado.
    invalido: bool = False


# Trocado pelos testes. Dois trabalhos por vez: cada um segura todos os quadros
# de uma capa em memória.
_executor = ThreadPoolExecutor(max_workers=2)
# Guarda ``_trabalhos`` e os campos de cada ``_Trabalho``. ``gerar`` a pega só
# na checagem final e no rename; nunca durante a geração nem num ``pronto``.
_trava = threading.Lock()
_trabalhos: dict[Path, _Trabalho] = {}  # destino -> trabalho pendente ou rodando


def pedir(
    origem: Path,
    destino: Path,
    tamanho: tuple[int, int],
    pronto: Callable[[Resultado], None],
) -> None:
    """Gera a cópia em segundo plano e avisa ``pronto`` na thread principal.

    Pedido repetido para o mesmo ``destino``, com o trabalho ainda pendente ou
    rodando, só acrescenta o ``pronto``. Se a capa muda (``apagar``) ou o pedido
    é cancelado antes do fim, ``pronto`` não é chamado: quem trocou a capa
    pede de novo.
    """
    with _trava:
        trabalho = _trabalhos.get(destino)
        if trabalho is not None:
            trabalho.prontos.append(pronto)
            return
        trabalho = _trabalhos[destino] = _Trabalho(origem.stem, [pronto])
    _executor.submit(lambda: _rodar(trabalho, origem, destino, tamanho))


def _rodar(
    trabalho: _Trabalho, origem: Path, destino: Path, tamanho: tuple[int, int]
) -> None:
    with _trava:
        if trabalho.invalido:
            return
        trabalho.iniciado = True
    resultado: Resultado | None = None
    try:
        gravada = gerar(
            origem, destino, tamanho, vigente=lambda: not trabalho.invalido
        )
        resultado = "pronta" if gravada else "estatica"
    except GravacaoFalhou:
        logging.warning("Não foi possível gravar a cópia animada de %s", origem.name)
        resultado = "falhou"
    except (OSError, ValueError, Image.DecompressionBombError):
        logging.warning("Não foi possível ler a capa animada %s", origem.name)
        resultado = "ilegivel"
    finally:
        with _trava:
            if _trabalhos.get(destino) is trabalho:
                del _trabalhos[destino]
            prontos = list(trabalho.prontos)
            descartado = trabalho.invalido
    if resultado is None or descartado:
        return
    for pronto in prontos:
        entregar_na_tela(_entregar, pronto, resultado)


def _entregar(pronto: Callable[[Resultado], None], resultado: Resultado) -> bool:
    pronto(resultado)
    return False  # o GLib repetiria o callback que devolvesse um valor verdadeiro


def apagar(game_id: str) -> None:
    """Apaga as cópias do jogo e invalida os trabalhos dele, pendentes ou não."""
    with _trava:
        for destino, trabalho in list(_trabalhos.items()):
            if trabalho.chave == game_id:
                trabalho.invalido = True
                # Fora do dicionário: um pedido novo para este destino (a capa
                # nova) não pode herdar um trabalho que vai descartar o resultado.
                del _trabalhos[destino]
    for arquivo in shared.capas_animadas_dir.glob(f"{game_id}_*.webp"):
        try:
            arquivo.unlink(missing_ok=True)
        except OSError:
            logging.warning("Não foi possível apagar a cópia animada %s", arquivo.name)


def encerrar() -> None:
    """Invalida todos os trabalhos, pendentes e em andamento. Para fechar o app.

    O executor não é daemon: sem isto o interpretador esperaria a geração em
    curso (segundos numa capa grande) e todo trabalho ainda na fila. Os
    pendentes saem sem gerar e os em andamento param no próximo quadro.
    """
    with _trava:
        for trabalho in _trabalhos.values():
            trabalho.invalido = True
        _trabalhos.clear()


def cancelar_pendentes() -> None:
    """Descarta o que ainda não começou; o que já roda segue até o fim."""
    with _trava:
        for destino, trabalho in list(_trabalhos.items()):
            if not trabalho.iniciado:
                trabalho.invalido = True
                del _trabalhos[destino]
