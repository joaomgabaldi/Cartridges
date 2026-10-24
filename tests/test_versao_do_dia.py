# test_versao_do_dia.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "versao_do_dia", Path(__file__).parent.parent / "build-aux" / "windows" / "versao_do_dia.py"
)
versao_do_dia = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(versao_do_dia)


def _metainfo(*itens_do_topo):
    itens = "".join(f"          <li>{item}</li>\n" for item in itens_do_topo)
    return (
        "  <releases>\n"
        '    <release version="2026.10.23" date="2026-10-23">\n'
        '      <description translate="no">\n'
        "        <ul>\n"
        f"{itens}"
        "        </ul>\n"
        "      </description>\n"
        "    </release>\n"
        '    <release version="2026.10.22" date="2026-10-22">\n'
        '      <description translate="no"><ul><li>Antigo</li></ul></description>\n'
        "    </release>\n"
        "  </releases>\n"
    )


def test_release_nao_publicada_ganha_a_data_do_dia():
    novo = versao_do_dia.datar(_metainfo("A"), "2026.10.24")
    assert novo == _metainfo("A").replace('"2026.10.23" date="2026-10-23"', '"2026.10.24" date="2026-10-24"')


def test_ja_na_versao_do_dia_nao_muda():
    texto = _metainfo("A")
    assert versao_do_dia.datar(texto, "2026.10.23") == texto


def test_itens_acrescentados_a_release_publicada_vao_para_uma_nova():
    novo = versao_do_dia.datar(_metainfo("A", "B", "C"), "2026.10.24", _metainfo("A"))
    assert novo == (
        "  <releases>\n"
        '    <release version="2026.10.24" date="2026-10-24">\n'
        '      <description translate="no">\n'
        "        <ul>\n"
        "          <li>B</li>\n"
        "          <li>C</li>\n"
        "        </ul>\n"
        "      </description>\n"
        "    </release>\n"
    ) + _metainfo("A").removeprefix("  <releases>\n")


def test_release_publicada_sem_novidades_para():
    with pytest.raises(SystemExit):
        versao_do_dia.datar(_metainfo("A"), "2026.10.24", _metainfo("A"))
