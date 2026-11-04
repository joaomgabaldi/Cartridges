# test_so_comentarios.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`tools/so_comentarios.py` só deixa passar mudança que seja de comentário ou docstring."""

import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "tools"))

from so_comentarios import diferencas  # noqa: E402


def _igual(antes, depois, ext):
    assert diferencas(antes, depois, ext) == []


def _difere(antes, depois, ext):
    assert diferencas(antes, depois, ext) != []


def test_py_so_comentario_ok():
    _igual("x = 1  # um\n# solto\ny = 2\n", "x = 1\ny = 2\n", ".py")


def test_py_docstring_removida_ok():
    antes = '"""Mod."""\n\n\nclass A:\n    """A."""\n\n    def f(self):\n        """F."""\n        return 1\n'
    depois = "class A:\n    def f(self):\n        return 1\n"
    _igual(antes, depois, ".py")


def test_py_corpo_vazio_e_diferenca():
    antes = 'def f():\n    """Só isto."""\n\n\ndef g():\n    return 1\n'
    _difere(antes, "def f():\n    pass\n\n\ndef g():\n    return 1\n", ".py")
    _difere(antes, "def f():\n\n\ndef g():\n    return 1\n", ".py")


def test_py_docstring_unica_intacta_ok():
    texto = 'def f():\n    """Só isto."""\n'
    _igual(texto, texto, ".py")


def test_py_noqa_removido_e_diferenca():
    _difere("import os  # noqa: F401\n", "import os\n", ".py")
    _difere("x = 1  # noqa\n", "x = 1\n", ".py")


def test_py_marcadores_removidos_ou_movidos_sao_diferenca():
    _difere("x = f()  # type: ignore\n", "x = f()\n", ".py")
    _difere("x = 1  # pragma: no cover\n", "x = 1\n", ".py")
    _difere("# fmt: off\nx = 1\n# fmt: on\n", "x = 1\n", ".py")
    _difere("# -*- coding: utf-8 -*-\nx = 1\n", "x = 1\n", ".py")
    _difere("a = 1  # noqa\nb = 2\n", "a = 1\nb = 2  # noqa\n", ".py")
    _difere("x = 1  # noqa: E1\n", "x = 1  # noqa: E2\n", ".py")


def test_py_marcador_dentro_de_string_nao_conta():
    _igual('x = "# noqa"  # solto\n', 'x = "# noqa"\n', ".py")


def test_py_codigo_mudado_e_diferenca():
    _difere("x = 1\n", "x = 2\n", ".py")
    _difere("x = 'a'\n", "x = 'b'\n", ".py")
    _difere("def f():\n    return 1\n", "def f(a):\n    return 1\n", ".py")


def test_py_sintaxe_quebrada_e_diferenca():
    _difere("x = 1\n", "x = (\n", ".py")


def test_py_string_solta_que_nao_e_docstring_e_diferenca():
    _difere("x = 1\n'''nota'''\ny = 2\n", "x = 1\ny = 2\n", ".py")


def test_qml_comentario_ok():
    antes = "// cabeçalho\nItem {\n    width: 10 // largura\n    /* bloco\n       longo */\n    height: 5\n}\n"
    depois = "Item {\n    width: 10\n    height: 5\n}\n"
    _igual(antes, depois, ".qml")


def test_qml_url_em_string_nao_e_comentario():
    _igual('Image { source: "http://x" }\n', 'Image { source: "http://x" }  // y\n', ".qml")
    _difere('Image { source: "http://x" }\n', 'Image { source: "http://y" }\n', ".qml")
    _difere('Image { source: "http://x//z" }\n', 'Image { source: "http://x" }\n', ".qml")
    _difere("Text { text: 'a /* b */ c' }\n", "Text { text: 'a  c' }\n", ".qml")


def test_qml_pragma_removido_e_diferenca():
    _difere("pragma Singleton\nimport QtQuick\nQtObject {}\n", "import QtQuick\nQtObject {}\n", ".qml")
    _difere(".pragma library\nvar a = 1\n", "var a = 1\n", ".js")


def test_qml_codigo_mudado_e_diferenca():
    _difere("Item { width: 10 }\n", "Item { width: 11 }\n", ".qml")
    _difere("a/**/b\n", "a b c\n", ".qml")


def test_qml_bloco_sem_fecho_e_diferenca():
    _difere("Item {}\n", "Item {}\n/* aberto\n", ".qml")


def test_iss_comentario_ok():
    antes = (
        "; cabeçalho\n[Setup]\nAppName=Kyron ; nada\n; outro\n[Code]\n// pascal\n{ bloco }\n"
        "procedure P;\nbegin\n  (* x *) Log('a // b'); // c\nend;\n"
    )
    depois = "[Setup]\nAppName=Kyron ; nada\n[Code]\nprocedure P;\nbegin\n  Log('a // b');\nend;\n"
    _igual(antes, depois, ".iss.in")


def test_iss_codigo_mudado_e_diferenca():
    _difere("[Setup]\nAppName=A\n", "[Setup]\nAppName=B\n", ".iss.in")
    _difere("[Code]\nLog('a // b');\n", "[Code]\nLog('a');\n", ".iss.in")
    _difere("[Setup]\nAppName=A\n", "[Setup]\n// AppName=A\n", ".iss.in")
    _difere("[Code]\nx := 1;\n;\n", "[Code]\nx := 1;\n", ".iss.in")
    _difere("[Code]\nx := '{#Versao}';\n", "[Code]\nx := '';\n", ".iss.in")
    _difere("[Code]\n{#Versao}\n", "[Code]\n", ".iss.in")


def test_bat_rem_ok():
    antes = "@echo off\nrem aviso\n:: outro\n  REM mais\necho oi\n"
    depois = "@echo off\necho oi\n"
    _igual(antes, depois, ".bat")
    _difere(antes, "@echo off\necho tchau\n", ".bat")
    _difere("echo a  b\n", "echo a b\n", ".bat")
    _difere("echo oi\n", "echo oi\r\n", ".bat")


def test_ps1_comentario_e_here_string():
    antes = "# a\n$x = 1 # b\n<# bloco #>\n$s = @'\n# fica\n'@\nWrite-Host '#nao'\n"
    depois = "$x = 1\n$s = @'\n# fica\n'@\nWrite-Host '#nao'\n"
    _igual(antes, depois, ".ps1")
    _difere(antes, depois.replace("# fica", "# some"), ".ps1")


def test_yml_comentario_e_bloco_literal():
    antes = '# a\nname: x  # b\nurl: "http://x#y"\nrun: |\n  # fica\n  echo 1\nz: 1\n'
    depois = 'name: x\nurl: "http://x#y"\nrun: |\n  # fica\n  echo 1\nz: 1\n'
    _igual(antes, depois, ".yml")
    _difere(antes, depois.replace("# fica", "# some"), ".yml")
    _difere("a:\n  b: 1\n", "a:\nb: 1\n", ".yml")


def test_c_comentario_ok():
    antes = '// x\nint main(void) { /* y */ return 0; } // z\nconst char *u = "http://a";\n'
    depois = 'int main(void) { return 0; }\nconst char *u = "http://a";\n'
    _igual(antes, depois, ".c")
    _difere(depois, depois.replace("return 0", "return 1"), ".rc")


def test_extensao_desconhecida_e_diferenca():
    _difere("a\n", "a\n", ".svg")
    _difere("a\n", "a\n", ".xyz")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "a@b")
    _git(tmp_path, "config", "user.name", "x")
    (tmp_path / "a.py").write_text("x = 1  # c\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("y = 1\n", encoding="utf-8")
    (tmp_path / "i.png").write_bytes(b"\x89PNG1")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def _cli(repo):
    return subprocess.run(
        [sys.executable, str(RAIZ / "tools" / "so_comentarios.py"), "HEAD"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8",
    )


def test_cli_arvore_limpa_sai_0(repo):
    assert _cli(repo).returncode == 0


def test_cli_so_comentario_sai_0(repo):
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    assert _cli(repo).returncode == 0


@pytest.mark.parametrize("mexer", ["codigo", "novo", "apagado", "binario", "preparado"])
def test_cli_diferenca_real_sai_1(repo, mexer):
    if mexer == "codigo":
        (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    elif mexer == "novo":
        (repo / "c.py").write_text("# so comentario\n", encoding="utf-8")
    elif mexer == "apagado":
        (repo / "b.py").unlink()
    elif mexer == "binario":
        (repo / "i.png").write_bytes(b"\x89PNG2")
    else:
        (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
        _git(repo, "add", "b.py")
    r = _cli(repo)
    assert r.returncode == 1
    assert ("b.py" in r.stdout) or ("c.py" in r.stdout) or ("i.png" in r.stdout)
