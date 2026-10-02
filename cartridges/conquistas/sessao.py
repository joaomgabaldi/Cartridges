"""Liga o vigia de conquistas à sessão de jogo e decide o que fazer com cada
conquista nova: o cartão por cima do jogo e o pulso na iluminação.

Quem chama é a janela, nos mesmos dois pontos em que a sessão já veste o papel
de parede e as fitas (`show_session_blocker` e `hide_session_blocker`). As
preferências são lidas na hora do aviso, então mudá-las no meio da partida
vale para a próxima conquista.
"""

import logging
from typing import Any, Optional

from cartridges import conquista_aviso, shared
from cartridges.conquistas.vigia import Desbloqueada, Vigia, acompanha
from cartridges.utils import session_fita

_vigia: Optional[Vigia] = None


def tipo_do_pulso(desbloqueada: Desbloqueada) -> str:
    if desbloqueada.completou:
        return "completo"
    if desbloqueada.info is not None and desbloqueada.info.rara:
        return "rara"
    return "normal"


def comecar(game: Any) -> None:
    """A sessão de ``game`` começou. Nunca levanta."""
    global _vigia  # pylint: disable=global-statement
    parar()
    try:
        if not acompanha(game):
            return
        _vigia = Vigia(game, _avisar)
        _vigia.iniciar()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível acompanhar as conquistas da sessão", exc_info=True)
        _vigia = None


def parar() -> None:
    """A sessão acabou (ou o app vai fechar). Nunca levanta."""
    global _vigia  # pylint: disable=global-statement
    vigia_, _vigia = _vigia, None
    try:
        if vigia_ is not None:
            vigia_.parar()
            conquista_aviso.fechar()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao encerrar o vigia de conquistas", exc_info=True)


def _avisar(desbloqueadas: list[Desbloqueada]) -> None:
    try:
        game = _vigia.game if _vigia is not None else None
        if shared.schema.get_boolean("conquistas-aviso"):
            for desbloqueada in desbloqueadas:
                aviso = conquista_aviso.Aviso.de(desbloqueada)
                if aviso is not None:
                    conquista_aviso.mostrar(aviso)
        if shared.schema.get_boolean("conquistas-iluminacao"):
            for desbloqueada in desbloqueadas:
                session_fita.pulsar_conquista(tipo_do_pulso(desbloqueada))
        if game is not None and getattr(shared.win, "active_game", None) is game:
            atualizar = getattr(shared.win, "update_conquistas_block", None)
            if atualizar is not None:
                atualizar(game)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao avisar das conquistas novas", exc_info=True)
