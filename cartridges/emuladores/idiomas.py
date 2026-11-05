# idiomas.py
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

"""Idiomas aceitos pela Steam, com o nome que a loja em português usa."""

import re

# "brazilian" primeiro (o idioma do app), depois por nome.
IDIOMAS: dict[str, str] = {
    "brazilian": "Português (Brasil)",
    "german": "Alemão",
    "arabic": "Árabe",
    "bulgarian": "Búlgaro",
    "schinese": "Chinês simplificado",
    "tchinese": "Chinês tradicional",
    "koreana": "Coreano",
    "danish": "Dinamarquês",
    "latam": "Espanhol (América Latina)",
    "spanish": "Espanhol (Espanha)",
    "finnish": "Finlandês",
    "french": "Francês",
    "greek": "Grego",
    "dutch": "Holandês",
    "hungarian": "Húngaro",
    "indonesian": "Indonésio",
    "english": "Inglês",
    "italian": "Italiano",
    "japanese": "Japonês",
    "norwegian": "Norueguês",
    "polish": "Polonês",
    "portuguese": "Português (Portugal)",
    "romanian": "Romeno",
    "russian": "Russo",
    "swedish": "Sueco",
    "thai": "Tailandês",
    "czech": "Tcheco",
    "turkish": "Turco",
    "ukrainian": "Ucraniano",
    "vietnamese": "Vietnamita",
}

def para_qml() -> list[dict[str, str]]:
    """As opções das telas: ``{codigo, nome}`` na ordem de ``IDIOMAS``."""
    return [{"codigo": codigo, "nome": nome} for codigo, nome in IDIOMAS.items()]


_POR_NOME = {nome: codigo for codigo, nome in IDIOMAS.items()}


def do_appdetails(texto: str) -> list[str]:
    """Os códigos dos idiomas em ``supported_languages`` (pedido com ``l=brazilian``), na ordem; nomes desconhecidos são ignorados."""
    if not isinstance(texto, str):
        return []
    # A nota final ("*idiomas com suporte total de áudio") vem depois do último <br>.
    lista = re.split(r"<br\s*/?>", texto, maxsplit=1)[0]
    nomes = (re.sub(r"<[^>]*>", "", parte).strip(" *") for parte in lista.split(","))
    return [_POR_NOME[nome] for nome in nomes if nome in _POR_NOME]
