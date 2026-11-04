# dpapi.py
#
# Copyright 2026 joaomgabaldi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O DPAPI do Windows, para guardar segredos (a conta da Tuya, a conta Microsoft).

A chave é amarrada à conta do Windows de quem roda o app: um blob não abre numa instalação nova,
em outro PC nem em outra conta; lá, `abrir` devolve ``None`` e quem chamou trata como "nada salvo".
"""

import ctypes
from ctypes import wintypes
from typing import Any, Optional

_crypt32 = ctypes.windll.crypt32  # type: ignore
_kernel32 = ctypes.windll.kernel32  # type: ignore


# `CRYPTPROTECT_UI_FORBIDDEN`: nenhuma das duas chamadas pode abrir uma janela de confirmação.
_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


# Uma assinatura serve às duas: os parâmetros que diferem (`ppszDataDescr`) só recebem `None` aqui.
_ARGTYPES = [
    ctypes.POINTER(_DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(_DATA_BLOB),
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(_DATA_BLOB),
]
_crypt32.CryptProtectData.argtypes = _ARGTYPES
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = _ARGTYPES
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [wintypes.LPVOID]
_kernel32.LocalFree.restype = wintypes.LPVOID


def _blob(dados: bytes) -> tuple[_DATA_BLOB, Any]:
    """Um DATA_BLOB para ``dados`` e o buffer que o sustenta (o blob só guarda o ponteiro; sem o buffer vivo, o coletor o libera)."""
    buffer = ctypes.create_string_buffer(dados, len(dados))
    return _DATA_BLOB(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _chamar(funcao: Any, dados: bytes) -> Optional[bytes]:
    entrada, _buffer = _blob(dados)
    saida = _DATA_BLOB()
    if not funcao(
        ctypes.byref(entrada), None, None, None, None, _UI_FORBIDDEN, ctypes.byref(saida)
    ):
        return None
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        _kernel32.LocalFree(saida.pbData)


def proteger(dados: bytes) -> Optional[bytes]:
    """``dados`` cifrados para o usuário Windows atual. None se o DPAPI falhar."""
    try:
        return _chamar(_crypt32.CryptProtectData, dados)
    except (OSError, ValueError, ctypes.ArgumentError):
        return None


def abrir(dados: bytes) -> Optional[bytes]:
    """O inverso de `proteger`. None se não abrir (outra conta, outro PC, adulterado)."""
    if not dados:
        return None
    try:
        return _chamar(_crypt32.CryptUnprotectData, dados)
    except (OSError, ValueError, ctypes.ArgumentError):
        return None
