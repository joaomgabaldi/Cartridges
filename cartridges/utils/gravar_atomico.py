# gravar_atomico.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gravação por temporário + ``replace``, a contraparte de `ler_json`.

Quem lê nunca vê o arquivo pela metade; uma queda no meio deixa só um ``.tmp`` órfão.
O nome do temporário é único por gravação, porque duas threads podem gravar o mesmo destino.
"""

import time
import uuid
from pathlib import Path
from typing import Union

# No Windows o `replace` falha com PermissionError enquanto o antivírus ou o indexador segura o destino (meio segundo no máximo).
_TENTATIVAS = 5
_PAUSA = 0.08


def gravar_atomico(destino: Path, conteudo: Union[str, bytes], outro_igual_basta: bool = False) -> None:
    """Grava ``conteudo`` (UTF-8 ou bytes) em ``destino``. Levanta OSError.

    ``outro_igual_basta``: para conteúdo fixo por destino (ícone nomeado pelo hash da origem);
    se o ``replace`` de outra thread falhar e o arquivo já existir, basta.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(f"{destino.name}.{uuid.uuid4().hex}.tmp")
    try:
        if isinstance(conteudo, bytes):
            temporario.write_bytes(conteudo)
        else:
            temporario.write_text(conteudo, encoding="utf-8")
        for tentativa in range(_TENTATIVAS):
            try:
                temporario.replace(destino)
                break
            except OSError as erro:
                if outro_igual_basta and destino.is_file():
                    break
                # Só o bloqueio passageiro merece nova tentativa; disco cheio e afins falham na hora.
                if not isinstance(erro, PermissionError) or tentativa == _TENTATIVAS - 1:
                    raise
                time.sleep(_PAUSA)
    finally:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass
