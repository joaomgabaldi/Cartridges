# test_store_ligacao_manual.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ligação: um jogo adicionado à mão e, depois, o atalho dele na pasta de
atalhos viram um jogo só, com tudo o que o manual já tinha."""

import pytest

from cartridges.store.store import alvo_do_comando


@pytest.mark.parametrize(
    "comando, alvo",
    [
        ('"C:\\Jogos\\X\\x.exe"', "C:\\Jogos\\X\\x.exe"),
        ('"C:\\Jogos\\X\\x.exe" -windowed', "C:\\Jogos\\X\\x.exe"),
        ('start "" /D "C:\\Jogos\\X" "C:\\Jogos\\X\\x.exe" -a', "C:\\Jogos\\X\\x.exe"),
        ('start "" "C:\\Jogos\\X\\x.exe"', "C:\\Jogos\\X\\x.exe"),
        ("C:\\Jogos\\X\\x.exe", "C:\\Jogos\\X\\x.exe"),
        ("  C:\\Jogos\\X\\x.exe  ", "C:\\Jogos\\X\\x.exe"),
        ("steam://rungameid/10", "steam://rungameid/10"),
        ('start "" "steam://rungameid/10"', "steam://rungameid/10"),
    ],
)
def test_alvo_do_comando(comando, alvo):
    assert alvo_do_comando(comando) == alvo


@pytest.mark.parametrize("comando", ["", "   ", '""', '"C:\\sem\\fim', 'start ""'])
def test_alvo_do_comando_sem_alvo(comando):
    assert alvo_do_comando(comando) is None
