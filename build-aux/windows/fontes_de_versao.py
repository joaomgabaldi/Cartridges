# fontes_de_versao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Descobre as versões mais novas das peças do build (por ora, só as bibliotecas do pip).

Resolver nunca instala nada: `pip install --dry-run --report -`, só rodas binárias (nunca sdist), para o
Python e a plataforma do app (win_amd64).
"""

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Pino:
    nome: str
    versao: str
    sha256: str


def resolver_libs(
    arquivos_in: list[Path],
    python: str,
    restricoes: list[str] = [],
    rodar=subprocess.run,
) -> list[Pino] | None:
    """Pinos (com SHA-256 da roda escolhida) de tudo o que os `.in` puxam; `None` se o pip não resolver.

    `python` é "3.15"; `restricoes` são linhas extras como "PySide6==6.12.0".
    """
    cmd = [
        sys.executable, "-m", "pip", "install", "--dry-run", "--quiet", "--report", "-",
        "--only-binary=:all:", "--platform", "win_amd64", "--python-version", python,
        "--ignore-installed", "--disable-pip-version-check",
    ]
    for arquivo in arquivos_in:
        cmd += ["-r", str(arquivo)]
    cmd += restricoes
    resultado = rodar(cmd, capture_output=True, text=True, encoding="utf-8")
    if resultado.returncode != 0:
        return None
    try:
        itens = json.loads(resultado.stdout)["install"]
        return [
            Pino(
                i["metadata"]["name"],
                i["metadata"]["version"],
                i["download_info"]["archive_info"]["hashes"]["sha256"],
            )
            for i in itens
        ]
    except (ValueError, KeyError, TypeError):
        return None


def _normalizado(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


def gravar_requirements(destino: Path, pinos: list[Pino], cabecalho: list[str]) -> None:
    """`nome==versao --hash=sha256:…`, por nome normalizado; o `cabecalho` (ex.: "-r requirements.txt") vai antes."""
    linhas = list(cabecalho)
    for p in sorted(pinos, key=lambda p: _normalizado(p.nome)):
        linhas.append(f"{p.nome}=={p.versao} --hash=sha256:{p.sha256}")
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8", newline="\n")
