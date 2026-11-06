# session_file_handler.py
#
# Copyright 2023 Geoffrey Coulaud
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

import lzma
from io import TextIOWrapper
from logging import LogRecord, StreamHandler
from lzma import FORMAT_XZ, PRESET_DEFAULT
from os import PathLike
from pathlib import Path
from shutil import copyfileobj
from typing import Optional

from kyron import shared


class SessionFileHandler(StreamHandler):
    """Handler que grava um arquivo novo a cada abertura do app; os antigos são comprimidos e mantidos até um limite."""

    NUMBER_SUFFIX_POSITION = 1

    # Teto do log vivo: `backup_count` limita quantas sessões ficam, não o tamanho de uma, e um laço travado enche o disco.
    MAX_BYTES = 32 * 1024 * 1024

    backup_count: int
    filename: Path
    log_file: Optional[TextIOWrapper] = None
    capped: bool = False

    def create_dir(self) -> None:
        self.filename.parent.mkdir(exist_ok=True, parents=True)

    def path_is_logfile(self, path: Path) -> bool:
        return path.is_file() and path.name.startswith(self.filename.stem)

    def path_has_number(self, path: Path) -> bool:
        try:
            int(path.suffixes[self.NUMBER_SUFFIX_POSITION][1:])
        except (ValueError, IndexError):
            return False
        return True

    def get_path_number(self, path: Path) -> int:
        suffixes = path.suffixes
        number = (
            0
            if not self.path_has_number(path)
            else int(suffixes[self.NUMBER_SUFFIX_POSITION][1:])
        )
        return number

    def set_path_number(self, path: Path, number: int) -> str:
        suffixes = path.suffixes
        if self.path_has_number(path):
            suffixes.pop(self.NUMBER_SUFFIX_POSITION)
        suffixes.insert(self.NUMBER_SUFFIX_POSITION, f".{number}")
        stem = path.name.split(".", maxsplit=1)[0]
        new_name = stem + "".join(suffixes)
        return new_name

    def file_sort_key(self, path: Path) -> int:
        return self.get_path_number(path) if self.path_has_number(path) else 0

    def get_logfiles(self) -> list[Path]:
        logfiles = list(filter(self.path_is_logfile, self.filename.parent.iterdir()))
        logfiles.sort(key=self.file_sort_key, reverse=True)
        return logfiles

    def rotate_file(self, path: Path) -> None:
        # A lista do `rotate()` é anterior aos renames: uma queda entre comprimir e apagar deixa `.log` e `.log.xz` no mesmo número, e sem este guard a inicialização seguinte rodava sem log.
        if not path.exists():
            return

        if not path.name.endswith(".xz"):
            # Em blocos de tamanho fixo (modo binário): o log anterior pode ter centenas de MB, e um byte truncado de uma sessão morta não custa mais o log inteiro.
            compressed_path = path.with_suffix(path.suffix + ".xz")
            with open(path, "rb") as original_file:
                with lzma.open(
                    compressed_path, "wb", format=FORMAT_XZ, preset=PRESET_DEFAULT
                ) as lzma_file:
                    copyfileobj(original_file, lzma_file)
            path.unlink()
            path = compressed_path

        # `replace`, não `rename`: no Windows o rename recusa sobrescrever o par deixado por uma queda.
        new_number = self.get_path_number(path) + 1
        new_path_name = self.set_path_number(path, new_number)
        path = path.replace(path.with_name(new_path_name))

        if new_number > self.backup_count:
            path.unlink()
            return

    def rotate(self) -> None:
        for path in self.get_logfiles():
            self.rotate_file(path)

    def __init__(self, filename: PathLike, backup_count: int = 2, sem_limite: bool = False) -> None:
        self.sem_limite = sem_limite  # o log detalhado grava além de MAX_BYTES
        self.filename = Path(filename)
        self.backup_count = backup_count
        self.create_dir()
        self.rotate()
        self.log_file = open(self.filename, "w", encoding="utf-8")
        shared.log_files = self.get_logfiles()
        super().__init__(self.log_file)

    def emit(self, record: LogRecord) -> None:
        """Grava o registro e para de vez ao chegar a MAX_BYTES.

        Parar preserva o *começo* da sessão (onde um descontrole começa e onde fica o banner); o corte é avisado no arquivo e os consoles seguem.
        """
        if self.capped:
            return

        super().emit(record)

        if self.sem_limite:
            return

        try:
            size = self.stream.tell()
        except (OSError, ValueError):
            # Sem seek ou fechado: não há teto a impor, e um log nunca levanta para quem o chamou.
            return

        if size < self.MAX_BYTES:
            return

        # Antes de gravar: se o aviso falhar, o teto continua valendo.
        self.capped = True
        try:
            self.stream.write(
                f"--- Log capped at {self.MAX_BYTES} bytes. "
                "This session kept running; anything after this point was not "
                "written to the file. ---\n"
            )
            self.flush()
        except (OSError, ValueError):
            # Mesmo motivo do `tell`: isto roda dentro do tratamento de outro erro.
            pass

    def close(self) -> None:
        if self.log_file:
            self.log_file.close()
        super().close()
