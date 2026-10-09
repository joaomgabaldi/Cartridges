# test_saves_pasta.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A pasta onde os saves moram: a padrão, a escolhida, e a troca entre elas."""

import shutil
import threading
from pathlib import Path

import pytest

from cartridges import shared
from cartridges.saves import pasta


@pytest.fixture(autouse=True)
def app_dir_proprio(tmp_path, monkeypatch):
    """A pasta do app numa subpasta: as pastas "de fora" dos testes ficam em
    `tmp_path`, que o `app_dirs` do conftest usa como a própria pasta do app."""
    monkeypatch.setattr(shared, "app_dir", tmp_path / "app")


def _guarda_save(raiz, jogo, arquivo="save.dat", conteudo="x"):
    """Uma pasta de jogo como o Ludusavi grava: com o `mapping.yaml`."""
    (raiz / jogo).mkdir(parents=True, exist_ok=True)
    (raiz / jogo / "mapping.yaml").write_text("name: x")
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
        with pytest.raises(pasta.TrocaRecusada) as recusa:
            pasta.trocar(nova)
        assert str(recusa.value) == "Escolha uma pasta fora da pasta atual dos saves."

    assert sorted(p.name for p in atual.iterdir()) == ["X"]
    assert sorted(p.name for p in (atual / "X").iterdir()) == ["mapping.yaml", "save.dat"]
    assert not (atual / "SUB").exists()
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_recusa_a_mesma_ignorando_maiusculas(settings) -> None:
    atual = pasta.padrao()
    atual.mkdir(parents=True)

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

    with pytest.raises(pasta.TrocaRecusada) as recusa:
        pasta.trocar(shared.app_dir)
    assert str(recusa.value) == "Escolha uma pasta que não contenha a pasta atual dos saves."

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

    with pytest.raises(pasta.TrocaRecusada) as recusa:
        pasta.trocar(nova)
    assert str(recusa.value) == (
        "A pasta escolhida já tem arquivos com os mesmos nomes dos saves. Escolha outra pasta."
    )

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


def test_so_os_saves_saem_de_uma_pasta_com_outras_coisas(settings, tmp_path) -> None:
    """A raiz do OneDrive adotada e depois trocada: só as pastas com `mapping.yaml` vão."""
    onedrive = tmp_path / "OneDrive"
    (onedrive / "Fotos").mkdir(parents=True)
    (onedrive / "Fotos" / "praia.jpg").write_text("foto")
    (onedrive / "nota.txt").write_text("nota")
    _guarda_save(onedrive, "Jogo")
    pasta.trocar(onedrive)
    assert pasta.atual() == onedrive  # adotada: já tinha um save

    vazia = tmp_path / "vazia"
    pasta.trocar(vazia)

    assert (onedrive / "Fotos" / "praia.jpg").read_text() == "foto"
    assert (onedrive / "nota.txt").read_text() == "nota"
    assert not (onedrive / "Jogo").exists()
    assert sorted(p.name for p in vazia.iterdir()) == ["Jogo"]
    assert (vazia / "Jogo" / "save.dat").is_file()


def test_pasta_so_com_outras_coisas_nao_e_adotada(settings, tmp_path) -> None:
    _guarda_save(pasta.padrao(), "X")
    documentos = tmp_path / "Documentos"
    (documentos / "Trabalho").mkdir(parents=True)

    pasta.trocar(documentos)

    assert (documentos / "X" / "save.dat").is_file()  # sem saves nela: os saves foram junto
    assert (documentos / "Trabalho").is_dir()


def test_pasta_sem_mapping_na_antiga_fica_onde_esta(settings, tmp_path) -> None:
    """Uma cópia pela metade (sem `mapping.yaml`) ou uma pasta qualquer não é save."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "X")
    (antiga / "Outra").mkdir()
    nova = tmp_path / "nova"
    (nova / "Outra").mkdir(parents=True)  # o mesmo nome não é conflito: não é save

    pasta.trocar(nova)

    assert (nova / "X" / "save.dat").is_file()
    assert (antiga / "Outra").is_dir()


@pytest.mark.parametrize("relativa", ["MeusSaves", "saves/Sub", ""])
def test_recusa_pasta_dentro_da_pasta_do_app(settings, tmp_path, relativa) -> None:
    pasta.trocar(tmp_path / "fora")  # a atual fora do app, para só esta regra recusar
    nova = shared.app_dir / relativa if relativa else shared.app_dir

    with pytest.raises(pasta.TrocaRecusada) as recusa:
        pasta.trocar(nova)
    assert str(recusa.value) == "Escolha uma pasta fora da pasta de dados do Cartridges."
    assert pasta.atual() == tmp_path / "fora"


def test_recusa_pasta_que_contem_a_pasta_do_app(settings, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(shared, "app_dir", tmp_path / "Local" / "app")
    pasta.trocar(tmp_path / "fora")

    with pytest.raises(pasta.TrocaRecusada) as recusa:
        pasta.trocar(tmp_path / "Local")
    assert str(recusa.value) == "Escolha uma pasta fora da pasta de dados do Cartridges."


def test_a_padrao_continua_aceita(settings, tmp_path) -> None:
    pasta.trocar(tmp_path / "fora")
    pasta.trocar(pasta.padrao())
    assert pasta.atual() == pasta.padrao()


def test_a_chave_e_gravada_na_thread_da_tela(settings, tmp_path, monkeypatch, flush_idle) -> None:
    _guarda_save(pasta.padrao(), "X")
    nova = tmp_path / "nova"
    gravou_em = []
    original = shared.schema

    class Espia:
        def __getattr__(self, nome):
            return getattr(original, nome)

        def set_string(self, chave, valor):
            gravou_em.append(threading.current_thread())
            return original.set_string(chave, valor)

    monkeypatch.setattr(shared, "schema", Espia())
    erros = []

    def trocar():
        try:
            pasta.trocar(nova)
        except Exception as erro:  # noqa: BLE001
            erros.append(erro)

    trabalho = threading.Thread(target=trocar)
    trabalho.start()
    while trabalho.is_alive():
        flush_idle()
        trabalho.join(0.01)

    assert erros == []
    assert gravou_em == [threading.main_thread()]
    assert pasta.atual() == nova
    assert not (pasta.padrao() / "X").exists()  # os originais só saem com a chave gravada
