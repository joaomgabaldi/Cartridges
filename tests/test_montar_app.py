"""Os `.pyc` da pasta do app valem em qualquer fuso.

O instalador sai da CI, em UTC, e o Inno Setup repõe a data dos arquivos como
hora local: em UTC-3 cada fonte chega 3 h adiantada. Um `.pyc` por data não
confere mais e o Python recompila tudo a cada abertura (~1,4 s).
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "build-aux" / "windows" / "montar_app.py"
_spec = importlib.util.spec_from_file_location("montar_app", _SCRIPT)
montar_app = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(montar_app)


def test_compilar_grava_os_pyc_por_hash(tmp_path, monkeypatch):
    fonte = tmp_path / "lib" / "modulo.py"
    fonte.parent.mkdir()
    fonte.write_text("x = 1\n", encoding="utf-8")

    real = subprocess.run

    def com_este_python(argumentos, **kwargs):
        return real([sys.executable, *argumentos[1:]], **kwargs)

    monkeypatch.setattr(montar_app.subprocess, "run", com_este_python)
    montar_app.compilar(tmp_path)

    pyc = Path(importlib.util.cache_from_source(str(fonte)))
    # Bits do cabeçalho (PEP 552): 1 = por hash, sem conferir a fonte.
    assert int.from_bytes(pyc.read_bytes()[4:8], "little") == 1
