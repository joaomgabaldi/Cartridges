"""O `meson.build` não deixa o bytecode dos subpacotes ir para a instalação."""

import re
from pathlib import Path

import pytest

_PASTA = Path(__file__).resolve().parent.parent / "cartridges"
_TEXTO = (_PASTA / "meson.build").read_text(encoding="utf-8")
# `install_subdir('nome', ... exclude_directories: <'x' ou ['x', 'y']>)`, em uma ou várias linhas.
_CHAMADA = re.compile(
    r"install_subdir\(\s*'([^']+)'(.*?)exclude_directories:\s*(\[[^\]]*\]|'[^']*')", re.DOTALL
)


def _excluidos(texto: str) -> dict[str, set[str]]:
    return {nome: set(re.findall(r"'([^']+)'", lista)) for nome, _, lista in _CHAMADA.findall(texto)}


def _subpastas_com_python(pasta: Path) -> set[str]:
    return {
        f"{sub.relative_to(pasta).as_posix()}/__pycache__"
        for sub in pasta.rglob("*")
        if sub.is_dir() and sub.name != "__pycache__" and any(sub.glob("*.py"))
    }


def test_o_parser_acha_as_chamadas_que_importam():
    assert {"store", "conquistas"} <= set(_excluidos(_TEXTO))


@pytest.mark.parametrize("nome", sorted(_excluidos(_TEXTO)))
def test_cada_subpacote_tem_o_pycache_excluido(nome):
    esperado = {"__pycache__"} | _subpastas_com_python(_PASTA / nome)
    faltando = esperado - _excluidos(_TEXTO)[nome]
    assert not faltando, f"install_subdir('{nome}') não exclui {sorted(faltando)}"


def test_o_teste_pega_um_pycache_esquecido():
    sem_um = _TEXTO.replace("    'xbox/__pycache__',\n", "").replace("    'xbox/__pycache__',\r\n", "")
    assert sem_um != _TEXTO
    assert "xbox/__pycache__" not in _excluidos(sem_um)["conquistas"]
