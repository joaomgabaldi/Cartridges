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

from cartridges import shared


class SessionFileHandler(StreamHandler):
    """
    A logging handler that writes to a new file on every app restart.
    The files are compressed and older sessions logs are kept up to a small limit.
    """

    NUMBER_SUFFIX_POSITION = 1

    # Ceiling on the live session log. Nothing else here bounds a single
    # session: `backup_count` limits how many sessions are kept, not how large
    # any one of them may grow, so one stuck loop — a poller failing every
    # tick, a retry storm during an import of a few hundred games — can fill
    # the user's disk over an afternoon of the app sitting in the background.
    # 32 MiB is orders of magnitude more than a healthy session writes and
    # still small enough to compress and attach to a bug report.
    MAX_BYTES = 32 * 1024 * 1024

    backup_count: int
    filename: Path
    log_file: Optional[TextIOWrapper] = None
    capped: bool = False

    def create_dir(self) -> None:
        """Create the log dir if needed"""
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
        """Get the number extension in the filename as an int"""
        suffixes = path.suffixes
        number = (
            0
            if not self.path_has_number(path)
            else int(suffixes[self.NUMBER_SUFFIX_POSITION][1:])
        )
        return number

    def set_path_number(self, path: Path, number: int) -> str:
        """Set or add the number extension in the filename"""
        suffixes = path.suffixes
        if self.path_has_number(path):
            suffixes.pop(self.NUMBER_SUFFIX_POSITION)
        suffixes.insert(self.NUMBER_SUFFIX_POSITION, f".{number}")
        stem = path.name.split(".", maxsplit=1)[0]
        new_name = stem + "".join(suffixes)
        return new_name

    def file_sort_key(self, path: Path) -> int:
        """Key function used to sort files"""
        return self.get_path_number(path) if self.path_has_number(path) else 0

    def get_logfiles(self) -> list[Path]:
        """Get the log files"""
        logfiles = list(filter(self.path_is_logfile, self.filename.parent.iterdir()))
        logfiles.sort(key=self.file_sort_key, reverse=True)
        return logfiles

    def rotate_file(self, path: Path) -> None:
        """Rotate a file's number suffix and remove it if it's too old"""

        # If uncompressed, compress
        if not path.name.endswith(".xz"):
            # Streamed through a fixed-size buffer instead of read whole. This
            # runs from __init__, before the first line of the new session is
            # written, so the previous session's log — which nothing capped
            # until now, and which a long background run could leave at several
            # hundred megabytes — used to be pulled into a single string while
            # the user waited on a window that had not appeared yet.
            #
            # Binary mode is what makes that possible, and it also removes the
            # reason the old code deleted logs on UnicodeDecodeError: there is
            # nothing left to decode, so a single mangled byte (a half-written
            # line from a session that was killed) no longer costs the user the
            # entire log it sits in.
            compressed_path = path.with_suffix(path.suffix + ".xz")
            with open(path, "rb") as original_file:
                with lzma.open(
                    compressed_path, "wb", format=FORMAT_XZ, preset=PRESET_DEFAULT
                ) as lzma_file:
                    copyfileobj(original_file, lzma_file)
            path.unlink()
            path = compressed_path

        # Rename with new number suffix
        new_number = self.get_path_number(path) + 1
        new_path_name = self.set_path_number(path, new_number)
        path = path.rename(path.with_name(new_path_name))

        # Remove older files
        if new_number > self.backup_count:
            path.unlink()
            return

    def rotate(self) -> None:
        """Rotate the numbered suffix on the log files and remove old ones"""
        for path in self.get_logfiles():
            self.rotate_file(path)

    def __init__(self, filename: PathLike, backup_count: int = 2) -> None:
        self.filename = Path(filename)
        self.backup_count = backup_count
        self.create_dir()
        self.rotate()
        self.log_file = open(self.filename, "w", encoding="utf-8")
        shared.log_files = self.get_logfiles()
        super().__init__(self.log_file)

    def emit(self, record: LogRecord) -> None:
        """Write a record, then stop for good once the file hits MAX_BYTES.

        Stopping keeps the *beginning* of the session, which is where a runaway
        starts and where the system info banner lives; a scheme that kept the
        end instead would throw away the first sign of trouble to preserve the
        millionth copy of it. The cut is announced in the file itself so nobody
        reads the last line as the moment the app went quiet, and the console
        handlers are untouched — a developer watching the terminal still sees
        everything.
        """
        if self.capped:
            return

        super().emit(record)

        try:
            # StreamHandler.emit flushes every record, so this is just a byte
            # offset on an already-synced file rather than an extra flush.
            size = self.stream.tell()
        except (OSError, ValueError):
            # Not seekable, or closed underneath us. There is no ceiling to
            # enforce and a logging call must never raise into the code that
            # made it, so leave the handler as it was.
            return

        if size < self.MAX_BYTES:
            return

        # Set before writing: if the note itself fails, the cap still holds and
        # the next record does not try again.
        self.capped = True
        try:
            self.stream.write(
                f"--- Log capped at {self.MAX_BYTES} bytes. "
                "This session kept running; anything after this point was not "
                "written to the file. ---\n"
            )
            self.flush()
        except (OSError, ValueError):
            # Same reasoning as the `tell` above, and it matters more here: this
            # runs inside somebody's logging call, which is very often the
            # handling of another error.
            pass

    def close(self) -> None:
        if self.log_file:
            self.log_file.close()
        super().close()
