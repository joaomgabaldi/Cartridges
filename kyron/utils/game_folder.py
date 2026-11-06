# game_folder.py
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

"""Onde ficam os arquivos de um jogo, a partir do comando que o abre.

Só dois tipos de comando dizem: o clássico, que nomeia o executável (a pasta é a dele, mesmo de um cliente como ``steam.exe -applaunch 440``; distinguir exe de jogo e de launcher exigiria uma lista de todos) e o empacotado (Microsoft Store / Game Pass), cujo AUMID leva à pasta que o Windows registra. O resto (``steam://``, URIs de Epic e GOG, ``.lnk`` do Menu Iniciar) pede a outro programa que abra o jogo: devolve None e o botão some, em vez de abrir a pasta errada.
"""

import itertools
import logging
import os
import re
import winreg
from typing import Optional

from kyron.utils.run_executable import aumid_from_command

# Os caminhos do comando, entre aspas ou soltos, na ordem em que aparecem ("o último executável é o jogo").
# Um caminho solto para no espaço, pois não se distingue dos argumentos.
_PATH = re.compile(
    r'"(?P<quoted>[A-Za-z]:[\\/][^"]*)"'
    r'|(?<!\S)(?P<bare>[A-Za-z]:[\\/][^\s"]*)(?!\S)'
)

# `.lnk` e `.url` ficam de fora: são ponteiros, e a pasta deles é o Menu Iniciar, não o jogo.
_LAUNCHABLE_SUFFIXES = (".exe", ".bat", ".cmd", ".com")

# Uma subchave por nome completo de pacote (``Name_Version_Architecture_ResourceId_PublisherId``), com a pasta de instalação.
_PACKAGES_KEY = (
    r"Software\Classes\Local Settings\Software\Microsoft\Windows"
    r"\CurrentVersion\AppModel\Repository\Packages"
)


def game_folder(command: str) -> Optional[str]:
    """A pasta para a qual o comando aponta, ou None. Só devolve pasta que existe: jogo desinstalado ou movido não tem pasta a oferecer."""
    if not (command := (command or "").strip()):
        return None

    if aumid := aumid_from_command(command):
        return _package_folder(aumid)

    return _executable_folder(command)


def _executable_folder(command: str) -> Optional[str]:
    candidates = []
    for match in _PATH.finditer(command):
        if quoted := match.group("quoted"):
            candidates.append(quoted)
        elif match.group("bare").casefold().endswith(_LAUNCHABLE_SUFFIXES):
            # Caminho solto só vale inteiro: cortado no espaço ("C:\Games\Halo"), viraria a pasta de um vizinho.
            candidates.append(match.group("bare"))

    # O executável do jogo vem depois do que o precede (título do `start`, `/D`) e antes de argumentos que também são caminhos.
    launchable = [
        candidate
        for candidate in candidates
        if candidate.casefold().endswith(_LAUNCHABLE_SUFFIXES)
    ]
    for candidate in reversed(launchable):
        if os.path.isfile(candidate):
            return _win32_dir(os.path.dirname(candidate))

    # O executável sumiu do disco: o jogo se foi, e a `/D` ou um caminho de configuração nos argumentos não é a pasta dele.
    if launchable:
        return None

    # Sem executável absoluto (forma do importador, `start "" /D "<workdir>" "game.exe"`): a primeira pasta existente é a de trabalho.
    for candidate in candidates:
        if os.path.isdir(candidate):
            return _win32_dir(candidate)

    return None


def _package_folder(aumid: str) -> Optional[str]:
    """A pasta de instalação do pacote de um AUMID.

    O registro usa o nome completo (com versão, arquitetura e recurso no meio), não a família
    (``Name_PublisherId``): percorre os pacotes e casa pelas duas pontas.
    """
    family = aumid.split("!", 1)[0]
    name, _sep, publisher = family.rpartition("_")
    if not name or not publisher:
        return None

    prefix = (name + "_").casefold()
    suffix = ("_" + publisher).casefold()

    # Uma família pode ter vários pacotes: de recursos (``split.language-pt``, sem executável) e versões antigas. Pula os primeiros e prefere o mais novo.
    best: Optional[tuple[tuple[int, ...], str]] = None
    try:
        packages = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PACKAGES_KEY)
    except OSError:
        logging.debug("No package repository in the registry")
        return None

    with packages:
        for index in itertools.count():
            try:
                full_name = winreg.EnumKey(packages, index)
            except OSError:
                break  # fim da lista

            folded = full_name.casefold()
            if not (folded.startswith(prefix) and folded.endswith(suffix)):
                continue

            middle = full_name[len(prefix) : len(full_name) - len(suffix)].split("_")
            if len(middle) != 3 or middle[2].casefold().startswith("split."):
                continue

            try:
                with winreg.OpenKey(packages, full_name) as package:
                    root = winreg.QueryValueEx(package, "PackageRootFolder")[0]
            except OSError:
                continue

            if not root or not os.path.isdir(root):
                continue

            try:
                version = tuple(int(part) for part in middle[0].split("."))
            except ValueError:
                version = ()

            if best is None or version > best[0]:
                best = (version, root)

    return _win32_dir(best[1]) if best else None


def _win32_dir(directory: str) -> str:
    """``directory`` no formato do shell do Windows.

    A versão anterior (GTK) rodava no MSYS2, onde `os.path.dirname` devolvia barra normal, que o Explorer não abre;
    as bibliotecas gravadas por ela ainda guardam esses caminhos.
    """
    return directory.replace("/", "\\")


def open_folder(directory: str) -> bool:
    if not directory:
        return False

    logging.info("Opening folder `%s`", directory)
    try:
        os.startfile(directory)  # type: ignore[attr-defined]  # Windows-only
    except OSError:
        logging.exception("Could not open folder `%s`", directory)
        return False
    return True
