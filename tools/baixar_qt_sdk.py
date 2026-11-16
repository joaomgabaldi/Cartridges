# baixar_qt_sdk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Baixa o que o `compilar.bat` do QWindowKit precisa: o SDK do Qt e o código do QWindowKit nas versões fixadas aqui.

O SDK (`qtbase` e `qtdeclarative`, MSVC 2022 64 bits) vem direto do download.qt.io, com o SHA-256 de cada
.7z fixado aqui; o `aqtinstall` não entende esse repositório. O QWindowKit e o `qmsetup` também
têm o commit fixado e conferido. Tudo vai para `build-aux/windows/qwk/_deps` (fora do git). O que já
existe e confere não é refeito.

Os .7z são extraídos com o 7-Zip, se instalado, ou com o `tar.exe` do Windows.

Uso:  .venv/Scripts/python tools/baixar_qt_sdk.py
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

DEPS = Path(__file__).resolve().parent.parent / "build-aux" / "windows" / "qwk" / "_deps"
QT_VERSAO = "6.12.0"
QT_DATA = "202609280346"
QTBASE_SHA256 = "219d1b86def3be418e31d704572bc4acc91b2ec373c65595c9fb12b42bf098dc"
QTDECLARATIVE_SHA256 = "258146e9972fadbc1162cda31c7d7ed7e627f5022b2a848f2edb84d9c2ce27db"
_QT_SEM_PONTOS = "qt6_" + QT_VERSAO.replace(".", "")
BASE = (
    f"https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/{_QT_SEM_PONTOS}/"
    f"{_QT_SEM_PONTOS}_msvc2022_64/qt.qt6.{QT_VERSAO.replace('.', '')}.win64_msvc2022_64/"
)
SUFIXO = "Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z"
# nome -> (arquivo remoto, SHA-256)
PACOTES = {
    "qtbase": (
        f"{QT_VERSAO}-0-{QT_DATA}qtbase-{SUFIXO}",
        QTBASE_SHA256,
    ),
    "qtdeclarative": (
        f"{QT_VERSAO}-0-{QT_DATA}qtdeclarative-{SUFIXO}",
        QTDECLARATIVE_SHA256,
    ),
}
QWK_REPOSITORIO = "https://github.com/stdware/qwindowkit.git"
QWK_TAG = "1.5.0"
QWK_COMMIT = "35e88f3655720ed0537c7dd1dde243bf4a70c94c"
QMSETUP_COMMIT = "85c6c3c783be8af8d3f2fa492748a82da8ec9bad"
MARCADOR = f".extraido-{QT_VERSAO}"


def _baixar(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as resposta:  # noqa: S310 - URL fixa, https
        return resposta.read()


def _sha256(caminho: Path) -> str:
    resumo = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1 << 20), b""):
            resumo.update(bloco)
    return resumo.hexdigest()


def baixar_pacote(nome: str, arquivo_remoto: str, sha256: str) -> Path:
    destino = DEPS / "downloads" / f"{nome}.7z"
    destino.parent.mkdir(parents=True, exist_ok=True)
    if not destino.exists() or _sha256(destino) != sha256:
        print(f"Baixando {arquivo_remoto}...")
        parcial = destino.with_suffix(".parcial")
        parcial.write_bytes(_baixar(BASE + arquivo_remoto))
        parcial.replace(destino)
    if _sha256(destino) != sha256:
        destino.unlink()
        raise RuntimeError(f"SHA-256 de {nome} não confere com o fixado no script; o arquivo foi descartado.")
    print(f"{nome}: SHA-256 conferido ({sha256})")
    return destino


def _identidade() -> str:
    """O que o marcador guarda: os nomes e os hashes dos pacotes; mudou algum, o SDK é extraído de novo."""
    return " ".join(f"{remoto}:{sha256}" for remoto, sha256 in PACOTES.values())


def extrair_qt(pacotes: list[Path], qt: Path, extrair=None) -> None:
    """Extrai os pacotes em `qt`; o marcador só é gravado depois dos dois, e sem ele recomeça do zero."""
    marcador = qt / MARCADOR
    if marcador.exists() and marcador.read_text(encoding="utf-8") == _identidade():
        print("SDK do Qt já extraído.")
        return
    if qt.exists():
        shutil.rmtree(qt)  # extração interrompida ou de outra versão: o que está solto não vale
    for pacote in pacotes:
        print(f"Extraindo {pacote.name}...")
        (extrair or _extrair)(pacote, qt)
    marcador.write_text(_identidade(), encoding="utf-8")


def _extrair(pacote: Path, destino: Path) -> None:
    # O 7-Zip vem na imagem da CI; o tar.exe do Windows Server 2022 (bsdtar 3.5) não lê LZMA, o do Windows 11 lê.
    # Assim o script não depende de nenhuma biblioteca do pip.
    destino.mkdir(parents=True, exist_ok=True)
    sete = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "7-Zip" / "7z.exe"
    if sete.is_file():
        cmd = [str(sete), "x", "-y", f"-o{destino}", str(pacote)]
    else:
        tar = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "tar.exe"
        cmd = [str(tar), "-xf", str(pacote), "-C", str(destino)]
    subprocess.run(cmd, check=True)


def toolset_do_qt(qt: Path) -> str:
    """O conjunto MSVC (`vcvars_ver`) que o SDK declara: `Compiler: msvc 19.44...` vira `14.44`."""
    resumo = (qt / "config_qtbase.summary").read_text(encoding="utf-8", errors="replace")
    achado = re.search(r"^Compiler: msvc 19\.(\d+)\.", resumo, re.MULTILINE)
    if not achado:
        raise RuntimeError("O SDK do Qt não declara a versão do MSVC em config_qtbase.summary.")
    return f"14.{achado.group(1)}"


def preparar_qt() -> None:
    qt = DEPS / "qt"
    extrair_qt([baixar_pacote(nome, remoto, sha256) for nome, (remoto, sha256) in PACOTES.items()], qt)
    # O `compilar.bat` lê daqui o conjunto MSVC que o Qt exige.
    (qt / ".vcvars_ver").write_text(toolset_do_qt(qt), encoding="utf-8")


def _commit(pasta: Path, rodar=subprocess.run) -> str:
    resultado = rodar(["git", "-C", str(pasta), "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return resultado.stdout.strip()


def _commits_conferem(pasta: Path, rodar) -> bool:
    return _commit(pasta, rodar) == QWK_COMMIT and _commit(pasta / "qmsetup", rodar) == QMSETUP_COMMIT


def preparar_qwindowkit(rodar=subprocess.run) -> None:
    destino = DEPS / "qwindowkit"
    if (
        (destino / "CMakeLists.txt").exists()
        and (destino / "qmsetup" / "CMakeLists.txt").exists()
        and _commits_conferem(destino, rodar)
    ):
        print("QWindowKit já clonado, no commit fixado.")
        return
    # Clona numa pasta de rascunho e só renomeia no fim: um clone interrompido ou no commit errado não vira "pronto".
    parcial = DEPS / "qwindowkit.parcial"
    shutil.rmtree(parcial, ignore_errors=True)
    shutil.rmtree(destino, ignore_errors=True)
    rodar(
        ["git", "clone", "--branch", QWK_TAG, "--depth", "1", "--recurse-submodules", "--shallow-submodules",
         QWK_REPOSITORIO, str(parcial)],
        check=True,
    )
    if not _commits_conferem(parcial, rodar):
        shutil.rmtree(parcial, ignore_errors=True)
        raise RuntimeError("O QWindowKit clonado não está nos commits fixados (a tag mudou?); o clone foi descartado.")
    parcial.replace(destino)


def main() -> int:
    preparar_qt()
    preparar_qwindowkit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
