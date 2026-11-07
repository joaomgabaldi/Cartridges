# regras_do_big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Big Picture: as regras puras (quais jogos entram, quando abre sozinho, carrossel, fundo, tique)."""

from __future__ import annotations

import array
import functools
import io
import logging
import math
import random
import threading
import time
import wave
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import winsound

if TYPE_CHECKING:  # `ordem` e `shared` puxam o Qt: aqui só a tipagem, para o módulo ficar sem Qt nem gi
    from kyron.modelos.ordem import Linha

DURACAO_FILA_ENTRADA_MS = 1700
DURACAO_FILA_SAIDA_MS = 1100
JOGOS_NA_FILA = 30

# Calibração do Cover Flow. Distâncias em múltiplos da largura da capa, exceto a profundidade (px).
PERSPECTIVA = 900
ANGULO_LATERAL = 65
ESPACO_CENTRAL = 1.15  # do centro até a primeira lateral
ESPACO_LATERAL = 0.45  # entre laterais
PROFUNDIDADE_LATERAL = 220
CAPAS_DE_CADA_LADO = 8
DURACAO_PASSO_MS = 350
REFLEXO_ALCANCE = 0.72  # o reflexo some a esta fração da altura da capa
REFLEXO_OPACIDADE = 0.22

# Fundo: degradê vertical do topo à base, pontilhado em no máximo 1 tom.
FUNDO_TOPO = (28, 28, 30)  # #1c1c1e
FUNDO_EXPOENTE = 1.6
_BAYER_8 = (
    (0, 32, 8, 40, 2, 34, 10, 42),
    (48, 16, 56, 24, 50, 18, 58, 26),
    (12, 44, 4, 36, 14, 46, 6, 38),
    (60, 28, 52, 20, 62, 30, 54, 22),
    (3, 35, 11, 43, 1, 33, 9, 41),
    (51, 19, 59, 27, 49, 17, 57, 25),
    (15, 47, 7, 39, 13, 45, 5, 37),
    (63, 31, 55, 23, 61, 29, 53, 21),
)
_LIMIARES = tuple(tuple((v + 0.5) / 64 for v in linha) for linha in _BAYER_8)


def bytes_do_fundo(largura: int, altura: int) -> bytes:
    """O fundo em RGB de 8 bits (`largura·altura·3` bytes, linha a linha).

    Cada linha tem um valor exato por canal, arredondado pelos limiares da matriz Bayer 8×8 (nenhum pixel difere do exato em
    mais de 1 tom); a linha é montada com 8 pixels que se repetem.
    """
    repeticoes = -(-largura // 8)
    linhas = []
    for y in range(altura):
        k = (1 - y / (altura - 1)) ** FUNDO_EXPOENTE if altura > 1 else 1.0
        limiares = _LIMIARES[y % 8]
        exatos = [c * k for c in FUNDO_TOPO]
        base = [int(e) for e in exatos]
        fracao = [e - b for e, b in zip(exatos, base, strict=True)]
        padrao = bytes(b + (f > limiar) for limiar in limiares for b, f in zip(base, fracao, strict=True))
        linhas.append((padrao * repeticoes)[: largura * 3])
    return b"".join(linhas)


def jogos_da_biblioteca(linhas: Iterable[Linha]) -> list[Linha]:
    """Os jogos que aparecem na biblioteca, do jogado mais recentemente ao mais antigo.

    O `ModeloDaBiblioteca` já tira bloqueados e pendentes; sobram os desinstalados (ali por causa de Jogos Zerados).
    """
    visiveis = [linha for linha in linhas if not linha.removido]
    # Duas ordenações estáveis: nome crescente primeiro, depois jogado_em decrescente.
    visiveis.sort(key=lambda linha: linha.nome.casefold())
    visiveis.sort(key=lambda linha: linha.jogado_em, reverse=True)
    return visiveis


def pode_entrar_sozinho(
    *,
    preferencia: bool,
    controle_ligado: bool,
    tem_3d: bool,
    grade_a_vista: bool,
    ja_saiu: bool,
) -> bool:
    return preferencia and controle_ligado and tem_3d and grade_a_vista and not ja_saiu


def _limitar(x: float) -> float:
    return max(0.0, min(1.0, x))


def quadro_da_fila(t: float, n: float, base: float) -> tuple[float, float, float, float]:
    """(posição, virada, opacidade das capas, opacidade do rodapé) da fila no instante `t` (0 a 1)."""
    corrida = 1 - (1 - _limitar(t / 0.7)) ** 3  # ease_out_cubic
    x = _limitar((t - 0.65) / 0.35)
    c1 = 1.4
    # ease_out_back; a virada fica em 0 até `x` sair de 0
    virada = 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2 if x > 0 else 0.0
    return base + n * (1 - corrida), virada, min(1.0, 5 * t), _limitar((t - 0.8) / 0.2)


class Carrossel:
    """O jogo central do Cover Flow: um índice preso aos limites da lista de ids."""

    def __init__(self, ids: list[str]) -> None:
        self.ids = list(ids)
        self.indice = 0

    @property
    def atual(self) -> str | None:
        return self.ids[self.indice] if self.ids else None

    def ir_para(self, indice: int) -> bool:
        """Vai para o índice (preso a [0, len-1]); devolve se o índice mudou."""
        novo = max(0, min(indice, len(self.ids) - 1))
        mudou = novo != self.indice
        self.indice = novo
        return mudou

    def mover(self, delta: int) -> bool:
        return self.ir_para(self.indice + delta)

    def inicio(self) -> bool:
        return self.ir_para(0)

    def fim(self) -> bool:
        return self.ir_para(len(self.ids) - 1)

    def trocar_lista(self, ids: list[str], centro: str | None = None) -> None:
        """Troca a lista mantendo o jogo central (ou o `centro`, se dado)."""
        alvo = centro if centro is not None else self.atual
        self.ids = list(ids)
        if alvo in self.ids:
            self.indice = self.ids.index(alvo)
        else:
            self.indice = max(0, min(self.indice, len(self.ids) - 1))


INTERVALO_TIQUE_S = 0.07
# `data/` fica ao lado do pacote `kyron` (e do `_dist`, que copia a pasta inteira).
_ARQUIVO_DO_TIQUE = Path(__file__).resolve().parent.parent.parent / "data" / "sons" / "tique.wav"
_ultimo_tique = float("-inf")
_dados_tique: bytes | None = None


def _tocar_dados(dados: bytes) -> None:
    # SND_MEMORY não aceita SND_ASYNC: por isso a thread. SND_NODEFAULT: sem som padrão do Windows por cima do jogo.
    try:
        winsound.PlaySound(dados, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception:
        logging.warning("Falha ao tocar o tique do Big Picture", exc_info=True)


def tocar_tique(tocar=_tocar_dados) -> None:  # noqa: ANN001
    """Toca o tique de troca de capa, se ligado e passados 70 ms do anterior. Nunca levanta."""
    global _ultimo_tique, _dados_tique  # noqa: PLW0603
    try:
        from kyron import shared  # noqa: PLC0415

        if not shared.schema.get_boolean("big-picture-som"):
            return
        agora = time.monotonic()
        if agora - _ultimo_tique < INTERVALO_TIQUE_S:
            return
        if _dados_tique is None:
            try:
                _dados_tique = _ARQUIVO_DO_TIQUE.read_bytes()
            except OSError:
                _dados_tique = b""  # avisa uma vez só; sem o arquivo, o tique fica mudo
                raise
        if not _dados_tique:
            return
        _ultimo_tique = agora
        threading.Thread(target=tocar, args=(_dados_tique,), daemon=True).start()
    except Exception:
        logging.warning("Não foi possível tocar o tique do Big Picture", exc_info=True)


TAXA_DO_SOM = 44100
_AMOSTRAS_DO_FLIP = 352  # 8 ms


def instantes_da_fila(n: int, *, entrar: bool, passam: int | None = None) -> list[float]:
    """Quando (0 a 1 da duração da fila) cada capa cruza o centro, pela conta de `quadro_da_fila`.

    Na entrada a posição desce de `n` a 0 e cada capa chega em `k = n-1 … 0`; na saída a fila anima de 1 a 0, e a
    posição sobe da central até `n` à frente, cruzando `k = 1 … n`. Invertendo `n·(1-u)³ = k`: `t = 0,7·(1 - ∛(k/n))`.
    `passam`: na saída, quantas capas existem depois da central (o QML não desenha além do fim da lista).
    """
    if n <= 0:
        return []
    if entrar:
        return [0.7 * (1 - (k / n) ** (1 / 3)) for k in range(n - 1, -1, -1)]
    ultima = n if passam is None else min(n, passam)
    return [1 - 0.7 * (1 - (k / n) ** (1 / 3)) for k in range(1, ultima + 1)]


@functools.lru_cache(maxsize=64)
def wav_do_embaralhar(n: int, *, entrar: bool, passam: int | None = None) -> bytes:
    """O embaralhar da fila em WAV (PCM 16-bit mono): um estalo curto de ruído por capa, no instante em que ela passa."""
    duracao_ms = DURACAO_FILA_ENTRADA_MS if entrar else DURACAO_FILA_SAIDA_MS
    total = TAXA_DO_SOM * duracao_ms // 1000
    mistura = [0.0] * (total + _AMOSTRAS_DO_FLIP)  # folga: na saída o último flip cai no fim
    sorteio = random.Random(n * 2 + entrar)  # o mesmo som a cada vez, para a mesma fila
    for t in instantes_da_fila(n, entrar=entrar, passam=passam):
        inicio = int(t * total)
        ganho = sorteio.uniform(0.55, 1.0)
        queda = sorteio.uniform(40, 80)
        anterior = 0.0
        for i in range(_AMOSTRAS_DO_FLIP):
            ruido = sorteio.uniform(-1, 1)
            mistura[inicio + i] += ganho * math.exp(-i / queda) * (ruido - 0.45 * anterior)  # agudo: o papel da carta
            anterior = ruido
    amostras = array.array("h", (max(-32767, min(32767, int(v * 9000))) for v in mistura))
    saida = io.BytesIO()
    with wave.open(saida, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(TAXA_DO_SOM)
        w.writeframes(amostras.tobytes())
    return saida.getvalue()


def tocar_embaralhar(n: int, *, entrar: bool, passam: int | None = None, tocar=_tocar_dados) -> None:  # noqa: ANN001
    """Toca o embaralhar da fila de `n` capas, se o som do Big Picture estiver ligado. Nunca levanta."""

    def sintetizar_e_tocar() -> None:
        try:
            dados = wav_do_embaralhar(n, entrar=entrar, passam=passam)
        except Exception:
            logging.warning("Não foi possível montar o embaralhar do Big Picture", exc_info=True)
            return
        tocar(dados)

    try:
        from kyron import shared  # noqa: PLC0415

        if not instantes_da_fila(n, entrar=entrar, passam=passam) or not shared.schema.get_boolean("big-picture-som"):
            return
        threading.Thread(target=sintetizar_e_tocar, daemon=True).start()
    except Exception:
        logging.warning("Não foi possível tocar o embaralhar do Big Picture", exc_info=True)
