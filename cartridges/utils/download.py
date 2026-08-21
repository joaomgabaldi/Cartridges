# download.py
#
# Copyright 2024 kramo
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

"""Small helper to download a URL into memory with a size cap.

Covers are portrait images (~600x900); even animated ones rarely exceed a few
megabytes. Capping the download keeps a misbehaving or oversized URL from
exhausting memory, and streaming means the cap is enforced even when the server
lies about (or omits) the Content-Length header.
"""

import requests

# 25 MiB is generous for any cover, animated included, while still bounding the
# worst case.
MAX_IMAGE_BYTES = 25 * 1024 * 1024


class ImageTooLargeError(requests.RequestException):
    """Raised when a download exceeds the allowed size.

    Subclasses ``requests.RequestException`` so existing download error handling
    (which already catches request failures) treats an oversized image the same
    way as any other failed download.
    """


def download_bytes(
    url: str, timeout: float = 10, max_bytes: int = MAX_IMAGE_BYTES
) -> bytes:
    """Download ``url`` into memory, aborting if it exceeds ``max_bytes``.

    :raises requests.HTTPError: on a 4xx/5xx response
    :raises ImageTooLargeError: if the payload exceeds ``max_bytes``
    """
    with requests.get(url, timeout=timeout, stream=True) as response:
        response.raise_for_status()

        # Trust a declared length when it's clearly too big (fail fast), but
        # always enforce the cap while streaming since the header can be wrong.
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                if int(declared) > max_bytes:
                    raise ImageTooLargeError(url)
            except ValueError:
                pass

        buffer = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            buffer.extend(chunk)
            if len(buffer) > max_bytes:
                raise ImageTooLargeError(url)
        return bytes(buffer)
