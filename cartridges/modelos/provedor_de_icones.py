# provedor_de_icones.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`image://icone/<nome>/<cor>`: os ícones simbólicos da `main`, pintados na cor pedida, como o GTK pinta os seus."""

import logging
import re
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtSvg import QSvgRenderer

_PASTA = Path(__file__).resolve().parent.parent.parent / "data" / "icones"
# O id vem do QML, mas vira caminho de arquivo: só nome simples, nunca um caminho.
_ID = re.compile(r"([a-z0-9-]+)/([0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_TAMANHO_PADRAO = 16


def caminho(nome: str) -> Path:
    return _PASTA / f"{nome}-symbolic.svg"


class ProvedorDeIcones(QQuickImageProvider):
    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id_: str, size: QSize, requested_size: QSize) -> QImage:  # noqa: N802
        largura = requested_size.width() if requested_size.width() > 0 else _TAMANHO_PADRAO
        altura = requested_size.height() if requested_size.height() > 0 else largura
        imagem = QImage(largura, altura, QImage.Format.Format_ARGB32_Premultiplied)
        imagem.fill(Qt.GlobalColor.transparent)
        size.setWidth(largura)
        size.setHeight(altura)
        pedido = _ID.fullmatch(id_)
        if pedido is None:
            logging.warning("Ícone com identificador inválido: %r", id_)
            return imagem
        arquivo = caminho(pedido[1])
        renderizador = QSvgRenderer(str(arquivo))
        if not renderizador.isValid():
            logging.warning("Ícone ausente ou inválido: %s", arquivo.name)
            return imagem
        pintor = QPainter(imagem)
        renderizador.render(pintor)
        pintor.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
        pintor.fillRect(imagem.rect(), QColor(f"#{pedido[2]}"))
        pintor.end()
        return imagem
