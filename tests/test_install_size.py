# test_install_size.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Medir quanto um jogo ocupa no disco, e dizer o número em português.

A parte interessante da medição é o que ela deixa de contar: uma pasta que não
dá para ler não pode derrubar a soma (instalações do Game Pass negam acesso no
meio do caminho), e um link não pode ser seguido — o mesmo arquivo contado dos
dois lados de uma junção daria um jogo com o dobro do tamanho.

Os números conferem com o que o Explorer mostra, que é com o que eles vão ser
comparados: base 1024, uma casa decimal, vírgula.
"""

import os

import pytest

from cartridges.utils.install_size import (
    folder_size,
    format_size,
    install_size_folder,
)

GIB = 1024**3


@pytest.mark.parametrize(
    ("size", "expected"),
    (
        (0, ""),  # desconhecido, não "ocupa nada"
        (-1, ""),
        (512, "512 B"),
        (2048, "2 KB"),
        (3 * 1024 * 1024, "3 MB"),
        (GIB, "1 GB"),
        (int(GIB * 87.42), "87,4 GB"),
        (2 * 1024**4, "2 TB"),
    ),
)
def test_format_size(size: int, expected: str) -> None:
    assert format_size(size) == expected


def write(path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)


def test_folder_size_sums_every_level(tmp_path) -> None:
    write(tmp_path / "game.exe", 1000)
    write(tmp_path / "bin" / "data.pak", 2000)
    write(tmp_path / "bin" / "deep" / "more.pak", 4000)

    assert folder_size(str(tmp_path)) == 7000
    assert folder_size(str(tmp_path / "bin")) == 6000


def test_folder_size_of_missing_folder_is_zero(tmp_path) -> None:
    """Um jogo que saiu do disco mede zero em vez de estourar."""
    assert folder_size(str(tmp_path / "desinstalado")) == 0


def test_a_folder_holding_a_whole_library_is_refused(tmp_path) -> None:
    """Um atalho para ``steam.exe -applaunch`` nomeia o cliente, cuja pasta tem
    a biblioteca Steam inteira dentro. Medir isso daria um jogo de 400 GB no
    topo justamente da ordenação feita para decidir o que apagar."""
    steam = tmp_path / "Games" / "Steam"
    write(steam / "steam.exe", 100)
    write(steam / "steamapps" / "common" / "Outro Jogo" / "data.pak", 5000)

    assert install_size_folder(f'"{steam}\\steam.exe" -applaunch 440') == ""

    # E o jogo ao lado, que não guarda a biblioteca de ninguém, continua medindo
    jogo = tmp_path / "Games" / "Hollow Knight"
    write(jogo / "hollow_knight.exe", 100)
    assert install_size_folder(f'"{jogo}\\hollow_knight.exe"') == str(jogo).replace(
        "/", "\\"
    )


def test_folder_size_ignores_links(tmp_path) -> None:
    """O mesmo arquivo do outro lado de um link não é contado duas vezes."""
    write(tmp_path / "game" / "data.pak", 3000)
    link = tmp_path / "game" / "atalho"
    try:
        os.symlink(tmp_path / "game", link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("criar link simbólico exige privilégio no Windows")

    assert folder_size(str(tmp_path / "game")) == 3000
