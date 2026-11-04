# data_da_release.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Põe a data na <release> do topo do metainfo, para a CI do instalador.

A versão vem de ``cartridges/shared.py: VERSION`` e as novidades já estão
escritas na <release> do topo; aqui só muda a data.

Uso: python data_da_release.py <metainfo.xml.in> <versão> <AAAA-MM-DD>
"""

import re
import sys

# A primeira <release>, com os atributos em qualquer ordem e a indentação como estiver.
TOPO = re.compile(r"^([ \t]*)<release\b([^>]*)>", re.M)
_VERSAO = re.compile(r'\bversion="([^"]*)"')
_DATA = re.compile(r'\bdate="[^"]*"')


def versao_do_topo(texto: str) -> str:
    topo = TOPO.search(texto)
    if not topo:
        raise SystemExit("Não há <release> no metainfo.")
    achou = _VERSAO.search(topo.group(2))
    return achou.group(1) if achou else ""


def datar(texto: str, versao: str, data: str) -> str:
    if versao_do_topo(texto) != versao:
        raise SystemExit(
            f'A <release> do topo do metainfo não é a {versao}: '
            f'escreva as novidades numa <release version="{versao}"> no topo.'
        )
    topo = TOPO.search(texto)
    atributo = f'date="{data}"'
    atributos = _DATA.sub(atributo, topo.group(2), 1) if _DATA.search(topo.group(2)) else f"{topo.group(2)} {atributo}"
    return f"{texto[: topo.start()]}{topo.group(1)}<release{atributos}>{texto[topo.end() :]}"


if __name__ == "__main__":
    caminho, versao, data = sys.argv[1:4]
    with open(caminho, encoding="utf-8", newline="") as f:
        texto = f.read()
    novo = datar(texto, versao, data)  # antes do open("w"): uma recusa não pode truncar o arquivo
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        f.write(novo)
