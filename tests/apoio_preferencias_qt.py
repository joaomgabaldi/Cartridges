# apoio_preferencias_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_preferencias_qt.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

from cartridges.utils.window_geometry import Monitor


PRINCIPAL = Monitor(r"\\.\DISPLAY1", 0, 0, 1920, 1080, True, 1, r"\\?\DISPLAY#A#1")


SEGUNDO = Monitor(r"\\.\DISPLAY2", 1920, 0, 800, 600, False, 2, r"\\?\DISPLAY#B#2")
