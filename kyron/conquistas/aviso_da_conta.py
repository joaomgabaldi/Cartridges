"""O que as contas das lojas (Xbox, Epic, EA) fazem igual quando conectam ou desconectam:
a lista de ouvintes, o aviso de desconexão (uma vez) e o cartão do jogo aberto.

O estado (a lista e o "já avisou") fica em cada `conta.py`, que os testes trocam.
"""

import logging
from typing import Callable

from kyron import shared


def inscrever(ouvintes: list[Callable[[], None]], ouvinte: Callable[[], None]) -> Callable[[], None]:
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
    """Na thread principal: o ``aviso`` (se ``avisar`` e ainda não avisado), os ouvintes e o cartão do jogo aberto; devolve se a desconexão já foi avisada. Nunca levanta (um ouvinte que falha não cala os outros); ``nome`` é o da conta, para o log."""
    try:
        if avisar and not ja_avisou and shared.aplicativo is not None:
            ja_avisou = True
            shared.aplicativo.avisos.adicionar(aviso)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao avisar da desconexão da conta %s", nome, exc_info=True)
    for ouvinte in list(ouvintes):
        try:
            ouvinte()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha num ouvinte da conta %s", nome, exc_info=True)
    try:
        if shared.conquistas is not None:
            shared.conquistas.mudou(None)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao atualizar o cartão de conquistas", exc_info=True)
    return ja_avisou
