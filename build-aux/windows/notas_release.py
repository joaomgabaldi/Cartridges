# notas_release.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Monta o corpo da release do GitHub a partir da <release> do metainfo.

Uso: python notas_release.py <metainfo.xml.in> <versão> [<última versão publicada>]
"""

import sys
import xml.etree.ElementTree as ET

INSTALACAO = "Baixe **Cartridges Windows.exe** abaixo e execute ou receba a atualização pelo próprio aplicativo."


def notas(metainfo: str, versao: str, anterior: str = "") -> str:
    """``anterior`` é a última versão publicada como final. As que vieram depois
    dela e nunca viraram release entram junto, para que as novidades delas não
    se percam; sem ``anterior``, só a ``versao``."""
    releases = ET.parse(metainfo).findall("releases/release")
    if not any(r.get("version") == versao for r in releases):
        raise SystemExit(f'Não há <release version="{versao}"> em {metainfo}.')
    # AAAA.MM.DD se compara como texto; o metainfo já vem da mais nova para a mais antiga.
    incluidas = [
        r for r in releases
        if r.get("version") == versao or (anterior and anterior < r.get("version", "") <= versao)
    ]
    # No metainfo os itens não levam ponto final; nas notas, levam.
    itens = [li.text.strip() for release in incluidas for li in release.iter("li")]
    linhas = "\n".join(f"- {item if item.endswith('.') else item + '.'}" for item in itens)
    return f"## Novidades\n\n{linhas}\n\n## Instalação\n\n{INSTALACAO}\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(notas(*sys.argv[1:4]), end="")
