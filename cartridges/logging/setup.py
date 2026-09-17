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

import logging
import logging.config as logging_dot_config
import os
import platform
import sys

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

    is_dev = shared.PROFILE == "development"
    profile_app_log_level = "DEBUG" if is_dev else "INFO"
    profile_lib_log_level = "INFO" if is_dev else "WARNING"
    app_log_level = os.environ.get("LOGLEVEL", profile_app_log_level).upper()
    lib_log_level = os.environ.get("LIBLOGLEVEL", profile_lib_log_level).upper()

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


def log_system_info() -> None:
    """Log system debug information"""

    logging.debug("Starting %s v%s (%s)", shared.APP_ID, shared.VERSION, shared.PROFILE)
    logging.debug("Python version: %s", sys.version)
    logging.debug("Platform: %s", platform.platform())
    for key, value in platform.uname()._asdict().items():
        logging.debug("\t%s: %s", key.title(), value)
    logging.debug("─" * 37)
