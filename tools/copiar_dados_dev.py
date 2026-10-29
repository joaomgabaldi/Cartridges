# copiar_dados_dev.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

r"""Copia os dados reais do Cartridges para a cópia de desenvolvimento (sufixo ``-dev``).

Uso::

    .venv\Scripts\python tools\copiar_dados_dev.py [--substituir]

Copia ``%LOCALAPPDATA%\io.github.joaomgabaldi.Cartridges`` e a chave
``HKCU\Software\GSettings\io\github\joaomgabaldi\Cartridges`` (com a subchave ``State``)
para as versões ``-dev``, com os mesmos tipos de valor (menos ``shortcuts-location``,
``auto-import`` e ``remove-missing``, forçados por ``isolar_dev``). Os originais são abertos só para
leitura. Se o destino já existe, pede ``--substituir``, que apaga apenas o destino.
"""

import argparse
import os
import shutil
import sys
import winreg
from pathlib import Path

APP_ID = "io.github.joaomgabaldi.Cartridges"
CHAVE = r"Software\GSettings\io\github\joaomgabaldi\Cartridges"
RAIZ = winreg.HKEY_CURRENT_USER

# O que a cópia -dev NÃO herda: valores e arquivos que guardam caminho absoluto para a pasta dos
# dados reais. Copiados, o app -dev faria backup/restauração dos saves na pasta real.
# Sem eles, o app -dev usa o padrão, dentro da própria pasta -dev (o ludusavi regrava os dois).
IGNORAR_VALORES = frozenset({"pasta-dos-saves"})
# As fitas de LED e a conta Tuya levam as chaves locais dos aparelhos reais da casa: o app -dev
# acende as fitas ao abrir e falaria com elas (D53).
IGNORAR_ARQUIVOS = frozenset({"ludusavi/config.yaml", "ludusavi/cache.yaml", "fitas.json", "tuya_conta.json"})

REPO = Path(__file__).resolve().parent.parent
ATALHOS_DE_TESTE = REPO / "_dev" / "atalhos-teste"


def isolar_dev(chave_destino: str, pasta_atalhos: Path = ATALHOS_DE_TESTE) -> None:
    r"""Desliga na chave -dev o que faria o app do código-fonte mexer nos dados reais.

    O lugar único dessa regra, aplicado depois da cópia e só na chave -dev. Por quê: soltar um
    ``.lnk`` no app -dev o copia para ``shortcuts-location``; se fosse a ``Documents\Atalhos`` real, o
    app GTK de uso diário o importaria para a biblioteca real. E com ``remove-missing`` ligado, uma
    importação -dev numa pasta diferente da real marcaria jogos como removidos.
    """
    pasta_atalhos.mkdir(parents=True, exist_ok=True)
    with winreg.CreateKeyEx(RAIZ, chave_destino, 0, winreg.KEY_WRITE) as chave:
        winreg.SetValueEx(chave, "shortcuts-location", 0, winreg.REG_SZ, str(pasta_atalhos))
        winreg.SetValueEx(chave, "auto-import", 0, winreg.REG_DWORD, 0)
        winreg.SetValueEx(chave, "remove-missing", 0, winreg.REG_DWORD, 0)


def pasta_real() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / APP_ID


def apagar_chave(caminho: str) -> None:
    """Apaga a chave e tudo abaixo dela. Só é chamada com o destino."""
    with winreg.OpenKey(RAIZ, caminho, 0, winreg.KEY_ALL_ACCESS) as chave:
        while True:
            try:
                filha = winreg.EnumKey(chave, 0)
            except OSError:
                break
            apagar_chave(f"{caminho}\\{filha}")
    winreg.DeleteKey(RAIZ, caminho)


def copiar_chave(origem: str, destino: str) -> int:
    """Copia valores e subchaves, recursivamente; devolve quantos valores copiou."""
    copiados = 0
    with winreg.OpenKey(RAIZ, origem, 0, winreg.KEY_READ) as de:
        with winreg.CreateKeyEx(RAIZ, destino, 0, winreg.KEY_WRITE) as para:
            indice = 0
            while True:
                try:
                    nome, dado, tipo = winreg.EnumValue(de, indice)
                except OSError:
                    break
                indice += 1
                if nome in IGNORAR_VALORES:
                    continue
                winreg.SetValueEx(para, nome, 0, tipo, dado)
                copiados += 1
        indice = 0
        while True:
            try:
                filha = winreg.EnumKey(de, indice)
            except OSError:
                break
            copiados += copiar_chave(f"{origem}\\{filha}", f"{destino}\\{filha}")
            indice += 1
    return copiados


def _chave_existe(caminho: str) -> bool:
    try:
        winreg.CloseKey(winreg.OpenKey(RAIZ, caminho, 0, winreg.KEY_READ))
    except FileNotFoundError:
        return False
    return True


def copiar(
    pasta_origem: Path,
    pasta_destino: Path,
    chave_origem: str,
    chave_destino: str,
    substituir: bool = False,
) -> tuple[int, int]:
    """Devolve (arquivos copiados, valores de registro copiados)."""
    if pasta_origem == pasta_destino or chave_origem == chave_destino:
        raise SystemExit("Origem e destino são iguais.")
    if not pasta_origem.is_dir() or not _chave_existe(chave_origem):
        raise SystemExit("Os dados de origem não existem.")
    if pasta_destino.exists() or _chave_existe(chave_destino):
        if not substituir:
            raise SystemExit("O destino já existe. Use --substituir para apagá-lo e copiar de novo.")
        shutil.rmtree(pasta_destino, ignore_errors=True)
        if _chave_existe(chave_destino):
            apagar_chave(chave_destino)
    shutil.copytree(
        pasta_origem,
        pasta_destino,
        ignore=lambda pasta, nomes: [
            n for n in nomes if (Path(pasta) / n).relative_to(pasta_origem).as_posix() in IGNORAR_ARQUIVOS
        ],
    )
    arquivos = sum(1 for p in pasta_destino.rglob("*") if p.is_file())
    return arquivos, copiar_chave(chave_origem, chave_destino)


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    analisador.add_argument("--substituir", action="store_true", help="apaga o destino -dev antes")
    args = analisador.parse_args(argv)
    origem = pasta_real()
    destino = origem.with_name(origem.name + "-dev")
    arquivos, valores = copiar(origem, destino, CHAVE, CHAVE + "-dev", args.substituir)
    isolar_dev(CHAVE + "-dev")
    jogos = len(list((destino / "games").glob("*.json")))
    print(f"Copiados {arquivos} arquivos ({jogos} jogos) para {destino}")
    print(f"Copiados {valores} valores do registro para HKCU\\{CHAVE}-dev")
    print(f"Na -dev: shortcuts-location={ATALHOS_DE_TESTE}, auto-import=0, remove-missing=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
