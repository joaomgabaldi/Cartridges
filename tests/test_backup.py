# test_backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Restaurar um backup sobre uma biblioteca que já existe.

O backup leva o que veio do usuário e de mais ninguém, e cada campo volta pela
regra da sua natureza: o tempo de jogo é uma parcela e soma, o status, a nota e
a anotação são valores e só preenchem o que está vazio. É a diferença entre
restaurar duas máquinas na mesma biblioteca (soma) e restaurar por cima de uma
biblioteca em uso (não apaga nada).

O arquivo veio de fora e pode ter sido editado à mão, então metade destes
testes é sobre o que ele *não* consegue gravar.
"""

import pytest

from cartridges.game import Game
from cartridges.preferences import BACKUP_FIELDS, restore_into


def game(**fields) -> Game:
    return Game(
        {
            "source": "shortcuts",
            "game_id": "shortcuts_1",
            "name": "Hollow Knight",
            "executable": "x",
            "added": 0,
            **fields,
        }
    )


def test_the_backup_carries_what_only_the_user_knows(win) -> None:
    """Se um campo digitado à mão sair desta lista, ele para de ser salvo em
    silêncio — e só se descobre no dia de restaurar."""
    assert set(BACKUP_FIELDS) == {"playtime", "status", "rating", "notes"}


def test_an_empty_library_gets_everything_back(win) -> None:
    """O caso principal: formatou o computador, reimportou os jogos."""
    fresh = game()
    entry = {
        "playtime": 7200,
        "status": "beaten",
        "rating": 4,
        "notes": "Parei no capítulo 4.",
    }

    assert restore_into(fresh, entry) is True
    assert fresh.playtime == 7200
    assert fresh.status == "beaten"
    assert fresh.rating == 4
    assert fresh.notes == "Parei no capítulo 4."


def test_the_playtime_adds_up(win) -> None:
    """O backup é uma parcela do total, não o total: restaurar o de outra
    máquina na mesma biblioteca tem de dar a soma das duas."""
    played = game(playtime=3600)

    assert restore_into(played, {"playtime": 1800}) is True
    assert played.playtime == 5400


def test_what_is_already_filled_in_survives(win) -> None:
    """O que está na biblioteca agora é mais novo que o que está no arquivo."""
    current = game(status="playing", rating=5, notes="Nota de agora")
    entry = {"status": "dropped", "rating": 1, "notes": "Nota velha"}

    assert restore_into(current, entry) is False
    assert current.status == "playing"
    assert current.rating == 5
    assert current.notes == "Nota de agora"


def test_importing_the_same_file_twice_only_doubles_the_playtime(win) -> None:
    """O preço conhecido do tempo somar. Os outros três ficam de pé."""
    fresh = game()
    entry = {"playtime": 3600, "status": "beaten", "rating": 3, "notes": "Zerei"}

    restore_into(fresh, entry)
    restore_into(fresh, entry)

    assert fresh.playtime == 7200
    assert (fresh.status, fresh.rating, fresh.notes) == ("beaten", 3, "Zerei")


@pytest.mark.parametrize(
    "entry",
    (
        {"status": "zerado"},  # o rótulo, e não a chave
        {"status": 3},
        {"status": ""},
        {"rating": 9},  # fora de 1–5
        {"rating": -1},
        {"rating": "ótimo"},
        {"playtime": "muito"},
        {"playtime": -3600},  # nunca tira tempo de ninguém
        {"notes": "   \n  "},  # espaço não é anotação
        {"notes": 42},
        {},
    ),
)
def test_a_hand_edited_file_cannot_write_nonsense(win, entry) -> None:
    """Um valor que o app não sabe exibir é descartado na entrada, e não
    gravado para quebrar uma tela mais adiante."""
    fresh = game()

    assert restore_into(fresh, entry) is False
    assert (fresh.playtime, fresh.status, fresh.rating, fresh.notes) == (0, "", 0, "")


def test_a_version_1_entry_still_restores(win) -> None:
    """Backups salvos quando o arquivo só levava tempo de jogo continuam
    valendo: eles trazem menos campos, e é só."""
    fresh = game()

    assert restore_into(fresh, {"name": "Hollow Knight", "playtime": 3600}) is True
    assert fresh.playtime == 3600
