# test_notas_release.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "notas_release", Path(__file__).parent.parent / "build-aux" / "windows" / "notas_release.py"
)
notas_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(notas_release)

METAINFO = """<?xml version="1.0" encoding="UTF-8"?>
<component type="desktop-application">
  <releases>
    <release version="2026.10.06" date="2026-10-06">
      <description translate="no">
        <ul>
          <li>Agora as buscas estão mais rápidas</li>
          <li>Foi corrigido o desenho da janela.</li>
        </ul>
      </description>
    </release>
    <release version="2026.09.29" date="2026-09-29">
      <description translate="no"><ul><li>Item antigo</li></ul></description>
    </release>
  </releases>
</component>
"""


def test_notas_da_versao_pedida(tmp_path):
    arquivo = tmp_path / "metainfo.xml.in"
    arquivo.write_text(METAINFO, encoding="utf-8")

    assert notas_release.notas(str(arquivo), "2026.10.06") == (
        "## Novidades\n\n"
        "- Agora as buscas estão mais rápidas.\n"
        "- Foi corrigido o desenho da janela.\n\n"
        "## Instalação\n\n"
        "Baixe **Cartridges Windows.exe** abaixo e execute ou receba a atualização pelo próprio aplicativo.\n"
    )


def test_versao_sem_release_para(tmp_path):
    arquivo = tmp_path / "metainfo.xml.in"
    arquivo.write_text(METAINFO, encoding="utf-8")

    with pytest.raises(SystemExit):
        notas_release.notas(str(arquivo), "2026.10.07")
