# test_montar_app_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A árvore do app instalado: lançador, Python embutido, bibliotecas e o pacote lado a lado com `data/`."""

import hashlib
import importlib.util
import json
import re
import zipfile
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


def _externo(pasta: Path, nome: str, licenca: str) -> Path:
    _tocar(pasta / nome / "LICENSE", licenca)
    return _tocar(pasta / nome / f"{nome}.exe")


@pytest.fixture
def insumos(tmp_path):
    """Repositório, Python embutido, bibliotecas e lançador falsos."""
    raiz = tmp_path / "repo"
    _tocar(raiz / "cartridges" / "__init__.py")
    _tocar(raiz / "cartridges" / "qml" / "Aplicativo.qml")
    _tocar(raiz / "cartridges" / "janela" / "qwk_ponte.dll")
    _tocar(raiz / "cartridges" / "__pycache__" / "x.pyc")
    _tocar(raiz / "cartridges" / "store" / "__init__.py")
    _tocar(raiz / "cartridges" / "store" / "__pycache__" / "y.pyc")
    _tocar(raiz / "cartridges" / "shared.pyi")
    _tocar(raiz / "cartridges" / "instalacao.json", '{"canal": "final"}')
    _tocar(raiz / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml.in")
    _tocar(raiz / "data" / "library_placeholder.svg")
    _tocar(raiz / "data" / "library_placeholder_small.svg")
    _tocar(raiz / "data" / "io.github.joaomgabaldi.Cartridges.metainfo.xml.in", "<component/>")
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
    _tocar(lib / "PySide6" / "plugins" / "imageformats" / "qwebp.dll")
    _tocar(lib / "PySide6" / "translations" / "qt_pt.qm")
    _tocar(lib / "PySide6" / "resources" / "icudtl.dat")
    _tocar(lib / "PySide6" / "__init__.py")  # "x" é Python válido: a montagem compila os `.py`
    qwk = raiz / "build-aux" / "windows" / "qwk" / "_deps" / "qwindowkit"
    _tocar(qwk / "LICENSE", "Apache")
    _tocar(qwk / "qmsetup" / "LICENSE", "MIT")
    _tocar(raiz / "build-aux/windows/licencas/adwaita-icon-theme.txt", "CC-BY-SA ou LGPL")
    _tocar(raiz / "build-aux/windows/licencas/libadwaita.txt", "LGPL 2.1")
    lancador = _tocar(tmp_path / "Kyron.exe")
    return dict(
        raiz=raiz, python=python, lib=lib, lancador=lancador,
        ffmpeg=_externo(tmp_path, "ffmpeg", "GPL do FFmpeg"), ludusavi=_externo(tmp_path, "ludusavi", "MIT do Ludusavi"),
    )  # fmt: skip


def test_monta_a_arvore_do_app(insumos, tmp_path):
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "desenvolvimento", **insumos)

    assert (destino / "bin" / "Kyron.exe").is_file()
    assert (destino / "python" / "python315.dll").is_file()
    assert (destino / "lib" / "requests" / "__init__.py").is_file()
    assert (destino / "app" / "cartridges" / "qml" / "Aplicativo.qml").is_file()
    assert (destino / "app" / "cartridges" / "janela" / "qwk_ponte.dll").is_file()
    # `data/` ao lado do pacote: é onde shared, configuracoes e modelos a procuram
    assert (destino / "app" / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml.in").is_file()
    assert (destino / "app" / "data" / "library_placeholder.svg").is_file()
    assert (destino / "app" / "data" / "library_placeholder_small.svg").is_file()
    assert (destino / "app" / "data" / "sons" / "tique.wav").is_file()
    assert (destino / "app" / "data" / "icons" / "hicolor" / "scalable" / "apps" / "app.svg").is_file()
    assert not (destino / "app" / "data" / "screenshots").exists()
    # o bytecode do repositório fica de fora: só entra o que a montagem compila
    assert not (destino / "app" / "cartridges" / "__pycache__" / "x.pyc").exists()
    assert (destino / "app" / "cartridges" / "store" / "__init__.py").is_file()
    assert not (destino / "app" / "cartridges" / "store" / "__pycache__" / "y.pyc").exists()
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
    # As capas animadas (AnimatedImage) dependem do plugin de WebP.
    assert (pyside / "plugins" / "imageformats" / "qwebp.dll").is_file()


@pytest.mark.parametrize("faltando", ["data/io.github.joaomgabaldi.Cartridges.gschema.xml.in",
                                      "data/library_placeholder.svg", "cartridges/janela/qwk_ponte.dll",
                                      "data/io.github.joaomgabaldi.Cartridges.metainfo.xml.in",
                                      "build-aux/windows/qwk/_deps/qwindowkit/LICENSE"])
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
    assert (destino / "bin" / "Kyron.exe").is_file()


def test_montar_mantem_o_qt5compat(insumos, tmp_path):
    # O reflexo do Big Picture usa o OpacityMask do Qt5Compat.GraphicalEffects.
    efeitos = insumos["lib"] / "PySide6" / "qml" / "Qt5Compat" / "GraphicalEffects"
    arquivos = (
        "qmldir", "OpacityMask.qml", "qtgraphicaleffectsplugin.dll", "private/qtgraphicaleffectsprivateplugin.dll",
    )  # fmt: skip
    for nome in arquivos:
        _tocar(efeitos / nome)
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "final", **insumos)

    for nome in arquivos:
        assert (destino / "lib" / "PySide6" / "qml" / "Qt5Compat" / "GraphicalEffects" / nome).is_file(), nome


def test_monta_as_imagens_do_assistente(insumos, tmp_path):
    """O assistente da primeira abertura mostra a capa e o ícone de conquista de exemplo, lidos de `data/`."""
    for nome in ("capa_de_exemplo.svg", "conquista_de_exemplo.svg"):
        _tocar(insumos["raiz"] / "data" / nome, "<svg/>")
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "desenvolvimento", **insumos)
    for nome in ("capa_de_exemplo.svg", "conquista_de_exemplo.svg"):
        assert (destino / "app" / "data" / nome).is_file(), nome


def test_monta_a_metainfo_para_o_sobre(insumos, tmp_path):
    """O "Sobre o Cartridges" lê as novidades e a descrição de `data/` ao lado do pacote."""
    _tocar(insumos["raiz"] / "data" / "io.github.joaomgabaldi.Cartridges.metainfo.xml.in", "<component/>")
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "desenvolvimento", **insumos)
    assert (destino / "app" / "data" / "io.github.joaomgabaldi.Cartridges.metainfo.xml.in").is_file()


def test_monta_o_ffmpeg_ao_lado_do_lancador(insumos, tmp_path):
    # `capa_video.executavel` o procura ao lado do `sys.executable`, que no app instalado é o lançador.
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "final", **insumos)
    assert (destino / "bin" / "ffmpeg.exe").is_file()
    assert (destino / "bin" / "Kyron.exe").is_file()


def test_monta_o_ludusavi_ao_lado_do_lancador(insumos, tmp_path):
    # O `[InstallDelete]` apaga o `ludusavi.exe` da versão GTK: sem este, o backup dos saves some em silêncio.
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "final", **insumos)
    assert (destino / "bin" / "ludusavi.exe").is_file()
    assert (destino / "licencas" / "Ludusavi.txt").read_text(encoding="utf-8") == "MIT do Ludusavi"


@pytest.mark.parametrize("externo", ["ffmpeg", "ludusavi"])
def test_canal_final_exige_o_ffmpeg(insumos, tmp_path, externo):
    insumos[externo] = None
    destino = tmp_path / "saida"
    with pytest.raises(SystemExit):
        montar_app_qt.montar(destino, "final", **insumos)
    assert not destino.exists()


def test_recusa_o_ffmpeg_sem_a_licenca(insumos, tmp_path):
    (insumos["ffmpeg"].parent / "LICENSE").unlink()
    with pytest.raises(SystemExit):
        montar_app_qt.montar(tmp_path / "saida", "final", **insumos)


def test_canal_de_desenvolvimento_monta_sem_ffmpeg(insumos, tmp_path):
    del insumos["ffmpeg"], insumos["ludusavi"]
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "desenvolvimento", **insumos)
    assert not (destino / "bin" / "ffmpeg.exe").exists()
    assert not (destino / "bin" / "ludusavi.exe").exists()
    assert not (destino / "licencas" / "FFmpeg.txt").exists()


def test_monta_as_licencas(insumos, tmp_path):
    _tocar(insumos["lib"] / "pyside6-6.12.0.dist-info" / "licenses" / "LICENSE", "LGPL")
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "final", **insumos)
    licencas = destino / "licencas"
    assert (licencas / "QWindowKit.txt").read_text(encoding="utf-8") == "Apache"
    assert (licencas / "qmsetup.txt").read_text(encoding="utf-8") == "MIT"
    assert (licencas / "adwaita-icon-theme.txt").read_text(encoding="utf-8") == "CC-BY-SA ou LGPL"
    assert (licencas / "libadwaita.txt").read_text(encoding="utf-8") == "LGPL 2.1"
    assert (licencas / "FFmpeg.txt").read_text(encoding="utf-8") == "GPL do FFmpeg"
    assert (destino / "lib" / "pyside6-6.12.0.dist-info" / "licenses" / "LICENSE").is_file()


def test_monta_com_os_pyc_compilados(insumos, tmp_path):
    # Em Program Files o Python não grava: sem `.pyc` prontos, cada abertura recompila tudo (M3). Por data não
    # serve: o Inno repõe a data dos arquivos e um `.pyc` feito na CI deixaria de conferir.
    destino = tmp_path / "saida"
    montar_app_qt.montar(destino, "final", **insumos)
    fontes = [*(destino / "app" / "cartridges").rglob("*.py"), *(destino / "lib").rglob("*.py")]
    assert len(fontes) >= 4
    for fonte in fontes:
        # O Python embutido é o 3.15: um `.pyc` de outra versão ele ignoraria, e recompilaria tudo a cada abertura.
        pyc = fonte.parent / "__pycache__" / f"{fonte.stem}.cpython-315.pyc"
        assert pyc.is_file(), fonte
        # Bits do cabeçalho (PEP 552): 1 = por hash, sem conferir a fonte.
        assert int.from_bytes(pyc.read_bytes()[4:8], "little") == 1, fonte


def test_compilar_pyc_exige_o_python_do_app(tmp_path, monkeypatch):
    _tocar(tmp_path / "modulo.py")
    monkeypatch.setattr(montar_app_qt.sys.implementation, "cache_tag", "cpython-314")
    with pytest.raises(SystemExit, match="3.15"):
        montar_app_qt.compilar_pyc(tmp_path)
    assert not (tmp_path / "__pycache__").exists()


def test_compilar_pyc_recusa_um_py_que_nao_compila(tmp_path):
    _tocar(tmp_path / "quebrado.py", "def (")
    with pytest.raises(SystemExit):
        montar_app_qt.compilar_pyc(tmp_path)


def test_lancador_avisa_quando_o_python_sai_com_erro():
    """Sem console, a recusa do `shared.py` e o QML que não carrega sairiam sem nenhum aviso (M2)."""
    fonte = (Path(montar_app_qt.RAIZ) / "build-aux" / "windows" / "lancador" / "cartridges.c").read_text(encoding="utf-8")
    assert "return py_main(" not in fonte
    assert re.search(r"int r = py_main\(argc, argv\);\s*return r \? falha\(\) : 0;", fonte)
    assert 'L"Não foi possível abrir o Cartridges. Reinstale o aplicativo."' in fonte


def _normalizado(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


def test_requirements_fixa_tudo():
    raiz = Path(montar_app_qt.RAIZ)
    linhas = [l.strip() for l in (raiz / "requirements.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    fixados = {}
    for linha in linhas:
        assert "==" in linha, linha
        nome, versao = linha.split("==")
        fixados[_normalizado(nome)] = versao
    infos = list((raiz / "_dist" / "cache-qt" / "lib").glob("*.dist-info"))
    if not infos:
        pytest.skip("sem o cache das bibliotecas")
    instalados = {}
    for info in infos:
        nome, versao = info.name.removesuffix(".dist-info").rsplit("-", 1)
        instalados[_normalizado(nome)] = versao
    # Nos dois sentidos: nem pacote do cache sem pino, nem pino que nada instala.
    assert fixados == instalados


def _pacote_falso(tmp_path, monkeypatch, membros: dict[str, str], prefixo: str, nome: str = "pacote.zip") -> None:
    """Um `.zip` local no lugar do pacote oficial: nada vai à rede."""
    arquivo = tmp_path / "origem" / nome
    arquivo.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(arquivo, "w") as z:
        for caminho, texto in membros.items():
            z.writestr(caminho, texto)
    monkeypatch.setattr(montar_app_qt, f"{prefixo}_URL", arquivo.as_uri())
    monkeypatch.setattr(montar_app_qt, f"{prefixo}_SHA256", hashlib.sha256(arquivo.read_bytes()).hexdigest())


@pytest.fixture
def pacote_do_ffmpeg(tmp_path, monkeypatch):
    _pacote_falso(tmp_path, monkeypatch, {
        montar_app_qt.FFMPEG_EXE: "binario", montar_app_qt.FFMPEG_LICENCA: "GPL", "outra/coisa.txt": "nao",
    }, "FFMPEG")  # fmt: skip


def test_baixar_ffmpeg_extrai_o_exe_e_a_licenca(pacote_do_ffmpeg, tmp_path):
    exe = montar_app_qt.baixar_ffmpeg(tmp_path / "cache")
    assert exe.name == "ffmpeg.exe" and exe.read_text(encoding="utf-8") == "binario"
    licenca = (exe.parent / "LICENSE").read_text(encoding="utf-8")
    assert licenca.endswith("GPL")
    # GPLv3 §6: quem recebe o binário precisa saber onde está a fonte correspondente.
    assert montar_app_qt.FFMPEG_FONTE in licenca
    assert montar_app_qt.FFMPEG_FONTE.startswith("https://github.com/FFmpeg/FFmpeg/commit/")
    assert not list(exe.parent.rglob("coisa.txt"))


def test_baixar_ffmpeg_recusa_o_sha256_errado(pacote_do_ffmpeg, tmp_path, monkeypatch):
    monkeypatch.setattr(montar_app_qt, "FFMPEG_SHA256", "0" * 64)
    with pytest.raises(SystemExit):
        montar_app_qt.baixar_ffmpeg(tmp_path / "cache")
    assert not list((tmp_path / "cache").rglob("ffmpeg.exe"))


def test_baixar_ffmpeg_nao_baixa_de_novo(pacote_do_ffmpeg, tmp_path, monkeypatch):
    exe = montar_app_qt.baixar_ffmpeg(tmp_path / "cache")
    # O mesmo nome de arquivo, numa origem que não existe: baixar de novo levantaria.
    monkeypatch.setattr(montar_app_qt, "FFMPEG_URL", "file:///nao/existe/pacote.zip")
    assert montar_app_qt.baixar_ffmpeg(tmp_path / "cache") == exe


def test_baixar_ffmpeg_recusa_pacote_sem_o_exe(tmp_path, monkeypatch):
    _pacote_falso(tmp_path, monkeypatch, {montar_app_qt.FFMPEG_LICENCA: "GPL"}, "FFMPEG")
    with pytest.raises(SystemExit):
        montar_app_qt.baixar_ffmpeg(tmp_path / "cache")


def test_baixar_ludusavi_extrai_o_exe_e_a_licenca(tmp_path, monkeypatch):
    _pacote_falso(tmp_path, monkeypatch, {"ludusavi.exe": "binario"}, "LUDUSAVI")
    _pacote_falso(tmp_path, monkeypatch, {montar_app_qt.LUDUSAVI_LICENCA: "texto legal"}, "LUDUSAVI_LEGAL", "legal.zip")
    exe = montar_app_qt.baixar_ludusavi(tmp_path / "cache")
    assert exe.name == "ludusavi.exe" and exe.read_text(encoding="utf-8") == "binario"
    assert (exe.parent / "LICENSE").read_text(encoding="utf-8") == "texto legal"


@pytest.fixture
def main_sem_rede(tmp_path, monkeypatch):
    """O `main` com tudo o que baixa ou compila trocado; devolve o que `montar` recebeu e o que foi baixado."""
    chamadas = {"baixados": []}

    def baixar(nome):
        return lambda cache: chamadas["baixados"].append(nome) or Path(nome)

    monkeypatch.setattr(montar_app_qt, "baixar_python", lambda cache: tmp_path)
    monkeypatch.setattr(montar_app_qt, "instalar_bibliotecas", lambda cache: tmp_path)
    monkeypatch.setattr(montar_app_qt, "compilar_lancador", lambda cache: tmp_path)
    monkeypatch.setattr(montar_app_qt, "renderizar_iss", lambda destino: tmp_path / "x.iss")
    monkeypatch.setattr(montar_app_qt, "baixar_ffmpeg", baixar("ffmpeg"))
    monkeypatch.setattr(montar_app_qt, "baixar_ludusavi", baixar("ludusavi"))
    monkeypatch.setattr(montar_app_qt, "montar", lambda destino, canal, **k: chamadas.update(k))
    return chamadas


def _rodar_main(monkeypatch, tmp_path, *argumentos):
    argv = ["montar_app_qt.py", "--destino", str(tmp_path / "saida"), "--cache", str(tmp_path / "cache"), *argumentos]
    monkeypatch.setattr(montar_app_qt.sys, "argv", argv)
    assert montar_app_qt.main() == 0


def test_main_do_canal_final_baixa_o_que_falta(main_sem_rede, monkeypatch, tmp_path):
    _rodar_main(monkeypatch, tmp_path, "--canal", "final")
    assert main_sem_rede["baixados"] == ["ffmpeg", "ludusavi"]
    assert main_sem_rede["ffmpeg"] == Path("ffmpeg") and main_sem_rede["ludusavi"] == Path("ludusavi")


def test_main_usa_os_executaveis_passados(main_sem_rede, monkeypatch, tmp_path):
    _rodar_main(monkeypatch, tmp_path, "--canal", "final", "--ffmpeg", "a.exe", "--ludusavi", "b.exe")
    assert main_sem_rede["baixados"] == []
    assert main_sem_rede["ffmpeg"] == Path("a.exe") and main_sem_rede["ludusavi"] == Path("b.exe")


def test_main_do_desenvolvimento_nao_baixa_os_externos(main_sem_rede, monkeypatch, tmp_path):
    _rodar_main(monkeypatch, tmp_path, "--canal", "desenvolvimento")
    assert main_sem_rede["baixados"] == []
    assert main_sem_rede["ffmpeg"] is None and main_sem_rede["ludusavi"] is None


def test_baixar_python_passa_pelo_download_conferido(tmp_path, monkeypatch):
    chamadas = []
    pacote = tmp_path / "python.zip"
    with zipfile.ZipFile(pacote, "w") as z:
        z.writestr("python315.dll", "x")

    def conferido(url, sha256, cache):
        chamadas.append((url, sha256))
        return pacote

    monkeypatch.setattr(montar_app_qt, "_baixar_conferido", conferido)
    extraido = montar_app_qt.baixar_python(tmp_path / "cache")
    assert chamadas == [(montar_app_qt.PYTHON_URL, montar_app_qt.PYTHON_SHA256)]
    assert (extraido / "python315.dll").is_file()
