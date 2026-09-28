# passeio_relatorio.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Lógica pura do passeio: classifica os passos e escreve o relatório.

Sem GTK e sem rede, para ser testada na suíte normal. Recebe os passos no
formato de ``passos.jsonl`` (ver ``tools/passeio_app.py``).
"""

import logging
import re
from typing import Any

# Falha de internet não é bug do app: Steam fora do ar, jogo que o
# HowLongToBeat não conhece. Vai para uma seção própria do relatório.
_LOGGERS_DE_REDE = ("urllib3", "requests")
_PALAVRAS_DE_REDE = (
    "HowLongToBeat",
    "Steam",
    "SteamGridDB",
    "Wallhaven",
    "feed",
    "HTTP",
    "Connection",
    "Timeout",
    "timed out",
    "Max retries",
)
# Nunca de rede, mesmo citando a Steam: um erro que escapou do app, ou um aviso
# do GTK/GLib (o writer grava "Gtk-CRITICAL **", "GLib-WARNING **" etc.).
_NUNCA_DE_REDE = ("Erro não tratado", "-CRITICAL", "-WARNING", "-ERROR")
# Quando há rastro, só a exceção de fato levantada decide — a mensagem pode
# citar "Steam" e o bug ser outro (ex.: metadata_refresh.py:193 loga
# "could not prefetch Steam tags" num except genérico; um KeyError ali dentro
# não é falha de rede só porque a mensagem cita a Steam).
_EXCECOES_DE_REDE = (
    "requests.",
    "urllib3.",
    "socket.",
    "ssl.",
    "http.client.",
    "TimeoutError",
    "ConnectionError",
)


def e_de_rede(registro: dict[str, Any]) -> bool:
    mensagem = registro["mensagem"]
    if any(marca in mensagem for marca in _NUNCA_DE_REDE):
        return False
    rastro = registro["rastro"]
    if rastro:
        linhas = [linha for linha in rastro.splitlines() if linha.strip()]
        ultima = linhas[-1] if linhas else ""
        return any(marca in ultima for marca in _EXCECOES_DE_REDE)
    if registro["logger"].startswith(_LOGGERS_DE_REDE):
        return True
    return any(palavra in mensagem for palavra in _PALAVRAS_DE_REDE)


def classificar(passo: dict[str, Any]) -> str:
    if passo["estado"] in ("travou", "falha"):
        return passo["estado"]
    if any(
        r["nivel"] >= logging.ERROR and not e_de_rede(r) for r in passo["registros"]
    ):
        return "falha"
    if passo["estado"] == "pulado":
        return "pulado"
    return "ok"


def _rotulo(passo: dict[str, Any]) -> str:
    return f"{passo['passo']} · {passo['jogo_nome']}" if passo["jogo_nome"] else passo["passo"]


# O GLib grava cada aviso com um prefixo de processo, um horário e endereços
# de memória em hexa — tudo isso muda a cada execução (e a cada aviso) sem
# mudar o aviso em si. Sem normalizar, 329 "grupos" únicos eram na verdade uns
# 4 avisos repetidos.
_RE_PREFIXO_PROCESSO = re.compile(r"^\([^()]*:\d+\):\s*")
_RE_HORARIO = re.compile(r"\b\d{2}:\d{2}:\d{2}\.\d+:\s*")
_RE_HEX = re.compile(r"\b[0-9a-fA-F]{8,16}\b")
_RE_NUMERO = re.compile(r"\d+")


def _chave_normalizada(mensagem: str) -> str:
    sem_prefixo = _RE_PREFIXO_PROCESSO.sub("", mensagem)
    sem_horario = _RE_HORARIO.sub("", sem_prefixo)
    sem_hex = _RE_HEX.sub("<end>", sem_horario)
    return _RE_NUMERO.sub("<n>", sem_hex)


def agrupar(passos: list[dict[str, Any]], de_rede: bool) -> list[tuple[str, int, str]]:
    """Avisos (abaixo de ERROR, fora da rede) ou avisos de rede (qualquer nível).

    Agrupa por uma chave normalizada (sem pid, horário, endereços e números);
    a mensagem de exemplo mostrada é a primeira mensagem crua do grupo.
    """
    grupos: dict[str, list[Any]] = {}
    for passo in passos:
        for r in passo["registros"]:
            rede = e_de_rede(r)
            if rede != de_rede or (not rede and r["nivel"] >= logging.ERROR):
                continue
            chave = _chave_normalizada(r["mensagem"])
            grupo = grupos.setdefault(chave, [0, _rotulo(passo), r["mensagem"]])
            grupo[0] += 1
    return [(exemplo, n, primeiro) for n, primeiro, exemplo in grupos.values()]


def _agrupar_registros(registros: list[dict[str, Any]]) -> list[tuple[dict[str, Any], int]]:
    """Mesma normalização de `agrupar`, mas para a lista de registros de uma falha."""
    grupos: dict[tuple[int, str], list[Any]] = {}
    ordem: list[tuple[int, str]] = []
    for r in registros:
        chave = (r["nivel"], _chave_normalizada(r["mensagem"]))
        if chave not in grupos:
            grupos[chave] = [r, 0]
            ordem.append(chave)
        grupos[chave][1] += 1
    return [(r, n) for r, n in (grupos[c] for c in ordem)]


def _duracao(segundos: float) -> str:
    minutos, resto = divmod(int(round(segundos)), 60)
    return f"{minutos} min {resto} s" if minutos else f"{resto} s"


def codigo_de_saida(passos: list[dict[str, Any]]) -> int:
    return int(any(classificar(p) in ("falha", "travou") for p in passos))


def montar_relatorio(
    passos: list[dict[str, Any]], duracao: float, despejo: str, janela: str = ""
) -> str:
    estados = [classificar(p) for p in passos]
    linhas = [
        "# Relatório do passeio",
        "",
    ]
    if janela:
        linhas.append(f"- Janela: {janela} px")
        altura = janela.split("x")[-1]
        if altura.isdigit() and int(altura) < 360:
            linhas.append(
                f"- **Aviso**: janela com {altura} px de altura, abaixo dos 360 px esperados."
            )
    linhas += [
        f"- Passos executados: {len(passos)}",
        f"- Falhas: {estados.count('falha')}",
        f"- Travamentos: {estados.count('travou')}",
        f"- Pulados: {estados.count('pulado')}",
        f"- Duração: {_duracao(duracao)}",
        "",
        "## Falhas e travamentos",
        "",
    ]
    problemas = [p for p, e in zip(passos, estados) if e in ("falha", "travou")]
    if not problemas:
        linhas += ["Nenhuma.", ""]
    for passo in problemas:
        linhas += [f"### {_rotulo(passo)}", ""]
        if passo["jogo_id"]:
            linhas.append(f"- Jogo: {passo['jogo_nome']} (`{passo['jogo_id']}`)")
        linhas.append(f"- Estado: {classificar(passo)}")
        if passo["motivo"]:
            linhas.append(f"- Motivo: {passo['motivo']}")
        linhas.append("")
        if passo["rastro"]:
            linhas += ["```", passo["rastro"].rstrip(), "```", ""]
        candidatos = [
            r for r in passo["registros"] if r["nivel"] >= logging.WARNING and not e_de_rede(r)
        ]
        for r, n in _agrupar_registros(candidatos):
            prefixo = f"{n}× " if n > 1 else ""
            linhas.append(f"- {prefixo}`{logging.getLevelName(r['nivel'])}` {r['mensagem']}")
            if r["rastro"]:
                linhas += ["", "```", r["rastro"].rstrip(), "```", ""]
        linhas.append("")
    if despejo.strip():
        linhas += ["## Pilha no travamento", "", "```", despejo.rstrip(), "```", ""]
    for titulo, de_rede in (("Avisos", False), ("Avisos de rede", True)):
        linhas += [f"## {titulo}", ""]
        grupos = agrupar(passos, de_rede)
        if not grupos:
            linhas += ["Nenhum.", ""]
        for mensagem, n, primeiro in grupos:
            linhas.append(f"- {n}× {mensagem} (primeiro em: {primeiro})")
        linhas.append("")
    pulados = [p for p, e in zip(passos, estados) if e == "pulado"]
    if pulados:
        linhas += ["## Pulados", ""]
        linhas += [f"- {_rotulo(p)}: {p['motivo']}" for p in pulados]
        linhas.append("")
    return "\n".join(linhas)
