# tela_do_jogo.py
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

"""A cor predominante do monitor do jogo, para a iluminação acompanhar a tela.

Só o monitor principal entra no print: o Pillow, pedida a área de todos, captura todos e só depois recorta.
A cor sai da mesma conta da capa (``dominante_da_imagem``). O print é o do GDI; jogo em tela cheia exclusiva
devolve a imagem toda preta (uma cena escura sempre tem algum pixel aceso): é a captura bloqueada.
"""

import ctypes
import logging
import os
import time
from ctypes import wintypes
from typing import Any, NamedTuple, Optional

from PIL import Image, ImageGrab, ImageStat

from kyron.utils.cor_da_capa import dominante_da_imagem


CORES_DA_TELA = 16
MIN_VALOR_DA_TELA = 0.06


class Amostra(NamedTuple):
    """``tipo``: ``"cor"`` (``cor`` = matiz 0–359, saturação 0–1000), ``"sem_cor"``, ``"ignorada"`` (nada
    capturado: sem janela na frente ou janela do próprio app) ou ``"bloqueada"`` (captura falhou ou toda preta).

    Com imagem, ``luz`` é a luminosidade média da cena (0 a 1) e ``ms`` o tempo da captura.
    """

    tipo: str
    cor: Optional[tuple[int, int]] = None
    luz: Optional[float] = None
    ms: Optional[int] = None


_user32: Optional[Any] = None


def _api() -> Any:
    """user32 com os tipos declarados, em cópia própria: os ``argtypes`` de ``ctypes.windll.user32`` valem para todos os módulos."""
    global _user32  # pylint: disable=global-statement
    if _user32 is None:
        u = ctypes.WinDLL("user32")  # type: ignore[attr-defined]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        _user32 = u
    return _user32


def _janela_da_frente() -> int:
    return _api().GetForegroundWindow() or 0


def _processo_da(hwnd: int) -> int:
    processo = wintypes.DWORD()
    _api().GetWindowThreadProcessId(hwnd, ctypes.byref(processo))
    return processo.value


def _capturar() -> Image.Image:
    return ImageGrab.grab()


def cor_da_tela() -> Amostra:
    """Uma amostra do monitor do jogo. Nunca levanta: roda numa thread da sessão."""
    try:
        hwnd = _janela_da_frente()
        # O próprio app na frente (Alt+Tab): a luz não pode pegar a cor dele; não conta como captura nem como bloqueio.
        if not hwnd or _processo_da(hwnd) == os.getpid():
            return Amostra("ignorada")
        inicio = time.perf_counter()
        imagem = _capturar()
        ms = round((time.perf_counter() - inicio) * 1000)
    # Larga de propósito: o GDI e o Pillow reclamam de jeitos diferentes (monitor desligado, sessão bloqueada).
    except Exception as erro:  # pylint: disable=broad-exception-caught
        logging.info("Captura da tela do jogo falhou: %s", erro)
        return Amostra("bloqueada")

    if imagem.getbbox() is None:
        return Amostra("bloqueada")
    luz = ImageStat.Stat(imagem.convert("L").resize((64, 36))).mean[0] / 255
    cor = dominante_da_imagem(imagem, CORES_DA_TELA, MIN_VALOR_DA_TELA)
    return Amostra("cor" if cor else "sem_cor", cor, luz, ms)
