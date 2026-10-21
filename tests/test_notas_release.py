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
    <release version="2026.10.04" date="2026-10-04">
      <description translate="no"><ul><li>Item pulado</li></ul></description>
    </release>
    <release version="2026.10.02" date="2026-10-02">
      <description translate="no"><ul><li>Item publicado</li></ul></description>
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


def test_junta_as_versoes_nunca_publicadas(tmp_path):
    """Uma versão que não virou release não perde as novidades: entram todas as
    mais novas que a última publicada, da mais nova para a mais antiga."""
    arquivo = tmp_path / "metainfo.xml.in"
    arquivo.write_text(METAINFO, encoding="utf-8")

    assert notas_release.notas(str(arquivo), "2026.10.06", "2026.10.02") == (
        "## Novidades\n\n"
        "- Agora as buscas estão mais rápidas.\n"
        "- Foi corrigido o desenho da janela.\n"
        "- Item pulado.\n\n"
        "## Instalação\n\n"
        "Baixe **Cartridges Windows.exe** abaixo e execute ou receba a atualização pelo próprio aplicativo.\n"
    )


def test_nao_passa_da_versao_pedida_nem_repete_a_publicada(tmp_path):
    """Uma <release> mais nova que a versão do meson.build não entra; e com a
    própria versão já publicada (re-execução), só ela."""
    arquivo = tmp_path / "metainfo.xml.in"
    arquivo.write_text(METAINFO, encoding="utf-8")

    def novidades(versao, anterior):
        return notas_release.notas(str(arquivo), versao, anterior).split("\n\n")[1]

    assert novidades("2026.10.04", "2026.09.29") == "- Item pulado.\n- Item publicado."
    assert novidades("2026.10.04", "2026.10.04") == "- Item pulado."
