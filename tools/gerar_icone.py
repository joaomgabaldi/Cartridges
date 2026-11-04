# gerar_icone.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Gera o `icon.ico` do instalador a partir do SVG do app (`python tools/gerar_icone.py`)."""

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

RAIZ = Path(__file__).resolve().parent.parent
SVG_DO_APP = RAIZ / "data" / "icons" / "hicolor" / "scalable" / "apps" / "io.github.joaomgabaldi.Cartridges.svg"
ICO_DO_INSTALADOR = RAIZ / "build-aux" / "windows" / "icon.ico"


def _png(renderer: QSvgRenderer, lado: int) -> bytes:
    imagem = QImage(lado, lado, QImage.Format.Format_ARGB32)
    imagem.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(imagem)
    renderer.render(pintor)
    pintor.end()
    dados = QByteArray()
    buffer = QBuffer(dados)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    imagem.save(buffer, "PNG")
    return bytes(dados)


def gerar_ico(svg: Path, destino: Path, tamanhos: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)) -> None:
    """Grava um ICO com um PNG embutido por tamanho (formato Vista+)."""
    renderer = QSvgRenderer(str(svg))
    if not renderer.isValid():
        raise ValueError(f"SVG inválido: {svg}")
    pngs = [_png(renderer, lado) for lado in tamanhos]
    cabecalho = struct.pack("<HHH", 0, 1, len(pngs))
    posicao = 6 + 16 * len(pngs)
    diretorio = b""
    for lado, png in zip(tamanhos, pngs):
        diretorio += struct.pack("<BBBBHHII", lado % 256, lado % 256, 0, 0, 1, 32, len(png), posicao)
        posicao += len(png)
    destino.write_bytes(cabecalho + diretorio + b"".join(pngs))


if __name__ == "__main__":
    _app = QGuiApplication.instance() or QGuiApplication([])
    gerar_ico(SVG_DO_APP, ICO_DO_INSTALADOR)
