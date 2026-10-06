"""O progresso de um jogo da Ubisoft Connect: o arquivo `<productId>.spool`.

O Ubisoft Connect grava em `%LOCALAPPDATA%\\Ubisoft Game Launcher\\spool\\<conta>\\` o
histórico das conquistas da conta para cada jogo aberto neste PC, e o regrava no instante
do desbloqueio (conferido no host em 05/10/2026). O formato é protobuf sem schema: o campo
1, repetido, é uma conquista; dentro dele, o campo 1 traz o id — numa submensagem,
`1:{1:id}`, como no host; o PSerban93/Achievements (MIT) lê o id direto, `1:id`, e os
dois são aceitos — e o campo 2 traz a hora do desbloqueio, em segundos Unix.
"""

import logging
from pathlib import Path
from typing import Optional

from cartridges.conquistas.formatos import Desbloqueio

PREFIXO = "UBI:"
_TAMANHO_MAXIMO = 1024 * 1024
_ID_MAXIMO = 2**31
_HORA_MINIMA = 946_684_800  # 2000-01-01
_HORA_MAXIMA = 4_102_444_800  # 2100-01-01
# Hora a partir daqui está em milissegundos.
_EM_MILISSEGUNDOS = 10**10


class _Invalido(Exception):
    """Os bytes não formam uma mensagem protobuf."""


def _varint(dados: bytes, pos: int, fim: int) -> tuple[int, int]:
    valor = 0
    for deslocamento in range(0, 70, 7):
        if pos >= fim:
            raise _Invalido("varint truncado")
        byte = dados[pos]
        pos += 1
        valor |= (byte & 0x7F) << deslocamento
        if not byte & 0x80:
            return valor, pos
    raise _Invalido("varint longo demais")


def _campos(dados: bytes, inicio: int, fim: int) -> list[tuple[int, int, object]]:
    """Os campos de uma mensagem: ``(número, tipo, valor)``.

    Varint vira ``int``; campo de tamanho vira ``(início, fim)`` do conteúdo; os tipos
    1 e 5 (fixos) são pulados.
    """
    campos: list[tuple[int, int, object]] = []
    pos = inicio
    while pos < fim:
        tag, pos = _varint(dados, pos, fim)
        numero, tipo = tag >> 3, tag & 7
        if numero == 0:
            raise _Invalido("campo zero")
        if tipo == 0:
            valor, pos = _varint(dados, pos, fim)
            campos.append((numero, 0, valor))
        elif tipo == 2:
            tamanho, pos = _varint(dados, pos, fim)
            if tamanho > fim - pos:
                raise _Invalido("tamanho maior que o resto")
            campos.append((numero, 2, (pos, pos + tamanho)))
            pos += tamanho
        elif tipo == 1:
            pos += 8
        elif tipo == 5:
            pos += 4
        else:
            raise _Invalido(f"tipo {tipo}")
    if pos != fim:
        raise _Invalido("passou do fim")
    return campos


def _segundos(hora: Optional[int]) -> int:
    if hora is None:
        return 0
    if hora >= _EM_MILISSEGUNDOS:
        hora //= 1000
    return hora if _HORA_MINIMA <= hora < _HORA_MAXIMA else 0


def _registro(dados: bytes, inicio: int, fim: int) -> Optional[Desbloqueio]:
    """Uma conquista, ou None se o registro não tiver um id que preste."""
    try:
        campos = _campos(dados, inicio, fim)
    except _Invalido:
        return None
    id_: Optional[int] = None
    hora: Optional[int] = None
    for numero, tipo, valor in campos:
        if numero == 1 and id_ is None:
            if tipo == 0:
                id_ = valor  # type: ignore[assignment]
            elif tipo == 2:
                try:
                    dentro = _campos(dados, *valor)  # type: ignore[misc]
                except _Invalido:
                    continue
                id_ = next((v for n, t, v in dentro if n == 1 and t == 0), None)  # type: ignore[misc]
        elif numero == 2 and tipo == 0 and hora is None:
            hora = valor  # type: ignore[assignment]
    if id_ is None or not 0 < id_ <= _ID_MAXIMO:
        return None
    return Desbloqueio(f"{PREFIXO}{id_}", _segundos(hora))


def ler_ou_none(caminho: Path) -> Optional[list[Desbloqueio]]:
    """As conquistas do `.spool`, ou None se ele não pôde ser lido agora.

    Arquivo ausente é o caso normal (jogo nunca aberto neste PC): None sem log.
    """
    try:
        with open(caminho, "rb") as arquivo:
            dados = arquivo.read(_TAMANHO_MAXIMO + 1)
    except FileNotFoundError:
        return None
    except OSError as erro:
        logging.info("Progresso de conquistas da Ubisoft ilegível: %s", type(erro).__name__)
        return None
    if len(dados) > _TAMANHO_MAXIMO:
        logging.info("Progresso de conquistas da Ubisoft grande demais; ignorado")
        return None
    try:
        campos = _campos(dados, 0, len(dados))
    except _Invalido as erro:
        logging.info("Progresso de conquistas da Ubisoft em formato inesperado: %s", erro)
        return None
    lidos = []
    for numero, tipo, valor in campos:
        if numero == 1 and tipo == 2:
            desbloqueio = _registro(dados, *valor)  # type: ignore[misc]
            if desbloqueio is not None:
                lidos.append(desbloqueio)
    return lidos


def ler(caminho: Path) -> list[Desbloqueio]:
    return ler_ou_none(caminho) or []
