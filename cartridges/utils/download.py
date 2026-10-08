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

"""Small helpers to read HTTP bodies into memory with a size cap.

Covers are portrait images (~600x900); even animated ones rarely exceed a few
megabytes. Capping the download keeps a misbehaving or oversized URL from
exhausting memory, and streaming means the cap is enforced even when the server
lies about (or omits) the Content-Length header. The request timeout does not
bound size: it limits silence between bytes, not the total.
"""

import threading
import time
from typing import Any, Callable, Optional

import requests

# 25 MiB is generous for any still image while still bounding the worst case.
MAX_IMAGE_BYTES = 25 * 1024 * 1024

# Capas animadas do SteamGridDB passam de 60 MB (APNG). A biblioteca toca as
# cópias reduzidas (``copias_animadas``), nunca o arquivo baixado.
MAX_ANIMATED_IMAGE_BYTES = 200 * 1024 * 1024

# Papel de parede em resolução de monitor grande.
MAX_WALLPAPER_BYTES = 50 * 1024 * 1024

# For API answers (JSON, HTML pages). 10 MiB covers with room to spare the
# largest real one — a HowLongToBeat /game/<id> page, ~1–2 MiB.
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Quem mostra o progresso redesenha a tela a cada chamada: dez por segundo já
# fazem a barra andar, e um arquivo de 200 MB tem mais de três mil pedaços.
INTERVALO_DO_PROGRESSO = 0.1

_local = threading.local()


class DownloadCancelado(Exception):
    """Levantada pelo ``ao_progredir`` para interromper o download.

    Não é ``requests.RequestException``: quem cancela não quer o aviso de
    falha nem a tela de erro que os seletores mostram para uma falha de rede.
    """


class ResponseTooLargeError(requests.RequestException):
    """Raised when a body exceeds the allowed size.

    Subclasses ``requests.RequestException`` so existing download error handling
    (which already catches request failures) treats an oversized body the same
    way as any other failed request.
    """


def _get(url: str, **kwargs: Any) -> requests.Response:
    """``requests.get`` through this thread's own session, keeping connections.

    ``requests.get`` opens a new connection (DNS, TCP, TLS) on every call. A
    picker downloads up to 30 previews in a row, and a fresh connection is what
    pays the 1-7 s stalls of a lost packet with no RTT estimate yet (measured on
    28/09/2026). One session per thread, not one global: ``requests.Session``
    is not documented as thread-safe, and the wallpaper picker downloads with
    six workers at once.
    """
    session = getattr(_local, "session", None)
    if session is None:
        session = _local.session = requests.Session()
    try:
        return session.get(url, **kwargs)
    finally:
        # `requests.get` never carried a cookie from one call to the next, and
        # a Steam cookie (country, session) must not change a later answer.
        session.cookies.clear()


def read_capped(
    response: requests.Response,
    max_bytes: int,
    ao_progredir: Optional[Callable[[int], None]] = None,
) -> bytes:
    """Read a streamed body, raising :class:`ResponseTooLargeError` past
    ``max_bytes``. The request must have been made with ``stream=True``, or the
    whole body is already in memory before this runs.

    ``ao_progredir`` recebe os bytes lidos até ali: no primeiro pedaço e depois
    no máximo a cada :data:`INTERVALO_DO_PROGRESSO`. O que ele levantar sobe.
    """
    buffer = bytearray()
    ultima: Optional[float] = None
    for chunk in response.iter_content(chunk_size=64 * 1024):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise ResponseTooLargeError(f"body exceeded {max_bytes} bytes")
        if ao_progredir is not None:
            agora = time.monotonic()
            if ultima is None or agora - ultima >= INTERVALO_DO_PROGRESSO:
                ultima = agora
                ao_progredir(len(buffer))
    return bytes(buffer)


def _with_body(response: requests.Response, max_bytes: int) -> requests.Response:
    """Read a streamed ``response`` under the cap and keep the body on it, so
    ``.json()`` / ``.text`` / ``.content`` work without reading again. Closes
    the response if the read fails or exceeds ``max_bytes``."""
    try:
        body = read_capped(response, max_bytes)
    except BaseException:
        response.close()
        raise
    # ponytail: sets requests' own cache of the body (what `.content` fills on
    # first access), private but stable for a decade; a wrapper type would be
    # the upgrade if requests ever moves it.
    response._content = body  # pylint: disable=protected-access
    return response


def get_capped(
    url: str, max_bytes: int = MAX_RESPONSE_BYTES, **kwargs: Any
) -> requests.Response:
    """A GET whose body is read under a cap before it is returned.

    A drop-in for call sites that go on to use ``.json()`` / ``.status_code``:
    the body is already read, so ``.json()`` parses what was read and never
    reads more. Raises :class:`ResponseTooLargeError` past ``max_bytes``.
    """
    return _with_body(_get(url, stream=True, **kwargs), max_bytes)


def request_capped(
    method: str, url: str, max_bytes: int = MAX_RESPONSE_BYTES, **kwargs: Any
) -> requests.Response:
    """Like :func:`get_capped` for any method (POST, DELETE...), on a fresh
    connection: these calls carry credentials and must not share a session
    (connections, cookies) with the covers' keep-alive pool."""
    return _with_body(requests.request(method, url, stream=True, **kwargs), max_bytes)


def download_bytes(
    url: str,
    timeout: float = 10,
    max_bytes: int = MAX_IMAGE_BYTES,
    ao_progredir: Optional[Callable[[int, Optional[int]], None]] = None,
) -> bytes:
    """Download ``url`` into memory, aborting if it exceeds ``max_bytes``.

    ``ao_progredir(recebido, total)`` roda nesta thread (ver
    :func:`read_capped`); ``total`` é o ``Content-Length``, ou ``None`` quando
    o servidor não o informa. Para cancelar, ele levanta
    :class:`DownloadCancelado`.

    :raises requests.HTTPError: on a 4xx/5xx response
    :raises ResponseTooLargeError: if the payload exceeds ``max_bytes``
    """
    with _get(url, timeout=timeout, stream=True) as response:
        response.raise_for_status()

        # Trust a declared length when it's clearly too big (fail fast), but
        # always enforce the cap while streaming since the header can be wrong.
        total: Optional[int] = None
        declared = response.headers.get("Content-Length")
        if declared is not None:
            try:
                total = int(declared)
            except ValueError:
                pass
        if total is not None and total > max_bytes:
            raise ResponseTooLargeError(url)
        if total is not None and total <= 0:
            total = None

        if ao_progredir is None:
            return read_capped(response, max_bytes)
        return read_capped(
            response, max_bytes, lambda recebido: ao_progredir(recebido, total)
        )
