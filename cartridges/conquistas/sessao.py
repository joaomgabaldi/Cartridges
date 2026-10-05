"""Liga o vigia de conquistas à sessão de jogo e decide o que fazer com cada
conquista nova: o cartão por cima do jogo e o pulso na iluminação.

Quem chama é a janela, nos mesmos dois pontos em que a sessão já veste o papel
de parede e as fitas (`show_session_blocker` e `hide_session_blocker`). As
preferências são lidas na hora do aviso, então mudá-las no meio da partida
vale para a próxima conquista. Nos jogos da Steam e das lojas com conta (Xbox,
Epic), só o pulso: a Steam, a Xbox Game Bar e o overlay da Epic já mostram o
aviso delas.

O vigia depende da fonte gravada do jogo: a de uma loja com conta consulta a
conta (`vigia_da_conta`); a da Steam, ou nenhuma, olha os arquivos (`vigia`).
"""

import logging
from typing import Any, Optional

from cartridges import conquista_aviso, shared
from cartridges.conquistas import arquivos, contas, fontes
from cartridges.conquistas.vigia import Desbloqueada, Vigia, acompanha
from cartridges.conquistas.xbox import vigia as vigia_xbox
from cartridges.utils import session_fita

# O módulo do vigia de cada loja com conta. `Vigia` é procurado na hora (os testes o trocam).
_VIGIAS = {"xbox": vigia_xbox}

# Os vigias (arquivos e de cada loja com conta) têm o mesmo contrato: `game`, `ativo`, `iniciar` e `parar`.
_vigia: Optional[Any] = None


def tipo_do_pulso(desbloqueada: Desbloqueada) -> str:
    if desbloqueada.completou:
        return "completo"
    if desbloqueada.info is not None and desbloqueada.info.rara:
        return "rara"
    return "normal"


def _da_steam(game: Any) -> bool:
    return game is not None and arquivos.eh_jogo_da_steam(getattr(game, "executable", "") or "")


def _so_pulso(game: Any) -> bool:
    """Steam e as lojas com conta já mostram o aviso delas: aqui, só o pulso."""
    if _da_steam(game):
        return True
    try:
        fonte = fontes.gravada(game) if game is not None else None
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao ler a fonte das conquistas", exc_info=True)
        return False
    return contas.da_fonte(fonte) is not None


def acompanhando(game: Any) -> bool:
    """Se o vigia está acompanhando ``game`` agora.

    Durante a sessão o vigia é o dono do histórico do jogo: quem mais grava ali
    (a varredura de abertura) tira dele a novidade que ele ia avisar.
    """
    vigia_ = _vigia
    return (
        vigia_ is not None
        and vigia_.ativo
        and getattr(vigia_.game, "game_id", None) == getattr(game, "game_id", object())
    )


def comecar(game: Any) -> None:
    """A sessão de ``game`` começou. Nunca levanta."""
    global _vigia  # pylint: disable=global-statement
    parar()
    try:
        fonte = fontes.gravada(game)
        if contas.da_fonte(fonte) is not None:
            # Sem a conta conectada (ou com o interruptor desligado), não há o que acompanhar:
            # o jogo de uma loja com conta não cai no vigia de arquivos.
            modulo = _VIGIAS.get(fonte.tipo)
            if modulo is not None and fontes.ativa(fonte) and getattr(game, "conquistas", True):
                _vigia = modulo.Vigia(game, _avisar)
                _vigia.iniciar()
            return
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
    if vigia_ is None:
        return
    # Cada um no seu try: falhar o vigia não pode deixar cartões aparecendo
    # depois do fim do jogo.
    try:
        vigia_.parar()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao encerrar o vigia de conquistas", exc_info=True)
    try:
        conquista_aviso.fechar()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao fechar os avisos de conquista", exc_info=True)


def _avisar(desbloqueadas: list[Desbloqueada]) -> None:
    # Um try por efeito: a falha de um não cala os outros.
    game = _vigia.game if _vigia is not None else None
    try:
        if shared.schema.get_boolean("conquistas-aviso") and not _so_pulso(game):
            for desbloqueada in desbloqueadas:
                aviso = conquista_aviso.Aviso.de(desbloqueada)
                if aviso is not None:
                    conquista_aviso.mostrar(aviso)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao mostrar o aviso de conquista", exc_info=True)
    try:
        if shared.schema.get_boolean("conquistas-iluminacao"):
            for desbloqueada in desbloqueadas:
                session_fita.pulsar_conquista(tipo_do_pulso(desbloqueada))
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao pulsar a iluminação pela conquista", exc_info=True)
    try:
        if game is not None and getattr(shared.win, "active_game", None) is game:
            atualizar = getattr(shared.win, "update_conquistas_block", None)
            if atualizar is not None:
                atualizar(game)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao atualizar a página de conquistas", exc_info=True)
