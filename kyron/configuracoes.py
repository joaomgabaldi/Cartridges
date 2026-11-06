# configuracoes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

r"""Preferências no registro do Windows (`HKCU\<subchave>`), com tipo e padrão de cada chave vindos do gschema; compatível com a versão anterior (GTK)."""

import ast
import logging
import winreg
import xml.etree.ElementTree as ET
from collections.abc import Callable
from functools import cache
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from kyron.utils.thread_principal import eh_thread_principal, na_thread_principal

# `kyron` é um pacote sem `__init__` (sem `__file__`): parte deste arquivo.
_GSCHEMA = (
    Path(__file__).resolve().parent.parent / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml.in"
)

# tipo GVariant -> (tipo no registro, bits)
_TIPOS = {
    "b": (winreg.REG_DWORD, 1),
    "i": (winreg.REG_DWORD, 32),
    "u": (winreg.REG_DWORD, 32),
    "x": (winreg.REG_QWORD, 64),
    "s": (winreg.REG_SZ, 0),
}


def _padrao(tipo: str, texto: str) -> bool | int | str:
    if tipo == "b":
        return {"true": True, "false": False}[texto]
    if tipo == "s":
        return ast.literal_eval(texto)  # "texto" ou 'texto'
    return int(texto)


@cache
def _esquemas() -> dict[str, dict[str, tuple]]:
    """id do esquema -> {chave: (tipo, padrão, faixa, escolhas)}; `faixa` é ``(mín, máx)``, `escolhas` as `<choices>`, ou ``None``."""
    esquemas = {}
    for esquema in ET.parse(_GSCHEMA).getroot().iter("schema"):
        chaves = {}
        for chave in esquema.iter("key"):
            tipo = chave.get("type")
            if tipo not in _TIPOS:
                raise ValueError(f"Tipo {tipo!r} da chave {chave.get('name')!r} não é suportado")
            intervalo = chave.find("range")
            faixa = None if intervalo is None else (int(intervalo.get("min")), int(intervalo.get("max")))
            opcoes = chave.findall("choices/choice")
            escolhas = frozenset(o.get("value") for o in opcoes) if opcoes else None
            padrao = _padrao(tipo, chave.findtext("default").strip())
            chaves[chave.get("name")] = (tipo, padrao, faixa, escolhas)
        esquemas[esquema.get("id")] = chaves
    return esquemas


class Configuracoes:
    def __init__(self, subchave: str, esquema: str) -> None:
        self._subchave = subchave
        self._chaves = _esquemas()[esquema]
        self._ligacoes: dict[int, tuple[str, Callable]] = {}
        self._proximo_id = 1

    def _definicao(self, chave: str, tipo: str | None = None) -> tuple[str, bool | int | str]:
        definicao = self._chaves[chave]  # KeyError, como o GSettings, que aborta
        if tipo is not None and definicao[0] != tipo:
            raise TypeError(f"A chave {chave!r} é do tipo {definicao[0]!r}, não {tipo!r}")
        return definicao[:2]

    def aceita(self, chave: str, valor: object) -> bool:
        """Se ``valor`` serve à chave: o tipo, o `<range>` e as `<choices>`. Chave desconhecida é ``False``."""
        if chave not in self._chaves:
            return False
        tipo, _, faixa, escolhas = self._chaves[chave]
        if tipo == "b":
            return isinstance(valor, bool)
        if tipo == "s":
            return isinstance(valor, str) and (escolhas is None or valor in escolhas)
        if not isinstance(valor, int) or isinstance(valor, bool):
            return False
        bits = _TIPOS[tipo][1]
        minimo = 0 if tipo == "u" else -(1 << (bits - 1))
        if not minimo <= valor < minimo + (1 << bits):
            return False
        return faixa is None or faixa[0] <= valor <= faixa[1]

    def _ler(self, chave: str, tipo: str | None = None) -> bool | int | str:
        tipo_da_chave, padrao = self._definicao(chave, tipo)
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self._subchave) as aberta:
                valor, tipo_no_registro = winreg.QueryValueEx(aberta, chave)
        except FileNotFoundError:
            return padrao
        tipo_esperado, bits = _TIPOS[tipo_da_chave]
        if tipo_no_registro != tipo_esperado:
            logging.warning("Preferência %s com tipo inesperado no registro; usando o padrão", chave)
            return padrao
        if tipo_da_chave == "s":
            return valor
        if tipo_da_chave == "b":
            return bool(valor)
        if tipo_da_chave != "u" and valor >> (bits - 1):  # complemento de 2
            valor -= 1 << bits
        return valor

    def _gravar(self, chave: str, tipo: str, valor: bool | int | str) -> None:
        tipo_da_chave, _ = self._definicao(chave, tipo)
        antes = self._ler(chave)
        tipo_no_registro, bits = _TIPOS[tipo_da_chave]
        if tipo_da_chave == "s":
            gravar = str(valor)
        else:
            gravar = int(valor)
            if tipo_da_chave != "b":
                minimo = 0 if tipo_da_chave == "u" else -(1 << (bits - 1))
                if not minimo <= gravar < minimo + (1 << bits):
                    raise OverflowError(f"{valor} fora do intervalo da chave {chave!r}")
                gravar &= (1 << bits) - 1
            else:
                gravar = int(bool(valor))
        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, self._subchave, 0, winreg.KEY_SET_VALUE
        ) as aberta:
            winreg.SetValueEx(aberta, chave, 0, tipo_no_registro, gravar)
        self._avisar(chave, antes)

    def _avisar(self, chave: str, antes: bool | int | str) -> None:
        if self._ler(chave) == antes:
            return
        for sinal, callback in list(self._ligacoes.values()):
            if sinal in ("changed", f"changed::{chave}"):
                # O callback mexe na tela: sempre na thread principal.
                if eh_thread_principal() or QCoreApplication.instance() is None:
                    callback(self, chave)
                else:
                    na_thread_principal(callback, self, chave)

    def get_boolean(self, chave: str) -> bool:
        return self._ler(chave, "b")

    def get_int(self, chave: str) -> int:
        return self._ler(chave, "i")

    def get_uint(self, chave: str) -> int:
        return self._ler(chave, "u")

    def get_int64(self, chave: str) -> int:
        return self._ler(chave, "x")

    def get_string(self, chave: str) -> str:
        return self._ler(chave, "s")

    def get_value(self, chave: str) -> bool | int | str:
        return self._ler(chave)

    def set_boolean(self, chave: str, valor: bool) -> None:
        self._gravar(chave, "b", valor)

    def set_int(self, chave: str, valor: int) -> None:
        self._gravar(chave, "i", valor)

    def set_int64(self, chave: str, valor: int) -> None:
        self._gravar(chave, "x", valor)

    def set_string(self, chave: str, valor: str) -> None:
        self._gravar(chave, "s", valor)

    def __setitem__(self, chave: str, valor: bool | int | str) -> None:
        self._gravar(chave, self._definicao(chave)[0], valor)

    def reset(self, chave: str) -> None:
        self._definicao(chave)
        antes = self._ler(chave)
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, self._subchave, 0, winreg.KEY_SET_VALUE
            ) as aberta:
                winreg.DeleteValue(aberta, chave)
        except FileNotFoundError:
            return
        self._avisar(chave, antes)

    def list_keys(self) -> list[str]:
        return list(self._chaves)

    def connect(self, sinal: str, callback: Callable) -> int:
        identificador = self._proximo_id
        self._proximo_id += 1
        self._ligacoes[identificador] = (sinal, callback)
        return identificador

    def disconnect(self, identificador: int) -> None:
        self._ligacoes.pop(identificador, None)
