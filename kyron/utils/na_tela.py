# na_tela.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Entrega do resultado de uma thread à tela, sem ficar atrás do redesenho."""

from typing import Any, Callable

from kyron.utils.thread_principal import na_thread_principal


def entregar_na_tela(func: Callable[..., Any], *args: Any) -> None:
    """Agenda ``func(*args)`` na thread principal, na ordem das chamadas e sem esperar o redesenho."""
    na_thread_principal(func, *args)
