# montar_app_qt.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Monta a pasta do app Qt instalado, para o Inno Setup empacotar.

    <destino>\\bin\\Cartridges.exe     o lançador (carrega ..\\python\\python315.dll)
    <destino>\\python\\               Python embutido do python.org
    <destino>\\lib\\                  dependências (pip install --target)
    <destino>\\app\\cartridges\\      o pacote (qml, qwk_ponte.dll, instalacao.json)
    <destino>\\app\\data\\            gschema, placeholders, sons e ícone

`data\\` fica ao lado do pacote porque `shared`, `configuracoes` e `modelos.biblioteca`
a procuram em `<pasta do pacote>\\..\\data`. O `python315._pth` lista `..\\lib` e `..\\app`.

Uso: python montar_app_qt.py --canal {desenvolvimento,final} --destino <pasta>
"""

import argparse
import hashlib
import json
import os
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

MARCADOR = ".montado-por-montar_app_qt"

CANAIS = ("desenvolvimento", "final")

# Sem eles o app nem importa (`shared` lê o gschema na importação), mostra cartões vazios ou perde, em silêncio,
# as "Novidades" e a descrição do "Sobre o Cartridges" (a metainfo).
OBRIGATORIOS = (
    "cartridges/janela/qwk_ponte.dll",
    "data/io.github.joaomgabaldi.Cartridges.gschema.xml.in",
    "data/io.github.joaomgabaldi.Cartridges.metainfo.xml.in",
    "data/library_placeholder.svg",
)
# O que de `data/` o app instalado lê.
DATA = (
    "io.github.joaomgabaldi.Cartridges.gschema.xml.in",
    # O "Sobre o Cartridges" lê as novidades da versão e a descrição daqui.
    "io.github.joaomgabaldi.Cartridges.metainfo.xml.in",
    "library_placeholder.svg",
    "library_placeholder_small.svg",
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


def montar(destino: Path, canal: str, *, raiz: Path = RAIZ, python: Path, lib: Path, lancador: Path) -> None:
    """Monta `destino` a partir do repositório (`raiz`), do Python embutido já extraído (`python`),
    das bibliotecas do pip (`lib`) e do `Cartridges.exe` compilado (`lancador`)."""
    if canal not in CANAIS:
        sys.exit(f"Canal inválido: {canal!r}. Use um de {CANAIS}.")
    faltando = [p for p in OBRIGATORIOS if not (raiz / p).is_file()]
    if faltando:
        sys.exit(f"Faltam arquivos que o app exige: {faltando}")
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
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyi", "*.in", "meson.build", "instalacao.json"),
    )
    (pacote / "instalacao.json").write_text(json.dumps({"canal": canal}), encoding="utf-8")

    (destino / "app" / "data").mkdir()
    for item in DATA:
        origem = raiz / "data" / item
        if origem.is_dir():
            shutil.copytree(origem, destino / "app" / "data" / item)
        elif origem.is_file():
            shutil.copy2(origem, destino / "app" / "data" / item)


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
    """O meson só preenche @VERSION@ no .iss; aqui o mesmo, ao lado de `destino`, sem o meson."""
    modelo = (raiz / "build-aux" / "windows" / "Cartridges.iss.in").read_text(encoding="utf-8")
    iss = destino.parent / f"{destino.name}.iss"
    iss.write_text(modelo.replace("@VERSION@", versao_do_app(raiz)), encoding="utf-8-sig")
    return iss


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--canal", choices=CANAIS, required=True)
    ap.add_argument("--destino", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=RAIZ / "_dist" / "cache-qt")
    args = ap.parse_args()
    destino = args.destino.resolve()
    montar(
        destino, args.canal,
        python=baixar_python(args.cache), lib=instalar_bibliotecas(args.cache),
        lancador=compilar_lancador(args.cache),
    )
    print(f"App montado em {destino}")
    print(f"Script do Inno Setup: {renderizar_iss(destino)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
