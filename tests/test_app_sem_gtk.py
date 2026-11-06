# test_app_sem_gtk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app Qt sobe sem o GTK: o `gi` bloqueado e o GTK morto fora do `sys.modules`."""

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

import kyron.app
import kyron.assistente

mortos = [
    m for m in ("kyron.main", "kyron.window", "kyron.details_dialog")
    if m in sys.modules
]
com_gi = [m for m in sys.modules if m == "gi" or m.startswith("gi.")]
print("MORTOS=" + ",".join(mortos))
print("GI=" + ",".join(com_gi))
"""


def test_app_qt_nao_importa_o_gtk():
    # KYRON_DADOS/REGISTRO herdados do conftest: o `shared` não toca os dados reais.
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


# Módulos GTK apagados. `utils.caixa_redimensionavel` e `logging.color_log_formatter` ficam: o app Qt os usa (o
# segundo, por texto, no `dictConfig`).
_APAGADOS = (
    "kyron.main", "kyron.window", "kyron.details_dialog", "kyron.big_picture",
    "kyron.gamepad", "kyron.game_cover", "kyron.logo_picker",
    "kyron.seletor_do_ludusavi", "kyron.sgdb_picker", "kyron.steam_picker",
    "kyron.wallpaper_picker", "kyron.utils.animated_flow_box",
    "kyron.utils.create_dialog", "kyron.utils.dialog_backdrop",
    "kyron.utils.sem_arrastar_texto", "kyron.utils.spring_scroll",
    "kyron.utils.tela_de_download", "kyron.utils.toast_queue",
    "kyron.utils.tocador_capas", "tools.passeio", "tools.passeio_app", "tools.passeio_relatorio",
)  # fmt: skip

_ROTEIRO_TODOS = _ROTEIRO.split("import kyron.app")[0] + r"""
import importlib
from pathlib import Path

import kyron.app  # instala o `_` nos builtins, como no app

# Todo .py, não `pkgutil.walk_packages`: ele pula as pastas sem `__init__.py` (utils, store, ...).
falhas = []
for arquivo in sorted(Path(RAIZ, "kyron").rglob("*.py")):
    partes = list(arquivo.relative_to(RAIZ).with_suffix("").parts)
    if partes[-1] == "__init__":
        partes.pop()
    nome = ".".join(partes)
    if nome == "kyron.__main__":  # roda o app
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
        for arquivo in (ROOT / "kyron").rglob("*.py")
        if any(n == "gi" or n.startswith("gi.") for n in _importados(arquivo))
    )
    assert not com_gi, com_gi


def test_nada_importa_um_modulo_apagado():
    ainda_existem = [m for m in _APAGADOS if (ROOT / (m.replace(".", "/") + ".py")).exists()]
    assert not ainda_existem, f"arquivos que deviam ter sido apagados: {ainda_existem}"
    quem_importa = {
        f"{arquivo.relative_to(ROOT).as_posix()} -> {nome}"
        for pasta in ("kyron", "tests", "tools")
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
        "data/meson.build",
        "build-aux/windows/meson.build",
    ],
)
def test_sem_gtk_no_repositorio(caminho):
    assert not (ROOT / caminho).exists()


def test_sem_estado_morto_do_gtk():
    from kyron import shared  # noqa: PLC0415

    assert not hasattr(shared, "AppState")
    assert not hasattr(shared, "win")
