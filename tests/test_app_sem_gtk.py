# test_app_sem_gtk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app Qt sobe sem o GTK: o `gi` bloqueado e o GTK morto fora do `sys.modules` (D90)."""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_ROTEIRO = r"""
RAIZ = %r

import sys
sys.path.insert(0, RAIZ)
from importlib.abc import MetaPathFinder

class _SemGi(MetaPathFinder):
    def find_spec(self, nome, caminho=None, alvo=None):
        if nome == "gi" or nome.startswith("gi."):
            raise ImportError("gi bloqueado: " + nome)
        return None

sys.meta_path.insert(0, _SemGi())

import cartridges.app
import cartridges.assistente

mortos = [
    m for m in ("cartridges.main", "cartridges.window", "cartridges.details_dialog")
    if m in sys.modules
]
com_gi = [m for m in sys.modules if m == "gi" or m.startswith("gi.")]
print("MORTOS=" + ",".join(mortos))
print("GI=" + ",".join(com_gi))
"""


def test_app_qt_nao_importa_o_gtk():
    # CARTRIDGES_DADOS/REGISTRO herdados do conftest: o `shared` não toca os dados reais.
    resultado = subprocess.run(
        [sys.executable, "-I", "-c", _ROTEIRO % str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "MORTOS=\n" in resultado.stdout + "\n", resultado.stdout
    assert "GI=\n" in resultado.stdout + "\n", resultado.stdout
