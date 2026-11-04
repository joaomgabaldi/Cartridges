# test_gerar_icone.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `icon.ico` do instalador sai do SVG do app, com todos os tamanhos."""

import struct
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from gerar_icone import gerar_ico  # noqa: E402

SVG = RAIZ / "data" / "icons" / "hicolor" / "scalable" / "apps" / "io.github.joaomgabaldi.Cartridges.svg"


def test_gerar_ico_tem_todos_os_tamanhos(tmp_path):
    destino = tmp_path / "icon.ico"
    gerar_ico(SVG, destino)
    dados = destino.read_bytes()
    reservado, tipo, quantidade = struct.unpack_from("<HHH", dados)
    assert (reservado, tipo, quantidade) == (0, 1, 7)
    larguras = [struct.unpack_from("<B", dados, 6 + 16 * i)[0] for i in range(quantidade)]
    assert larguras == [16, 24, 32, 48, 64, 128, 0]  # 256 é gravado como 0
    for i in range(quantidade):
        tamanho, posicao = struct.unpack_from("<II", dados, 6 + 16 * i + 8)
        assert dados[posicao:posicao + 8] == b"\x89PNG\r\n\x1a\n"
