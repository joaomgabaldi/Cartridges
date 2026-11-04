# jogo.py
#
# Copyright 2022-2023 kramo
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

"""O jogo da biblioteca."""

import logging
from pathlib import Path
from time import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal

from cartridges import shared
from cartridges.process_session import ProcessSession
from cartridges.session_window import SessionWindow
from cartridges.utils.process_monitor import install_dir_from_command
from cartridges.utils.run_executable import aumid_from_command, run_executable

ANIMATED_SUFFIXES = (".gif", ".webp", ".apng")

PERSISTED_ATTRS = (
    "added",
    "executable",
    "game_id",
    "source",
    "last_played",
    "playtime",
    "status",
    "rating",
    "notes",
    "name",
    "developer",
    "publisher",
    "release_date",
    "metacritic",
    "steam_review",
    "genre",
    "controller_support",
    "gamepad_recommended",
    "description",
    "steam_checked",
    "steam_appid",
    "hltb_id",
    "hltb_main",
    "hltb_main_extra",
    "hltb_completionist",
    "hltb_chapters",
    "removed",
    "blacklisted",
    "version",
    "install_size",
    "install_size_ts",
    "shortcut_mtime",
    "shortcut_path",
    "run_as_admin",
    "track_process",
    "process_executable",
    "track_updates",
    "update_available_ts",
    "update_dismissed_ts",
    "update_url",
    "conquistas",
    "ludusavi_nome",
    "saves_local_desconhecido_avisado",
    "backup_dos_saves_desligado",
    "comando_a_conferir",
)

_KNOWN_KEYS = frozenset(PERSISTED_ATTRS)

STATUS_LABELS = {
    "backlog": _("Quero jogar"),
    "playing": _("Jogando"),
    "beaten": _("Zerado"),
    "dropped": _("Abandonado"),
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status or "", "")


# pylint: disable=too-many-instance-attributes
class Jogo(QObject):
    atualizado = Signal()
    salvar = Signal()
    aviso = Signal(str, str)
    confirmar_comando = Signal(object)
    sair_da_frente = Signal()

    loading: int = 0
    filtered: bool = False

    added: int = 0
    executable: str
    game_id: str
    source: str
    last_played: int = 0
    playtime: int = 0
    # Onde o jogo está na sua vida: escolhido à mão, nunca deduzido do tempo de jogo.
    status: str = ""
    rating: int = 0
    # Onde você parou: texto livre, com as quebras de linha que tiver.
    notes: str = ""
    name: str
    developer: Optional[str] = None
    publisher: Optional[str] = None
    release_date: Optional[str] = None
    metacritic: Optional[int] = None
    steam_review: Optional[str] = None
    genre: Optional[str] = None
    controller_support: Optional[str] = None
    gamepad_recommended: bool = False
    description: Optional[str] = None
    steam_checked: int = 0
    steam_appid: Optional[str] = None
    hltb_id: Optional[int] = None
    hltb_main: Optional[int] = None
    hltb_main_extra: Optional[int] = None
    hltb_completionist: Optional[int] = None
    hltb_chapters: Optional[list[dict]] = None
    install_size: int = 0
    install_size_ts: int = 0
    removed: bool = False
    blacklisted: bool = False
    game_cover: Optional[Any] = None
    version: int = 0
    shortcut_mtime: int = 0
    shortcut_path: str = ""
    run_as_admin: bool = False  # launch this game elevated (UAC) on Windows
    track_process: bool = False
    process_executable: str = ""
    track_updates: bool = False
    update_available_ts: int = 0
    update_dismissed_ts: int = 0
    update_url: str = ""
    conquistas: bool = True
    # O nome deste jogo no Ludusavi (o do manifesto, ou o do próprio jogo quando o manifesto não o conhece).
    ludusavi_nome: str = ""
    # O usuário já foi avisado de que o local dos saves deste jogo é desconhecido (sem appID e fora do manifesto, não há
    # backup): as próximas sessões só vão para o log.
    saves_local_desconhecido_avisado: bool = False
    # O usuário escolheu "Nenhum" no Jogo no Ludusavi: sem backup deste jogo, e o appID não o religa sozinho.
    backup_dos_saves_desligado: bool = False
    # Veio de um backup restaurado: o comando pode ter sido escrito por outra pessoa, e roda num shell (ou como
    # administrador).
    comando_a_conferir: bool = False

    def __init__(self, data: dict[str, Any], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.version = shared.SPEC_VERSION

        self.update_values(data)
        self.base_source = self.source.split("_")[0]

    @property
    def has_update(self) -> bool:
        return self.track_updates and self.update_available_ts > 0

    @property
    def zerado(self) -> bool:
        return self.removed and not self.blacklisted and self.status == "beaten"

    def definir_status(self, status: str) -> None:
        era_zerado = self.zerado
        self.status = status
        if (
            era_zerado
            and not self.zerado
            and self.executable
            and self.shortcut_path
            and Path(self.shortcut_path).is_file()
        ):
            self.removed = False

    def dismiss_update(self) -> None:
        self.update_dismissed_ts = max(
            self.update_dismissed_ts, self.update_available_ts
        )
        self.update_available_ts = 0
        self.update_url = ""
        self.save()
        self.update()

    @property
    def stars(self) -> int:
        """``rating`` limitado a 0–5, tolerando um registro editado à mão: um "rating": 9 ou "ótimo" vira 5 ou 0 num
        lugar só.
        """
        try:
            return max(0, min(5, int(self.rating)))
        except (TypeError, ValueError):
            return 0

    @property
    def hltb_times(self) -> tuple[Optional[int], Optional[int], Optional[int]]:
        return (self.hltb_main, self.hltb_main_extra, self.hltb_completionist)

    @property
    def has_hltb_times(self) -> bool:
        return any(self.hltb_times) or bool(self.hltb_chapters)

    def update_values(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if key not in _KNOWN_KEYS:
                logging.debug("Ignoring unknown field %s in a game record", key)
                continue
            setattr(self, key, value)

    def update(self) -> None:
        self.atualizado.emit()

    def save(self) -> None:
        self.salvar.emit()

    def _avisar(self, title: str, action: str = "") -> None:
        """``title`` is a template where {} is the game's name."""
        self.aviso.emit(title.format(self.name), action)

    @property
    def comando_visivel(self) -> str:
        return "".join(
            c if c.isprintable() else f"<U+{ord(c):04X}>" for c in self.executable
        )

    def _conferir_comando(self, lancar: Callable[[], Any]) -> None:
        def confirmar() -> None:
            self.comando_a_conferir = False
            self.save()
            lancar()

        self.confirmar_comando.emit(confirmar)

    def launch(self, ao_confirmar: Optional[Callable[[], Any]] = None) -> bool:
        """``ao_confirmar`` é como relançar depois da confirmação do comando de um jogo restaurado; sem ele, é este
        mesmo ``launch``.
        """
        # Dentro da função: o `backup_de_saves` importa o `Jogo`.
        from cartridges.saves import backup_de_saves  # noqa: PLC0415

        if backup_de_saves.restaurando(self):
            self._avisar(_("Aguarde o fim da restauração dos saves de {}."))
            return False
        if self.comando_a_conferir:
            self._conferir_comando(ao_confirmar or self.launch)
            return False

        self.last_played = int(time())
        self.save()
        self.update()

        tracking = shared.schema.get_boolean("playtime-tracking")
        followable = (
            (self.track_process and bool(self.process_executable.strip()))
            or bool(aumid_from_command(self.executable))
            or bool(install_dir_from_command(self.executable))
        )
        sessao = shared.sessao
        moved = tracking and sessao is not None and sessao.move_to_session_monitor()

        run_executable(self.executable, self.run_as_admin)
        if sessao is not None:
            sessao.vibrar_abertura()

        # Encerra (com registro) a sessão em andamento antes de começar outra: dois rastreadores nunca contam ao mesmo
        # tempo.
        if SessionWindow.active is not None:
            SessionWindow.active.close()
        if ProcessSession.active is not None:
            ProcessSession.active.stop(record=True)

        if sessao is not None and tracking and followable:
            ProcessSession(self).start()
            if not moved:
                self.sair_da_frente.emit()
        elif sessao is not None and tracking:
            SessionWindow(self).present()
            if not moved:
                self.sair_da_frente.emit()
        elif shared.schema.get_boolean("minimize-after-launch"):
            self.sair_da_frente.emit()

        self._avisar(_("{} iniciado"))
        return True

    def remove_game(self) -> None:
        self.removed = True
        self.save()
        self.update()

        if self.zerado:
            self._avisar(_("{} movido para Jogos Zerados"), "remove")
        else:
            self._avisar(_("{} removido"), "remove")

    def set_loading(self, state: int) -> None:
        antes = self.loading > 0
        self.loading += state
        if (self.loading > 0) != antes:
            self.update()

    capa_da_sessao: Optional[Path] = None

    def get_cover_path(self) -> Optional[Path]:
        if self.capa_da_sessao is not None and self.capa_da_sessao.is_file():
            return self.capa_da_sessao
        for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
            cover_path = shared.covers_dir / f"{self.game_id}{suffix}"
            if cover_path.is_file():
                return cover_path

        return None
