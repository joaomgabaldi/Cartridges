# tuya_conta.py
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

"""A conta de nuvem da Tuya, salva para o assistente não pedir de novo.

O Access ID e o Access Secret só servem para a busca inicial de dispositivos (o dia a dia usa a chave local, em `fitas.json`). Gravados com o DPAPI, amarrado à conta do Windows: o arquivo vai no backup, mas o blob não decifra em outra instalação ou conta, e `carregar` devolve ``None``.
"""

import json
import logging
from typing import NamedTuple, Optional

from kyron import shared
from kyron.utils import dpapi


class Conta(NamedTuple):
    """As credenciais da nuvem, do jeito que a tela do assistente as usa."""

    chave: str
    segredo: str
    regiao: str


def salvar(conta: Conta) -> None:
    """Grava as credenciais, criptografadas. Nunca levanta.

    Por temporário e troca: uma queda no meio não pode deixar um arquivo truncado que apague a conta salva.
    """
    protegido = dpapi.proteger(json.dumps(conta._asdict()).encode("utf-8"))
    if protegido is None:
        logging.warning("Não foi possível criptografar as credenciais da Tuya")
        return

    caminho = shared.tuya_conta_arquivo
    temporario = caminho.with_name(caminho.name + ".tmp")
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_bytes(protegido)
        temporario.replace(caminho)
    except OSError as erro:
        logging.warning("Não foi possível gravar as credenciais da Tuya: %s", erro)


def carregar() -> Optional[Conta]:
    """As credenciais salvas, ou ``None`` (sem arquivo, outra conta ou PC, arquivo corrompido)."""
    try:
        protegido = shared.tuya_conta_arquivo.read_bytes()
    except FileNotFoundError:
        return None
    except OSError as erro:
        logging.warning("Conta da Tuya ilegível: %s", erro)
        return None

    dados = dpapi.abrir(protegido)
    if dados is None:
        return None
    try:
        bruto = json.loads(dados.decode("utf-8"))
        return Conta(str(bruto["chave"]), str(bruto["segredo"]), str(bruto["regiao"]))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        logging.warning("Credenciais da Tuya salvas, mas ilegíveis")
        return None
