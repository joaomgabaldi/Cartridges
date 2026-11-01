# test_app_sem_gtk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app Qt sobe sem o GTK: o `gi` bloqueado e o GTK morto fora do `sys.modules` (D90)."""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_ROTEIRO = r"""
RAIZ = %r

import sys
sys.path.insert(0, RAIZ)
from importlib.abc import MetaPathFinder

class _SemGi(MetaPathFinder):
    def find_spec(self, nome, caminho=None, alvo=None):
        if nome == "gi" or nome.startswith("gi."):
            raise ImportError("gi bloqueado: " + nome)
        return None

sys.meta_path.insert(0, _SemGi())

import cartridges.app
import cartridges.assistente

mortos = [
    m for m in ("cartridges.main", "cartridges.window", "cartridges.details_dialog")
    if m in sys.modules
]
com_gi = [m for m in sys.modules if m == "gi" or m.startswith("gi.")]
print("MORTOS=" + ",".join(mortos))
print("GI=" + ",".join(com_gi))
"""


def test_app_qt_nao_importa_o_gtk():
    # CARTRIDGES_DADOS/REGISTRO herdados do conftest: o `shared` não toca os dados reais.
    resultado = subprocess.run(
        [sys.executable, "-I", "-c", _ROTEIRO % str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "MORTOS=\n" in resultado.stdout + "\n", resultado.stdout
    assert "GI=\n" in resultado.stdout + "\n", resultado.stdout


# Os módulos GTK que a D93 apagou (nomes pontuados completos). `utils.caixa_redimensionavel` e
# `logging.color_log_formatter` ficam: o app Qt os usa (o segundo, por texto, no `dictConfig`).
_APAGADOS = (
    "cartridges.main", "cartridges.window", "cartridges.details_dialog", "cartridges.big_picture",
    "cartridges.gamepad", "cartridges.game_cover", "cartridges.logo_picker",
    "cartridges.seletor_do_ludusavi", "cartridges.sgdb_picker", "cartridges.steam_picker",
    "cartridges.wallpaper_picker", "cartridges.utils.animated_flow_box",
    "cartridges.utils.create_dialog", "cartridges.utils.dialog_backdrop",
    "cartridges.utils.sem_arrastar_texto", "cartridges.utils.spring_scroll",
    "cartridges.utils.tela_de_download", "cartridges.utils.toast_queue",
    "cartridges.utils.tocador_capas", "tools.passeio", "tools.passeio_app", "tools.passeio_relatorio",
)  # fmt: skip

_ROTEIRO_TODOS = _ROTEIRO.split("import cartridges.app")[0] + r"""
import importlib
from pathlib import Path

import cartridges.app  # instala o `_` nos builtins, como no app

# Todo .py, não `pkgutil.walk_packages`: ele pula as pastas sem `__init__.py` (utils, store, ...).
falhas = []
for arquivo in sorted(Path(RAIZ, "cartridges").rglob("*.py")):
    partes = list(arquivo.relative_to(RAIZ).with_suffix("").parts)
    if partes[-1] == "__init__":
        partes.pop()
    nome = ".".join(partes)
    if nome == "cartridges.__main__":  # roda o app
        continue
    try:
        importlib.import_module(nome)
    except BaseException as erro:  # noqa: BLE001
        falhas.append(nome + ": " + repr(erro))
print("FALHAS=" + " | ".join(falhas))
"""


def test_todo_modulo_do_app_importa_sem_gi():
    resultado = subprocess.run(
        [sys.executable, "-I", "-c", _ROTEIRO_TODOS % str(ROOT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "FALHAS=\n" in resultado.stdout + "\n", resultado.stdout


def _importados(arquivo: Path) -> set[str]:
    """Nomes pontuados completos que o arquivo importa (também `from pacote import modulo` e relativos)."""
    pacote = list(arquivo.relative_to(ROOT).with_suffix("").parts[:-1])
    achados: set[str] = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            achados.update(a.name for a in no.names)
        elif isinstance(no, ast.ImportFrom):
            base = pacote[: len(pacote) - (no.level - 1)] if no.level else []
            modulo = ".".join(base + ([no.module] if no.module else [])) if no.level else (no.module or "")
            achados.add(modulo)
            achados.update(f"{modulo}.{a.name}" for a in no.names)
    return achados


def test_nenhum_modulo_do_app_importa_gi_nem_dentro_de_funcao():
    """Por AST: pega o `import gi` tardio (dentro de função) que o import do teste acima não executa."""
    com_gi = sorted(
        arquivo.relative_to(ROOT).as_posix()
        for arquivo in (ROOT / "cartridges").rglob("*.py")
        if any(n == "gi" or n.startswith("gi.") for n in _importados(arquivo))
    )
    assert not com_gi, com_gi


def test_nada_importa_um_modulo_apagado():
    ainda_existem = [m for m in _APAGADOS if (ROOT / (m.replace(".", "/") + ".py")).exists()]
    assert not ainda_existem, f"arquivos que deviam ter sido apagados: {ainda_existem}"
    quem_importa = {
        f"{arquivo.relative_to(ROOT).as_posix()} -> {nome}"
        for pasta in ("cartridges", "tests", "tools")
        for arquivo in (ROOT / pasta).rglob("*.py")
        for nome in _importados(arquivo) & set(_APAGADOS)
    }
    assert not quem_importa, sorted(quem_importa)


@pytest.mark.parametrize(
    "caminho",
    [
        "data/gtk",
        "data/cartridges.gresource.xml.in",
        "meson.build",
        "cartridges/meson.build",
        "data/meson.build",
        "build-aux/windows/meson.build",
        "cartridges/cartridges.in",
    ],
)
def test_sem_gtk_no_repositorio(caminho):
    assert not (ROOT / caminho).exists()
