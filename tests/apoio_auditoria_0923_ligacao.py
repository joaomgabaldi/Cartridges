# apoio_auditoria_0923_ligacao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_auditoria_0923_ligacao.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

import pytest


@pytest.fixture
def ligar():
    from cartridges.utils.ligacao_zerado import ligar_zerado  # noqa: PLC0415

    return ligar_zerado
