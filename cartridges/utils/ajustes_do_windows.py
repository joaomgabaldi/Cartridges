# ajustes_do_windows.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os ajustes do Windows relidos com o app aberto (D88).

O Windows avisa toda janela de topo com um `WM_SETTINGCHANGE` quando um ajuste do sistema muda (os "Efeitos de
animação", entre outros). O tema o Qt já segue sozinho; as animações são lidas por nós
(`SPI_GETCLIENTAREAANIMATION`), e este filtro diz quando relê-las. O realce também: o Qt entrega a variante clara
dele no tema escuro, e a `main` usa o `AccentColor` cru do registro.
"""

import logging
import winreg
from collections.abc import Callable
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QCoreApplication
from PySide6.QtGui import QColor, QGuiApplication, QPalette

from cartridges.utils.thread_principal import na_thread_principal

_WM_SETTINGCHANGE = 0x001A
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
    """Põe o realce do registro na paleta do app, de onde o `Tema` o lê (`apply_windows_theme` da `main`)."""
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


class FiltroDeAjustes(QAbstractNativeEventFilter):
    """Instalado no app: a cada `WM_SETTINGCHANGE` de uma janela dele, chama ``ao_mudar`` pela thread principal.

    Roda dentro do procedimento da janela, em toda mensagem nativa: nunca consome nenhuma, nunca levanta, e o retorno
    vai para a fila (fora do procedimento da janela). Várias janelas recebem a mesma mudança: quem relê só avisa se
    o valor mudou.
    """

    def __init__(self, ao_mudar: Callable[[], None]) -> None:
        super().__init__()
        self._ao_mudar = ao_mudar

    def nativeEventFilter(self, tipo, mensagem) -> tuple[bool, int]:  # noqa: N802, ANN001
        try:
            if e_mudanca_de_ajuste(tipo, mensagem):
                na_thread_principal(self._ao_mudar)
        except Exception:  # noqa: BLE001
            logging.warning("Falha ao ler uma mensagem do Windows", exc_info=True)
        return False, 0

    def desligar(self) -> None:
        """Sai do app. O Qt guarda só o ponteiro: o filtro sai antes de o objeto Python poder morrer."""
        if (app := QCoreApplication.instance()) is not None:
            app.removeNativeEventFilter(self)
