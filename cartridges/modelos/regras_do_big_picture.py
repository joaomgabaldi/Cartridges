# regras_do_big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Big Picture: as regras puras (quais jogos entram, quando abre sozinho, carrossel, fundo, tique)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import winsound

if TYPE_CHECKING:  # `ordem` e `shared` puxam o Qt: aqui só a tipagem, para o módulo ficar sem Qt nem gi
    from cartridges.modelos.ordem import Linha

DURACAO_ABERTURA_MS = 400
DURACAO_FILA_ENTRADA_MS = 1700
DURACAO_FILA_SAIDA_MS = 1100
JOGOS_NA_FILA = 30

# Calibração do Cover Flow.
PERSPECTIVA = 900
ANGULO_LATERAL = 65
ESPACO_CENTRAL = 1.15
ESPACO_LATERAL = 0.45
PROFUNDIDADE_LATERAL = 220
CAPAS_DE_CADA_LADO = 8
DURACAO_PASSO_MS = 350
ESCALA_NA_ABERTURA = 1.6
REFLEXO_ALCANCE = 0.55
REFLEXO_OPACIDADE = 0.35

FUNDO_TOPO = (28, 28, 30)
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
    """O fundo em RGB de 8 bits (`largura·altura·3` bytes, linha a linha)."""
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
    visiveis = [linha for linha in linhas if not linha.removido]
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
    corrida = 1 - (1 - _limitar(t / 0.7)) ** 3
    x = _limitar((t - 0.65) / 0.35)
    c1 = 1.4
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
        alvo = centro if centro is not None else self.atual
        self.ids = list(ids)
        if alvo in self.ids:
            self.indice = self.ids.index(alvo)
        else:
            self.indice = max(0, min(self.indice, len(self.ids) - 1))


INTERVALO_TIQUE_S = 0.07
_ARQUIVO_DO_TIQUE = Path(__file__).resolve().parent.parent.parent / "data" / "sons" / "tique.wav"
_ultimo_tique = float("-inf")
_dados_tique: bytes | None = None


def _tocar_dados(dados: bytes) -> None:
    # SND_MEMORY não aceita SND_ASYNC: por isso a thread.
    try:
        winsound.PlaySound(dados, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception:
        logging.warning("Falha ao tocar o tique do Big Picture", exc_info=True)


def tocar_tique(tocar=_tocar_dados) -> None:  # noqa: ANN001
    """Toca o tique de troca de capa, se ligado e passados 70 ms do anterior."""
    global _ultimo_tique, _dados_tique  # noqa: PLW0603
    try:
        from cartridges import shared  # noqa: PLC0415

        if not shared.schema.get_boolean("big-picture-som"):
            return
        agora = time.monotonic()
        if agora - _ultimo_tique < INTERVALO_TIQUE_S:
            return
        if _dados_tique is None:
            try:
                _dados_tique = _ARQUIVO_DO_TIQUE.read_bytes()
            except OSError:
                _dados_tique = b""
                raise
        if not _dados_tique:
            return
        _ultimo_tique = agora
        threading.Thread(target=tocar, args=(_dados_tique,), daemon=True).start()
    except Exception:
        logging.warning("Não foi possível tocar o tique do Big Picture", exc_info=True)
