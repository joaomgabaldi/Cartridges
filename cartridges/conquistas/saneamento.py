"""Saneadores dos dados que vêm da rede das lojas (Xbox, Epic): data, texto, ícone."""

import calendar
import datetime
from typing import Any


def segundos_iso(texto: Any) -> int:
    """``2026-08-06T01:15:55.7870000Z`` em segundos Unix; 0 quando não vale."""
    if not isinstance(texto, str):
        return 0
    try:
        momento = datetime.datetime.strptime(texto[:19], "%Y-%m-%dT%H:%M:%S")
        # As lojas usam o ano 1 para "nunca"; nada anterior a 1971 é uma data real.
        if momento.year < 1971:
            return 0
        segundos = calendar.timegm(momento.timetuple())
    except (ValueError, OverflowError, OSError):
        return 0
    return segundos if 0 <= segundos < 2**63 else 0


def codifica(texto: str) -> bool:
    """Se o texto grava em UTF-8: `json.loads` aceita `"\\ud800"`, que não grava."""
    try:
        texto.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def limpo(texto: str) -> str:
    """O texto sem surrogate solto (vira `?`)."""
    return texto.encode("utf-8", "replace").decode("utf-8")
