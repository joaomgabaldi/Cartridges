"""O formato binário KeyValues, em que a Steam guarda as conquistas em `appcache\\stats`.

Cada item é um byte de tipo, a chave em UTF-8 terminada em zero e o valor. Uma
seção (tipo 0) traz itens até o seu fim (8, ou 11 em arquivos mais novos). O
arquivo inteiro é a seção raiz, e também termina em 8.

Nunca levanta. A Steam pode estar gravando o arquivo no instante da leitura: um
arquivo cortado, travado ou estranho vale None ("falha de leitura"), e quem lê
tenta de novo depois.
"""

import logging
import re
import struct
from pathlib import Path
from typing import Any, Optional

LIMITE_DE_BYTES = 16 * 1024 * 1024
LIMITE_DE_NIVEIS = 32

_SECAO = 0
_TEXTO = 1
_FIM = (8, 11)
# Os tipos de tamanho fixo: int32, float32, ponteiro, cor, uint64 e int64.
_FIXOS = {2: "<i", 3: "<f", 4: "<I", 6: "<I", 7: "<Q", 10: "<q"}


class _Ilegivel(Exception):
    pass


def _texto(dados: bytes, inicio: int) -> tuple[str, int]:
    fim = dados.find(b"\0", inicio)
    if fim < 0:
        raise _Ilegivel("texto sem fim")
    return dados[inicio:fim].decode("utf-8", errors="replace"), fim + 1


def _secao(dados: bytes, inicio: int, nivel: int) -> tuple[dict[str, Any], int]:
    if nivel > LIMITE_DE_NIVEIS:
        raise _Ilegivel("seções fundas demais")
    itens: dict[str, Any] = {}
    i = inicio
    while True:
        if i >= len(dados):
            raise _Ilegivel("seção sem fim")
        tipo = dados[i]
        i += 1
        if tipo in _FIM:
            return itens, i
        chave, i = _texto(dados, i)
        if tipo == _SECAO:
            itens[chave], i = _secao(dados, i, nivel + 1)
        elif tipo == _TEXTO:
            itens[chave], i = _texto(dados, i)
        elif tipo in _FIXOS:
            formato = _FIXOS[tipo]
            tamanho = struct.calcsize(formato)
            if i + tamanho > len(dados):
                raise _Ilegivel("valor cortado")
            itens[chave] = struct.unpack_from(formato, dados, i)[0]
            i += tamanho
        else:
            raise _Ilegivel(f"tipo {tipo}")


def ler_bytes(dados: bytes) -> Optional[dict[str, Any]]:
    """A seção raiz de ``dados``, ou None se não for KeyValues inteiro e válido."""
    if len(dados) > LIMITE_DE_BYTES:
        return None
    try:
        return _secao(dados, 0, 0)[0]
    except _Ilegivel:
        return None


LIMITE_DO_TEXTO = 1024 * 1024
# Uma string entre aspas (com barra invertida escapando o que vier) ou uma chave.
_TOKEN_DE_TEXTO = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])', re.DOTALL)


def ler_texto_bytes(dados: bytes) -> Optional[dict[str, Any]]:
    """O KeyValues em texto (``"chave" "valor"`` e ``"chave" { ... }``), ou None.

    Tolerante: só entende strings entre aspas e chaves, e vale None para
    qualquer coisa que não feche direito. Os valores vêm como texto.
    """
    if len(dados) > LIMITE_DO_TEXTO:
        return None
    texto = dados.decode("utf-8", errors="replace")
    raiz: dict[str, Any] = {}
    pilha = [raiz]
    chave: Optional[str] = None
    for achado in _TOKEN_DE_TEXTO.finditer(texto):
        if achado.group(2) == "{":
            if chave is None or len(pilha) > LIMITE_DE_NIVEIS:
                return None
            secao: dict[str, Any] = {}
            pilha[-1][chave] = secao
            pilha.append(secao)
            chave = None
        elif achado.group(2) == "}":
            if len(pilha) == 1 or chave is not None:
                return None
            pilha.pop()
        elif chave is None:
            chave = achado.group(1)
        else:
            pilha[-1][chave] = achado.group(1)
            chave = None
    return raiz if len(pilha) == 1 and chave is None else None


def ler_texto(caminho: Path) -> Optional[dict[str, Any]]:
    """O arquivo KeyValues em texto, ou None se não pôde ser lido ou entendido.

    Nada do conteúdo vai ao log (o ``loginusers.vdf`` traz nomes de conta).
    """
    try:
        with open(caminho, "rb") as arquivo:
            dados = arquivo.read(LIMITE_DO_TEXTO + 1)
    except (OSError, ValueError):
        return None
    return ler_texto_bytes(dados)


def ler(caminho: Path) -> Optional[dict[str, Any]]:
    """O conteúdo do arquivo, ou None se ele não pôde ser lido ou entendido."""
    try:
        with open(caminho, "rb") as arquivo:
            dados = arquivo.read(LIMITE_DE_BYTES + 1)
    except (OSError, ValueError) as erro:  # ValueError: caminho com NUL embutido
        logging.info("KeyValues ilegível em %s: %s", caminho, type(erro).__name__)
        return None
    return ler_bytes(dados)
