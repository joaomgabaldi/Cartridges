# versao_do_dia.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Põe a <release> do topo do metainfo na versão do dia, para a CI do instalador.

Uso: python versao_do_dia.py <metainfo.xml.in> <versão> [<metainfo da última versão final>]
"""

import re
import sys

RELEASE = re.compile(r'^( *)<release version="([^"]*)" date="[^"]*">', re.M)
ITEM = re.compile(r"^ *<li>.*</li>\n", re.M)


def _topo(texto: str) -> re.Match:
    if not (topo := RELEASE.search(texto)):
        raise SystemExit("Não há <release> no metainfo.")
    return topo


def _itens_do_topo(texto: str) -> list[str]:
    inicio = _topo(texto).end()
    return ITEM.findall(texto, inicio, texto.index("</release>", inicio))


def datar(texto: str, versao: str, publicado: str = "") -> str:
    """``publicado`` é o metainfo da última versão final. Se a <release> do topo
    já saiu nela, os itens acrescentados depois vão para uma <release> nova."""
    topo = _topo(texto)
    if topo.group(2) == versao:
        return texto
    data = versao.replace(".", "-")
    if not (publicado and _topo(publicado).group(2) == topo.group(2)):
        return f'{texto[:topo.start()]}{topo.group(1)}<release version="{versao}" date="{data}">{texto[topo.end():]}'

    ja_saiu = set(_itens_do_topo(publicado))
    novos = [item for item in _itens_do_topo(texto) if item not in ja_saiu]
    if not novos:
        raise SystemExit(f"A <release> {topo.group(2)} já foi publicada e não há novidades depois dela no metainfo.")
    fim = texto.index("</release>", topo.end())
    antiga = texto[topo.start():fim]
    for item in novos:
        antiga = antiga.replace(item, "", 1)
    r = topo.group(1)
    nova = (
        f'{r}<release version="{versao}" date="{data}">\n'
        f'{r}  <description translate="no">\n'
        f"{r}    <ul>\n"
        f"{''.join(novos)}"
        f"{r}    </ul>\n"
        f"{r}  </description>\n"
        f"{r}</release>\n"
    )
    return texto[:topo.start()] + nova + antiga + texto[fim:]


if __name__ == "__main__":
    caminho, versao, *resto = sys.argv[1:]
    with open(caminho, encoding="utf-8", newline="") as f:
        texto = f.read()
    publicado = ""
    if resto:
        with open(resto[0], encoding="utf-8", newline="") as f:
            publicado = f.read()
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        f.write(datar(texto, versao, publicado))
