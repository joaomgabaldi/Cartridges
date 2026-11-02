# setup.py
#
# Copyright 2023 Geoffrey Coulaud
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import faulthandler
import logging
import logging.config as logging_dot_config
import os
import platform
import sys
import threading

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

from cartridges import shared
from cartridges.logging import detalhado
from cartridges.logging.session_file_handler import SessionFileHandler


def _enable_windows_ansi() -> None:
    """Enable ANSI escape processing on the attached console.

    Windows Terminal handles ANSI natively, but the classic conhost only does
    so after ENABLE_VIRTUAL_TERMINAL_PROCESSING is set — without it the color
    formatter's escapes show up as literal ``←[31m`` garbage. Best effort: no
    console (pythonw) or an old console simply leaves colors off.
    """
    try:
        import ctypes  # pylint: disable=import-outside-toplevel

        kernel32 = ctypes.windll.kernel32  # type: ignore
        for std_handle in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(std_handle)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                # 0x0004 = ENABLE_VIRTUAL_TERMINAL_PROCESSING
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:  # pylint: disable=broad-exception-caught
        pass


# Bibliotecas barulhentas, silenciadas aqui em vez de na raiz. Módulo, e não
# variável local de `setup_logging`, para que um teste consiga prender o nível
# de cada uma sem ter de chamar o `dictConfig` de verdade — que reconfigura o
# logging do processo inteiro.
LIB_LOGGERS = {
    "PIL": {
        "handlers": ["lib_console_handler", "file_handler"],
        "propagate": False,
        "level": "WARNING",
    },
    "urllib3": {
        "handlers": ["lib_console_handler", "file_handler"],
        "propagate": False,
        # Explicitly INFO, not NOTSET. NOTSET means "ask my parent",
        # and the parent here is the root at NOTSET too, i.e. level 0,
        # i.e. everything passes — so urllib3's DEBUG went straight
        # into file_handler, which sits at DEBUG. That is one
        # "Starting new HTTPS connection" plus a request line per cover
        # download, per SteamGridDB lookup, per HowLongToBeat query and
        # per poll, and it buried the app's own lines in the session
        # log people attach to bug reports. `propagate: False` never
        # helped: file_handler is attached right here, not inherited.
        # The root is deliberately left at NOTSET — the app's own
        # DEBUG output is the reason the file handler exists.
        "level": "INFO",
    },
    "tinytuya": {
        "handlers": ["lib_console_handler", "file_handler"],
        "propagate": False,
        # WARNING é obrigatório aqui, e não uma questão de ruído: em DEBUG a
        # tinytuya loga o dicionário de cabeçalhos inteiro de cada chamada à
        # nuvem, e enquanto ela ainda não tem token esse dicionário carrega a
        # API Secret da conta em claro. Sem esta entrada o logger cai na raiz,
        # que está em NOTSET (tudo passa) e alimenta o `file_handler`, que está
        # em DEBUG — ou seja, a Secret iria parar no `cartridges.log`, que é
        # justamente o arquivo que as pessoas anexam a relatório de bug. O
        # nível cobre os sub-loggers da biblioteca por herança.
        "level": "WARNING",
    },
}


def setup_logging() -> None:
    """Intitate the app's logging"""

    _enable_windows_ansi()

    app_log_level = os.environ.get("LOGLEVEL", "INFO").upper()
    lib_log_level = os.environ.get("LIBLOGLEVEL", "WARNING").upper()

    log_filename = shared.log_dir / "cartridges.log"

    config = {
        "version": 1,
        "formatters": {
            "file_formatter": {
                "format": "%(asctime)s - %(levelname)s: %(message)s",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "console_formatter": {
                "format": "%(name)s %(levelname)s - %(message)s",
                "class": "cartridges.logging.color_log_formatter.ColorLogFormatter",
            },
        },
        "handlers": {
            "file_handler": {
                "class": "cartridges.logging.session_file_handler.SessionFileHandler",
                "formatter": "file_formatter",
                "level": "DEBUG",
                "filename": log_filename,
                "backup_count": 2,
            },
            "app_console_handler": {
                "class": "logging.StreamHandler",
                "formatter": "console_formatter",
                "level": app_log_level,
            },
            "lib_console_handler": {
                "class": "logging.StreamHandler",
                "formatter": "console_formatter",
                "level": lib_log_level,
            },
        },
        "loggers": LIB_LOGGERS,
        "root": {
            "level": "NOTSET",
            "handlers": ["app_console_handler", "file_handler"],
        },
    }
    logging_dot_config.dictConfig(config)
    _ligar_rastreio()
    registrar_excecoes_nao_tratadas()
    registrar_avisos_do_qt()
    for handler in logging.getLogger().handlers:
        if isinstance(handler, SessionFileHandler):
            registrar_quedas_nativas(handler.log_file)


def _ligar_rastreio() -> None:
    """Liga o log detalhado, se ativo. Outra ferramenta com o mesmo id (cProfile) só gera um aviso."""
    if not detalhado.ativo():
        return
    try:
        detalhado.instalar_rastreio()
    except ValueError:
        logging.warning("Log detalhado desligado: outra ferramenta de monitoramento (cProfile, p.ex.) está em uso")


def registrar_excecoes_nao_tratadas() -> None:
    """Grava no log todo erro não tratado, do thread principal ou de outro.

    Depois de gravar, avisa o usuário num diálogo (o `unraisablehook` não: erro
    num `__del__` não é uma ação do usuário que falhou).

    O padrão do Python só escreve no stderr, e o app instalado roda no
    pythonw, sem console: um erro num slot do Qt (abrir a tela de edição,
    salvar) sumia sem deixar rastro no `cartridges.log`. O PySide entrega
    esses erros ao `sys.excepthook`.
    """

    def registrar(tipo, valor, rastro) -> None:  # type: ignore
        logging.critical("Erro não tratado", exc_info=(tipo, valor, rastro))
        try:
            # Import tardio: o módulo de logging não depende da tela no import.
            from cartridges.utils import erro_inesperado  # pylint: disable=import-outside-toplevel

            erro_inesperado.avisar(tipo, rastro)
        except Exception:  # pylint: disable=broad-exception-caught
            # No encerramento do interpretador o import pode falhar.
            pass

    def da_thread(args) -> None:  # type: ignore
        # Como o padrão do Python: o SystemExit de uma thread é só o fim dela.
        if args.exc_type is not SystemExit:
            registrar(args.exc_type, args.exc_value, args.exc_traceback)

    sys.excepthook = registrar
    threading.excepthook = da_thread
    # Erros que não sobem para ninguém (num __del__, na coleta de lixo): o
    # Python os entrega a este gancho, que por padrão também só usa o stderr.
    sys.unraisablehook = lambda u: logging.critical(
        "Erro não tratado (não levantável): %s",
        u.err_msg or "exceção ignorada",
        exc_info=(u.exc_type, u.exc_value, u.exc_traceback),
    )


def registrar_quedas_nativas(arquivo) -> None:  # type: ignore
    """Grava no ``arquivo`` a pilha de uma queda nativa (C, driver, Qt).

    Uma queda dessas mata o processo sem passar pelo Python, e o log ficava
    parado na última linha normal. O ``faulthandler`` escreve direto no
    descritor do arquivo, por isso precisa do arquivo que continua aberto.
    """
    faulthandler.enable(file=arquivo, all_threads=True)


# Informação, aviso, crítico e fatal; a depuração do Qt fica de fora, como antes.
_NIVEIS_DO_QT = {
    QtMsgType.QtInfoMsg: ("INFO", logging.INFO),
    QtMsgType.QtWarningMsg: ("WARNING", logging.WARNING),
    QtMsgType.QtCriticalMsg: ("CRITICAL", logging.ERROR),
    QtMsgType.QtFatalMsg: ("FATAL", logging.CRITICAL),
}
_qt_registrado = False
# Um aviso do Qt nascido enquanto outro é registrado (um handler do log que mexe no Qt) não é registrado: sem laço.
_registrando = threading.local()


def _registrar_do_qt(tipo, contexto, mensagem) -> None:  # type: ignore
    """O gancho de mensagens do Qt: roda em qualquer thread e nunca levanta."""
    if getattr(_registrando, "ativo", False):
        return
    _registrando.ativo = True
    try:
        if (nivel := _NIVEIS_DO_QT.get(tipo)) is None:
            return
        nome, nivel_do_log = nivel
        # O arquivo QML e a linha, quando o Qt os informa e a mensagem ainda não os traz (o `console.warn`).
        arquivo = getattr(contexto, "file", None)
        onde = f" ({arquivo}:{contexto.line})" if arquivo and arquivo not in mensagem else ""
        logging.log(nivel_do_log, "Qt-%s: %s%s", nome, mensagem, onde)
    except Exception:  # pylint: disable=broad-exception-caught
        pass
    finally:
        _registrando.ativo = False


def registrar_avisos_do_qt() -> None:
    """Grava no log os avisos do Qt e do QML.

    Pelo mesmo motivo de `registrar_excecoes_nao_tratadas`: o padrão é o
    stderr, e o pythonw não tem console. Um aviso do QML é o rastro típico de
    uma tela que parou de responder. Só age na primeira chamada.
    """
    global _qt_registrado  # pylint: disable=global-statement
    if _qt_registrado:
        return
    _qt_registrado = True
    qInstallMessageHandler(_registrar_do_qt)


def log_system_info() -> None:
    """Log system debug information"""

    logging.debug("Starting %s v%s", shared.APP_ID, shared.VERSION)
    logging.debug("Python version: %s", sys.version)
    logging.debug("Platform: %s", platform.platform())
    for key, value in platform.uname()._asdict().items():
        logging.debug("\t%s: %s", key.title(), value)
    logging.debug("─" * 37)
