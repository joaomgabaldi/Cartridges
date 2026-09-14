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

import hashlib
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
from gi.repository import Adw, GLib, Gtk

from cartridges import shared

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


class DownloadCancelled(Exception):
    """A pessoa apertou Cancelar, ou o app fechou, no meio do download."""


def download_installer(
    release: Release,
    target: Path,
    progress: Callable[[float], None],
    cancelled: threading.Event,
) -> None:
    """Baixa o instalador para ``target``, conferindo o SHA256 no caminho.

    Grava em ``target.part`` e só renomeia depois de o hash bater, então um
    ``target`` que existe é sempre um instalador inteiro e conferido. Em
    qualquer falha, Cancelar incluído, o ``.part`` é apagado e a exceção sobe.
    ``progress`` recebe a fração de 0 a 1, chamado desta mesma thread.

    :raises DownloadCancelled: ``cancelled`` foi ligado no meio
    :raises ValueError: a release não informa o hash, ou ele não confere
    :raises requests.RequestException: falha de rede ou HTTP
    """
    # Sem hash não há como saber se o .exe é o que foi publicado, e ele vai
    # rodar com o pedido de administrador. Recusa antes de baixar 60 MB.
    if not release.sha256:
        raise ValueError("a release não informa o SHA256 do instalador")

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + ".part")
    hasher = hashlib.sha256()
    received = 0
    try:
        with requests.get(release.url, timeout=10, stream=True) as response:
            response.raise_for_status()
            with part.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    if cancelled.is_set():
                        raise DownloadCancelled
                    file.write(chunk)
                    hasher.update(chunk)
                    received += len(chunk)
                    if release.size:
                        progress(min(received / release.size, 1.0))

        if hasher.hexdigest() != release.sha256:
            raise ValueError("o SHA256 do instalador baixado não confere")
        part.replace(target)
    except BaseException:
        # O `with` já fechou o arquivo, senão o Windows não deixaria apagar.
        part.unlink(missing_ok=True)
        raise


class AppUpdater:
    """Checagem na abertura, pergunta, download e troca pelo instalador."""

    def __init__(self) -> None:
        # Ligado pelo Cancelar ou pelo fechamento do app: o download para no
        # próximo pedaço e um resultado que chegue depois é descartado.
        self._cancel = threading.Event()
        self._stopped = False

    def start(self) -> None:
        """Checa uma vez, fora da thread principal. Só no app instalado."""
        if installed_root() is None:
            return
        threading.Thread(target=self._check_thread, daemon=True).start()

    def stop(self) -> None:
        """Descarta a checagem ou o download que ainda estiverem no caminho."""
        self._stopped = True
        self._cancel.set()

    # -- thread de checagem --------------------------------------------------

    def _check_thread(self) -> None:
        # O instalador da atualização anterior sai aqui. Se ainda estiver em
        # uso (acabou de reabrir o app), o erro é ignorado e ele sai na próxima.
        shutil.rmtree(download_dir(), ignore_errors=True)

        try:
            response = requests.get(
                RELEASES_URL,
                timeout=10,
                headers={"Accept": "application/vnd.github+json"},
            )
            response.raise_for_status()
            release = parse_release(response.json())
        except (requests.RequestException, ValueError) as error:
            # Sem rede não é erro: o app abre como sempre, e a pergunta fica
            # para a próxima abertura.
            logging.info("Checagem de versão nova falhou: %s", error)
            return
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Erro inesperado na checagem de versão nova", exc_info=True)
            return

        if release is None or not is_newer(release.version, shared.VERSION):
            return
        logging.info("Versão nova disponível: %s", release.version)
        GLib.idle_add(self._ask, release)

    # -- thread principal ----------------------------------------------------

    def _ask(self, release: Release) -> bool:
        if self._stopped or shared.win is None:
            return False

        notes = Gtk.Label(
            label=notes_to_markup(release.notes),
            use_markup=True,
            wrap=True,
            xalign=0,
        )
        scrolled = Gtk.ScrolledWindow(
            child=notes,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            max_content_height=360,
            propagate_natural_height=True,
        )
        dialog = Adw.AlertDialog(
            heading=_("Nova versão disponível: {}").format(release.version),
            extra_child=scrolled,
            prefer_wide_layout=True,
        )
        dialog.add_response("no", _("Não"))
        dialog.add_response("yes", _("Sim"))
        dialog.set_response_appearance("yes", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("yes")
        dialog.set_close_response("no")
        dialog.connect("response", self._on_answer, release)
        dialog.present(shared.win)
        return False

    def _on_answer(
        self, _dialog: Adw.AlertDialog, response: str, release: Release
    ) -> None:
        # "Não" não grava nada: na próxima abertura, a pergunta volta.
        if response == "yes":
            self._download(release)

    def _download(self, release: Release) -> None:
        bar = Gtk.ProgressBar(show_text=True)
        dialog = Adw.AlertDialog(heading=_("Baixando atualização…"), extra_child=bar)
        dialog.add_response("cancel", _("Cancelar"))
        dialog.set_close_response("cancel")
        dialog.connect("response", lambda *_args: self._cancel.set())
        # Modal, como a pergunta: não dá para iniciar um jogo com o app prestes
        # a fechar para instalar.
        dialog.present(shared.win)

        target = download_dir() / f"Cartridges-{release.version}.exe"

        def progress(fraction: float) -> None:
            GLib.idle_add(bar.set_fraction, fraction)

        def work() -> None:
            try:
                download_installer(release, target, progress, self._cancel)
            except DownloadCancelled:
                return
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.warning("Download da atualização falhou: %s", error)
                GLib.idle_add(self._finish, dialog, None)
                return
            GLib.idle_add(self._finish, dialog, target)

        threading.Thread(target=work, daemon=True).start()

    def _finish(self, dialog: Adw.AlertDialog, target: Optional[Path]) -> bool:
        # Cancelar apertado no último instante, ou o app fechando: o resultado
        # chegou tarde e não vale mais.
        if self._stopped or self._cancel.is_set():
            return False

        if target is None:
            message = _("Não foi possível baixar a atualização")
        else:
            try:
                # ShellExecute, e não subprocess: instalado para todos os
                # usuários, o instalador pede UAC, e o CreateProcess do
                # subprocess falharia com o erro 740. As barras são trocadas
                # porque o Python do MSYS2 monta caminhos com "/".
                os.startfile(
                    str(target).replace("/", "\\"), arguments=INSTALLER_ARGUMENTS
                )
            except OSError as error:
                logging.warning("Não foi possível abrir o instalador: %s", error)
                message = _("Não foi possível abrir o instalador")
            else:
                # O instalador precisa do app fechado para trocar os arquivos,
                # e o [Run] do .iss o reabre no fim.
                shared.win.get_application().quit()
                return False

        dialog.force_close()
        shared.win.toast_queue.add(Adw.Toast.new(message))
        return False
