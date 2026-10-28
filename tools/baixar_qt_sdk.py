# baixar_qt_sdk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Baixa o que o `compilar.bat` do QWindowKit precisa: o SDK do Qt 6.12.0 e o código do QWindowKit 1.5.0.

O SDK (`qtbase` e `qtdeclarative`, MSVC 2022 64 bits) vem direto do download.qt.io, com o SHA-1
publicado ao lado de cada .7z conferido; o `aqtinstall` não entende esse repositório. Tudo vai
para `build-aux/windows/qwk/_deps` (fora do git). O que já existe e confere não é refeito.

Uso:  .venv/Scripts/python tools/baixar_qt_sdk.py
"""

import hashlib
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import py7zr

DEPS = Path(__file__).resolve().parent.parent / "build-aux" / "windows" / "qwk" / "_deps"
BASE = (
    "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6120/"
    "qt6_6120_msvc2022_64/qt.qt6.6120.win64_msvc2022_64/"
)
SUFIXO = "Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z"
PACOTES = {
    "qtbase": f"6.12.0-0-202609280346qtbase-{SUFIXO}",
    "qtdeclarative": f"6.12.0-0-202609280346qtdeclarative-{SUFIXO}",
}
QWK_REPOSITORIO = "https://github.com/stdware/qwindowkit.git"
QWK_TAG = "1.5.0"
MARCADOR = ".extraido-6.12.0"


def _baixar(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resposta:  # noqa: S310 - URL fixa, https
        return resposta.read()


def _sha1(caminho: Path) -> str:
    resumo = hashlib.sha1()  # noqa: S324 - é o digest que o Qt publica
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def baixar_pacote(nome: str, arquivo_remoto: str) -> Path:
    destino = DEPS / "downloads" / f"{nome}.7z"
    destino.parent.mkdir(parents=True, exist_ok=True)
    esperado = _baixar(BASE + arquivo_remoto + ".sha1").decode().split()[0].lower()
    if not destino.exists() or _sha1(destino) != esperado:
        print(f"Baixando {arquivo_remoto}...")
        parcial = destino.with_suffix(".parcial")
        parcial.write_bytes(_baixar(BASE + arquivo_remoto))
        parcial.replace(destino)
    if _sha1(destino) != esperado:
        destino.unlink()
        raise RuntimeError(f"SHA-1 de {nome} não confere com o publicado pelo Qt; o arquivo foi descartado.")
    print(f"{nome}: SHA-1 conferido ({esperado})")
    return destino


def extrair_qt(pacotes: list[Path], qt: Path, extrair=None) -> None:
    """Extrai os pacotes em `qt`; o marcador só é gravado depois dos dois, e sem ele recomeça do zero."""
    marcador = qt / MARCADOR
    if marcador.exists():
        print("SDK do Qt já extraído.")
        return
    if qt.exists():
        shutil.rmtree(qt)  # extração anterior interrompida: partes soltas não valem
    for pacote in pacotes:
        print(f"Extraindo {pacote.name}...")
        (extrair or _extrair)(pacote, qt)
    marcador.write_text(" ".join(PACOTES.values()), encoding="utf-8")


def _extrair(pacote: Path, destino: Path) -> None:
    with py7zr.SevenZipFile(pacote) as arquivo:
        arquivo.extractall(destino)


def preparar_qt() -> None:
    extrair_qt([baixar_pacote(nome, remoto) for nome, remoto in PACOTES.items()], DEPS / "qt")


def preparar_qwindowkit() -> None:
    destino = DEPS / "qwindowkit"
    if (destino / "CMakeLists.txt").exists() and (destino / "qmsetup" / "CMakeLists.txt").exists():
        print("QWindowKit já clonado.")
        return
    # Clona numa pasta de rascunho e só renomeia no fim: um clone interrompido não vira "pronto".
    parcial = DEPS / "qwindowkit.parcial"
    shutil.rmtree(parcial, ignore_errors=True)
    shutil.rmtree(destino, ignore_errors=True)
    subprocess.run(
        ["git", "clone", "--branch", QWK_TAG, "--depth", "1", "--recurse-submodules", "--shallow-submodules",
         QWK_REPOSITORIO, str(parcial)],
        check=True,
    )
    parcial.replace(destino)


def main() -> int:
    preparar_qt()
    preparar_qwindowkit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
