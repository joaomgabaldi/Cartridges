# session_history.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As regras puras do histórico de sessões de um jogo: data por extenso, períodos do gráfico, corte das pausas longas,
resumo dos últimos dias e a geometria do gráfico.
"""

import math
from bisect import bisect_left
from datetime import date, datetime, timedelta
from itertools import accumulate
from typing import Any

from cartridges.utils import session_log
from cartridges.utils.format_playtime import format_playtime
from cartridges.utils.relative_date import MONTHS


def format_session_date(timestamp: int) -> str:
    date = datetime.fromtimestamp(timestamp)
    return f"{date.day} de {MONTHS[date.month - 1].lower()} de {date.year}"


PERIODS = {"week": 7, "month": 30, "all": None}


def period_range(
    sessions: list[dict[str, Any]], period: str, today: date
) -> tuple[date, date]:
    """O primeiro e o último dia que o gráfico mostra para ``period``."""
    first = min(
        (max(0, entry["end"] - entry["seconds"]) for entry in sessions),
        default=None,
    )
    last = max(
        (max(0, entry["end"] - (1 if entry["seconds"] else 0)) for entry in sessions),
        default=None,
    )
    # Uma sessão "no futuro" (relógio adiantado, arquivo editado) não pode inverter a faixa nem passar de hoje.
    last_date = min(datetime.fromtimestamp(last).date(), today) if last is not None else today
    first_date = None
    if first is not None:
        first_date = min(datetime.fromtimestamp(first).date(), last_date)

    days = PERIODS[period]
    if days is None:
        return first_date or last_date, last_date

    start = last_date - timedelta(days=days - 1)
    return (max(start, first_date) if first_date else start), last_date


# Uma pausa de mais de duas semanas sem jogar vira uma quebra no gráfico de "Todo o período", em vez de um dia vazio por
# ponto: um ano parado seriam 365.
LACUNA_MAXIMA = 14


def sem_lacunas_longas(
    days: list[tuple[date, int]],
) -> tuple[list[tuple[date, int]], frozenset[int]]:
    """``days`` sem o miolo das pausas longas, e onde ficaram as quebras."""
    dias: list[tuple[date, int]] = []
    quebras: set[int] = set()
    i = 0
    while i < len(days):
        if days[i][1]:
            dias.append(days[i])
            i += 1
            continue
        fim = i
        while fim < len(days) and not days[fim][1]:
            fim += 1
        if fim - i > LACUNA_MAXIMA and i > 0 and fim < len(days):
            dias.append(days[i])
            quebras.add(len(dias) - 1)
            dias.append(days[fim - 1])
        else:
            dias.extend(days[i:fim])
        i = fim
    return dias, frozenset(quebras)


def nice_step(max_hours: float) -> float:
    for step in (0.25, 0.5, 1, 2, 3, 4, 6, 12, 24):
        if max_hours <= step * 4:
            return step
    return 24.0


def format_hours(hours: float) -> str:
    return f"{hours:g} h".replace(".", ",")


PAGINA = 100


def resumo_dos_ultimos_dias(sessions: list[dict[str, Any]], today: date) -> tuple[int, int]:
    """Segundos jogados nos últimos 7 e 30 dias de calendário, hoje incluído (o gráfico termina no último dia jogado).
    """

    def soma(dias: int) -> int:
        inicio = today - timedelta(days=dias - 1)
        return sum(s for _d, s in session_log.daily_seconds(sessions, inicio, today))

    return soma(7), soma(30)


def tempo_ou_nenhuma(seconds: int) -> str:
    return format_playtime(seconds) if seconds else _("nenhuma sessão")


# Quanto uma quebra (ver `sem_lacunas_longas`) ocupa no eixo X, em dias: o dobro de um intervalo comum, para a linha
# tracejada ter onde ficar.
LARGURA_DA_QUEBRA = 2


def _por_mes(dias: list[tuple[date, int]]) -> bool:
    return (dias[-1][0] - dias[0][0]).days > 60


def _rotulo_do_dia(dia: date, por_mes: bool) -> str:
    return f"{MONTHS[dia.month - 1][:3].lower()} {dia.year % 100:02d}" if por_mes else f"{dia.day:02d}/{dia.month:02d}"


def _sem_encostar(indices: list[int], posicoes: list[int], dias: list[tuple[date, int]]) -> list[int]:
    minimo = posicoes[-1] / 10
    ficam: list[int] = []
    for i in indices:
        if ficam and posicoes[i] - posicoes[ficam[-1]] < minimo:
            if dias[i][0].day == 1 and dias[ficam[-1]][0].day != 1:
                ficam[-1] = i
            continue
        ficam.append(i)
    return ficam


def _indices_rotulados(dias: list[tuple[date, int]], quebras: frozenset[int], posicoes: list[int]) -> list[int]:
    if _por_mes(dias):
        # O dia 1º pode ter caído no miolo de uma pausa cortada: aí o mês é rotulado no primeiro dia dele que sobrou
        # depois da quebra.
        inicios = [
            i
            for i, (dia, _s) in enumerate(dias)
            if dia.day == 1
            or (
                i - 1 in quebras
                and (dias[i - 1][0].year, dias[i - 1][0].month) != (dia.year, dia.month)
            )
        ]
        return _sem_encostar(inicios[:: max(1, math.ceil(len(inicios) / 6))], posicoes, dias)

    total = len(dias)
    cada = max(1, math.ceil(total / 6))
    rotulados = list(range(0, total, cada))
    if rotulados[-1] != total - 1:
        if total - 1 - rotulados[-1] < cada / 2 and len(rotulados) > 1:
            rotulados.pop()
        rotulados.append(total - 1)
    return rotulados


def geometria_do_grafico(dias: list[tuple[date, int]], quebras: frozenset[int]) -> dict[str, Any]:
    if not dias:
        return {}
    posicoes = list(
        accumulate(
            (LARGURA_DA_QUEBRA if i - 1 in quebras else 1 for i in range(1, len(dias))),
            initial=0,
        )
    )
    horas = [segundos / 3600 for _dia, segundos in dias]
    passo = nice_step(max(horas))
    topo = passo * max(1, math.ceil(max(horas) / passo))
    por_mes = _por_mes(dias)
    rotulos = []
    for indice in _indices_rotulados(dias, quebras, posicoes):
        if len(dias) == 1:
            alinhamento = 0.5
        else:
            alinhamento = 0.0 if indice == 0 else 1.0 if indice == len(dias) - 1 else 0.5
        rotulos.append([indice, _rotulo_do_dia(dias[indice][0], por_mes), alinhamento])
    return {
        "posicoes": posicoes,
        "horas": horas,
        "topo": topo,
        "passo": passo,
        "grade": [[passo * i, format_hours(passo * i)] for i in range(round(topo / passo) + 1)],
        "rotulos": rotulos,
        "quebras": sorted(quebras),
    }


def dia_mais_perto(posicoes: list[int], fracao: float) -> int:
    """O índice do dia mais perto de ``fracao`` (0 = borda esquerda do gráfico, 1 = direita): o inverso do eixo X."""
    ultimo = len(posicoes) - 1
    if ultimo <= 0:
        return 0
    posicao = fracao * posicoes[-1]
    depois = min(max(bisect_left(posicoes, posicao), 1), ultimo)
    antes = depois - 1
    meio = (posicoes[antes] + posicoes[depois]) / 2
    return antes if posicao < meio else depois
