# app_updater.py
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

"""Avisa quando saiu uma versão nova do Cartridges e instala, se a pessoa quiser.

A cada abertura do app instalado, uma thread pergunta ao GitHub qual é a última
release. Se a tag for mais nova que ``shared.VERSION``, a thread principal mostra
as notas da release com Sim/Não. No Sim, o instalador é baixado para
``%TEMP%\\Cartridges-update``, conferido pelo SHA256 que o GitHub publica e aberto
em modo silencioso; o app fecha e o próprio instalador o reabre no fim.

Não confundir com ``updates_checker``, que trata das atualizações dos jogos.
"""

import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from gi.repository import GLib

RELEASES_URL = "https://api.github.com/repos/joaomgabaldi/Cartridges/releases/latest"

# Janela de progresso sem nenhuma pergunta, e sem reiniciar o Windows. O [Run]
# do Cartridges.iss.in não tem skipifsilent, então reabre o app no fim.
INSTALLER_ARGUMENTS = "/SILENT /SUPPRESSMSGBOXES /NORESTART"

_VERSION_RE = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class Release:
    """O que interessa de ``releases/latest``."""

    version: str
    notes: str
    url: str
    size: int
    # Hex minúsculo; "" quando o GitHub não informou o digest do anexo.
    sha256: str


def parse_release(data: dict) -> Optional[Release]:
    """Lê a resposta da API; None quando a release não tem instalador."""
    installer = next(
        (
            asset
            for asset in data.get("assets") or []
            if str(asset.get("name", "")).lower().endswith(".exe")
        ),
        None,
    )
    if installer is None or not installer.get("browser_download_url"):
        return None

    digest = str(installer.get("digest") or "")
    return Release(
        version=str(data.get("tag_name") or "").removeprefix("v"),
        notes=str(data.get("body") or ""),
        url=str(installer["browser_download_url"]),
        size=int(installer.get("size") or 0),
        sha256=digest.removeprefix("sha256:").lower()
        if digest.startswith("sha256:")
        else "",
    )


def is_newer(version: str, current: str) -> bool:
    """``AAAA.MM.DD`` já ordena como texto; outro formato nunca é mais novo."""
    if not (_VERSION_RE.match(version) and _VERSION_RE.match(current)):
        return False
    return version > current


def notes_to_markup(notes: str) -> str:
    """Converte o Markdown das notas da release para markup do Pango.

    Só o que as notas usam: ``## título``, ``**negrito**``, crases e ``- `` no
    começo da linha. A seção ``## Instalação`` é cortada: ela manda baixar o
    arquivo da página do GitHub, o que dentro do app não faz sentido.
    """
    # ponytail: negrito e crase cruzados ("`a **b` c**") geram markup inválido e
    # o Gtk.Label fica vazio; as notas são escritas à mão, não vale um parser.
    lines: list[str] = []
    skipping = False
    for raw in notes.replace("\r\n", "\n").split("\n"):
        if raw.startswith("## "):
            title = raw[3:].strip()
            skipping = title == "Instalação"
            if not skipping:
                lines.append(f"<b>{GLib.markup_escape_text(title)}</b>")
            continue
        if skipping:
            continue

        # Escapar antes de trocar: `**` e crase não mudam no escape, e o que o
        # texto trouxer de `<` ou `&` não vira tag.
        line = GLib.markup_escape_text(raw)
        line = _BOLD_RE.sub(r"<b>\1</b>", line)
        line = _CODE_RE.sub(r"<tt>\1</tt>", line)
        if line.startswith("- "):
            line = "• " + line[2:]
        lines.append(line)
    return "\n".join(lines).strip()


def installed_root() -> Optional[Path]:
    """Pasta da instalação, ou None quando o app roda do código-fonte.

    O app instalado roda de ``{app}\\bin\\pythonw.exe`` e o Inno Setup deixa o
    ``unins000.exe`` em ``{app}``. No MSYS2 o pai de ``bin`` é ``ucrt64``, que
    não tem desinstalador, e o app nunca tenta se atualizar.
    """
    root = Path(sys.executable).resolve().parent.parent
    return root if (root / "unins000.exe").is_file() else None


def download_dir() -> Path:
    """Onde o instalador baixado fica até a próxima abertura do app."""
    return Path(tempfile.gettempdir()) / "Cartridges-update"
