# notas_release.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Monta o corpo da release do GitHub a partir da <release> do metainfo.

Uso: python notas_release.py <metainfo.xml.in> <versão>
"""

import sys
import xml.etree.ElementTree as ET

INSTALACAO = "Baixe **Cartridges Windows.exe** abaixo e execute ou receba a atualização pelo próprio aplicativo."


def notas(metainfo: str, versao: str) -> str:
    release = ET.parse(metainfo).find(f"releases/release[@version='{versao}']")
    if release is None:
        raise SystemExit(f'Não há <release version="{versao}"> em {metainfo}.')
    # No metainfo os itens não levam ponto final; nas notas, levam.
    itens = [li.text.strip() for li in release.iter("li")]
    linhas = "\n".join(f"- {item if item.endswith('.') else item + '.'}" for item in itens)
    return f"## Novidades\n\n{linhas}\n\n## Instalação\n\n{INSTALACAO}\n"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(notas(sys.argv[1], sys.argv[2]), end="")
