# calibracao.py
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

"""A correção de cor de cada dispositivo, ajustada no assistente de calibração.

O firmware de cada fita reproduz as cores do seu jeito: o "vermelho" que o
app manda pode sair arroxeado. A calibração guarda, para seis cores de
referência, quanto o tom anda e quanto a intensidade muda, e as cores entre
elas usam a mistura proporcional das duas vizinhas. O branco tem um ajuste
próprio, que pesa mais quanto mais pálida for a cor.

Só contas: nada de tela nem de rede. As cores chegam e saem como a ``Cor`` de
``session_fita`` (matiz 0–359, saturação e brilho 0–1000); o brilho nunca muda.
"""

import math
from typing import Any, NamedTuple

# As cores de referência, uma por etapa do assistente.
REFERENCIAS = (0, 60, 120, 180, 240, 300)

# Os limites dos controles do assistente.
TOM_MAXIMO = 30
FATOR_MINIMO = 0.5
FATOR_MAXIMO = 1.5
SATURACAO_DO_BRANCO = 300

# Até onde o ajuste do branco alcança: cor com saturação 0 recebe o ajuste
# inteiro, e a partir de 40% não recebe nada — uma cor viva não tem branco.
FAIXA_DO_BRANCO = 400

# Os tons de branco nas pontas da Temperatura.
MATIZ_QUENTE = 30
MATIZ_FRIO = 210


class Calibracao(NamedTuple):
    """``cores``: seis pares (deslocamento de tom em graus, fator de
    intensidade), um por ``REFERENCIAS``. ``branco``: matiz e saturação do tom
    de branco (saturação 0 = branco neutro)."""

    cores: tuple[tuple[int, float], ...]
    branco: tuple[int, int]


NEUTRA = Calibracao(((0, 1.0),) * len(REFERENCIAS), (0, 0))


def corrigir(cor: Any, calibracao: Calibracao) -> Any:
    """A cor que a fita deve receber para mostrar ``cor``."""
    matiz, saturacao = cor.matiz, cor.saturacao

    # Tom e intensidade: a mistura das duas referências vizinhas.
    indice = int(matiz // 60) % 6
    andado = (matiz - REFERENCIAS[indice]) / 60
    tom_a, fator_a = calibracao.cores[indice]
    tom_b, fator_b = calibracao.cores[(indice + 1) % 6]
    tom = tom_a + (tom_b - tom_a) * andado
    fator = fator_a + (fator_b - fator_a) * andado
    matiz = (matiz + tom) % 360
    saturacao = min(1000.0, saturacao * fator)

    # Branco: a cor e o tom do branco como vetores no círculo de cores; a cor
    # pálida ganha o vetor do branco quase inteiro, a viva não ganha nada.
    peso = max(0.0, 1 - saturacao / FAIXA_DO_BRANCO)
    matiz_b, saturacao_b = calibracao.branco
    if peso and saturacao_b:
        x = saturacao * math.cos(math.radians(matiz)) + peso * saturacao_b * math.cos(
            math.radians(matiz_b)
        )
        y = saturacao * math.sin(math.radians(matiz)) + peso * saturacao_b * math.sin(
            math.radians(matiz_b)
        )
        saturacao = min(1000.0, math.hypot(x, y))
        matiz = math.degrees(math.atan2(y, x)) % 360

    return cor._replace(matiz=round(matiz) % 360, saturacao=round(saturacao))


def _limitar(valor: float, minimo: float, maximo: float) -> float:
    return max(minimo, min(maximo, valor))


def de_json(dados: Any) -> Calibracao:
    """A calibração gravada no ``fitas.json``. Arquivo mexido à mão (tipo
    errado, lista curta) vale como neutra, e número fora dos limites é
    trazido para dentro deles: isto roda em toda troca de cor."""
    try:
        cores = tuple(
            (
                round(_limitar(float(tom), -TOM_MAXIMO, TOM_MAXIMO)),
                _limitar(float(fator), FATOR_MINIMO, FATOR_MAXIMO),
            )
            for tom, fator in dados["cores"]
        )
        matiz_b, saturacao_b = dados["branco"]
        branco = (
            round(float(matiz_b)) % 360,
            round(_limitar(float(saturacao_b), 0, SATURACAO_DO_BRANCO)),
        )
    except (KeyError, TypeError, ValueError):
        return NEUTRA
    if len(cores) != len(REFERENCIAS):
        return NEUTRA
    return Calibracao(cores, branco)


def para_json(calibracao: Calibracao) -> dict[str, Any]:
    return {
        "cores": [[tom, fator] for tom, fator in calibracao.cores],
        "branco": list(calibracao.branco),
    }


def branco_da_temperatura(temperatura: float) -> tuple[int, int]:
    """O tom de branco de uma posição da Temperatura: −1 o mais quente, 0
    neutro, +1 o mais frio."""
    temperatura = _limitar(temperatura, -1, 1)
    matiz = MATIZ_QUENTE if temperatura < 0 else MATIZ_FRIO
    return matiz, round(abs(temperatura) * SATURACAO_DO_BRANCO)


def temperatura_do_branco(branco: tuple[int, int]) -> float:
    """O caminho de volta, para o controle mostrar a posição gravada."""
    matiz, saturacao = branco
    distancia_do_frio = abs((matiz - MATIZ_FRIO + 180) % 360 - 180)
    sinal = 1 if distancia_do_frio < 90 else -1
    return sinal * saturacao / SATURACAO_DO_BRANCO
