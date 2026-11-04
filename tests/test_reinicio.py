# test_reinicio.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app se reabre sozinho depois de agendar uma restauração ou uma redefinição (D75)."""

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from cartridges import app as modulo_app
from tests.apoio_abertura import preparar_main

RAIZ = Path(__file__).resolve().parent.parent


def test_relancar_abre_o_mesmo_comando_desacoplado(monkeypatch):
    chamadas = []
    monkeypatch.setattr(modulo_app, "_popen", lambda args, **kw: chamadas.append((args, kw)))
    monkeypatch.setattr(sys, "executable", r"C:\Python315\python.exe")
    monkeypatch.setattr(sys, "argv", [str(RAIZ / "cartridges" / "__main__.py"), "--algo"])
    modulo_app.relancar()
    args, kw = chamadas[0]
    assert args == [r"C:\Python315\python.exe", "-m", "cartridges", "--algo"]
    assert Path(kw["cwd"]) == RAIZ  # a pasta acima do pacote: o `-m cartridges` acha este código
    assert kw["creationflags"] & subprocess.DETACHED_PROCESS
    assert kw["creationflags"] & subprocess.CREATE_NEW_PROCESS_GROUP
    assert kw["close_fds"] is True


def test_relancar_reconhece_o_kyron_exe_nao_repete_o_script(monkeypatch):
    chamadas = []
    monkeypatch.setattr(modulo_app, "_popen", lambda args, **_kw: chamadas.append(args))
    exe = r"C:\Program Files\Cartridges Revamped\bin\Kyron.exe"
    monkeypatch.setattr(sys, "executable", exe)
    monkeypatch.setattr(sys, "argv", [r"C:\Program Files\Cartridges Revamped\bin\cartridges", "x"])
    modulo_app.relancar()
    assert chamadas == [[exe, "x"]]  # o Kyron.exe já põe o `-m cartridges`


def test_main_so_relanca_quando_pedido(monkeypatch):
    eventos = []
    reiniciar = [False]

    def abrir(_app, _argv, abertura):
        abertura.aplicativo = SimpleNamespace(reiniciar=reiniciar[0])

    preparar_main(monkeypatch, abrir, eventos)
    assert modulo_app.main(["cartridges"]) == 0
    assert "release" not in eventos and "relancar" not in eventos

    reiniciar[0] = True
    eventos.clear()
    assert modulo_app.main(["cartridges"]) == 0
    # A trava sai antes: o processo novo precisa conseguir tomá-la.
    assert eventos[-2:] == ["release", "relancar"]


def test_conftest_bloqueia_o_relancar():
    with pytest.raises(AssertionError, match="relancar: o app não é reaberto nos testes"):
        modulo_app.relancar()
