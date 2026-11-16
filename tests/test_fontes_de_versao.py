# test_fontes_de_versao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resolução das bibliotecas: lê o relatório do pip e grava `requirements` com SHA-256."""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build-aux" / "windows"))
import fontes_de_versao as fontes  # noqa: E402

DADOS = Path(__file__).resolve().parent / "dados" / "versoes"
SHA_TINYTUYA = "ac5650c30f1153b1eae0b8d75f67043fb2397a168d3834e47da2d88d2c08c722"


def test_resolver_libs_le_relatorio_do_pip(tmp_path):
    relatorio = (DADOS / "pip_report.json").read_text(encoding="utf-8")
    chamadas = []

    def rodar(cmd, **kw):
        chamadas.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=relatorio, stderr="")

    pinos = fontes.resolver_libs([tmp_path / "requirements.in"], "3.15", ["PySide6==6.12.0"], rodar)
    assert fontes.Pino("tinytuya", "1.20.0", SHA_TINYTUYA) in pinos
    cmd = chamadas[0]
    for trecho in ("--dry-run", "--only-binary=:all:", "--platform", "win_amd64",
                   "--python-version", "3.15", "--ignore-installed", "PySide6==6.12.0"):
        assert trecho in cmd


def test_resolver_libs_devolve_none_quando_pip_falha(tmp_path):
    rodar = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ResolutionImpossible")
    assert fontes.resolver_libs([tmp_path / "r.in"], "3.16", [], rodar) is None


def test_resolver_libs_devolve_none_com_relatorio_ilegivel(tmp_path):
    rodar = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="não é json", stderr="")
    assert fontes.resolver_libs([tmp_path / "r.in"], "3.15", [], rodar) is None


def test_gravar_requirements_ordena_e_poe_hash(tmp_path):
    destino = tmp_path / "r.txt"
    fontes.gravar_requirements(destino, [fontes.Pino("b", "2", "bb"), fontes.Pino("A", "1", "aa")], ["-r x.txt"])
    assert destino.read_text(encoding="utf-8") == "-r x.txt\nA==1 --hash=sha256:aa\nb==2 --hash=sha256:bb\n"
