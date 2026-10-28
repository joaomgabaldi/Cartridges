# test_montar_app_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A árvore do app instalado: lançador, Python embutido, bibliotecas e o pacote lado a lado com `data/`."""

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "build-aux" / "windows" / "montar_app_qt.py"
_spec = importlib.util.spec_from_file_location("montar_app_qt", _SCRIPT)
montar_app_qt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(montar_app_qt)


def _tocar(caminho: Path, texto: str = "x") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")
    return caminho


@pytest.fixture
def insumos(tmp_path):
    """Repositório, Python embutido, bibliotecas e lançador falsos."""
    raiz = tmp_path / "repo"
    _tocar(raiz / "cartridges" / "__init__.py")
    _tocar(raiz / "cartridges" / "qml" / "Aplicativo.qml")
    _tocar(raiz / "cartridges" / "janela" / "qwk_ponte.dll")
    _tocar(raiz / "cartridges" / "__pycache__" / "x.pyc")
    _tocar(raiz / "cartridges" / "shared.pyi")
    _tocar(raiz / "cartridges" / "instalacao.json", '{"canal": "final"}')
    _tocar(raiz / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml.in")
    _tocar(raiz / "data" / "library_placeholder.svg")
    _tocar(raiz / "data" / "sons" / "tique.wav")
    _tocar(raiz / "data" / "icons" / "hicolor" / "scalable" / "apps" / "app.svg")
    _tocar(raiz / "data" / "screenshots" / "grande.png")
    python = tmp_path / "embutido"
    _tocar(python / "python315.dll")
    _tocar(python / "python315._pth", "python315.zip\n.\n\n#import site\n")
    lib = tmp_path / "pip"
    _tocar(lib / "requests" / "__init__.py")
    _tocar(lib / "PySide6" / "QtCore.pyd")
    _tocar(lib / "PySide6" / "Qt6WebEngineCore.dll")
    _tocar(lib / "PySide6" / "QtWebEngineCore.pyd")
    _tocar(lib / "PySide6" / "designer.exe")
    _tocar(lib / "PySide6" / "translations" / "qt_pt.qm")
    _tocar(lib / "PySide6" / "resources" / "icudtl.dat")
    lancador = _tocar(tmp_path / "Cartridges.exe")
    return dict(raiz=raiz, python=python, lib=lib, lancador=lancador)


def test_monta_a_arvore_do_app(insumos, tmp_path):
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "desenvolvimento", **insumos)

    assert (destino / "bin" / "Cartridges.exe").is_file()
    assert (destino / "python" / "python315.dll").is_file()
    assert (destino / "lib" / "requests" / "__init__.py").is_file()
    assert (destino / "app" / "cartridges" / "qml" / "Aplicativo.qml").is_file()
    assert (destino / "app" / "cartridges" / "janela" / "qwk_ponte.dll").is_file()
    # `data/` ao lado do pacote: é onde shared, configuracoes e modelos a procuram
    assert (destino / "app" / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml.in").is_file()
    assert (destino / "app" / "data" / "library_placeholder.svg").is_file()
    assert (destino / "app" / "data" / "sons" / "tique.wav").is_file()
    assert (destino / "app" / "data" / "icons" / "hicolor" / "scalable" / "apps" / "app.svg").is_file()
    assert not (destino / "app" / "data" / "screenshots").exists()
    assert not (destino / "app" / "cartridges" / "__pycache__").exists()
    assert not (destino / "app" / "cartridges" / "shared.pyi").exists()


def test_grava_o_canal_pedido_e_o_pth(insumos, tmp_path):
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "desenvolvimento", **insumos)

    gravado = json.loads((destino / "app" / "cartridges" / "instalacao.json").read_text(encoding="utf-8"))
    assert gravado == {"canal": "desenvolvimento"}
    linhas = (destino / "python" / "python315._pth").read_text(encoding="utf-8").splitlines()
    assert "..\\lib" in linhas and "..\\app" in linhas
    assert "python315.zip" in linhas
    # o repositório de origem não é alterado
    assert json.loads((insumos["raiz"] / "cartridges" / "instalacao.json").read_text()) == {"canal": "final"}


def test_tira_os_modulos_do_qt_que_o_app_nao_usa(insumos, tmp_path):
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "final", **insumos)

    pyside = destino / "lib" / "PySide6"
    assert (pyside / "QtCore.pyd").is_file()
    for sobrou in ("Qt6WebEngineCore.dll", "QtWebEngineCore.pyd", "designer.exe", "translations", "resources"):
        assert not (pyside / sobrou).exists(), sobrou


@pytest.mark.parametrize("faltando", ["data/io.github.joaomgabaldi.Cartridges.gschema.xml.in",
                                      "data/library_placeholder.svg", "cartridges/janela/qwk_ponte.dll"])
def test_recusa_montar_sem_o_que_o_app_exige(insumos, tmp_path, faltando):
    (insumos["raiz"] / faltando).unlink()
    with pytest.raises(SystemExit):
        montar_app_qt.montar(tmp_path / "saida", "final", **insumos)


def test_canal_invalido_e_recusado(insumos, tmp_path):
    with pytest.raises(SystemExit):
        montar_app_qt.montar(tmp_path / "saida", "beta", **insumos)


def test_nao_apaga_pasta_alheia_nem_o_repositorio(insumos, tmp_path):
    alheia = tmp_path / "alheia"
    _tocar(alheia / "meu.txt")
    with pytest.raises(SystemExit):
        montar_app_qt.montar(alheia, "final", **insumos)
    assert (alheia / "meu.txt").is_file()
    for perigo in (insumos["raiz"], tmp_path):
        with pytest.raises(SystemExit):
            montar_app_qt.montar(perigo, "final", **insumos)
    assert (insumos["raiz"] / "cartridges" / "__init__.py").is_file()


def test_remonta_por_cima_do_que_ele_mesmo_montou(insumos, tmp_path):
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "final", **insumos)
    _tocar(destino / "resto.txt")
    montar_app_qt.montar(destino, "desenvolvimento", **insumos)
    assert not (destino / "resto.txt").exists()
    assert (destino / "bin" / "Cartridges.exe").is_file()
