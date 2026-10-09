# test_hwnd_ordem_import.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O HWND tem de sair mesmo com a superfície lida antes de qualquer uso dela.

Se o PyGObject embrulha uma superfície antes de o namespace GdkWin32 ser
carregado, ele registra para o GType uma classe genérica, sem métodos, e daí em
diante ``GdkWin32.Win32Surface`` devolve essa classe: o ``get_handle`` some e
nenhuma janela é posicionada (mover o app para outro monitor, os números de
"Identificar monitores"). O ``main.py`` tem de carregar o GdkWin32 antes de
qualquer janela existir. Roda num processo novo porque o registro de tipos do
PyGObject é do processo inteiro e outro teste já pode ter importado o GdkWin32.
"""

import subprocess
import sys
import textwrap
from pathlib import Path


def test_hwnd_com_superficie_lida_antes():
    testes = Path(__file__).resolve().parent
    script = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(testes)!r})
        import conftest  # monta o cartridges.shared falso e o gresource
        import cartridges.main  # o que o app carrega ao abrir
        from gi.repository import Gtk
        from cartridges.utils import window_geometry

        janela = Gtk.Window()
        janela.realize()
        janela.get_surface()  # o autoplay lê a superfície no "realize"
        print("HWND", window_geometry._hwnd(janela))
        """
    )
    filho = subprocess.run(
        [sys.executable, "-c", script], check=False, capture_output=True, text=True
    )

    assert "HWND None" not in filho.stdout, filho.stderr
    assert "HWND " in filho.stdout, filho.stderr
