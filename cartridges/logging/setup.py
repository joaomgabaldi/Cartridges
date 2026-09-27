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

import ctypes
import logging
import logging.config as logging_dot_config
import os
import platform
import sys
import threading

from gi.repository import GLib

from cartridges import shared


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
    registrar_excecoes_nao_tratadas()
    registrar_avisos_do_glib()


def registrar_excecoes_nao_tratadas() -> None:
    """Grava no log todo erro não tratado, do thread principal ou de outro.

    O padrão do Python só escreve no stderr, e o app instalado roda no
    pythonw, sem console: um erro num callback do GTK (abrir a tela de edição,
    salvar) sumia sem deixar rastro no `cartridges.log`. O PyGObject entrega
    esses erros ao `sys.excepthook`.
    """

    def registrar(tipo, valor, rastro) -> None:  # type: ignore
        logging.critical("Erro não tratado", exc_info=(tipo, valor, rastro))

    sys.excepthook = registrar
    threading.excepthook = lambda args: registrar(
        args.exc_type, args.exc_value, args.exc_traceback
    )


# Erro, crítico, aviso e mensagem; depuração e informação o GLib já descarta
# por padrão, e continuam descartadas.
_NIVEIS_DO_GLIB = (
    (GLib.LogLevelFlags.LEVEL_ERROR, "ERROR", logging.ERROR),
    (GLib.LogLevelFlags.LEVEL_CRITICAL, "CRITICAL", logging.ERROR),
    (GLib.LogLevelFlags.LEVEL_WARNING, "WARNING", logging.WARNING),
    (GLib.LogLevelFlags.LEVEL_MESSAGE, "MESSAGE", logging.INFO),
)


def _campo(campos, chave: str) -> str:  # type: ignore
    """O valor de um campo do GLib, lido como UTF-8.

    Não `GLib.log_writer_format_fields`: ele devolve o texto na codificação do
    Windows, e qualquer acento na mensagem (UTF-8 no GTK) quebrava a leitura.
    """
    for campo in campos:
        if campo.key == chave and campo.value:
            if campo.length < 0:
                bruto = ctypes.string_at(campo.value)
            else:
                bruto = ctypes.string_at(campo.value, campo.length)
            return bruto.decode("utf-8", errors="replace")
    return ""
_glib_registrado = False


def registrar_avisos_do_glib() -> None:
    """Grava no log os avisos do GTK, do GLib e do Adwaita.

    Pelo mesmo motivo de `registrar_excecoes_nao_tratadas`: o padrão é o
    stderr, e o pythonw não tem console. Um `Gtk-CRITICAL` é o rastro típico de
    uma tela que parou de responder. Só age na primeira chamada: o GLib aborta
    o processo se o destino dos avisos for trocado duas vezes.
    """
    global _glib_registrado  # pylint: disable=global-statement
    if _glib_registrado:
        return
    _glib_registrado = True

    def registrar(nivel, campos, _n, _dados):  # type: ignore
        for bandeira, nome, nivel_do_log in _NIVEIS_DO_GLIB:
            if nivel & bandeira:
                dominio = _campo(campos, "GLIB_DOMAIN") or "GLib"
                mensagem = _campo(campos, "MESSAGE")
                logging.log(nivel_do_log, "%s-%s: %s", dominio, nome, mensagem)
                break
        return GLib.LogWriterOutput.HANDLED

    GLib.log_set_writer_func(registrar, None)


def log_system_info() -> None:
    """Log system debug information"""

    logging.debug("Starting %s v%s", shared.APP_ID, shared.VERSION)
    logging.debug("Python version: %s", sys.version)
    logging.debug("Platform: %s", platform.platform())
    for key, value in platform.uname()._asdict().items():
        logging.debug("\t%s: %s", key.title(), value)
    logging.debug("─" * 37)
