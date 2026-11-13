# wallhaven.py
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

"""Busca de papéis de parede no wallhaven.cc.

A chave da API é opcional: a busca SFW responde sem autenticação; a chave só serve para NSFW e para os filtros da conta.

O módulo não escolhe formato: só 21% dos jogos de uma biblioteca real têm papel de parede em retrato no site.
A busca vai em degraus (o formato pedido, depois qualquer um) e o corte (``session_wallpaper.enquadrar``) resolve a diferença.
"""

import logging
import re
from typing import Any, Optional
from urllib.parse import urlencode

lazy import requests

from kyron import shared
from kyron.utils.download import get_capped

BASE = "https://wallhaven.cc/api/v1/search"

# Só "general": "anime" traz fan art de personagem, não arte de jogo, e "people" só ensaios e cosplay.
CATEGORIES = "100"

# Sempre SFW, mesmo que a chave da conta libere o resto: o papel de parede aparece sozinho em vários monitores.
PURITY = "100"

IMAGE_SUFFIXES = (".jpg", ".jpeg", ".png")

# Só o que a tela de escolha e o corte consomem; o resto da resposta é grande e não é usado.
_CAMPOS = ("id", "path", "resolution", "dimension_x", "dimension_y", "favorites")

# Edições e remasterizações não mudam a arte e deixam a busca sem resultado ("Conan Exiles Enhanced" volta vazio).
_SUFIXO_EDICAO = re.compile(
    r"\s*[-–]?\s*\(?\b("
    r"game of the year|goty|definitive|anniversary|enhanced|remastered|"
    r"complete|deluxe|ultimate|legendary|redux"
    r")\b\s*(edition)?\)?\s*$",
    re.IGNORECASE,
)


class WallhavenError(Exception):
    """A busca não pôde ser feita ou veio num formato inesperado."""


def consultas(nome: str) -> list[str]:
    """As formas de procurar ``nome``, da mais fiel à mais solta.

    O terceiro degrau corta o subtítulo, e "Aliens: Dark Descent" vira "Aliens" (o filme): daí a guarda
    de duas palavras, que derruba os casos ruins ("Alien", "Vampire") e preserva "Watch Dogs 2".
    """
    limpo = re.sub(r"[™®©]", "", nome)
    limpo = limpo.replace("_", " ").replace("’", "'")
    limpo = re.sub(r"\s+", " ", limpo).strip()

    formas = [limpo]

    sem_edicao = _SUFIXO_EDICAO.sub("", limpo).strip()
    if sem_edicao and sem_edicao != limpo:
        formas.append(sem_edicao)

    base = re.split(r"\s*(?::|\s[-–]\s)\s*", sem_edicao or limpo)[0].strip()
    if base and base not in formas and len(base.split()) >= 2:
        formas.append(base)

    return formas


def buscar(
    consulta: str,
    largura: int,
    altura: int,
    formato: Optional[str] = None,
    pagina: int = 1,
    timeout: float = 15,
) -> list[dict[str, Any]]:
    """Uma página de resultados para ``consulta``, do mais favoritado ao menos.

    ``largura`` e ``altura`` são o mínimo dos cortes dos monitores-alvo (``atleast``), para nenhum candidato
    ser ampliado depois do corte. ``formato`` é o ``ratios`` do site (``"portrait"``/``"landscape"``); ``None`` aceita qualquer um.

    :raises WallhavenError: rede fora, resposta não-JSON ou chave recusada
    """
    parametros = {
        "q": consulta,
        "categories": CATEGORIES,
        "purity": PURITY,
        "sorting": "relevance",
        "atleast": f"{largura}x{altura}",
        "page": str(pagina),
    }
    if formato:
        parametros["ratios"] = formato

    cabecalhos = {}
    if chave := shared.schema.get_string("wallhaven-key").strip():
        # No cabeçalho, não no `?apikey=`: a URL vai parar em log de proxy e de erro.
        cabecalhos["X-API-Key"] = chave

    try:
        resposta = get_capped(
            f"{BASE}?{urlencode(parametros)}", headers=cabecalhos, timeout=timeout
        )
        resposta.raise_for_status()
        dados = resposta.json()
    except requests.RequestException as erro:
        raise WallhavenError(str(erro)) from erro
    except ValueError as erro:
        raise WallhavenError("resposta não era JSON") from erro

    itens = dados.get("data") if isinstance(dados, dict) else None
    if not isinstance(itens, list):
        raise WallhavenError("resposta sem lista de resultados")

    resultados = []
    for item in itens:
        if not isinstance(item, dict) or not item.get("path"):
            continue
        registro = {campo: item.get(campo) for campo in _CAMPOS}
        miniaturas = item.get("thumbs")
        # A "large" preserva a proporção original; a "small" vem cortada em 3x2 pelo site.
        registro["thumb"] = (
            miniaturas.get("large") if isinstance(miniaturas, dict) else None
        ) or item["path"]
        resultados.append(registro)

    # A relevância decide quais 24 chegam; dentro deles, o mais favoritado é o melhor palpite de qualidade.
    resultados.sort(key=lambda item: item.get("favorites") or 0, reverse=True)
    return resultados


def melhor_para(
    nome: str, largura: int, altura: int, formato: str
) -> Optional[dict[str, Any]]:
    """O melhor candidato para ``nome``, descendo os degraus até achar um.

    Em cada forma do nome, ``formato`` primeiro e qualquer formato depois. ``None`` se nenhum degrau deu
    resultado (quem chamou cai na capa). Nunca levanta: roda enquanto o jogo abre.
    """
    for consulta in consultas(nome):
        for degrau in (formato, None):
            try:
                achados = buscar(consulta, largura, altura, formato=degrau)
            except WallhavenError as erro:
                logging.info("Busca no wallhaven falhou (%s): %s", consulta, erro)
                continue
            if achados:
                return achados[0]
    return None
