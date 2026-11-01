# test_data_da_release.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from cartridges import shared

RAIZ = Path(__file__).parent.parent
SCRIPT = RAIZ / "build-aux" / "windows" / "data_da_release.py"
_spec = importlib.util.spec_from_file_location("data_da_release", SCRIPT)
data_da_release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(data_da_release)


def _metainfo(versao="2.0.1", data="2026-11-01", topo=None):
    topo = topo or f'    <release version="{versao}" date="{data}">\n'
    return (
        "  <releases>\n"
        f"{topo}"
        '      <description translate="no"><ul><li>A</li></ul></description>\n'
        "    </release>\n"
        '    <release version="2.0.0" date="2026-11-01">\n'
        '      <description translate="no"><ul><li>Antigo</li></ul></description>\n'
        "    </release>\n"
        "  </releases>\n"
    )


def test_data_a_release_do_topo():
    novo = data_da_release.datar(_metainfo(data="2000-01-01"), "2.0.1", "2026-11-02")
    assert novo == _metainfo(data="2026-11-02")  # só o topo muda; a 2.0.0 fica com a data dela


def test_topo_de_outra_versao_recusa():
    with pytest.raises(SystemExit) as erro:
        data_da_release.datar(_metainfo(), "2.0.2", "2026-11-02")
    assert str(erro.value) == (
        'A <release> do topo do metainfo não é a 2.0.2: '
        'escreva as novidades numa <release version="2.0.2"> no topo.'
    )


def test_versao_de_baixo_nao_e_datada_se_o_topo_e_outra():
    texto = _metainfo(topo='    <release version="2.0.1" type="stable">\n')  # topo fora da forma exata
    with pytest.raises(SystemExit):
        data_da_release.datar(texto, "2.0.0", "2026-11-02")


def test_topo_sem_date_ganha_a_data():
    texto = _metainfo(topo='    <release version="2.0.1">\n')
    assert data_da_release.datar(texto, "2.0.1", "2026-11-02") == _metainfo(data="2026-11-02")


def test_date_antes_de_version_e_outros_atributos_ficam():
    texto = _metainfo(topo='\t<release date="2000-01-01" type="stable" version="2.0.1">\n')
    esperado = _metainfo(topo='\t<release date="2026-11-02" type="stable" version="2.0.1">\n')
    assert data_da_release.datar(texto, "2.0.1", "2026-11-02") == esperado


def test_release_ausente_recusa():
    with pytest.raises(SystemExit):
        data_da_release.datar("<releases/>\n", "2.0.0", "2026-11-02")


def test_mesma_data_nao_muda_nada():
    texto = _metainfo()
    assert data_da_release.datar(texto, "2.0.1", "2026-11-01") == texto


def test_preserva_as_quebras_de_linha(tmp_path):
    arquivo = tmp_path / "metainfo.xml.in"
    arquivo.write_bytes(_metainfo(data="2000-01-01").replace("\n", "\r\n").encode("utf-8"))
    subprocess.run([sys.executable, str(SCRIPT), str(arquivo), "2.0.1", "2026-11-02"], check=True)
    assert arquivo.read_bytes() == _metainfo(data="2026-11-02").replace("\n", "\r\n").encode("utf-8")


def test_recusa_nao_mexe_nos_bytes_do_arquivo(tmp_path):
    arquivo = tmp_path / "metainfo.xml.in"
    antes = _metainfo().replace("\n", "\r\n").encode("utf-8")
    arquivo.write_bytes(antes)
    r = subprocess.run([sys.executable, str(SCRIPT), str(arquivo), "2.0.2", "2026-11-02"], capture_output=True)
    assert r.returncode != 0
    assert arquivo.read_bytes() == antes


def test_metainfo_do_repositorio_tem_a_versao_do_app_no_topo():
    texto = (RAIZ / "data" / "io.github.joaomgabaldi.Cartridges.metainfo.xml.in").read_text(encoding="utf-8")
    assert data_da_release.versao_do_topo(texto) == shared.VERSION
