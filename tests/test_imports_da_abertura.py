"""A abertura não carrega as bibliotecas de rede: elas só servem às threads de trabalho."""

import subprocess
import sys


def test_abrir_o_app_nao_importa_requests():
    codigo = "import kyron.app, sys; print('requests' in sys.modules, 'urllib3' in sys.modules)"
    saida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True).stdout
    assert saida.split() == ["False", "False"]
