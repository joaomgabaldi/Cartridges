"""O provedor `image://icone`: pinta o ícone na cor pedida e recusa o que não é um nome simples."""

import os

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kyron.modelos.provedor_de_icones import ProvedorDeIcones, caminho  # noqa: E402


@pytest.fixture(autouse=True)
def _app(app_qt):
    yield app_qt


def _pedir(id_, tamanho=QSize(16, 16)):
    size = QSize()
    return ProvedorDeIcones().requestImage(id_, size, tamanho), size


def _pixels_opacos(imagem):
    return [
        imagem.pixelColor(x, y)
        for x in range(imagem.width())
        for y in range(imagem.height())
        if imagem.pixelColor(x, y).alpha() == 255
    ]


def test_pinta_na_cor_pedida():
    imagem, size = _pedir("window-close/ff0000")
    assert size == QSize(16, 16)
    opacos = _pixels_opacos(imagem)
    assert opacos
    assert all(c == QColor("#ff0000") for c in opacos)


@pytest.mark.parametrize(
    "id_",
    ["../../segredo/ff0000", r"..\segredo/ff0000", "window-close", "window-close/zzzzzz", "/ff0000", "a/b/ff0000"],
)
def test_id_invalido_devolve_imagem_vazia(id_):
    imagem, _ = _pedir(id_)
    assert not _pixels_opacos(imagem)


def test_icone_ausente_devolve_imagem_vazia():
    imagem, _ = _pedir("nao-existe/ffffff")
    assert not _pixels_opacos(imagem)


@pytest.mark.parametrize(
    "nome",
    ["window-close", "window-minimize", "window-maximize", "window-restore", "trofeu", "novidades", "open-menu"],
)
def test_os_icones_da_barra_existem(nome):
    assert caminho(nome).is_file()
