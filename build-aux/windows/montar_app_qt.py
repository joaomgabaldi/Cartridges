# montar_app_qt.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Monta a pasta do app Qt instalado, para o Inno Setup empacotar.

    <destino>\\bin\\Cartridges.exe     o lançador (carrega ..\\python\\python315.dll)
    <destino>\\bin\\ffmpeg.exe         capa de vídeo; `capa_video` o procura ao lado do `sys.executable`
    <destino>\\bin\\ludusavi.exe       backup dos saves; `ludusavi` o procura do mesmo jeito
    <destino>\\python\\               Python embutido do python.org
    <destino>\\lib\\                  dependências (pip install --target)
    <destino>\\app\\cartridges\\      o pacote (qml, qwk_ponte.dll, instalacao.json)
    <destino>\\app\\data\\            gschema, placeholders, sons e ícone
    <destino>\\licencas\\             textos das licenças de terceiros que não estão nos `*.dist-info` de `lib`

`data\\` fica ao lado do pacote porque `shared`, `configuracoes` e `modelos.biblioteca`
a procuram em `<pasta do pacote>\\..\\data`. O `python315._pth` lista `..\\lib` e `..\\app`.

O ffmpeg e o Ludusavi são obrigatórios no canal final e opcionais no de desenvolvimento.

Uso: python montar_app_qt.py --canal {desenvolvimento,final} --destino <pasta> [--ffmpeg <exe>] [--ludusavi <exe>]
(`--ffmpeg` e `--ludusavi` apontam para um executável com um arquivo LICENSE ao lado; sem eles, o canal final baixa os
dois, conferidos pelo SHA-256)
"""

import argparse
import compileall
import hashlib
import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent

PYTHON_URL = "https://www.python.org/ftp/python/3.15.1/python-3.15.1-embed-amd64.zip"
# O mesmo SHA-256 do resumo assinado no .sigstore publicado ao lado do arquivo na página da release.
PYTHON_SHA256 = "352e232f25b5120508f11a6dfc1bd9076d3e70c30977d552a63338838c2ae8fb"

# Build "essentials" do gyan.dev, um dos indicados em ffmpeg.org para Windows; traz a libwebp que a capa de vídeo usa.
# O SHA-256 é o publicado ao lado do arquivo, em <FFMPEG_URL>.sha256.
_FFMPEG_PASTA = "ffmpeg-9.0.2-essentials_build"
FFMPEG_URL = f"https://www.gyan.dev/ffmpeg/builds/packages/{_FFMPEG_PASTA}.zip"
FFMPEG_SHA256 = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"
FFMPEG_EXE = f"{_FFMPEG_PASTA}/bin/ffmpeg.exe"
FFMPEG_LICENCA = f"{_FFMPEG_PASTA}/LICENSE"
# GPLv3 §6: a fonte correspondente, o commit que a página do build publica para esta versão.
FFMPEG_FONTE = "https://github.com/FFmpeg/FFmpeg/commit/946fcce07b"

# A mesma versão e os mesmos SHA-256 que o instalador da versão GTK levava.
_LUDUSAVI = "ludusavi-v0.31.0"
_LUDUSAVI_BASE = "https://github.com/mtkennerly/ludusavi/releases/download/v0.31.0"
LUDUSAVI_URL = f"{_LUDUSAVI_BASE}/{_LUDUSAVI}-win64.zip"
LUDUSAVI_SHA256 = "f47a8ad8c708f01d2eb124704973beffab205e292f5287a10fc4a101f8d68706"
LUDUSAVI_LEGAL_URL = f"{_LUDUSAVI_BASE}/{_LUDUSAVI}-legal.zip"
LUDUSAVI_LEGAL_SHA256 = "9fce11fc44942efdd5969928d89b106c229f9a041d7a713c424a6da981660ebf"
LUDUSAVI_LICENCA = f"{_LUDUSAVI}-legal.txt"

MARCADOR = ".montado-por-montar_app_qt"

CANAIS = ("desenvolvimento", "final")

# licencas\\<nome> a partir do repositório (o compilar.bat do QWindowKit já exige o SDK em `_deps`).
LICENCAS = {
    "QWindowKit.txt": "build-aux/windows/qwk/_deps/qwindowkit/LICENSE",
    "qmsetup.txt": "build-aux/windows/qwk/_deps/qwindowkit/qmsetup/LICENSE",
}

# Sem eles o app nem importa (`shared` lê o gschema na importação), mostra cartões vazios ou perde, em silêncio,
# as "Novidades" e a descrição do "Sobre o Cartridges" (a metainfo).
OBRIGATORIOS = (
    "cartridges/janela/qwk_ponte.dll",
    "data/io.github.joaomgabaldi.Cartridges.gschema.xml.in",
    "data/io.github.joaomgabaldi.Cartridges.metainfo.xml.in",
    "data/library_placeholder.svg",
    *LICENCAS.values(),
)
# O que de `data/` o app instalado lê.
DATA = (
    "io.github.joaomgabaldi.Cartridges.gschema.xml.in",
    # O "Sobre o Cartridges" lê as novidades da versão e a descrição daqui.
    "io.github.joaomgabaldi.Cartridges.metainfo.xml.in",
    "library_placeholder.svg",
    # A capa e o ícone de conquista de exemplo do assistente da primeira abertura.
    "capa_de_exemplo.svg",
    "conquista_de_exemplo.svg",
    "sons",
    "icons/hicolor",
)

# Do PySide6, o que o app não usa: WebEngine, 3D, PDF, o Designer, as ferramentas de
# linha de comando, as traduções e o material para gerar bindings.
SOBRAS_DO_PYSIDE = (
    "*WebEngine*", "Qt63D*", "Qt3D*", "Qt6Pdf*", "QtPdf*", "Qt6Designer*", "QtDesigner*",
    "*.exe", "*.pyi", "*.lib", "resources", "translations", "doc", "glue", "include",
    "typesystems", "scripts",
)


def compilar_pyc(pasta: Path) -> None:
    """Grava os `.pyc` de `pasta` por hash, sem conferir a fonte: em Program Files o Python não os grava, e por data
    deixariam de valer (o Inno Setup repõe a data dos arquivos). O `[InstallDelete]` troca `.py` e `.pyc` juntos."""
    if sys.implementation.cache_tag != "cpython-315":
        # O Python embutido ignoraria os `.pyc` de outra versão, sem nenhum aviso.
        sys.exit(f"Os .pyc precisam do Python 3.15, o do app; este é {sys.implementation.cache_tag}.")
    if not compileall.compile_dir(
        pasta, quiet=1, force=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH
    ):
        sys.exit(f"Há arquivos que não compilam em {pasta}.")


def montar(
    destino: Path, canal: str, *, raiz: Path = RAIZ, python: Path, lib: Path, lancador: Path,
    ffmpeg: Path | None = None, ludusavi: Path | None = None,
) -> None:  # fmt: skip
    """Monta `destino` a partir do repositório (`raiz`), do Python embutido já extraído (`python`),
    das bibliotecas do pip (`lib`), do `Cartridges.exe` compilado (`lancador`) e dos executáveis de
    terceiros (`ffmpeg`, `ludusavi`), cada um com um arquivo LICENSE ao lado."""
    if canal not in CANAIS:
        sys.exit(f"Canal inválido: {canal!r}. Use um de {CANAIS}.")
    faltando = [p for p in OBRIGATORIOS if not (raiz / p).is_file()]
    if faltando:
        sys.exit(f"Faltam arquivos que o app exige: {faltando}")
    externos = {"FFmpeg": ffmpeg, "Ludusavi": ludusavi}
    for nome, exe in externos.items():
        if exe is None and canal == "final":
            # Sem ele a função some em silêncio para quem instalar.
            sys.exit(f"O canal final exige o {nome}.")
        if exe is not None and not (exe.is_file() and (exe.parent / "LICENSE").is_file()):
            sys.exit(f"O {nome} em {exe} não existe ou não tem um arquivo LICENSE ao lado.")
    destino = destino.resolve()
    if destino == raiz.resolve() or destino in raiz.resolve().parents:
        sys.exit(f"O destino {destino} é o repositório ou uma pasta que o contém.")
    if destino.exists() and any(destino.iterdir()):
        # Só se apaga o que este script montou antes
        if not (destino / MARCADOR).is_file():
            sys.exit(f"O destino {destino} não está vazio nem foi montado por este script; nada foi apagado.")
        shutil.rmtree(destino)
    destino.mkdir(parents=True, exist_ok=True)
    (destino / MARCADOR).write_text("montar_app_qt.py\n", encoding="utf-8")

    (destino / "bin").mkdir()
    shutil.copy2(lancador, destino / "bin" / "Cartridges.exe")

    (destino / "licencas").mkdir()
    for nome, origem in LICENCAS.items():
        shutil.copy2(raiz / origem, destino / "licencas" / nome)
    for nome, exe in externos.items():
        if exe is not None:
            shutil.copy2(exe, destino / "bin" / f"{nome.lower()}.exe")
            shutil.copy2(exe.parent / "LICENSE", destino / "licencas" / f"{nome}.txt")

    shutil.copytree(python, destino / "python")
    pth = destino / "python" / "python315._pth"
    linhas = [l for l in pth.read_text(encoding="utf-8").splitlines() if l.strip() not in ("..\\lib", "..\\app")]
    pth.write_text("\n".join([*linhas, "..\\lib", "..\\app", ""]), encoding="utf-8")

    shutil.copytree(lib, destino / "lib")
    pyside = destino / "lib" / "PySide6"
    for padrao in SOBRAS_DO_PYSIDE:
        for sobra in pyside.glob(padrao):
            shutil.rmtree(sobra) if sobra.is_dir() else sobra.unlink()

    pacote = destino / "app" / "cartridges"
    shutil.copytree(
        raiz / "cartridges", pacote,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyi", "*.in", "instalacao.json"),
    )
    (pacote / "instalacao.json").write_text(json.dumps({"canal": canal}), encoding="utf-8")

    (destino / "app" / "data").mkdir()
    for item in DATA:
        origem = raiz / "data" / item
        if origem.is_dir():
            shutil.copytree(origem, destino / "app" / "data" / item)
        elif origem.is_file():
            shutil.copy2(origem, destino / "app" / "data" / item)

    compilar_pyc(pacote)
    compilar_pyc(destino / "lib")


def _sha256(caminho: Path) -> str:
    return hashlib.sha256(caminho.read_bytes()).hexdigest()


def baixar_python(cache: Path) -> Path:
    """Baixa o Python embutido para `cache`, confere o SHA-256 e devolve a pasta extraída."""
    extraido = cache / "python-embutido"
    marcador = extraido / ".sha256"
    if marcador.is_file() and marcador.read_text() == PYTHON_SHA256:
        return extraido
    cache.mkdir(parents=True, exist_ok=True)
    arquivo = cache / PYTHON_URL.rsplit("/", 1)[1]
    if not arquivo.is_file() or _sha256(arquivo) != PYTHON_SHA256:
        with urllib.request.urlopen(PYTHON_URL, timeout=120) as r:
            arquivo.write_bytes(r.read())
    if _sha256(arquivo) != PYTHON_SHA256:
        arquivo.unlink()
        sys.exit("O SHA-256 do Python embutido baixado não confere; nada foi extraído.")
    shutil.rmtree(extraido, ignore_errors=True)
    with zipfile.ZipFile(arquivo) as z:
        z.extractall(extraido)
    marcador.write_text(PYTHON_SHA256)
    return extraido


def _baixar_conferido(url: str, sha256: str, cache: Path) -> Path:
    """O arquivo de `url` em `cache`, com o SHA-256 esperado; senão o script para e nada é extraído."""
    cache.mkdir(parents=True, exist_ok=True)
    arquivo = cache / url.rsplit("/", 1)[1]
    if arquivo.is_file() and _sha256(arquivo) == sha256:
        return arquivo
    with urllib.request.urlopen(url, timeout=120) as r:
        arquivo.write_bytes(r.read())
    if _sha256(arquivo) != sha256:
        arquivo.unlink()
        sys.exit(f"O SHA-256 de {url} não confere; nada foi extraído.")
    return arquivo


def _extrair(arquivo: Path, membro: str, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(arquivo) as z:
        if membro not in z.namelist():
            sys.exit(f"{arquivo.name} não traz {membro}.")
        destino.write_bytes(z.read(membro))


def baixar_ffmpeg(cache: Path) -> Path:
    """O `ffmpeg.exe` conferido e extraído em `cache`, com o LICENSE do pacote ao lado."""
    arquivo = _baixar_conferido(FFMPEG_URL, FFMPEG_SHA256, cache)
    exe = cache / "ffmpeg" / "ffmpeg.exe"
    _extrair(arquivo, FFMPEG_EXE, exe)
    licenca = exe.parent / "LICENSE"
    _extrair(arquivo, FFMPEG_LICENCA, licenca)
    origem = f"FFmpeg, build essentials de https://www.gyan.dev/ffmpeg/builds/\nCódigo-fonte correspondente: {FFMPEG_FONTE}\n\n"
    licenca.write_bytes(origem.encode("utf-8") + licenca.read_bytes())
    return exe


def baixar_ludusavi(cache: Path) -> Path:
    """O `ludusavi.exe` conferido e extraído em `cache`, com o texto legal do projeto ao lado, como LICENSE."""
    exe = cache / "ludusavi" / "ludusavi.exe"
    _extrair(_baixar_conferido(LUDUSAVI_URL, LUDUSAVI_SHA256, cache), "ludusavi.exe", exe)
    legal = _baixar_conferido(LUDUSAVI_LEGAL_URL, LUDUSAVI_LEGAL_SHA256, cache)
    _extrair(legal, LUDUSAVI_LICENCA, exe.parent / "LICENSE")
    return exe


def instalar_bibliotecas(cache: Path, raiz: Path = RAIZ) -> Path:
    """`pip install --target` do requirements.txt, com o mesmo Python (3.15, win_amd64) que roda este script."""
    requisitos = raiz / "requirements.txt"
    lib = cache / "lib"
    marcador = lib / ".requirements.sha256"
    atual = _sha256(requisitos)
    if marcador.is_file() and marcador.read_text() == atual:
        return lib
    shutil.rmtree(lib, ignore_errors=True)
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--target", str(lib), "--only-binary=:all:",
         "--no-compile", "--disable-pip-version-check", "-r", str(requisitos)],
        check=True,
    )
    marcador.write_text(atual)
    return lib


def versao_do_app(raiz: Path = RAIZ) -> str:
    achada = re.search(r'^VERSION = "([\d.]+)"', (raiz / "cartridges" / "shared.py").read_text(encoding="utf-8"), re.M)
    if not achada:
        sys.exit("Não achei VERSION em cartridges/shared.py.")
    return achada[1]


def compilar_lancador(cache: Path, raiz: Path = RAIZ) -> Path:
    """Compila o Cartridges.exe com o MSVC 14.44 (o mesmo do compilar.bat do QWindowKit)."""
    fonte = raiz / "build-aux" / "windows" / "lancador"
    saida = cache / "lancador"
    shutil.rmtree(saida, ignore_errors=True)
    saida.mkdir(parents=True)
    versao = versao_do_app(raiz)
    roteiro = saida / "compilar.bat"
    # Alguns shells (Git Bash) descartam a variável "ProgramFiles(x86)"
    pf86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    vs = subprocess.run(
        [Path(pf86) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe", "-latest", "-products", "*",
         "-version", "[17,18)", "-property", "installationPath"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    if not vs:
        sys.exit("Não achei o Visual Studio 2022 (vswhere).")
    roteiro.write_text(
        "@echo off\r\n"
        f'call "{vs}\\VC\\Auxiliary\\Build\\vcvars64.bat" -vcvars_ver=14.44 >nul || exit /b 1\r\n'
        f'rc /nologo /DVERSAO={versao} /DVERSAO_NUM={versao.replace(".", ",")},0 /fo cartridges.res "{fonte}\\cartridges.rc" || exit /b 1\r\n'
        f'cl /nologo /O2 /MT /utf-8 /W3 "{fonte}\\cartridges.c" cartridges.res /Fe:Cartridges.exe '
        "/link /SUBSYSTEM:WINDOWS user32.lib || exit /b 1\r\n",
        encoding="ascii",
    )
    subprocess.run(["cmd", "/c", str(roteiro)], cwd=saida, check=True)
    return saida / "Cartridges.exe"


def renderizar_iss(destino: Path, raiz: Path = RAIZ) -> Path:
    """Preenche @VERSION@ no .iss, ao lado de `destino`: `cartridges/shared.py` é a fonte única da versão."""
    modelo = (raiz / "build-aux" / "windows" / "Cartridges.iss.in").read_text(encoding="utf-8")
    iss = destino.parent / f"{destino.name}.iss"
    iss.write_text(modelo.replace("@VERSION@", versao_do_app(raiz)), encoding="utf-8-sig")
    return iss


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--canal", choices=CANAIS, required=True)
    ap.add_argument("--destino", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=RAIZ / "_dist" / "cache-qt")
    ap.add_argument("--ffmpeg", type=Path, help="ffmpeg.exe com um LICENSE ao lado; sem ele, o canal final o baixa")
    ap.add_argument("--ludusavi", type=Path, help="ludusavi.exe com um LICENSE ao lado; sem ele, o canal final o baixa")
    args = ap.parse_args()
    destino = args.destino.resolve()
    final = args.canal == "final"
    montar(
        destino, args.canal,
        python=baixar_python(args.cache), lib=instalar_bibliotecas(args.cache),
        lancador=compilar_lancador(args.cache),
        ffmpeg=args.ffmpeg or (baixar_ffmpeg(args.cache) if final else None),
        ludusavi=args.ludusavi or (baixar_ludusavi(args.cache) if final else None),
    )
    print(f"App montado em {destino}")
    print(f"Script do Inno Setup: {renderizar_iss(destino)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
