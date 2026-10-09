# test_saves_pasta.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A pasta onde os saves moram: a padrão, a escolhida, e a troca entre elas."""

import pytest

from cartridges import shared
from cartridges.saves import pasta


def _guarda_save(raiz, jogo, arquivo="save.dat", conteudo="x"):
    (raiz / jogo).mkdir(parents=True, exist_ok=True)
    (raiz / jogo / arquivo).write_text(conteudo)


def test_sem_escolha_a_pasta_atual_e_a_padrao(settings) -> None:
    assert pasta.atual() == shared.app_dir / "saves"
    assert pasta.padrao() == shared.app_dir / "saves"


def test_move_quando_a_nova_esta_vazia(settings, tmp_path) -> None:
    antiga = pasta.padrao()
    _guarda_save(antiga, "X", conteudo="a")
    nova = tmp_path / "outra"

    pasta.trocar(nova)

    assert (nova / "X" / "save.dat").read_text() == "a"
    assert not (antiga / "X").exists()
    assert pasta.atual() == nova


def test_adota_quando_a_nova_tem_saves(settings, tmp_path) -> None:
    antiga = pasta.padrao()
    _guarda_save(antiga, "X")
    nova = tmp_path / "outra"
    _guarda_save(nova, "Y")

    pasta.trocar(nova)

    assert (antiga / "X" / "save.dat").is_file()
    assert not (nova / "X").exists()
    assert (nova / "Y" / "save.dat").is_file()
    assert pasta.atual() == nova


def test_recusa_a_mesma_e_subpasta(settings) -> None:
    atual = pasta.padrao()
    _guarda_save(atual, "X")

    for nova in (atual, atual / "SUB", atual / "X"):
        with pytest.raises(pasta.TrocaRecusada):
            pasta.trocar(nova)

    assert sorted(p.name for p in atual.iterdir()) == ["X"]
    assert [p.name for p in (atual / "X").iterdir()] == ["save.dat"]
    assert not (atual / "SUB").exists()
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_recusa_a_mesma_ignorando_maiusculas(settings) -> None:
    atual = pasta.padrao()
    atual.mkdir()

    with pytest.raises(pasta.TrocaRecusada):
        pasta.trocar(atual.parent / atual.name.upper())


def test_voltar_ao_padrao_grava_vazio(settings, tmp_path) -> None:
    outra = tmp_path / "outra"
    _guarda_save(pasta.padrao(), "X")
    pasta.trocar(outra)
    assert shared.schema.get_string("pasta-dos-saves") == str(outra)

    pasta.trocar(pasta.padrao())

    assert shared.schema.get_string("pasta-dos-saves") == ""
    assert pasta.atual() == pasta.padrao()
    assert (pasta.padrao() / "X" / "save.dat").is_file()
    assert not (outra / "X").exists()


def test_antiga_inexistente_so_grava_a_chave(settings, tmp_path) -> None:
    nova = tmp_path / "outra"

    pasta.trocar(nova)

    assert nova.is_dir()
    assert pasta.atual() == nova
