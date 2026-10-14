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

O jogo roda sempre no monitor principal, e é só ele que entra no print: a
Pillow, pedida a área de todos os monitores, captura todos e só depois
recorta — com três monitores, o triplo do custo a cada amostra. A cor sai da
mesma conta da capa (``dominante_da_imagem``), então pretos, cinzas e
brancos não viram luz.

O print é o da Pillow (GDI), que pega janela e tela cheia sem bordas. Jogo em
tela cheia exclusiva devolve a imagem toda preta — e isso é distinto de uma
cena escura, que sempre tem algum pixel aceso: é a captura bloqueada, e quem
acompanha a sessão avisa o usuário no fim dela.
"""

import ctypes
import logging
import os
from ctypes import wintypes
from typing import Any, NamedTuple, Optional

from PIL import Image, ImageGrab

from cartridges.utils.cor_da_capa import dominante_da_imagem


class Amostra(NamedTuple):
    """O resultado de uma amostra da tela.

    ``tipo``: ``"cor"`` (com ``cor`` = matiz 0–359 e saturação 0–1000),
    ``"sem_cor"`` (a imagem veio, mas sem cor útil), ``"ignorada"`` (nada foi
    capturado: nenhuma janela na frente, ou a janela é do próprio app) ou
    ``"bloqueada"`` (a captura falhou ou veio toda preta).
    """

    tipo: str
    cor: Optional[tuple[int, int]] = None


_user32: Optional[Any] = None


def _api() -> Any:
    """user32 com os tipos declarados. Uma cópia só deste módulo, pelo mesmo
    motivo de ``janela_por_cima._api``: ``ctypes.windll.user32`` é
    compartilhado, e os ``argtypes`` de um módulo valem para todos."""
    global _user32  # pylint: disable=global-statement
    if _user32 is None:
        u = ctypes.WinDLL("user32")  # type: ignore[attr-defined]
        u.GetForegroundWindow.restype = wintypes.HWND
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        _user32 = u
    return _user32


def _janela_da_frente() -> int:
    """A janela em primeiro plano, ou 0 se não houver nenhuma."""
    return _api().GetForegroundWindow() or 0


def _processo_da(hwnd: int) -> int:
    processo = wintypes.DWORD()
    _api().GetWindowThreadProcessId(hwnd, ctypes.byref(processo))
    return processo.value


def _capturar() -> Image.Image:
    """O monitor principal inteiro, que é onde o jogo roda."""
    return ImageGrab.grab()


def cor_da_tela() -> Amostra:
    """Uma amostra do monitor do jogo. Nunca levanta: roda numa thread da
    sessão, e um enfeite não pode derrubá-la."""
    try:
        hwnd = _janela_da_frente()
        # O próprio Cartridges na frente (Alt+Tab no meio do jogo): a luz não
        # pode pegar o roxo do app. Nada é capturado, e isso não conta nem
        # como captura que funcionou nem como bloqueio.
        if not hwnd or _processo_da(hwnd) == os.getpid():
            return Amostra("ignorada")
        imagem = _capturar()
    # Larga como a da capa: o GDI e a Pillow reclamam de jeitos diferentes
    # (monitor desligado no meio, sessão bloqueada do Windows), e todos querem
    # dizer a mesma coisa — não deu para ver a tela.
    except Exception as erro:  # pylint: disable=broad-exception-caught
        logging.info("Captura da tela do jogo falhou: %s", erro)
        return Amostra("bloqueada")

    if imagem.getbbox() is None:
        return Amostra("bloqueada")
    cor = dominante_da_imagem(imagem)
    return Amostra("cor", cor) if cor else Amostra("sem_cor")
