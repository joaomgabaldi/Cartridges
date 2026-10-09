# test_saves_pasta.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A pasta onde os saves moram: a padrão, a escolhida, e a troca entre elas."""

import shutil
from pathlib import Path

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


def test_recusa_uma_pasta_que_contem_a_atual(settings) -> None:
    atual = pasta.padrao()
    _guarda_save(atual, "X")

    with pytest.raises(pasta.TrocaRecusada):
        pasta.trocar(shared.app_dir)

    assert (atual / "X" / "save.dat").is_file()
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_a_raiz_de_um_disco_contem_o_que_esta_nela() -> None:
    assert pasta._dentro(Path("E:/Saves"), Path("E:/"))
    assert pasta._dentro(Path("E:/"), Path("E:/"))
    assert not pasta._dentro(Path("E:/"), Path("E:/Saves"))
    assert not pasta._dentro(Path("D:/Saves"), Path("E:/"))


def test_recusa_se_a_nova_tem_um_arquivo_com_o_nome_de_um_item(settings, tmp_path) -> None:
    _guarda_save(pasta.padrao(), "X")
    nova = tmp_path / "outra"
    nova.mkdir()
    (nova / "X").write_text("meu")  # arquivo, não subpasta: a nova segue "sem saves"

    with pytest.raises(pasta.TrocaRecusada):
        pasta.trocar(nova)

    assert (pasta.padrao() / "X" / "save.dat").is_file()
    assert (nova / "X").read_text() == "meu"
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_falha_no_meio_nao_deixa_saves_pela_metade(settings, tmp_path, monkeypatch) -> None:
    antiga = pasta.padrao()
    _guarda_save(antiga, "A")
    _guarda_save(antiga, "B")
    nova = tmp_path / "outra"
    copiar = shutil.copytree
    chamadas = []

    def copytree_que_falha_na_segunda(origem, destino, *a, **k):
        chamadas.append(origem)
        if len(chamadas) == 2:
            Path(destino).mkdir()  # cópia pela metade
            raise OSError("disco cheio")
        return copiar(origem, destino, *a, **k)

    monkeypatch.setattr(shutil, "copytree", copytree_que_falha_na_segunda)

    with pytest.raises(OSError):
        pasta.trocar(nova)

    assert (antiga / "A" / "save.dat").is_file()
    assert (antiga / "B" / "save.dat").is_file()
    assert not any(item.is_dir() for item in nova.iterdir())
    assert shared.schema.get_string("pasta-dos-saves") == ""
    assert pasta.atual() == antiga


def test_original_que_nao_sai_nao_desfaz_a_troca(settings, tmp_path, monkeypatch) -> None:
    antiga = pasta.padrao()
    _guarda_save(antiga, "X")
    nova = tmp_path / "outra"

    def rmtree_travado(*_a, **_k):
        raise PermissionError("em uso")

    monkeypatch.setattr(shutil, "rmtree", rmtree_travado)

    pasta.trocar(nova)  # não levanta

    assert pasta.atual() == nova
    assert (nova / "X" / "save.dat").is_file()
    assert (antiga / "X" / "save.dat").is_file()  # sobrou duplicado, sem perda
