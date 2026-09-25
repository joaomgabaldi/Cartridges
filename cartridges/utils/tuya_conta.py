# tuya_conta.py
#
# Copyright 2026 kramo
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

O Access ID e o Access Secret vêm do painel de desenvolvedor da Tuya — não do
app Smart Life — e só servem para a busca inicial de dispositivos; o dia a dia
das fitas fala direto com a chave local, gravada à parte em `fitas.json`. Sem
isto salvo, todo IP trocado ou fita nova obrigaria a voltar ao painel da Tuya
para pegar os dois códigos de novo.

Gravados com o DPAPI do Windows (`CryptProtectData`), amarrado à conta do
Windows de quem roda o app: decifra só quem já é esse usuário, neste PC — o
mesmo modelo de um navegador guardando senha salva. Por isso o arquivo mora à
parte e fora do backup do app: um blob DPAPI não decifra numa instalação nova
nem numa conta diferente, então não pertenceria a um backup portátil mesmo se
entrasse nele.
"""

import ctypes
import json
import logging
from ctypes import wintypes
from typing import Any, NamedTuple, Optional

from cartridges import shared

_crypt32 = ctypes.windll.crypt32  # type: ignore
_kernel32 = ctypes.windll.kernel32  # type: ignore


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


# As duas funções têm a mesma forma no que interessa aqui: o segundo, terceiro,
# quarto e quinto parâmetros só recebem `None` nas chamadas deste módulo (sem
# descrição, sem entropia extra, sem prompt), então uma assinatura serve às
# duas — a diferença real entre elas (o `ppszDataDescr` de saída da
# `CryptUnprotectData`) nunca é usada.
_ARGTYPES = [
    ctypes.POINTER(_DATA_BLOB),
    wintypes.LPCWSTR,
    ctypes.POINTER(_DATA_BLOB),
    wintypes.LPVOID,
    wintypes.LPVOID,
    wintypes.DWORD,
    ctypes.POINTER(_DATA_BLOB),
]
_crypt32.CryptProtectData.argtypes = _ARGTYPES
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = _ARGTYPES
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [wintypes.LPVOID]
_kernel32.LocalFree.restype = wintypes.LPVOID


class Conta(NamedTuple):
    """As credenciais da nuvem, do jeito que a tela do assistente as usa."""

    chave: str
    segredo: str
    regiao: str


def _blob(dados: bytes) -> tuple[_DATA_BLOB, Any]:
    """Um DATA_BLOB apontando para ``dados``, com o buffer que o sustenta.

    O DATA_BLOB só guarda o ponteiro, não o dono da memória — sem uma
    referência Python viva ao buffer enquanto a chamada ao DPAPI está em
    curso, o coletor de lixo pode liberá-lo antes da leitura.
    """
    buffer = ctypes.create_string_buffer(dados, len(dados))
    return _DATA_BLOB(len(dados), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _chamar(funcao: Any, dados: bytes) -> Optional[bytes]:
    """Roda ``CryptProtectData`` ou ``CryptUnprotectData`` sobre ``dados``."""
    entrada, _buffer = _blob(dados)
    saida = _DATA_BLOB()
    if not funcao(ctypes.byref(entrada), None, None, None, None, 0, ctypes.byref(saida)):
        return None
    try:
        return ctypes.string_at(saida.pbData, saida.cbData)
    finally:
        _kernel32.LocalFree(saida.pbData)


def salvar(conta: Conta) -> None:
    """Grava as credenciais, criptografadas. Nunca levanta.

    Pelo temporário e troca, como o resto do que o app grava: uma queda de
    energia no meio não pode deixar um arquivo truncado que nem o DPAPI nem o
    JSON leem de volta, apagando a conta salva sem aviso nenhum.
    """
    protegido = _chamar(
        _crypt32.CryptProtectData, json.dumps(conta._asdict()).encode("utf-8")
    )
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
    """As credenciais salvas, ou ``None``.

    ``None`` sem arquivo, sem chave do Windows que abra o blob (outra conta,
    outro PC), ou com o arquivo corrompido — em todos os casos o assistente
    volta a pedir os códigos, como se nada tivesse sido salvo.
    """
    try:
        protegido = shared.tuya_conta_arquivo.read_bytes()
    except OSError:
        return None

    dados = _chamar(_crypt32.CryptUnprotectData, protegido)
    if dados is None:
        return None
    try:
        bruto = json.loads(dados.decode("utf-8"))
        return Conta(str(bruto["chave"]), str(bruto["segredo"]), str(bruto["regiao"]))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        logging.warning("Credenciais da Tuya salvas, mas ilegíveis")
        return None
