# gravar_atomico.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gravação por temporário + ``replace``, a contraparte de `ler_json`.

Quem lê nunca vê o arquivo pela metade: o conteúdo vai para um temporário ao
lado e só troca de lugar no fim. O nome do temporário é único por gravação,
porque duas threads podem gravar o mesmo destino ao mesmo tempo (a varredura e
a varredura de um jogo, dois downloads do mesmo ícone). Uma queda no meio deixa
só um ``.tmp`` órfão; o destino fica como estava.
"""

import time
import uuid
from pathlib import Path
from typing import Union

# No Windows o `replace` falha com PermissionError enquanto outro programa
# (antivírus, indexador) segura o destino aberto, e só por um instante. A espera
# total, no pior caso, fica abaixo de meio segundo.
_TENTATIVAS = 5
_PAUSA = 0.08


def gravar_atomico(destino: Path, conteudo: Union[str, bytes], outro_igual_basta: bool = False) -> None:
    """Grava ``conteudo`` (texto em UTF-8, ou bytes) em ``destino``. Levanta OSError.

    ``outro_igual_basta``: para conteúdo que não muda por destino (um ícone
    baixado, cujo nome é o hash da origem). No Windows, dois ``replace`` no
    mesmo destino ao mesmo tempo fazem um deles falhar; se o arquivo já está
    lá, o outro ganhou com o mesmo conteúdo, e basta.
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
