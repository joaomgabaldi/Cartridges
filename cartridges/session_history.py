# session_history.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As regras puras do histórico de sessões de um jogo: data por extenso, períodos do gráfico, corte das pausas longas,
resumo dos últimos dias e a geometria do gráfico. O modelo (`modelos/historico.py`) as entrega ao QML, que só
desenha.
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
    """"12 de agosto de 2026" — a data por extenso, em pt-BR.

    Datas absolutas, e não "Hoje"/"Ontem" como no resto do aplicativo: a lista existe para ser lida de cima a baixo, e
    misturar "Terça-feira" com "3 de maio" não deixa comparar linhas.
    """
    date = datetime.fromtimestamp(timestamp)
    return f"{date.day} de {MONTHS[date.month - 1].lower()} de {date.year}"


# Nome do período no seletor → quantos dias ele cobre; None é "desde a
# primeira sessão".
PERIODS = {"week": 7, "month": 30, "all": None}


def period_range(
    sessions: list[dict[str, Any]], period: str, today: date
) -> tuple[date, date]:
    """O primeiro e o último dia que o gráfico mostra para ``period``.

    Termina no último dia com sessão, não hoje: depois dele só há dias vazios, que empurrariam o jogado para um canto.
    "Semana" e "Mês" são a última semana e o último mês com sessões. O início nunca é anterior à primeira sessão.
    """
    first = min(
        (max(0, entry["end"] - entry["seconds"]) for entry in sessions),
        default=None,
    )
    # O dia do último segundo jogado: uma sessão que termina à meia-noite em
    # ponto não abre um dia vazio a mais.
    last = max(
        (max(0, entry["end"] - (1 if entry["seconds"] else 0)) for entry in sessions),
        default=None,
    )
    # Uma sessão "no futuro" (relógio adiantado, arquivo editado) não pode
    # inverter a faixa nem passar de hoje.
    last_date = min(datetime.fromtimestamp(last).date(), today) if last is not None else today
    first_date = None
    if first is not None:
        first_date = min(datetime.fromtimestamp(first).date(), last_date)

    days = PERIODS[period]
    if days is None:
        return first_date or last_date, last_date

    start = last_date - timedelta(days=days - 1)
    return (max(start, first_date) if first_date else start), last_date


# Uma pausa de mais de duas semanas sem jogar vira uma quebra no gráfico de
# "Todo o período", em vez de um dia vazio por ponto: um ano parado seriam 365.
LACUNA_MAXIMA = 14


def sem_lacunas_longas(
    days: list[tuple[date, int]],
) -> tuple[list[tuple[date, int]], frozenset[int]]:
    """``days`` sem o miolo das pausas longas, e onde ficaram as quebras.

    De cada sequência de mais de ``LACUNA_MAXIMA`` dias vazios ficam só o primeiro e o último, para a linha descer a
    zero dos dois lados; a quebra ``i`` fica entre ``dias[i]`` e ``dias[i + 1]``.
    """
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
    """O intervalo das linhas de grade: o menor que deixa no máximo 4 delas."""
    for step in (0.25, 0.5, 1, 2, 3, 4, 6, 12, 24):
        if max_hours <= step * 4:
            return step
    return 24.0


def format_hours(hours: float) -> str:
    """"1,5 h" — a vírgula decimal do resto da interface."""
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
    """O tempo formatado, ou "nenhuma sessão" quando nada foi jogado."""
    return format_playtime(seconds) if seconds else _("nenhuma sessão")


# Quanto uma quebra (ver `sem_lacunas_longas`) ocupa no eixo X, em dias: o dobro de um intervalo comum, para a linha
# tracejada ter onde ficar.
LARGURA_DA_QUEBRA = 2


def _por_mes(dias: list[tuple[date, int]]) -> bool:
    # Mais de dois meses na tela e "12/09" vira ruído que não diz o ano; aí o eixo é rotulado por mês.
    return (dias[-1][0] - dias[0][0]).days > 60


def _rotulo_do_dia(dia: date, por_mes: bool) -> str:
    return f"{MONTHS[dia.month - 1][:3].lower()} {dia.year % 100:02d}" if por_mes else f"{dia.day:02d}/{dia.month:02d}"


def _sem_encostar(indices: list[int], posicoes: list[int], dias: list[tuple[date, int]]) -> list[int]:
    """Tira o rótulo que ficaria colado no anterior: os dois lados de uma quebra podem ser meses diferentes a um passo
    de distância. Dos dois, fica o do dia 1º."""
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
    """Os dias que ganham rótulo no eixo X, no máximo uns 6.

    Por mês, só os dias 1º (senão "jul 26" apareceria duas vezes seguidas). Por dia, sempre o primeiro e o último, e
    nenhum colado no último.
    """
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
    """Tudo o que o gráfico precisa para ser desenhado, sem uma única medida em pixels.

    ``posicoes``: onde cada dia cai no eixo X, em intervalos desde o primeiro (a quebra ocupa ``LARGURA_DA_QUEBRA``);
    ``horas``: as horas de cada dia; ``topo`` e ``passo``: o alto do eixo Y e o intervalo da grade; ``grade``:
    ``[valor, "1,5 h"]`` por linha; ``rotulos``: ``[indice, texto, alinhamento]`` (0 = o texto começa em x, 0,5 = fica
    centrado, 1 = termina em x; as pontas alinham para dentro para não sair da área); ``quebras``: os índices ``i`` com
    uma pausa cortada entre ``dias[i]`` e ``dias[i + 1]``. Sem dias, ``{}``.
    """
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
    """O índice do dia mais perto de ``fracao`` (0 = borda esquerda do gráfico, 1 = direita): o inverso do eixo X.

    Busca binária nas posições (em anos de histórico são milhares de dias). Fora do gráfico vale o dia da ponta.
    """
    ultimo = len(posicoes) - 1
    if ultimo <= 0:
        return 0
    posicao = fracao * posicoes[-1]
    depois = min(max(bisect_left(posicoes, posicao), 1), ultimo)
    antes = depois - 1
    meio = (posicoes[antes] + posicoes[depois]) / 2
    return antes if posicao < meio else depois
