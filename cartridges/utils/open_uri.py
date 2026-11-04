# open_uri.py
#
# Copyright 2026 joaomgabaldi
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

"""Entrega uma URL ao navegador do usuário, com segurança.

As URLs vêm de feeds RSS e JSON de terceiros: só ``http``/``https`` é seguido,
para que um ``file:`` ou ``javascript:`` não vire abertura pelo sistema.
"""

import logging

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

_ALLOWED_SCHEMES = ("http://", "https://")


def abrir_url(url: str) -> bool:
    """Abre ``url`` no navegador padrão; False (e nada se abre) se vazia ou de outro esquema."""
    url = (url or "").strip()
    if not url.lower().startswith(_ALLOWED_SCHEMES):
        if url:
            logging.warning("Refusing to open URI with unexpected scheme: %r", url)
        return False
    return QDesktopServices.openUrl(QUrl(url))
