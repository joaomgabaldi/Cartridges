# test_soltar_atalhos.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Arrastar atalhos para a janela: o que entra na pasta de atalhos."""

from cartridges.utils import soltar_atalhos
from cartridges.utils.soltar_atalhos import MAX_ARQUIVOS, MAX_BYTES, Resultado


def arquivo(pasta, nome, conteudo=b"x"):
    caminho = pasta / nome
    caminho.write_bytes(conteudo)
    return caminho


def test_filtra_por_extensao(tmp_path):
    nomes = ["a.lnk", "b.URL", "c.exe", "d.txt"]
    caminhos = [arquivo(tmp_path, nome) for nome in nomes]

    aceitos, ignorados = soltar_atalhos.filtrar(caminhos)

    assert [c.name for c in aceitos] == ["a.lnk", "b.URL"]
    assert ignorados == 2


def test_ignora_nao_local_e_pasta(tmp_path):
    pasta = tmp_path / "pasta.lnk"
    pasta.mkdir()

    assert soltar_atalhos.filtrar([None, pasta]) == ([], 2)


def test_ignora_arquivo_grande(tmp_path):
    grande = arquivo(tmp_path, "grande.lnk", b"x" * (MAX_BYTES + 1))
    no_limite = arquivo(tmp_path, "limite.lnk", b"x" * MAX_BYTES)

    assert soltar_atalhos.filtrar([grande, no_limite]) == ([no_limite], 1)


def test_limita_quantidade(tmp_path):
    caminhos = [arquivo(tmp_path, f"{i}.lnk") for i in range(MAX_ARQUIVOS + 1)]

    aceitos, ignorados = soltar_atalhos.filtrar(caminhos)

    assert aceitos == caminhos[:MAX_ARQUIVOS]
    assert ignorados == 1


def pasta_de_atalhos(tmp_path, schema):
    pasta = tmp_path / "Atalhos"
    pasta.mkdir()
    schema["shortcuts-location"] = str(pasta)
    return pasta


def test_copia_sem_sobrescrever(tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)
    arquivo(pasta, "Halo.lnk", b"velho")
    fora = tmp_path / "Downloads"
    fora.mkdir()

    resultado = soltar_atalhos.copiar(
        [arquivo(fora, "Halo.lnk", b"novo"), arquivo(fora, "Doom.lnk")]
    )

    assert resultado == Resultado(copiados=1, ja_existiam=1, ignorados=0)
    assert (pasta / "Halo.lnk").read_bytes() == b"velho"
    assert (pasta / "Doom.lnk").is_file()


def test_atalho_ja_dentro_da_pasta_conta_como_copiado(tmp_path, schema):
    pasta = pasta_de_atalhos(tmp_path, schema)

    resultado = soltar_atalhos.copiar([arquivo(pasta, "Halo.lnk")])

    assert resultado == Resultado(copiados=1, ja_existiam=0, ignorados=0)


def test_pasta_configurada(tmp_path, schema):
    assert soltar_atalhos.pasta_configurada() is False
    schema["shortcuts-location"] = str(tmp_path / "nao-existe")
    assert soltar_atalhos.pasta_configurada() is False
    schema["shortcuts-location"] = str(tmp_path)
    assert soltar_atalhos.pasta_configurada() is True
