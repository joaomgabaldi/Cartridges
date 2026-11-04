# apoio_session_fita.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_session_fita.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

from types import SimpleNamespace

from PIL import Image


def _jogo(tmp_path, game_id="jogo-1", cor=(220, 20, 20)):
    capa = tmp_path / f"{game_id}.png"
    Image.new("RGB", (60, 90), cor).save(capa)
    return SimpleNamespace(game_id=game_id, name="Jogo", get_cover_path=lambda: capa)
