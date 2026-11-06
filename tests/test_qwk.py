# test_qwk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A ponte com o QWindowKit: carrega a DLL e recusa um Qt diferente do de compilação."""

import ctypes
from pathlib import Path

import pytest
from PySide6.QtQml import QQmlEngine

from kyron.janela import qwk

DLL = Path(qwk.__file__).parent / "qwk_ponte.dll"

pytestmark = pytest.mark.skipif(
    not DLL.exists(), reason="qwk_ponte.dll é um artefato de build: rode build-aux/windows/qwk/compilar.bat"
)


def test_registrar_com_dll_compilada(app_qt):
    qwk.registrar(QQmlEngine())


def test_registrar_recusa_qt_diferente(app_qt, monkeypatch):
    class Falsa:
        class qwk_registrar:  # noqa: N801
            argtypes = restype = None

            def __new__(cls, _motor):
                return 0

    monkeypatch.setattr(ctypes, "CDLL", lambda _caminho: Falsa)
    with pytest.raises(RuntimeError, match="compilada para outro Qt"):
        qwk.registrar(QQmlEngine())
