"""O que as contas das lojas (Xbox, Epic) fazem igual quando conectam ou desconectam:
a lista de ouvintes, o aviso de desconexão (uma vez) e o cartão do jogo aberto.

O estado (a lista e o "já avisou") fica em cada `conta.py`, que os testes trocam.
"""

import logging
from typing import Callable

from gi.repository import Adw

from cartridges import shared


def inscrever(ouvintes: list[Callable[[], None]], ouvinte: Callable[[], None]) -> Callable[[], None]:
    """Põe ``ouvinte`` em ``ouvintes`` e devolve a função que o tira (pode ser chamada de novo)."""
    ouvintes.append(ouvinte)

    def remover() -> None:
        try:
            ouvintes.remove(ouvinte)
        except ValueError:
            pass

    return remover


def notificar(
    avisar: bool, ja_avisou: bool, ouvintes: list[Callable[[], None]], aviso: str, nome: str
) -> bool:
    """Na thread principal: o ``aviso`` (se ``avisar`` e ainda não avisado), os
    ouvintes e o cartão do jogo aberto. Devolve se a desconexão já foi avisada.

    Nunca levanta: um ouvinte que falha não cala os outros. ``nome`` é o da conta, para o log.
    """
    try:
        if avisar and not ja_avisou and shared.win is not None:
            ja_avisou = True
            toast = Adw.Toast.new(aviso)
            toast.set_use_markup(False)
            shared.win.toast_queue.add(toast)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao avisar da desconexão da conta %s", nome, exc_info=True)
    for ouvinte in list(ouvintes):
        try:
            ouvinte()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha num ouvinte da conta %s", nome, exc_info=True)
    try:
        game = getattr(shared.win, "active_game", None)
        atualizar = getattr(shared.win, "update_conquistas_block", None)
        if game is not None and atualizar is not None:
            atualizar(game)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao atualizar o cartão de conquistas", exc_info=True)
    return ja_avisou
