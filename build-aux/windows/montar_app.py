"""Monta numa pasta só o que o app instalado usa, para o Inno Setup empacotar.

O instalador copiava ucrt64/bin/*.dll e lib/python3.14 inteiros, e com isso
levava tudo o que estivesse instalado no MSYS2: compiladores de shader, Tcl/Tk,
a suíte de testes do Python, pip, pytest, meson. Aqui as DLLs saem da cadeia de
dependências, a partir dos executáveis, das bibliotecas que o GObject
Introspection carrega pelo nome e dos módulos binários do Python. Um pacote
instalado no MSYS2 para outra coisa não entra; uma dependência nova do GTK entra
sozinha.

No fim, o Python da pasta montada importa o app inteiro e abre uma imagem de
cada formato, sem enxergar o MSYS2. Se faltar algo, o build para aqui, e não no
computador de quem instalou.

Uso (com o Python do MSYS2): python montar_app.py <prefixo ucrt64> <destino>
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PYTHON = f"python{sys.version_info.major}.{sys.version_info.minor}"

EXECUTAVEIS = (
    "pythonw.exe",
    "python.exe",
    "gdbus.exe",
    "gspawn-win64-helper.exe",
    "gspawn-win64-helper-console.exe",
)

# Os namespaces que o app importa de gi.repository, mais os dois que o GLib
# carrega sozinho no Windows. As dependências entre os typelibs (HarfBuzz,
# freetype2, GModule...) entram sozinhas.
TYPELIBS = (
    "GioWin32-2.0",
    "GLibWin32-2.0",
    "Adw-1",
    "Gdk-4.0",
    "GdkPixbuf-2.0",
    "GdkWin32-4.0",
    "Gio-2.0",
    "GLib-2.0",
    "GObject-2.0",
    "Graphene-1.0",
    "Gsk-4.0",
    "Gtk-4.0",
    "Pango-1.0",
    "PangoCairo-1.0",
    "cairo-1.0",
)

# Pacotes de site-packages usados em execução, com a distribuição de cada um
# (para levar o .dist-info, que importlib.metadata pode consultar).
PACOTES = {
    "cartridges": None,
    "gi": "PyGObject",
    "cairo": "pycairo",
    "PIL": "pillow",
    "requests": "requests",
    "urllib3": "urllib3",
    "idna": "idna",
    "charset_normalizer": "charset_normalizer",
    "certifi": "certifi",
    "tinytuya": "tinytuya",
    "cryptography": "cryptography",
    "cffi": "cffi",
    "pycparser": "pycparser",
    "colorama": "colorama",
}
MODULOS_SOLTOS = ("_cffi_backend.*.pyd",)

FORA_DA_STDLIB = {"test", "idlelib", "ensurepip", "tkinter", "turtledemo", "site-packages"}
FORA_DO_LIB_DYNLOAD = ("_tkinter.*", "_test*", "_ctypes_test*", "_xxtestfuzz*", "xx*")

# Os .pyc da origem ficam de fora porque `compilar` os regenera na pasta montada.
IGNORAR = shutil.ignore_patterns("__pycache__", "*.pyc", "*.a")


def dependencias(objdump: Path, arquivo: Path) -> list[str]:
    saida = subprocess.run(
        [str(objdump), "-p", str(arquivo)],
        capture_output=True,
        text=True,
        errors="replace",
        check=True,
    ).stdout
    return re.findall(r"DLL Name: (\S+)", saida)


def fecho_de_dlls(objdump: Path, bin_dir: Path, raizes: list[Path]) -> set[Path]:
    """As DLLs de bin_dir que são raízes ou das quais uma raiz depende, direta
    ou indiretamente. DLLs do Windows não estão em bin_dir e ficam de fora."""
    por_nome = {dll.name.lower(): dll for dll in bin_dir.glob("*.dll")}
    achadas = {raiz for raiz in raizes if raiz.parent == bin_dir and raiz.suffix == ".dll"}
    pendentes = list(raizes)
    while pendentes:
        for nome in dependencias(objdump, pendentes.pop()):
            dll = por_nome.get(nome.lower())
            if dll and dll not in achadas:
                achadas.add(dll)
                pendentes.append(dll)
    return achadas


def typelibs(typelib_dir: Path) -> set[Path]:
    """Os typelibs de TYPELIBS e todos os de que eles dependem."""
    achados: set[Path] = set()
    pendentes = list(TYPELIBS)
    while pendentes:
        typelib = typelib_dir / f"{pendentes.pop()}.typelib"
        if typelib in achados:
            continue
        achados.add(typelib)
        # O cabeçalho guarda as dependências como "GLib-2.0|GObject-2.0"
        for nome in re.findall(rb"([A-Za-z][A-Za-z0-9]*-\d+\.\d+)(?=[|\x00])", typelib.read_bytes()):
            if (typelib_dir / f"{nome.decode()}.typelib").exists():
                pendentes.append(nome.decode())
    return achados


def copiar(origem: Path, destino: Path) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if origem.is_dir():
        shutil.copytree(origem, destino, ignore=IGNORAR, dirs_exist_ok=True)
    else:
        shutil.copy2(origem, destino)


def montar(prefixo: Path, destino: Path) -> None:
    bin_dir = prefixo / "bin"
    lib_python = prefixo / "lib" / PYTHON
    site = lib_python / "site-packages"
    typelib_dir = prefixo / "lib" / "girepository-1.0"

    if destino.exists():
        shutil.rmtree(destino)

    # Python: a stdlib sem testes nem ferramentas, e só os pacotes do app
    for item in lib_python.iterdir():
        if item.name in FORA_DA_STDLIB or item.name == "__pycache__":
            continue
        if item.name == "lib-dynload":
            ignorar = shutil.ignore_patterns(*FORA_DO_LIB_DYNLOAD, "__pycache__", "*.a")
            shutil.copytree(item, destino / "lib" / PYTHON / item.name, ignore=ignorar)
        else:
            copiar(item, destino / "lib" / PYTHON / item.name)
    for pacote, distribuicao in PACOTES.items():
        copiar(site / pacote, destino / "lib" / PYTHON / "site-packages" / pacote)
        if distribuicao:
            (dist_info,) = site.glob(f"{distribuicao}-*.dist-info")
            copiar(dist_info, destino / "lib" / PYTHON / "site-packages" / dist_info.name)
    for padrao in MODULOS_SOLTOS:
        for modulo in site.glob(padrao):
            copiar(modulo, destino / "lib" / PYTHON / "site-packages" / modulo.name)

    tipos = typelibs(typelib_dir)
    for typelib in tipos:
        copiar(typelib, destino / "lib" / "girepository-1.0" / typelib.name)

    for pasta in ("etc/ssl", "lib/gdk-pixbuf-2.0", "share/cartridges", "share/glib-2.0", "share/gtk-4.0"):
        copiar(prefixo / pasta, destino / pasta)
    # O tema de ícones sem os PNG e sem os cursores, como antes
    shutil.copytree(
        prefixo / "share" / "icons",
        destino / "share" / "icons",
        ignore=shutil.ignore_patterns("*.png", "cursors", "__pycache__"),
    )

    # DLLs: o fecho a partir de tudo o que o Windows ou o GObject carregam
    raizes = [bin_dir / exe for exe in EXECUTAVEIS]
    for typelib in tipos:
        for dll in set(re.findall(rb"lib[\w.+-]+\.dll", typelib.read_bytes())):
            raizes.append(bin_dir / dll.decode())
    raizes += (destino / "lib").rglob("*.dll")
    raizes += (destino / "lib").rglob("*.pyd")
    faltando = [raiz for raiz in raizes if not raiz.exists()]
    if faltando:
        sys.exit(f"Arquivos citados que não existem: {faltando}")

    objdump = bin_dir / "objdump.exe"
    for dll in fecho_de_dlls(objdump, bin_dir, raizes):
        copiar(dll, destino / "bin" / dll.name)
    for exe in (*EXECUTAVEIS, "cartridges"):
        copiar(bin_dir / exe, destino / "bin" / exe)


VERIFICACAO = r"""
import builtins, importlib, os, pkgutil, sys, tempfile

destino = sys.argv[1]
assert os.path.samefile(sys.prefix, destino), f"o Python veio de {sys.prefix}"

builtins._ = lambda message: message
builtins.ngettext = lambda singular, plural, n: singular if n == 1 else plural
pkgdatadir = os.path.join(destino, "share", "cartridges")
sys.path.insert(1, pkgdatadir)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf, Gio
Gio.Resource.load(os.path.join(pkgdatadir, "cartridges.gresource"))._register()

import cartridges
for modulo in pkgutil.walk_packages(cartridges.__path__, "cartridges."):
    importlib.import_module(modulo.name)

# WebP e ICO só pelo PIL: o MSYS2 não tem leitor de WebP para o GdkPixbuf (o
# app já cai no PIL quando o GdkPixbuf não reconhece o arquivo), e o ICO que o
# PIL grava é comprimido, que o leitor do GdkPixbuf não aceita
from PIL import Image
pasta = tempfile.mkdtemp()
for formato in ("PNG", "JPEG", "WEBP", "GIF", "TIFF", "AVIF", "BMP", "ICO"):
    caminho = os.path.join(pasta, "teste." + formato.lower())
    Image.new("RGB", (16, 16), "red").save(caminho, formato)
    with Image.open(caminho) as imagem:
        imagem.load()
    if formato not in ("WEBP", "ICO"):
        GdkPixbuf.Pixbuf.new_from_file(caminho)
svg = os.path.join(pasta, "teste.svg")
with open(svg, "w") as arquivo:
    arquivo.write('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>')
GdkPixbuf.Pixbuf.new_from_file(svg)

import ssl, certifi, requests
ssl.create_default_context(cafile=certifi.where())
requests.Session().close()

import tinytuya
assert tinytuya.AESCipher.CRYPTOLIB == "pyca/cryptography", tinytuya.AESCipher.CRYPTOLIB
cifra = tinytuya.AESCipher(b"0123456789abcdef")
assert cifra.decrypt(cifra.encrypt(b"cartridges")) == "cartridges"
print("ok")
"""


def verificar(destino: Path) -> None:
    windows = os.environ.get("SystemRoot", r"C:\Windows")
    ambiente = {
        chave: valor
        for chave, valor in os.environ.items()
        if not chave.upper().startswith(("PYTHON", "GI_", "GDK_", "GTK_", "XDG_", "MSYS", "MINGW"))
    }
    ambiente["PATH"] = os.pathsep.join(
        (str(destino / "bin"), os.path.join(windows, "System32"), windows)
    )
    resultado = subprocess.run(
        [str(destino / "bin" / "python.exe"), "-B", "-c", VERIFICACAO, str(destino)],
        env=ambiente,
        cwd=destino,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if resultado.returncode != 0 or resultado.stdout.strip() != "ok":
        sys.exit(f"A pasta montada não roda sozinha:\n{resultado.stdout}{resultado.stderr}")


def compilar(destino: Path) -> None:
    """Gera os .pyc de toda a pasta lib com o Python montado.

    De propósito, e não como efeito colateral da verificação: numa instalação
    para todos os usuários, {app}\\lib não é gravável, e sem .pyc cada abertura
    do app recompila tudo (medido em 23/09: 1,2 s com cache, 2,8 s sem).
    """
    resultado = subprocess.run(
        [str(destino / "bin" / "python.exe"), "-m", "compileall", "-q", "-j", "0",
         str(destino / "lib")],
        cwd=destino,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if resultado.returncode != 0:
        sys.exit(f"compileall falhou:\n{resultado.stdout}{resultado.stderr}")


def main() -> None:
    prefixo, destino = Path(sys.argv[1]), Path(sys.argv[2])
    montar(prefixo, destino)
    verificar(destino)
    compilar(destino)
    arquivos = [arquivo for arquivo in destino.rglob("*") if arquivo.is_file()]
    tamanho = sum(arquivo.stat().st_size for arquivo in arquivos) / 2**20
    print(f"Pasta do app montada: {len(arquivos)} arquivos, {tamanho:.0f} MB")


if __name__ == "__main__":
    main()
