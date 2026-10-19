"""Avisa o usuário de um erro não tratado, num diálogo da janela principal.

Chamado pelos ganchos de exceção de `cartridges.logging.setup`, de qualquer
thread: o diálogo sempre é aberto na thread da tela, via `GLib.idle_add`.
Sem enxurrada: um diálogo aberto por vez, e o mesmo erro (tipo + arquivo:linha
do último quadro do app) só avisa uma vez por execução do app. Só `Exception`
merece diálogo: `KeyboardInterrupt`, `SystemExit` e afins só vão para o log.
"""

import logging
import threading
import traceback
from pathlib import Path

from gi.repository import GLib

from cartridges import shared
from cartridges.utils.create_dialog import create_dialog

_PACOTE = Path(__file__).resolve().parent.parent.name
_trava = threading.Lock()
_ja_avisados: set = set()
_aberto = False


def _chave(tipo, rastro) -> tuple:  # type: ignore
    try:
        quadros = traceback.extract_tb(rastro)
        # O quadro do app, não o da biblioteca (requests, GTK) onde estourou.
        do_app = [q for q in quadros if _PACOTE in Path(q.filename).parts]
        quadro = (do_app or quadros)[-1]
        return (tipo, quadro.filename, quadro.lineno)
    except Exception:  # pylint: disable=broad-exception-caught
        return (tipo, None, None)


def _liberar() -> None:
    global _aberto  # pylint: disable=global-statement
    with _trava:
        _aberto = False


def _abrir(janela) -> bool:  # type: ignore
    try:
        dialogo = create_dialog(
            janela,
            _("Ocorreu um erro inesperado"),
            _("Uma ação do aplicativo não foi concluída. Os detalhes foram registrados no log."),
        )
        dialogo.connect("closed", lambda *_a: _liberar())
    except Exception:  # pylint: disable=broad-exception-caught
        _liberar()
        logging.warning("Falha ao abrir o aviso de erro inesperado", exc_info=True)
    return False


def _janela_para_o_dialogo():  # type: ignore
    """A principal; se ela está escondida (backup de saída), a ativa do app."""
    janela = getattr(shared, "win", None)
    if janela is not None and hasattr(janela, "is_visible") and not janela.is_visible():
        ativa = janela.get_application().get_active_window()
        if ativa is not None:
            return ativa
    return janela


def avisar(tipo, rastro) -> None:  # type: ignore
    """Agenda o diálogo, se há janela e o erro merece um. Nunca levanta."""
    global _aberto  # pylint: disable=global-statement
    try:
        if not (isinstance(tipo, type) and issubclass(tipo, Exception)):
            return
        janela = _janela_para_o_dialogo()
        if janela is None:
            return
        chave = _chave(tipo, rastro)
        with _trava:
            if _aberto or chave in _ja_avisados:
                return
            _aberto = True
            _ja_avisados.add(chave)
        try:
            GLib.idle_add(_abrir, janela)
        except Exception:  # pylint: disable=broad-exception-caught
            _liberar()
            raise
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao agendar o aviso de erro inesperado", exc_info=True)
