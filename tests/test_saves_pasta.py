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
    assert pasta.dentro(Path("E:/Saves"), Path("E:/"))
    assert pasta.dentro(Path("E:/"), Path("E:/"))
    assert not pasta.dentro(Path("E:/"), Path("E:/Saves"))
    assert not pasta.dentro(Path("D:/Saves"), Path("E:/"))


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
            (Path(destino) / "metade.dat").write_text("x")  # cópia pela metade
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


def _sobra(raiz, jogo, conteudo="pela metade"):
    """Uma cópia que o app começou e deixou no meio: `<jogo>.copiando` com a marca dele."""
    _guarda_save(raiz, jogo + ".copiando", conteudo=conteudo)
    (raiz / (jogo + ".copiando") / pasta.MARCA_COPIANDO).touch()


@pytest.mark.parametrize("nome", ["X.copiando", "X.COPIANDO", "X.Copiando"])
def test_saves_em_ignora_copiando_em_qualquer_caixa(tmp_path, nome) -> None:
    _guarda_save(tmp_path, nome)
    _guarda_save(tmp_path, "Y")

    assert [p.name for p in pasta.saves_em(tmp_path)] == ["Y"]


def test_copia_pela_metade_nao_e_adotada(settings, tmp_path) -> None:
    """A sobra de uma troca interrompida (app fechado no meio) não vale como save."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "X", conteudo="a")
    nova = tmp_path / "outra"
    _sobra(nova, "X")

    assert pasta.saves_em(nova) == []

    pasta.trocar(nova)

    assert (nova / "X" / "save.dat").read_text() == "a"  # os saves foram junto
    assert not (antiga / "X").exists()
    assert pasta.atual() == nova


def test_sobra_copiando_e_apagada(settings, tmp_path) -> None:
    """A sobra do app, de um save que vai ser levado, sai; o save chega sem a marca."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "X", conteudo="a")
    _guarda_save(antiga, "Y", conteudo="b")
    nova = tmp_path / "outra"
    _sobra(nova, "X")
    _sobra(nova, "Y")

    pasta.trocar(nova)

    assert sorted(p.name for p in nova.iterdir()) == ["X", "Y"]
    assert (nova / "X" / "save.dat").read_text() == "a"
    assert (nova / "Y" / "save.dat").read_text() == "b"
    assert not (nova / "X" / pasta.MARCA_COPIANDO).exists()


def test_so_o_que_o_app_criou_e_apagado(settings, tmp_path) -> None:
    """Na pasta nova, só as sobras com a marca do app (qualquer save, qualquer caixa);
    na antiga e no resto, nada."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "X")
    _guarda_save(antiga, "Z.copiando")  # não é save: não vai, não some
    nova = tmp_path / "outra"
    (nova / "Fotos.copiando").mkdir(parents=True)  # do usuário, nome de cópia sem ser nossa
    (nova / "Fotos.copiando" / "praia.jpg").write_text("foto")
    (nova / "nota.copiando").write_text("arquivo, não pasta")
    _guarda_save(nova, "W.copiando")  # com cara de sobra, mas sem a marca: do usuário
    _sobra(nova, "Y")  # nossa, de um jogo que esta troca não leva
    _sobra(nova, "Q")
    (nova / "Q.copiando").rename(nova / "Q.COPIANDO")  # nossa, em outra caixa

    pasta.trocar(nova)

    nomes = sorted(p.name for p in nova.iterdir())
    assert nomes == ["Fotos.copiando", "W.copiando", "X", "nota.copiando"]
    assert (nova / "Fotos.copiando" / "praia.jpg").read_text() == "foto"
    assert (nova / "W.copiando" / "save.dat").is_file()
    assert (antiga / "Z.copiando" / "save.dat").is_file()
    assert not (nova / "Z.copiando").exists()


def test_sobra_marcada_sai_tambem_antes_de_adotar(settings, tmp_path) -> None:
    """Uma pasta nova com saves é adotada, mas a sobra do app nela não fica: o Ludusavi
    acha a pasta de um jogo pelo nome dentro do `mapping.yaml`, não pelo da pasta."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "X")
    nova = tmp_path / "outra"
    _guarda_save(nova, "Y")
    _sobra(nova, "Z")  # de um jogo que nem está na antiga
    _guarda_save(nova, "W.copiando")  # sem a marca: do usuário

    pasta.trocar(nova)

    assert sorted(p.name for p in nova.iterdir()) == ["W.copiando", "Y"]
    assert (antiga / "X" / "save.dat").is_file()  # adotada: nada foi levado
    assert pasta.atual() == nova


@pytest.mark.parametrize("nome", ["X.copiando", "X.COPIANDO"])
def test_pasta_do_usuario_com_nome_de_copia_barra_a_troca(settings, tmp_path, nome) -> None:
    """Uma pasta do usuário que já ocupa o `<nome>.copiando` (em qualquer caixa) não é
    apagada nem usada: a troca falha e o que ela já tinha criado desaparece."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "A")
    _guarda_save(antiga, "X")
    nova = tmp_path / "outra"
    (nova / nome).mkdir(parents=True)
    (nova / nome / "meu.txt").write_text("meu")

    with pytest.raises(OSError):
        pasta.trocar(nova)

    assert [p.name for p in nova.iterdir()] == [nome]
    assert (nova / nome / "meu.txt").read_text() == "meu"
    assert (antiga / "A" / "save.dat").is_file()
    assert (antiga / "X" / "save.dat").is_file()
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_copiando_que_e_atalho_nao_e_seguido(settings, tmp_path) -> None:
    """Uma junção `X.copiando` para fora, mesmo com a marca no destino dela, não é apagada."""
    winapi = pytest.importorskip("_winapi")
    _guarda_save(pasta.padrao(), "X")
    fora = tmp_path / "fora"
    fora.mkdir()
    (fora / "importante.txt").write_text("meu")
    (fora / pasta.MARCA_COPIANDO).touch()
    nova = tmp_path / "outra"
    nova.mkdir()
    winapi.CreateJunction(str(fora), str(nova / "X.copiando"))

    with pytest.raises(OSError):
        pasta.trocar(nova)

    assert (fora / "importante.txt").read_text() == "meu"
    assert (nova / "X.copiando").is_junction()
    assert not (nova / "X").exists()
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_sobra_que_nao_sai_avisa_no_log_e_deixa_a_marca_para_a_proxima(
    settings, tmp_path, monkeypatch, caplog
) -> None:
    antiga = pasta.padrao()
    _guarda_save(antiga, "X", conteudo="a")
    nova = tmp_path / "outra"
    _sobra(nova, "X")
    apagar = Path.unlink

    def unlink_travado(self, *a, **k):
        if self.name == "save.dat":
            raise PermissionError("em uso")
        return apagar(self, *a, **k)

    with monkeypatch.context() as travado:
        travado.setattr(Path, "unlink", unlink_travado)
        with pytest.raises(OSError):  # a pasta do nome segue ocupada
            pasta.trocar(nova)

    assert any("X.copiando" in registro.getMessage() for registro in caplog.records)
    sobra = nova / "X.copiando"
    assert (sobra / "save.dat").is_file()
    assert (sobra / pasta.MARCA_COPIANDO).is_file()  # a marca sai por último
    assert not (sobra / pasta.MAPA).exists()  # e o que a faria parecer um save, primeiro
    assert (antiga / "X" / "save.dat").is_file()
    assert shared.schema.get_string("pasta-dos-saves") == ""

    pasta.trocar(nova)  # a próxima troca limpa e leva

    assert sorted(p.name for p in nova.iterdir()) == ["X"]
    assert (nova / "X" / "save.dat").read_text() == "a"
    assert pasta.atual() == nova


def test_sobra_com_mapping_que_nao_sai_barra_a_troca(settings, tmp_path, monkeypatch) -> None:
    """Uma sobra do app que o Ludusavi ainda reconheceria não pode ficar na pasta que vai
    valer: a troca falha e nada muda."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "X")
    nova = tmp_path / "outra"
    _sobra(nova, "Z")  # de um jogo que nem está na antiga
    apagar = Path.unlink

    def unlink_travado(self, *a, **k):
        if self.name == pasta.MAPA:
            raise PermissionError("em uso")
        return apagar(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink_travado)

    with pytest.raises(PermissionError):
        pasta.trocar(nova)

    assert (nova / "Z.copiando" / pasta.MAPA).is_file()
    assert (nova / "Z.copiando" / pasta.MARCA_COPIANDO).is_file()
    assert (antiga / "X" / "save.dat").is_file()
    assert not (nova / "X").exists()
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_sobra_sem_mapping_que_nao_sai_so_avisa_e_a_troca_segue(
    settings, tmp_path, monkeypatch, caplog
) -> None:
    """Sem o `mapping.yaml` a pasta não parece mais um jogo para o Ludusavi."""
    _guarda_save(pasta.padrao(), "X")
    nova = tmp_path / "outra"
    _sobra(nova, "Z")
    apagar = Path.unlink

    def unlink_travado(self, *a, **k):
        if self.name == "save.dat":
            raise PermissionError("em uso")
        return apagar(self, *a, **k)

    monkeypatch.setattr(Path, "unlink", unlink_travado)

    pasta.trocar(nova)  # não levanta

    assert any("Z.copiando" in registro.getMessage() for registro in caplog.records)
    assert not (nova / "Z.copiando" / pasta.MAPA).exists()
    assert (nova / "X" / "save.dat").is_file()
    assert pasta.atual() == nova


@pytest.mark.parametrize("caso", ["a_atual", "dentro_da_atual", "contem_a_atual", "dentro_do_app"])
def test_recusas_do_comeco_deixam_a_sobra_onde_esta(settings, tmp_path, caso) -> None:
    """As três primeiras recusas não mexem em nada, nem na sobra do app."""
    if caso == "dentro_do_app":
        pasta.trocar(tmp_path / "fora")  # a atual fora do app, para só esta regra recusar
    atual = pasta.atual()
    nova = {
        "a_atual": atual,
        "dentro_da_atual": atual / "SUB",
        "contem_a_atual": shared.app_dir,
        "dentro_do_app": shared.app_dir / "MeusSaves",
    }[caso]
    _sobra(nova, "Z")
    escolha = shared.schema.get_string("pasta-dos-saves")

    with pytest.raises(pasta.TrocaRecusada):
        pasta.trocar(nova)

    assert (nova / "Z.copiando" / pasta.MAPA).is_file()
    assert (nova / "Z.copiando" / "save.dat").is_file()
    assert (nova / "Z.copiando" / pasta.MARCA_COPIANDO).is_file()
    assert shared.schema.get_string("pasta-dos-saves") == escolha


def test_recusa_por_conflito_nao_toca_no_que_e_do_usuario(settings, tmp_path) -> None:
    _guarda_save(pasta.padrao(), "X")
    nova = tmp_path / "outra"
    (nova / "X").mkdir(parents=True)
    (nova / "X" / "meu.txt").write_text("meu")
    _guarda_save(nova, "Y.copiando")  # sem a marca: do usuário
    _sobra(nova, "Z")  # a do app sai antes de a troca decidir

    with pytest.raises(pasta.TrocaRecusada):
        pasta.trocar(nova)

    assert (nova / "X" / "meu.txt").read_text() == "meu"
    assert (nova / "Y.copiando" / "save.dat").is_file()
    assert not (nova / "Z.copiando").exists()
    assert (pasta.padrao() / "X" / "save.dat").is_file()
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_todos_sao_copiados_antes_de_algum_ser_renomeado(settings, tmp_path, monkeypatch) -> None:
    antiga = pasta.padrao()
    _guarda_save(antiga, "A")
    _guarda_save(antiga, "B")
    nova = tmp_path / "outra"
    copiar = shutil.copytree
    vistos = []

    def copytree_que_registra(origem, destino, *a, **k):
        destino = Path(destino)
        vistos.append(
            (
                destino,
                k.get("dirs_exist_ok"),
                (destino / pasta.MARCA_COPIANDO).is_file(),  # a marca entra antes da cópia
                sorted(p.name for p in nova.iterdir()),
            )
        )
        return copiar(origem, destino, *a, **k)

    monkeypatch.setattr(shutil, "copytree", copytree_que_registra)

    pasta.trocar(nova)

    assert [(v[0].name, v[1], v[2]) for v in vistos] == [
        ("A.copiando", True, True),
        ("B.copiando", True, True),
    ]
    assert vistos[0][3] == ["A.copiando"]
    assert vistos[1][3] == ["A.copiando", "B.copiando"]  # nenhum renomeado ainda
    assert sorted(p.name for p in nova.iterdir()) == ["A", "B"]
    assert (nova / "A" / "save.dat").is_file()
    assert (nova / "B" / "save.dat").is_file()
    assert not (nova / "A" / pasta.MARCA_COPIANDO).exists()
    assert not (nova / "B" / pasta.MARCA_COPIANDO).exists()


def test_morto_no_meio_da_copia_nao_e_adotado_e_a_nova_tentativa_completa(
    settings, tmp_path, monkeypatch
) -> None:
    """O app morre copiando o segundo save: nada foi renomeado, então a pasta não vale
    como adotada e a nova tentativa leva os dois."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "A", conteudo="a")
    _guarda_save(antiga, "B", conteudo="b")
    nova = tmp_path / "outra"
    copiar = shutil.copytree

    def copytree_que_morre_na_segunda(origem, destino, *a, **k):
        if Path(destino).name == "B.copiando":
            (Path(destino) / "metade.dat").write_text("x")
            raise OSError("morto")
        return copiar(origem, destino, *a, **k)

    with monkeypatch.context() as morte:
        morte.setattr(shutil, "copytree", copytree_que_morre_na_segunda)
        # morto não desfaz nada
        morte.setattr(shutil, "rmtree", lambda *_a, **_k: None)
        morte.setattr(Path, "unlink", lambda *_a, **_k: None)
        morte.setattr(Path, "rmdir", lambda *_a, **_k: None)
        with pytest.raises(OSError):
            pasta.trocar(nova)

    assert sorted(p.name for p in nova.iterdir()) == ["A.copiando", "B.copiando"]
    assert pasta.saves_em(nova) == []
    assert shared.schema.get_string("pasta-dos-saves") == ""

    pasta.trocar(nova)  # a nova tentativa

    assert sorted(p.name for p in nova.iterdir()) == ["A", "B"]
    assert (nova / "A" / "save.dat").read_text() == "a"
    assert (nova / "B" / "save.dat").read_text() == "b"
    assert not (nova / "B" / "metade.dat").exists()
    assert not (antiga / "A").exists()
    assert not (antiga / "B").exists()
    assert pasta.atual() == nova


def test_falha_ao_renomear_desfaz_tambem_o_ja_renomeado(settings, tmp_path, monkeypatch) -> None:
    antiga = pasta.padrao()
    _guarda_save(antiga, "A")
    _guarda_save(antiga, "B")
    nova = tmp_path / "outra"
    renomear = Path.replace
    chamadas = []

    def replace_que_falha_na_segunda(self, destino):
        chamadas.append(self)
        if len(chamadas) == 2:
            raise OSError("em uso")
        return renomear(self, destino)

    monkeypatch.setattr(Path, "replace", replace_que_falha_na_segunda)

    with pytest.raises(OSError):
        pasta.trocar(nova)

    assert chamadas[0].name == "A.copiando"
    assert not list(nova.iterdir())  # nem "A" (já renomeado) nem "B.copiando"
    assert (antiga / "A" / "save.dat").is_file()
    assert (antiga / "B" / "save.dat").is_file()
    assert shared.schema.get_string("pasta-dos-saves") == ""


def test_desfazer_tira_o_mapping_do_renomeado_primeiro(settings, tmp_path, monkeypatch) -> None:
    """Mesmo que apagar o resto falhe, o que foi renomeado não fica com cara de save."""
    antiga = pasta.padrao()
    _guarda_save(antiga, "A")
    _guarda_save(antiga, "B")
    nova = tmp_path / "outra"
    renomear = Path.replace
    apagar = Path.unlink
    chamadas = []

    def replace_que_falha_na_segunda(self, destino):
        chamadas.append(self)
        if len(chamadas) == 2:
            raise OSError("em uso")
        return renomear(self, destino)

    def unlink_travado(self, *a, **k):
        if self.name == "save.dat":
            raise PermissionError("em uso")
        return apagar(self, *a, **k)

    monkeypatch.setattr(Path, "replace", replace_que_falha_na_segunda)
    monkeypatch.setattr(Path, "unlink", unlink_travado)
    monkeypatch.setattr(shutil, "rmtree", lambda *_a, **_k: None)  # o resto não sai

    with pytest.raises(OSError, match="em uso"):
        pasta.trocar(nova)

    assert (nova / "A" / "save.dat").is_file()  # o resto ficou
    assert not (nova / "A" / pasta.MAPA).exists()
    assert pasta.saves_em(nova) == []
    assert shared.schema.get_string("pasta-dos-saves") == ""


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
