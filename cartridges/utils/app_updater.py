# app_updater.py
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

"""Avisa quando saiu uma versão nova do Kyron e instala, se a pessoa quiser.

A cada abertura do app instalado, uma thread pergunta ao GitHub a última release; se a tag for mais nova que ``shared.VERSION``, a principal mostra as notas com "Agora não"/"Atualizar". No "Atualizar", o instalador é baixado para ``%TEMP%\\Cartridges-update``, conferido pelo SHA256 do GitHub e aberto em modo silencioso; o app fecha e o instalador o reabre. Não confundir com ``updates_checker`` (atualizações dos jogos).
"""

import hashlib
import html
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import weakref
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests
from PySide6.QtCore import Property, QCoreApplication, QObject, QTimer, Signal, Slot

from cartridges import shared
from cartridges.saves import backup_de_saves
from cartridges.utils.thread_principal import na_thread_principal

RELEASES_URL = "https://api.github.com/repos/joaomgabaldi/Cartridges/releases/latest"

# Só a janela de progresso, sem perguntas nem reiniciar o Windows. O [Run] do Cartridges.iss.in não tem skipifsilent e reabre o app no fim. Falhas depois de o app fechar só aparecem no log do Inno, em %TEMP%\Setup Log AAAA-MM-DD #NNN.txt.
# /FORCECLOSEAPPLICATIONS: em modo silencioso, um processo que não fecha com educação faz o instalador desistir e desfazer tudo. Risco: encerra também o app se o fechamento não acabou (`session_fita.fechar()` leva até 8 s; a chave órfã das fitas é desfeita na reabertura).
INSTALLER_ARGUMENTS = "/SILENT /SUPPRESSMSGBOXES /NORESTART /LOG /FORCECLOSEAPPLICATIONS"

# Teto do download quando a release não informa o tamanho do anexo: só impede um corpo sem fim de encher o disco.
MAX_INSTALLER_BYTES = 512 * 1024 * 1024

ASK_RETRY_SECONDS = 60

_NORMAL = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_DATA = re.compile(r"^\d{4}\.\d{2}\.\d{2}$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_CODE_RE = re.compile(r"`([^`]+)`")


@dataclass(frozen=True)
class Release:
    """O que interessa de ``releases/latest``."""

    version: str
    notes: str
    url: str
    size: int
    # Hex minúsculo; "" sem digest do anexo.
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
    """``X.Y.Z`` compara por número; ``AAAA.MM.DD`` (as versões antigas) é sempre
    mais velha que ``X.Y.Z``; outro formato nunca é mais novo."""
    # A data também casa com _NORMAL, por isso é testada antes.
    if _DATA.fullmatch(version) or _DATA.fullmatch(current):
        return bool(_DATA.fullmatch(version) and _DATA.fullmatch(current) and version > current)
    if (nova := _NORMAL.fullmatch(version)) and (atual := _NORMAL.fullmatch(current)):
        return tuple(map(int, nova.groups())) > tuple(map(int, atual.groups()))
    return False


def notes_to_markup(notes: str) -> str:
    """Converte o Markdown das notas da release para o ``Text.RichText`` do Qt (só ``## título``, ``**negrito**``, crases e ``- ``). A seção ``## Instalação`` é cortada: manda baixar da página do GitHub, o que no app não faz sentido."""
    # shortcut: negrito e crase cruzados ("`a **b` c**") geram tags mal aninhadas que o Qt engole; trocar por um parser se as notas deixarem de ser escritas à mão.
    lines: list[str] = []
    skipping = False
    for raw in notes.replace("\r\n", "\n").split("\n"):
        if raw.startswith("## "):
            title = raw[3:].strip()
            skipping = title == "Instalação"
            if not skipping:
                lines.append(f"<b>{html.escape(title, quote=False)}</b>")
            continue
        if skipping:
            continue

        # Escapa antes de trocar: `**` e crase não mudam no escape, e `<` ou `&` do texto não viram tag.
        line = html.escape(raw, quote=False)
        line = _BOLD_RE.sub(r"<b>\1</b>", line)
        line = _CODE_RE.sub(r"<tt>\1</tt>", line)
        if line.startswith("- "):
            line = "• " + line[2:]
        lines.append(line)
    return "\n".join(lines).strip().replace("\n", "<br>")


def installed_root() -> Optional[Path]:
    """Pasta da instalação, ou None quando o app roda do código-fonte.

    O app instalado roda de ``{app}\\bin\\Kyron.exe`` e o Inno Setup deixa o ``unins000.exe`` em ``{app}``;
    do código-fonte não há desinstalador, e o app nunca tenta se atualizar. A cópia de desenvolvimento também
    nunca se atualiza: a versão final não pode ser instalada por cima dela.
    """
    if shared.canal() != "final":
        return None
    root = Path(sys.executable).resolve().parent.parent
    return root if (root / "unins000.exe").is_file() else None


def download_dir() -> Path:
    return Path(tempfile.gettempdir()) / "Cartridges-update"


def _abrir_instalador(caminho: Path) -> None:
    """Abre o instalador sem esperar por ele (o ponto que os testes trocam). Levanta ``OSError``.

    ShellExecute: o Inno Setup pede o UAC depois de começar, com o app já fechado. As barras são trocadas porque um caminho pode vir com "/".
    """
    os.startfile(str(caminho).replace("/", "\\"), arguments=INSTALLER_ARGUMENTS)


def _buscar_release() -> Optional[Release]:
    """Pergunta ao GitHub qual é a última release. Levanta ``RequestException`` (rede/HTTP) ou ``ValueError`` (não é JSON)."""
    response = requests.get(
        RELEASES_URL,
        timeout=10,
        headers={"Accept": "application/vnd.github+json"},
    )
    response.raise_for_status()
    return parse_release(response.json())


class DownloadCancelled(Exception):
    """A pessoa apertou Cancelar, ou o app fechou, no meio do download."""


def download_installer(
    release: Release,
    target: Path,
    progress: Callable[[float], None],
    cancelled: threading.Event,
) -> None:
    """Baixa o instalador para ``target``, conferindo o SHA256.

    Grava em ``target.<thread>.part`` e só renomeia com o hash batendo: um ``target`` existente é sempre inteiro e conferido. Em qualquer falha (Cancelar incluído) o ``.part`` é apagado e a exceção sobe: ``DownloadCancelled``, ``ValueError`` (sem hash ou hash errado) ou ``RequestException``. ``progress`` (0 a 1) é chamado desta thread.
    """
    # Sem hash não há como saber se o .exe é o publicado, e ele roda como administrador: recusa antes de baixar.
    if not release.sha256:
        raise ValueError("a release não informa o SHA256 do instalador")

    target.parent.mkdir(parents=True, exist_ok=True)
    # Um `.part` por thread: dois downloads do mesmo instalador não se pisam.
    part = target.with_name(f"{target.name}.{threading.get_ident()}.part")
    hasher = hashlib.sha256()
    received = 0
    # Passar do tamanho do anexo publicado já é outro arquivo; não adianta baixar o resto para o hash recusar.
    limit = release.size or MAX_INSTALLER_BYTES
    try:
        with requests.get(
            release.url,
            timeout=10,
            stream=True,
        ) as response:
            response.raise_for_status()
            with part.open("wb") as file:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    if cancelled.is_set():
                        raise DownloadCancelled
                    file.write(chunk)
                    hasher.update(chunk)
                    received += len(chunk)
                    if received > limit:
                        raise ValueError("o instalador passou do tamanho esperado")
                    if release.size:
                        progress(min(received / release.size, 1.0))

        if hasher.hexdigest() != release.sha256:
            raise ValueError("o SHA256 do instalador baixado não confere")
        part.replace(target)
    except BaseException:
        # O `with` já fechou o arquivo; senão o Windows não deixaria apagar.
        part.unlink(missing_ok=True)
        raise


class AppUpdater(QObject):
    """Checagem na abertura, pergunta, download e troca pelo instalador.

    O QML (``DialogoDaAtualizacao``) lê ``pergunta``, ``baixando`` e ``progresso`` e responde por ``responder``/``cancelar``;
    o botão das Preferências chama ``buscarAgora``. O que toca a tela roda na thread principal.
    """

    alterado = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Ligado pelo Cancelar ou pelo fechamento: o download para no próximo pedaço e um resultado tardio é descartado.
        self._cancel = threading.Event()
        self._stopped = False
        # A pergunta (ou o download dela) está na tela: nenhuma outra abre.
        self._perguntando = False
        # Uma busca do botão no caminho.
        self._buscando = False
        self._release: Optional[Release] = None
        self._pergunta: dict = {}
        self._baixando = False
        self._progresso = 0.0

    @Property("QVariantMap", notify=alterado)
    def pergunta(self) -> dict:
        return self._pergunta

    @Property(bool, notify=alterado)
    def baixando(self) -> bool:
        return self._baixando

    @Property(float, notify=alterado)
    def progresso(self) -> float:
        return self._progresso

    @Property(bool, notify=alterado)
    def buscando(self) -> bool:
        return self._buscando

    @Property(str, constant=True)
    def versao(self) -> str:
        return shared.VERSION

    def start(self) -> None:
        if installed_root() is None:
            return
        threading.Thread(target=self._check_thread, daemon=True).start()

    def stop(self) -> None:
        self._stopped = True
        self._cancel.set()

    def buscar_agora(self, responder: Callable[[Optional[str]], None]) -> None:
        """Checagem pedida pelo botão das Preferências: toda resposta chega à pessoa (versão nova vira a pergunta e
        ``responder(None)``; o resto vira ``responder(texto)``). Sempre na thread principal, uma vez."""
        if installed_root() is None:
            responder("A busca de atualizações só funciona no aplicativo instalado.")
            return
        if self._buscando:
            responder("A busca de atualizações já está em andamento.")
            return
        self._definir_busca(True)

        def work() -> None:
            try:
                release = _buscar_release()
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.info("Busca de versão nova falhou: %s", error)
                na_thread_principal(
                    self._responder_busca,
                    responder,
                    "Não foi possível buscar atualizações. Verifique a conexão "
                    "com a internet.",
                )
                return
            if release is None or not is_newer(release.version, shared.VERSION):
                na_thread_principal(
                    self._responder_busca,
                    responder,
                    "O Kyron já está na versão mais recente.",
                )
                return
            na_thread_principal(self._perguntar_agora, release, responder)

        threading.Thread(target=work, daemon=True).start()

    @Slot()
    def buscarAgora(self) -> None:  # noqa: N802
        """O botão das Preferências: a resposta vira um aviso na fila do app."""

        def responder(texto: Optional[str]) -> None:
            if texto is not None and shared.aplicativo is not None:
                shared.aplicativo.avisos.adicionar(texto)

        self.buscar_agora(responder)

    @Slot(bool)
    def responder(self, atualizar: bool) -> None:
        release = self._release
        if not self._pergunta or release is None:
            return
        self._pergunta = {}
        self._release = None
        if atualizar:
            self._download(release)
        else:
            self._perguntando = False
            self.alterado.emit()

    @Slot()
    def cancelar(self) -> None:
        self._cancel.set()
        self._perguntando = False
        self._baixando = False
        self.alterado.emit()

    def _check_thread(self) -> None:
        # O instalador da atualização anterior sai aqui; em uso (app recém-reaberto), sai na próxima.
        shutil.rmtree(download_dir(), ignore_errors=True)

        try:
            release = _buscar_release()
        except (requests.RequestException, ValueError) as error:
            # Sem rede não é erro: a pergunta fica para a próxima abertura.
            logging.info("Checagem de versão nova falhou: %s", error)
            return
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Erro inesperado na checagem de versão nova", exc_info=True)
            return

        if release is None:
            logging.info("A última release não tem instalador .exe")
            return
        if not is_newer(release.version, shared.VERSION):
            return
        logging.info("Versão nova disponível: %s", release.version)
        na_thread_principal(self._ask, release)

    def _definir_busca(self, buscando: bool) -> None:
        self._buscando = buscando
        self.alterado.emit()

    def _ask(self, release: Release) -> None:
        if self._stopped or shared.aplicativo is None or self._perguntando:
            return

        if self._ocupado():
            eu = weakref.ref(self)
            QTimer.singleShot(
                ASK_RETRY_SECONDS * 1000, lambda: (u := eu()) and u._ask(release)  # noqa: SLF001
            )
            return

        self._release = release
        self._pergunta = {"versao": release.version, "notas": notes_to_markup(release.notes)}
        self._perguntando = True
        self.alterado.emit()

    @staticmethod
    def _ocupado() -> bool:
        """Com um jogo aberto, o "Atualizar" fecharia o app no meio da sessão, e o app reaberto não volta a rastrear o jogo.
        Vale também para o backup ou a restauração dos saves."""
        # evita import circular
        from cartridges.process_session import ProcessSession
        from cartridges.session_window import SessionWindow

        return (
            SessionWindow.active is not None
            or ProcessSession.active is not None
            or backup_de_saves.em_andamento()
        )

    def _responder_busca(
        self, responder: Callable[[Optional[str]], None], texto: Optional[str]
    ) -> None:
        self._definir_busca(False)
        responder(texto)

    def _perguntar_agora(
        self, release: Release, responder: Callable[[Optional[str]], None]
    ) -> None:
        self._definir_busca(False)
        # Pedida pelo botão, a pergunta não espera em silêncio: a pessoa precisa de uma resposta agora.
        if self._ocupado():
            responder(
                "Versão {} disponível. Conclua o jogo, o backup ou a restauração "
                "dos saves em andamento para atualizar.".format(release.version)
            )
            return
        self._ask(release)
        responder(None)

    def _download(self, release: Release) -> None:
        # Evento novo por download: um Cancelar anterior não o para, e o resultado de um download antigo é descartado.
        self._cancel = cancel = threading.Event()
        self._baixando = True
        self._progresso = 0.0
        self.alterado.emit()

        target = download_dir() / f"Kyron-{release.version}.exe"

        def progress(fraction: float) -> None:
            na_thread_principal(self._atualizar_progresso, fraction, cancel)

        def work() -> None:
            try:
                download_installer(release, target, progress, cancel)
            except DownloadCancelled:
                return
            except Exception as error:  # pylint: disable=broad-exception-caught
                logging.warning("Download da atualização falhou: %s", error)
                na_thread_principal(self._finish, None, cancel)
                return
            na_thread_principal(self._finish, target, cancel)

        threading.Thread(target=work, daemon=True).start()

    def _atualizar_progresso(self, fraction: float, cancel: threading.Event) -> None:
        if cancel is self._cancel and not cancel.is_set() and self._baixando and not self._stopped:
            self._progresso = fraction
            self.alterado.emit()

    def _finish(self, target: Optional[Path], cancel: threading.Event) -> None:
        # Cancelar de última hora, app fechando ou download mais novo: o resultado chegou tarde.
        if self._stopped or cancel is not self._cancel or cancel.is_set():
            return

        if target is None:
            message = "Não foi possível baixar a atualização"
        else:
            try:
                _abrir_instalador(target)
            except OSError as error:
                logging.warning("Não foi possível abrir o instalador: %s", error)
                message = "Não foi possível abrir o instalador"
            else:
                # O instalador precisa do app fechado para trocar os arquivos (o [Run] do .iss o reabre); um segundo resultado não sai de novo.
                self._stopped = True
                QCoreApplication.quit()
                return

        self._perguntando = False
        self._baixando = False
        self.alterado.emit()
        if shared.aplicativo is not None:
            shared.aplicativo.avisos.adicionar(message)
