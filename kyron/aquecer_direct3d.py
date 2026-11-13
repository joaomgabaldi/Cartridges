# aquecer_direct3d.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Acorda o driver de vídeo enquanto o app carrega.

Criar o primeiro dispositivo Direct3D 11 com o driver parado leva mais de um segundo (1,3 s medidos numa RTX 4060), e o
Qt só o cria depois de carregar o QML, com a janela esperando o primeiro quadro. Criado aqui, numa thread, logo no começo
do processo, esse tempo corre junto com os imports e a carga do QML; o dispositivo é solto em seguida e o do Qt nasce
com o driver já acordado. Sem Qt e sem `kyron.shared`: é a primeira coisa que o `__main__` importa.
"""

import ctypes
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import Any

_HARDWARE = 1  # D3D_DRIVER_TYPE_HARDWARE
_VERSAO_DO_SDK = 7  # D3D11_SDK_VERSION
_RELEASE = 2  # posição de IUnknown::Release na tabela de métodos


def _soltar(ponteiro: ctypes.c_void_p) -> None:
    if ponteiro.value:
        metodos = ctypes.cast(ponteiro, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(metodos[_RELEASE])(ponteiro)


def _criar_e_soltar(carregar: Callable[[str], Any], soltar: Callable[[ctypes.c_void_p], None] = _soltar) -> None:
    # É só um adiantamento: com qualquer falha (sem placa, sem a DLL), o Qt cria o dispositivo dele como sempre.
    try:
        criar = carregar("d3d11").D3D11CreateDevice
        criar.restype = ctypes.c_long
        criar.argtypes = [
            ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]  # fmt: skip
        dispositivo, contexto = ctypes.c_void_p(), ctypes.c_void_p()
        if criar(None, _HARDWARE, None, 0, None, 0, _VERSAO_DO_SDK, ctypes.byref(dispositivo), None, ctypes.byref(contexto)) < 0:
            return
        soltar(contexto)
        soltar(dispositivo)
    except Exception:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        pass


def aquecer(
    argv: Sequence[str], ambiente: Mapping[str, str] = os.environ, carregar: Callable[[str], Any] | None = None
) -> threading.Thread | None:
    """Começa o aquecimento e volta na hora; ``None`` quando não há janela a desenhar pela placa."""
    if "--sair-apos-carregar" in argv or ambiente.get("QT_QPA_PLATFORM") == "offscreen" or ambiente.get("QT_QUICK_BACKEND") == "software":
        return None
    thread = threading.Thread(
        target=_criar_e_soltar, args=(carregar or ctypes.WinDLL,), name="aquecer-direct3d", daemon=True  # type: ignore[attr-defined]
    )
    thread.start()
    return thread
