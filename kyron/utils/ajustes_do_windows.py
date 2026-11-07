# ajustes_do_windows.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os ajustes do Windows relidos com o app aberto.

O Windows avisa toda janela de topo com um `WM_SETTINGCHANGE` quando um ajuste muda. O tema o Qt já segue;
as animações (`SPI_GETCLIENTAREAANIMATION`) e o realce são relidos por nós, e este filtro diz quando.
O Qt entrega a variante clara do realce no tema escuro, por isso se usa o `AccentColor` cru do registro.
"""

import logging
import winreg
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication, QMetaObject
from PySide6.QtGui import QColor, QGuiApplication, QPalette
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickWindow

from kyron.utils.thread_principal import na_thread_principal

_WM_SETTINGCHANGE = 0x001A
_CLIQUES_NA_MOLDURA = {0x00A1, 0x00A4}  # WM_NCLBUTTONDOWN, WM_NCRBUTTONDOWN
_FECHA_COM_CLIQUE_FORA = 0x1 | 0x2  # Popup.CloseOnPressOutside | Popup.CloseOnPressOutsideParent
_GENERICA = b"windows_generic_MSG"


def cor_de_destaque() -> str | None:
    """O `AccentColor` do Windows, como `#rrggbb` (o DWORD vem como 0xAABBGGRR); None se não houver."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as chave:
            valor = winreg.QueryValueEx(chave, "AccentColor")[0]
    except OSError:
        return None
    if not isinstance(valor, int):  # REG_SZ/REG_BINARY de um tema de terceiros
        return None
    return f"#{valor & 0xFF:02x}{(valor >> 8) & 0xFF:02x}{(valor >> 16) & 0xFF:02x}"


def aplicar_cor_de_destaque() -> None:
    """Põe o realce do registro na paleta do app, de onde o `Tema` o lê."""
    if (cor := cor_de_destaque()) is None:
        return
    paleta = QGuiApplication.palette()
    if paleta.color(QPalette.ColorRole.Accent) != QColor(cor):
        paleta.setColor(QPalette.ColorRole.Accent, QColor(cor))
        QGuiApplication.setPalette(paleta)


def e_mudanca_de_ajuste(tipo, mensagem) -> bool:  # noqa: ANN001
    """Se a mensagem nativa (o endereço de um `MSG`) é um `WM_SETTINGCHANGE`.

    O PySide entrega o `QByteArray` e um `shiboken6.VoidPtr`, cujo `bool()` é falso mesmo com endereço: só o `int()`.
    """
    if bytes(tipo) != _GENERICA or not (endereco := int(mensagem)):
        return False
    return wintypes.MSG.from_address(endereco).message == _WM_SETTINGCHANGE


def janela_clicada_na_moldura(tipo, mensagem) -> int | None:  # noqa: ANN001
    """O `HWND` de um clique na moldura (a barra responde `HTCAPTION`: esse clique nunca vira evento de mouse do Qt)."""
    if bytes(tipo) != _GENERICA or not (endereco := int(mensagem)):
        return None
    msg = wintypes.MSG.from_address(endereco)
    return msg.hWnd if msg.message in _CLIQUES_NA_MOLDURA else None


def fechar_menus_da_janela(hwnd: int) -> None:
    """Fecha o que fecharia com um clique fora: os popups abertos ficam no `Overlay` da janela, cada um como pai do seu item."""
    try:
        for janela in QGuiApplication.topLevelWindows():
            if isinstance(janela, QQuickWindow) and janela.isVisible() and int(janela.winId()) == hwnd:
                for overlay in janela.contentItem().childItems():
                    if overlay.inherits("QQuickOverlay"):
                        for item in overlay.childItems():
                            popup = item.parent()
                            # Sem contexto, o construtor do `QQmlExpression` derruba o processo em vez de levantar.
                            if popup is not None and popup.inherits("QQuickPopup") and (contexto := QQmlEngine.contextForObject(popup)) is not None:
                                # Pela expressão: o PySide não converte o `QFlags` de `property("closePolicy")`.
                                politica, _indefinida = QQmlExpression(contexto, popup, "closePolicy").evaluate()
                                if politica & _FECHA_COM_CLIQUE_FORA:
                                    QMetaObject.invokeMethod(popup, "close")
    except Exception:  # noqa: BLE001  # fora do filtro: subiria ao diálogo de erro inesperado, e fechar um menu não justifica isso
        logging.warning("Falha ao fechar os menus da janela", exc_info=True)


class FiltroDeAjustes(QAbstractNativeEventFilter):
    """A cada `WM_SETTINGCHANGE`, chama ``ao_mudar`` pela thread principal; a cada clique na moldura, fecha os menus da janela.

    Roda no procedimento da janela, em toda mensagem nativa: nunca consome nenhuma nem levanta.
    Várias janelas recebem a mesma mudança: quem relê só avisa se o valor mudou.
    """

    def __init__(self, ao_mudar: Callable[[], None], ao_clicar_na_moldura: Callable[[int], None] = fechar_menus_da_janela) -> None:
        super().__init__()
        self._ao_mudar = ao_mudar
        self._ao_clicar_na_moldura = ao_clicar_na_moldura

    def nativeEventFilter(self, tipo, mensagem) -> tuple[bool, int]:  # noqa: N802, ANN001
        try:
            if e_mudanca_de_ajuste(tipo, mensagem):
                na_thread_principal(self._ao_mudar)
            elif (hwnd := janela_clicada_na_moldura(tipo, mensagem)) is not None:
                na_thread_principal(self._ao_clicar_na_moldura, hwnd)  # fora do filtro: o Windows ainda vai começar o arrasto
        except Exception:  # noqa: BLE001
            logging.warning("Falha ao ler uma mensagem do Windows", exc_info=True)
        return False, 0

    def desligar(self) -> None:
        """O Qt guarda só o ponteiro: o filtro sai antes de o objeto Python poder morrer."""
        if (app := QCoreApplication.instance()) is not None:
            app.removeNativeEventFilter(self)
