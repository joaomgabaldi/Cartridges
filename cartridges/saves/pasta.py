"""Onde os backups dos saves moram, e a troca dessa pasta.

A escolha fica na chave `pasta-dos-saves` (vazia = a pasta padrão). Trocar não
joga os backups fora: se a pasta nova está vazia eles vão junto; se ela já tem
backups, é ela que vale e a antiga fica como estava.
"""

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


def _tem_saves(pasta: Path) -> bool:
    return pasta.is_dir() and any(item.is_dir() for item in pasta.iterdir())


def trocar(nova: Path) -> None:
    """Passa a guardar os saves em `nova`.

    Levanta `TrocaRecusada`, sem mexer em nada, se `nova` é a pasta atual ou
    está dentro dela.
    """
    antiga = atual()
    chave_nova, chave_antiga = _chave(nova), _chave(antiga)
    if chave_nova == chave_antiga or chave_nova.startswith(chave_antiga + os.sep):
        raise TrocaRecusada(str(nova))

    nova.mkdir(parents=True, exist_ok=True)
    if antiga.is_dir() and not _tem_saves(nova):
        for item in list(antiga.iterdir()):
            shutil.move(str(item), str(nova / item.name))
    # Só depois de mover: uma falha no meio deixa a escolha como estava.
    shared.schema.set_string(_CHAVE, "" if chave_nova == _chave(padrao()) else str(nova))
