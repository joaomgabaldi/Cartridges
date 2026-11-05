# busca.py
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

"""Achar a raiz de um jogo e os .ini dos emuladores de Steam dentro dela.

Roda numa thread: toca o disco. A pasta do jogo é entrada não confiável: não segue links nem junções e tem limite de profundidade e de entradas.
"""

import logging
import os
import stat
from pathlib import Path
from typing import Iterable, Optional

from cartridges.conquistas import arquivos
from cartridges.emuladores import ini
from cartridges.utils.game_folder import game_folder

_PROFUNDIDADE = 8
_LIMITE_DE_ENTRADAS = 50_000
_CHANGER = "language.changer.ini"
_DO_APPID = frozenset({"steam_emu.ini", "codex.ini", "ali213.ini"})


def _chave(caminho: object) -> str:
    try:
        return os.path.normcase(str(Path(str(caminho)).resolve()))
    except (OSError, ValueError):
        return os.path.normcase(str(caminho))


def _raiz_valida(raiz: Path) -> Optional[Path]:
    return None if raiz.parent == raiz else raiz


def _tem_engine(pasta: Path) -> bool:
    try:
        return any(e.is_dir() and e.name.casefold() == "engine" for e in os.scandir(pasta))
    except OSError:
        return False


def raiz_do_jogo(executavel: str, executaveis_dos_outros: Iterable[str]) -> Optional[Path]:
    pasta = game_folder(executavel or "")
    if not pasta:
        return None
    bases = arquivos.bases_da_pasta(Path(pasta))
    raiz = bases[-1]
    # Unreal: Raiz\Projeto\Binaries\Win64\x.exe — só sobe mais um nível se a pasta acima tem `Engine`
    if any(b.name.casefold() == "binaries" for b in bases[:-1]) and _tem_engine(raiz.parent):
        raiz = raiz.parent
    if _raiz_valida(raiz) is None:
        return None

    meu = _chave(executavel.strip().strip('"'))
    base = _chave(raiz)
    for outro in executaveis_dos_outros:
        if not outro or _chave(outro.strip().strip('"')) == meu or outro == executavel:
            continue
        pasta_outro = game_folder(outro)
        if not pasta_outro:
            continue
        pasta_outro = _chave(pasta_outro)
        if pasta_outro == base or pasta_outro.startswith(base.rstrip("\\/") + os.sep):
            return None
    return raiz


def _eh_link(entrada: os.DirEntry) -> bool:
    try:
        if entrada.is_symlink() or entrada.is_junction():
            return True
        return bool(entrada.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def _prefixo_do_changer(caminho: Path) -> Optional[str]:
    """O valor de `LanguageFileTemplate`, só se for um nome simples (sem caminho)."""
    try:
        with open(caminho, "rb") as f:
            dados = f.read(ini.LIMITE)
    except OSError:
        return None
    if dados.startswith(b"\xef\xbb\xbf"):
        dados = dados[3:]
    for linha in dados.decode("latin-1").splitlines():
        linha = linha.strip()
        if linha.startswith((";", "#", "//")) or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        if chave.strip().casefold() == "languagefiletemplate":
            valor = valor.strip()
            if not valor or "/" in valor or "\\" in valor or ".." in valor or ":" in valor:
                return None
            return valor
    return None


def procurar(raiz: Path) -> list[Path]:
    achados: set[Path] = set()
    visitadas = 0
    pilha = [(raiz, 0)]
    while pilha:
        pasta, nivel = pilha.pop()
        try:
            with os.scandir(pasta) as it:
                entradas = list(it)
        except OSError:
            continue
        nomes_de_arquivo = []
        for e in entradas:
            visitadas += 1
            if visitadas > _LIMITE_DE_ENTRADAS:
                logging.debug("Busca de .ini parou no limite de entradas em `%s`", raiz)
                return sorted(achados)
            try:
                if _eh_link(e):
                    continue
                if e.is_dir(follow_symlinks=False):
                    if nivel < _PROFUNDIDADE:
                        pilha.append((Path(e.path), nivel + 1))
                elif e.is_file(follow_symlinks=False):
                    nomes_de_arquivo.append(e.name)
            except OSError:
                continue
        for nome in nomes_de_arquivo:
            if nome.casefold() in ini.FORMATOS:
                achados.add(pasta / nome)
        for nome in nomes_de_arquivo:
            if nome.casefold() == _CHANGER and (prefixo := _prefixo_do_changer(pasta / nome)):
                achados.update(
                    pasta / n for n in nomes_de_arquivo if n.casefold().startswith(prefixo.casefold())
                    and n.casefold().endswith(".ini")
                    and n.casefold() != _CHANGER
                )
    return sorted(achados)


def formato_de(caminho: Path) -> str:
    nome = caminho.name.casefold()
    if nome in ini.FORMATOS:
        return nome
    # modelo do language.changer: tem o formato do steam_emu.ini
    return "steam_emu.ini" if (caminho.parent / _CHANGER).is_file() else nome


def _valido(valor: Optional[str]) -> bool:
    return bool(valor) and arquivos.appid_valido(valor) and valor != "480"


def appid_dos(inis: list[Path]) -> Optional[str]:
    def nivel(c: Path) -> int:
        nome = c.name.casefold()
        if nome in _DO_APPID:
            return 1
        if nome == "steam_appid.txt":
            return 2 if c.parent.name.casefold() == "steam_settings" else 3
        return 0

    for n in (1, 2, 3):
        valores = {v for c in inis if nivel(c) == n and _valido(v := ini.ler(c).appid)}
        if valores:
            return valores.pop() if len(valores) == 1 else None
    return None
