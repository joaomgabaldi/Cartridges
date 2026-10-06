"""Qual jogo é da Ubisoft Connect, e qual é o productId dele.

O atalho do launcher é `uplay://launch/<productId>/0` (Playnite, `Uplay.cs`; conferido nos
atalhos do usuário). Um `.lnk` direto para o `.exe` é reconhecido pela pasta de instalação
que o registro do launcher guarda para cada produto (`locais.instalacoes`): vale a mais
funda que contém a pasta do executável.
"""

import os
import re
from pathlib import Path
from typing import Any, Optional

from cartridges.conquistas import arquivos
from cartridges.conquistas.ubisoft import locais

_URL = re.compile(r"uplay://launch/([0-9]{1,10})\b", re.IGNORECASE)


def de_url(executavel: str) -> Optional[str]:
    """O productId do atalho do launcher. Só o texto, nunca o disco."""
    achado = _URL.search(executavel or "")
    return achado.group(1) if achado else None


def _da_pasta(pastas: list[Path]) -> Optional[str]:
    melhor: Optional[tuple[int, str]] = None
    for produto, raiz in locais.instalacoes().items():
        for base in pastas:
            try:
                pasta = Path(os.path.normcase(os.path.abspath(base)))
            except (OSError, ValueError):
                continue
            # Pasta inteira: `AC2` não está dentro de `AC`.
            if (pasta == raiz or raiz in pasta.parents) and (melhor is None or len(raiz.parts) > melhor[0]):
                melhor = (len(raiz.parts), produto)
    return melhor[1] if melhor is not None else None


def do_jogo(game: Any) -> Optional[str]:
    """O productId do jogo da Ubisoft, ou None. Olha o disco e o registro: só em thread."""
    executavel = getattr(game, "executable", "") or ""
    produto = de_url(executavel)
    if produto is not None:
        return produto
    pastas = arquivos.bases_do_jogo(executavel)
    return _da_pasta(pastas) if pastas else None
