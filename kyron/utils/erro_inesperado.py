"""Avisa o usuário de um erro não tratado, num diálogo da janela principal.

Chamado pelos ganchos de exceção de `kyron.logging.setup`, de qualquer thread; o diálogo é pedido na thread da tela (com a principal escondida, abre na janela das tarefas). Sem `shared.aplicativo` ou depois do `aboutToQuit` só o log fica. Um diálogo por vez, e o mesmo erro (tipo + arquivo:linha do último quadro do app) avisa uma vez por execução; só `Exception` merece diálogo.
"""

import logging
import threading
import traceback
from pathlib import Path

from kyron import shared
from kyron.utils.thread_principal import na_thread_principal

_PACOTE = Path(__file__).resolve().parent.parent.name
_trava = threading.Lock()
_ja_avisados: set = set()
_aberto = False


def _chave(tipo, rastro) -> tuple:  # type: ignore
    try:
        quadros = traceback.extract_tb(rastro)
        # O quadro do app, não o da biblioteca onde estourou.
        do_app = [q for q in quadros if _PACOTE in Path(q.filename).parts]
        quadro = (do_app or quadros)[-1]
        return (tipo, quadro.filename, quadro.lineno)
    except Exception:  # pylint: disable=broad-exception-caught
        return (tipo, None, None)


def _liberar() -> None:
    global _aberto  # pylint: disable=global-statement
    with _trava:
        _aberto = False


def _abrir() -> None:
    """Na thread principal. Nunca levanta: um erro aqui voltaria ao gancho."""
    try:
        aplicativo = getattr(shared, "aplicativo", None)
        if aplicativo is None:  # o app fechou entre o erro e a entrega
            _liberar()
            return
        titulo = _("Ocorreu um erro inesperado")
        corpo = _("Uma ação do aplicativo não foi concluída. Os detalhes foram registrados no log.")
        from kyron.modelos import tarefas  # pylint: disable=import-outside-toplevel  # o gancho do log carrega este módulo cedo

        painel = tarefas.painel_aberto_sem_a_principal()
        if painel is not None:
            painel.pedir_aviso(titulo, corpo, _liberar)
        else:
            aplicativo.pedir_dialogo(titulo, corpo, [], _liberar)
    except Exception:  # pylint: disable=broad-exception-caught
        _liberar()
        logging.warning("Falha ao abrir o aviso de erro inesperado", exc_info=True)


def avisar(tipo, rastro) -> None:  # type: ignore
    """Agenda o diálogo, se há janela e o erro merece um. Nunca levanta."""
    global _aberto  # pylint: disable=global-statement
    try:
        if not (isinstance(tipo, type) and issubclass(tipo, Exception)):
            return
        if getattr(shared, "aplicativo", None) is None:
            return
        chave = _chave(tipo, rastro)
        with _trava:
            if _aberto or chave in _ja_avisados:
                return
            _aberto = True
            _ja_avisados.add(chave)
        try:
            na_thread_principal(_abrir)
        except Exception:  # pylint: disable=broad-exception-caught
            _liberar()
            raise
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao agendar o aviso de erro inesperado", exc_info=True)
