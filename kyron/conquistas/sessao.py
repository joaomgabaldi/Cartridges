"""Liga o vigia de conquistas à sessão de jogo e decide o que fazer com cada conquista nova: o cartão por cima do jogo e o pulso na iluminação.

A janela chama nos mesmos pontos em que a sessão veste o papel de parede e as fitas (`show_session_blocker`/`hide_session_blocker`). As preferências são lidas na hora do aviso. Nos jogos da Steam, das lojas com conta e da Ubisoft Connect só o pulso: a Steam, a Xbox Game Bar e os overlays da Epic, EA e Ubisoft já mostram o aviso.

O vigia depende do tipo da fonte gravada (`_VIGIAS`): loja com conta consulta a conta (`vigia_da_conta`), a Ubisoft olha o `.spool` (`ubisoft/vigia`), a Steam ou nenhuma olha os arquivos (`vigia`).
"""

import logging
from typing import Any, Optional

from kyron import conquista_aviso, shared
from kyron.conquistas import arquivos, fontes
from kyron.conquistas.ea import vigia as vigia_ea
from kyron.conquistas.epic import vigia as vigia_epic
from kyron.conquistas.ubisoft import vigia as vigia_ubisoft
from kyron.conquistas.vigia import Desbloqueada, Vigia, acompanha
from kyron.conquistas.xbox import vigia as vigia_xbox
from kyron.utils import session_fita

# O vigia de cada tipo de fonte que não é a Steam. `Vigia` é procurado na hora (os testes o trocam); Steam, ou nenhuma, fica com o vigia de arquivos deste módulo.
_VIGIAS = {"xbox": vigia_xbox, "epic": vigia_epic, "ea": vigia_ea, "ubisoft": vigia_ubisoft}
# Fontes cujo próprio aviso já aparece durante a partida (Xbox Game Bar, overlay da
# Epic, overlay do Ubisoft Connect): aqui, só o pulso.
_SO_PULSO = frozenset({"xbox", "epic", "ea", "ubisoft"})

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
    if _da_steam(game):
        return True
    try:
        fonte = fontes.gravada(game) if game is not None else None
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao ler a fonte das conquistas", exc_info=True)
        return False
    return fonte is not None and fonte.tipo in _SO_PULSO


def acompanhando(game: Any) -> bool:
    """Se o vigia está acompanhando ``game`` agora: durante a sessão ele é o dono do histórico do jogo, e a varredura de abertura tiraria dele a novidade a avisar."""
    vigia_ = _vigia
    return (
        vigia_ is not None
        and vigia_.ativo
        and getattr(vigia_.game, "game_id", None) == getattr(game, "game_id", object())
    )


def comecar(game: Any) -> None:
    global _vigia  # pylint: disable=global-statement
    parar()
    try:
        fonte = fontes.gravada(game)
        modulo = _VIGIAS.get(fonte.tipo) if fonte is not None else None
        if modulo is not None:
            # Sem a conta conectada (ou com o interruptor desligado), não há o que acompanhar:
            # o jogo de uma fonte com vigia próprio não cai no vigia de arquivos.
            if fontes.ativa(fonte) and getattr(game, "conquistas", True):
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
        if shared.schema.get_boolean("conquistas-iluminacao") and desbloqueadas:
            # Um lote é uma rajada: um pulso só, do tipo mais forte.
            tipos = [tipo_do_pulso(desbloqueada) for desbloqueada in desbloqueadas]
            session_fita.pulsar_conquista(max(tipos, key=session_fita.FORCA_DOS_PULSOS.index))
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao pulsar a iluminação pela conquista", exc_info=True)
    try:
        if game is not None and shared.conquistas is not None:
            shared.conquistas.mudou(game.game_id)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao atualizar as telas de conquistas", exc_info=True)
