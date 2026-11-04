# cortina_da_abertura.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A janela principal só aparece desenhada, com as capas à vista.

O `Principal.qml` chama `cobrir` depois do setup do QWindowKit: o DWM esconde a janela (`DWMWA_CLOAK`) mas continua
entregando quadros, e ela é revelada no quadro seguinte ao das capas prontas, ou no `PRAZO_MS`.
"""

import ctypes
import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Slot

_DWMWA_CLOAK = 13


def _cloak(hwnd: int, ligado: bool) -> bool:
    valor = ctypes.c_int(1 if ligado else 0)
    try:
        dwm = ctypes.WinDLL("dwmapi")  # type: ignore[attr-defined]
        return dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), _DWMWA_CLOAK, ctypes.byref(valor), 4) == 0
    except OSError:
        return False


def _capa_carregando(raiz: Any) -> bool:
    pilha = [raiz]
    while pilha:
        item = pilha.pop()
        if item.objectName() == "capaParada" and item.property("carregandoArquivo"):
            return True
        pilha.extend(item.childItems())
    return False


class CortinaDaAbertura(QObject):

    # Teto da espera: uma capa lenta não segura a janela.
    PRAZO_MS = 2500

    def __init__(self) -> None:
        super().__init__()
        self._janela: Any = None
        self._hwnd = 0
        self._pronta = False
        self._ao_revelar: list[Callable[[], None]] = []
        self._prazo = QTimer(self, singleShot=True, interval=self.PRAZO_MS)
        self._prazo.timeout.connect(self.revelar)

    @Slot(QObject)
    def cobrir(self, janela: Any) -> None:
        try:
            hwnd = int(janela.winId())
            if not _cloak(hwnd, True):
                return
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Não foi possível esconder a janela até o primeiro quadro", exc_info=True)
            return
        self._janela, self._hwnd = janela, hwnd
        # No laço threaded o `frameSwapped` sai da thread de render; o slot deste objeto roda na principal (fila).
        janela.frameSwapped.connect(self._quadro)
        self._prazo.start()

    def depois_de_revelar(self, funcao: Callable[[], None]) -> None:
        if self._janela is None:
            funcao()
        else:
            self._ao_revelar.append(funcao)

    @Slot()
    def _quadro(self) -> None:
        if self._janela is None:
            return
        try:
            carregando = _capa_carregando(self._janela.contentItem())
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Não foi possível conferir as capas da abertura", exc_info=True)
            self.revelar()
            return
        if carregando:
            self._pronta = False
        elif self._pronta:
            self.revelar()
        else:
            # O quadro que acabou pode ter sido desenhado antes da última capa: revela no próximo.
            self._pronta = True
            self._janela.update()

    @Slot()
    def revelar(self) -> None:
        if self._janela is None:
            return
        janela, self._janela = self._janela, None
        self._prazo.stop()
        try:
            janela.frameSwapped.disconnect(self._quadro)
        except (RuntimeError, TypeError):
            pass
        if not _cloak(self._hwnd, False):
            logging.warning("Não foi possível mostrar a janela principal pelo DWM")
        funcoes, self._ao_revelar = self._ao_revelar, []
        for funcao in funcoes:
            try:
                funcao()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha no que esperava a janela principal aparecer", exc_info=True)
