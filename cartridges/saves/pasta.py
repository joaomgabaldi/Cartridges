"""Onde os backups dos saves moram, e a troca dessa pasta.

A escolha fica na chave `pasta-dos-saves` (vazia = a pasta padrão). Trocar não
joga os backups fora: se a pasta nova está vazia eles vão junto; se ela já tem
backups, é ela que vale e a antiga fica como estava.
"""

import logging
import os
import shutil
from pathlib import Path

from cartridges import shared

_CHAVE = "pasta-dos-saves"


class TrocaRecusada(ValueError):
    """A pasta nova é a atual ou fica dentro dela."""


def padrao() -> Path:
    return shared.app_dir / "saves"


def atual() -> Path:
    escolhida = shared.schema.get_string(_CHAVE)
    return Path(escolhida) if escolhida else padrao()


def _chave(caminho: Path) -> str:
    """Forma comparável do caminho: absoluto e sem diferença de maiúsculas."""
    return os.path.normcase(os.path.abspath(caminho))


def _dentro(caminho: Path, pasta: Path) -> bool:
    """Se `caminho` é `pasta` ou está dentro dela. `commonpath` e não prefixo de
    texto: a raiz de um disco já termina no separador."""
    try:
        return os.path.commonpath([_chave(caminho), _chave(pasta)]) == _chave(pasta)
    except ValueError:  # discos diferentes
        return False


def _tem_saves(pasta: Path) -> bool:
    return pasta.is_dir() and any(item.is_dir() for item in pasta.iterdir())


def _copiar(item: Path, destino: Path) -> None:
    if item.is_dir():
        shutil.copytree(item, destino)
    else:
        shutil.copy2(item, destino)


def _apagar(caminho: Path) -> None:
    if caminho.is_dir():
        shutil.rmtree(caminho)
    else:
        caminho.unlink()


def _levar(antiga: Path, nova: Path) -> list[Path]:
    """Copia o conteúdo de `antiga` para `nova` e devolve os itens copiados.

    Se qualquer cópia falhar, apaga só o que esta chamada já copiou para `nova`
    (os originais nunca foram tocados) e relança o erro.
    """
    itens = list(antiga.iterdir())
    if any((nova / item.name).exists() for item in itens):
        raise TrocaRecusada(str(nova))
    nova.mkdir(parents=True, exist_ok=True)
    copiados: list[Path] = []
    try:
        for item in itens:
            copiados.append(nova / item.name)  # antes, para limpar uma cópia pela metade
            _copiar(item, nova / item.name)
    except BaseException:
        for copiado in copiados:
            if copiado.is_dir():
                shutil.rmtree(copiado, ignore_errors=True)
            else:
                copiado.unlink(missing_ok=True)
        raise
    return itens


def trocar(nova: Path) -> None:
    """Passa a guardar os saves em `nova`.

    Levanta `TrocaRecusada`, sem mexer em nada, se `nova` é a pasta atual, está
    dentro dela, é uma pasta que a contém, ou já tem arquivos com o nome de algo
    que precisaria receber.
    """
    antiga = atual()
    if _dentro(nova, antiga) or _dentro(antiga, nova):
        raise TrocaRecusada(str(nova))

    originais: list[Path] = []
    if antiga.is_dir() and not _tem_saves(nova):
        originais = _levar(antiga, nova)
    nova.mkdir(parents=True, exist_ok=True)
    # A escolha só muda com tudo copiado; uma falha antes deixa a antiga valendo.
    shared.schema.set_string(_CHAVE, "" if _chave(nova) == _chave(padrao()) else str(nova))
    for original in originais:
        try:
            _apagar(original)
        except OSError:
            logging.warning("Save antigo não removido de %s", original, exc_info=True)
