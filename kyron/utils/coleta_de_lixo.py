# coleta_de_lixo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A coleta de lixo do Python só na thread principal.

Automática, a coleta roda na thread que estiver executando na hora. Numa thread de rede, ela destrói um `QObject` da
principal: o `QTimer` filho dele não consegue sair do dispatcher, e a principal depois entrega o evento desse timer a um
objeto morto (`access violation`).
"""

import gc

from PySide6.QtCore import QCoreApplication, QTimer

_INTERVALO_MS = 1000


def coletar_o_que_passou_do_limite() -> None:
    """A geração mais velha que passou do limite (a coleta dela inclui as mais novas)."""
    contagens, limites = gc.get_count(), gc.get_threshold()
    for geracao in (2, 1, 0):
        if contagens[geracao] > limites[geracao]:
            gc.collect(geracao)
            return


def coletar_so_na_principal(app: QCoreApplication) -> None:
    """Chamar na thread principal, uma vez, logo depois de criar o `app`."""
    gc.disable()
    temporizador = QTimer(app, interval=_INTERVALO_MS)
    temporizador.timeout.connect(coletar_o_que_passou_do_limite)
    temporizador.start()
