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

"""Lê corpos HTTP para a memória com limite de tamanho.

O limite evita que uma URL gigante esgote a memória; a leitura em fluxo o impõe mesmo quando o servidor mente
sobre (ou omite) o Content-Length. O timeout não limita o tamanho, só o silêncio entre bytes.
"""

import threading
import time
from typing import Any, Callable, Optional

import requests

MAX_IMAGE_BYTES = 25 * 1024 * 1024

# Capas animadas do SteamGridDB passam de 60 MB (APNG).
MAX_ANIMATED_IMAGE_BYTES = 200 * 1024 * 1024

MAX_WALLPAPER_BYTES = 50 * 1024 * 1024

# Respostas de API (JSON, HTML); a maior real, uma página /game/<id> do HowLongToBeat, tem ~1–2 MiB.
MAX_RESPONSE_BYTES = 10 * 1024 * 1024

# Quem mostra o progresso redesenha a cada chamada; dez por segundo bastam.
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
    """``requests.get`` pela sessão da própria thread, reaproveitando conexões.

    Uma conexão nova por chamada sofria travadas de 1 a 7 s com um pacote perdido. Uma sessão por thread:
    ``requests.Session`` não é documentada como thread-safe.
    """
    session = getattr(_local, "session", None)
    if session is None:
        session = _local.session = requests.Session()
    try:
        return session.get(url, **kwargs)
    finally:
        # Cookie (país, sessão da Steam) não pode mudar a resposta seguinte.
        session.cookies.clear()


def read_capped(
    response: requests.Response,
    max_bytes: int,
    ao_progredir: Optional[Callable[[int], None]] = None,
) -> bytes:
    """Lê um corpo em fluxo (``stream=True``), levantando :class:`ResponseTooLargeError` acima de ``max_bytes``.

    ``ao_progredir`` recebe os bytes lidos no primeiro pedaço e depois no máximo a cada :data:`INTERVALO_DO_PROGRESSO`.
    """
    buffer = bytearray()
    ultima: Optional[float] = None
    informado = 0
    for chunk in response.iter_content(chunk_size=64 * 1024):
        buffer.extend(chunk)
        if len(buffer) > max_bytes:
            raise ResponseTooLargeError(f"body exceeded {max_bytes} bytes")
        if ao_progredir is not None:
            agora = time.monotonic()
            if ultima is None or agora - ultima >= INTERVALO_DO_PROGRESSO:
                ultima = agora
                informado = len(buffer)
                ao_progredir(informado)
    # O fim sempre chega a quem mostra o progresso, senão a barra para nos últimos MB.
    if ao_progredir is not None and informado != len(buffer):
        ao_progredir(len(buffer))
    return bytes(buffer)


def _with_body(response: requests.Response, max_bytes: int) -> requests.Response:
    """Lê a ``response`` sob o limite e guarda o corpo nela; fecha-a se a leitura falhar ou passar de ``max_bytes``."""
    try:
        body = read_capped(response, max_bytes)
    except BaseException:
        response.close()
        raise
    # shortcut: usa o cache privado do requests (o que `.content` preenche), estável há anos; trocar por um wrapper se mudar.
    response._content = body  # pylint: disable=protected-access
    return response


def get_capped(
    url: str, max_bytes: int = MAX_RESPONSE_BYTES, **kwargs: Any
) -> requests.Response:
    """Um GET cujo corpo é lido sob o limite antes de voltar. Levanta :class:`ResponseTooLargeError` acima de ``max_bytes``."""
    return _with_body(_get(url, stream=True, **kwargs), max_bytes)


def request_capped(
    method: str, url: str, max_bytes: int = MAX_RESPONSE_BYTES, **kwargs: Any
) -> requests.Response:
    """Como :func:`get_capped` para qualquer método, em conexão nova: leva credenciais e não divide sessão com as capas."""
    return _with_body(requests.request(method, url, stream=True, **kwargs), max_bytes)


def download_bytes(
    url: str,
    timeout: float = 10,
    max_bytes: int = MAX_IMAGE_BYTES,
    ao_progredir: Optional[Callable[[int, Optional[int]], None]] = None,
) -> bytes:
    """Baixa ``url`` para a memória, abortando acima de ``max_bytes``.

    ``ao_progredir(recebido, total)`` roda nesta thread (``total`` é o ``Content-Length`` ou ``None``);
    para cancelar, levanta :class:`DownloadCancelado`. Levanta ``HTTPError`` em 4xx/5xx e :class:`ResponseTooLargeError`.
    """
    with _get(url, timeout=timeout, stream=True) as response:
        response.raise_for_status()

        # Falha cedo se o tamanho declarado já é grande demais; o limite vale no fluxo porque o cabeçalho pode mentir.
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
