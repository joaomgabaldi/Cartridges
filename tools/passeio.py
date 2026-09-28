# passeio.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Passeio: roda o Cartridges de verdade sobre uma cópia de uma biblioteca.

Uso, com o Python do MSYS2 e o _build atualizado (ninja)::

    PYTHONUTF8=1 C:/msys64/ucrt64/bin/python.exe tools/passeio.py <pasta-ou-zip>

A entrada é o conteúdo de %LOCALAPPDATA%\\io.github.joaomgabaldi.Cartridges
(pasta ou .zip). Ela é copiada para _passeio/<data-hora>/biblioteca, sem a
subpasta logs, e nunca é alterada. O app abre na tela, percorre o roteiro
(ver tools/passeio_app.py) e fecha sozinho. O resultado fica em
_passeio/<data-hora>/relatorio.md; o código de saída é 1 quando há falha.
Spec: docs/superpowers/specs/2026-09-27-passeio-design.md.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from tools.passeio_relatorio import codigo_de_saida, montar_relatorio  # noqa: E402

_EXIGIDOS = (
    RAIZ / "_build" / "cartridges" / "shared.py",
    RAIZ / "_build" / "data" / "cartridges.gresource",
    RAIZ / "_build" / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml",
)


def _raiz_da_biblioteca(pasta: Path) -> Path:
    """A pasta que contém ``games``: a própria, ou a única subpasta (zip com pasta)."""
    if (pasta / "games").is_dir():
        return pasta
    candidatas = [p for p in pasta.iterdir() if (p / "games").is_dir()]
    if len(candidatas) != 1:
        raise SystemExit(f"Nenhuma pasta 'games' encontrada em {pasta}")
    return candidatas[0]


def copiar_entrada(entrada: Path, destino: Path) -> None:
    ignorar = shutil.ignore_patterns("logs")
    if entrada.is_file() and zipfile.is_zipfile(entrada):
        with tempfile.TemporaryDirectory() as temporaria:
            with zipfile.ZipFile(entrada) as arquivo:
                arquivo.extractall(temporaria)
            shutil.copytree(_raiz_da_biblioteca(Path(temporaria)), destino, ignore=ignorar)
    elif entrada.is_dir():
        shutil.copytree(_raiz_da_biblioteca(entrada), destino, ignore=ignorar)
    else:
        raise SystemExit(f"Entrada inválida: {entrada} (use uma pasta ou um .zip)")


def ler_passos(saida: Path, codigo_do_filho: int) -> list[dict]:
    arquivo = saida / "passos.jsonl"
    passos = (
        [json.loads(l) for l in arquivo.read_text(encoding="utf-8").splitlines() if l.strip()]
        if arquivo.exists()
        else []
    )
    atual = saida / "atual.txt"
    # atual.txt sobrevive tanto a um travamento quanto a um fechamento manual
    # da janela (aí o app.run devolve 0 e o passo em andamento, sem isto,
    # desaparecia do relatório em silêncio): sintetiza o passo interrompido
    # sempre que ele existir, não só quando o código de saída é diferente de 0.
    if atual.exists():
        nome, jogo_id, jogo_nome = (atual.read_text(encoding="utf-8").split("\t") + ["", ""])[:3]
        if codigo_do_filho != 0:
            estado, motivo = "travou", f"o app parou de responder ou fechou (código {codigo_do_filho})"
        else:
            estado, motivo = "falha", "o passeio foi interrompido (janela fechada?)"
        passos.append(
            {
                "passo": nome,
                "jogo_id": jogo_id or None,
                "jogo_nome": jogo_nome or None,
                "estado": estado,
                "motivo": motivo,
                "rastro": None,
                "duracao": 0,
                "registros": [],
            }
        )
    elif codigo_do_filho != 0:
        # Terminou o roteiro, mas saiu com erro: a falha está no encerramento.
        passos.append(
            {
                "passo": "O app saiu com erro fora de um passo",
                "jogo_id": None,
                "jogo_nome": None,
                "estado": "falha",
                "motivo": f"o app saiu com o código {codigo_do_filho}",
                "rastro": None,
                "duracao": 0,
                "registros": [],
            }
        )
    return passos


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    faltando = [str(p) for p in _EXIGIDOS if not p.exists()]
    if faltando:
        print("Rode o ninja no _build antes. Faltam:\n  " + "\n  ".join(faltando))
        return 2

    saida = RAIZ / "_passeio" / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    saida.mkdir(parents=True)
    copiar_entrada(Path(sys.argv[1]).resolve(), saida / "biblioteca")

    inicio = time.monotonic()
    filho = subprocess.run(
        [sys.executable, str(RAIZ / "tools" / "passeio_app.py"), str(saida)], check=False
    )
    duracao = time.monotonic() - inicio

    passos = ler_passos(saida, filho.returncode)
    despejo = saida / "despejo.txt"
    janela = saida / "janela.txt"
    log = saida / "biblioteca" / "logs" / "cartridges.log"
    if log.exists():
        shutil.copy(log, saida / "cartridges.log")
    relatorio = montar_relatorio(
        passos,
        duracao,
        despejo.read_text(encoding="utf-8") if despejo.exists() else "",
        janela.read_text(encoding="utf-8").strip() if janela.exists() else "",
    )
    (saida / "relatorio.md").write_text(relatorio, encoding="utf-8")
    print(relatorio.split("## Falhas", 1)[0])
    print(f"Relatório: {saida / 'relatorio.md'}")
    return codigo_de_saida(passos)


if __name__ == "__main__":
    sys.exit(main())
