# qwk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Registra os tipos QML do QWindowKit (WindowAgent) no motor QML.

A `qwk_ponte.dll` (build-aux/windows/qwk/compilar.bat) recebe o ponteiro C++ do motor, obtido pelo shiboken6.
"""

import ctypes
import os
from pathlib import Path

import PySide6
import shiboken6
from PySide6.QtCore import qVersion
from PySide6.QtQml import QQmlEngine


def registrar(motor: QQmlEngine) -> None:
    os.add_dll_directory(str(Path(PySide6.__file__).parent))
    ponte = ctypes.CDLL(str(Path(__file__).with_name("qwk_ponte.dll")))
    ponte.qwk_registrar.argtypes = [ctypes.c_void_p]
    ponte.qwk_registrar.restype = ctypes.c_int
    if not ponte.qwk_registrar(shiboken6.getCppPointer(motor)[0]):
        raise RuntimeError(
            f"qwk_ponte.dll foi compilada para outro Qt (o PySide6 traz o {qVersion()}): "
            "rode build-aux/windows/qwk/compilar.bat"
        )
