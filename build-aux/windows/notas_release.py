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

INSTALACAO = "Baixe **Kyron Windows.exe** abaixo e execute ou receba a atualização pelo próprio aplicativo."


def notas(metainfo: str, versao: str, anterior: str = "") -> str:
    """``anterior`` é a última versão publicada como final. As releases do arquivo
    entre a ``versao`` (inclusive) e a ``anterior`` (exclusive) entram juntas, para
    que as novidades de uma versão que nunca saiu não se percam; sem ``anterior``
    (ou se ela não está no arquivo), só a ``versao``."""
    releases = ET.parse(metainfo).findall("releases/release")
    versoes = [r.get("version") for r in releases]
    if versao not in versoes:
        raise SystemExit(f'Não há <release version="{versao}"> em {metainfo}.')
    # O metainfo vem da mais nova para a mais antiga; a ordem do arquivo é a que vale
    # (data e X.Y.Z não se comparam como texto).
    inicio = versoes.index(versao)
    fim = versoes.index(anterior) if anterior in versoes[inicio:] else inicio + 1
    incluidas = releases[inicio : max(fim, inicio + 1)]
    # No metainfo os itens não levam ponto final; nas notas, levam.
    itens = [li.text.strip() for release in incluidas for li in release.iter("li")]
    linhas = "\n".join(f"- {item if item.endswith('.') else item + '.'}" for item in itens)
    return f"## Novidades\n\n{linhas}\n\n## Instalação\n\n{INSTALACAO}\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(notas(*sys.argv[1:4]), end="")
