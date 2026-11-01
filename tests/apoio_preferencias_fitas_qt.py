# apoio_preferencias_fitas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_preferencias_fitas_qt.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

import pytest

from cartridges.utils import session_fita


def _com_fitas(*nomes):
    session_fita.gravar_fitas(
        [session_fita.Fita(nome, f"eb{i}", f"192.0.2.{10 + i}", "chave") for i, nome in enumerate(nomes or ("Centro",))]
    )


@pytest.fixture
def previas(monkeypatch):
    """Cada `previa(cor, tetos)` pedida, sem acender nada."""
    pedidas = []
    monkeypatch.setattr(session_fita, "previa", lambda cor, tetos=None, *_a: pedidas.append((cor, tetos)))
    return pedidas
