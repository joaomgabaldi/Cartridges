# test_copiar_dados_dev.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A cópia de desenvolvimento preserva os tipos do registro e nunca altera a origem."""

import uuid
import winreg

import pytest

from tools import copiar_dados_dev as cd


def _ler(caminho: str) -> dict:
    """Valores e subchaves de uma chave, como dicionário comparável."""
    saida = {}
    with winreg.OpenKey(cd.RAIZ, caminho, 0, winreg.KEY_READ) as chave:
        i = 0
        while True:
            try:
                nome, dado, tipo = winreg.EnumValue(chave, i)
            except OSError:
                break
            saida[nome] = (dado, tipo)
            i += 1
        i = 0
        while True:
            try:
                filha = winreg.EnumKey(chave, i)
            except OSError:
                break
            saida[filha + "\\"] = _ler(f"{caminho}\\{filha}")
            i += 1
    return saida


@pytest.fixture
def chaves():
    raiz = rf"Software\CartridgesTestes\{uuid.uuid4()}"
    origem, destino = raiz + r"\origem", raiz + r"\destino"
    with winreg.CreateKeyEx(cd.RAIZ, origem, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "inteiro", 0, winreg.REG_DWORD, 7)
        winreg.SetValueEx(k, "grande", 0, winreg.REG_QWORD, 2**40)
        winreg.SetValueEx(k, "texto", 0, winreg.REG_SZ, "olá")
    with winreg.CreateKeyEx(cd.RAIZ, origem + r"\State", 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "width", 0, winreg.REG_DWORD, 1170)
    yield origem, destino
    cd.apagar_chave(raiz)


def test_copia_tipos_e_nao_altera_a_origem(chaves, tmp_path):
    origem, destino = chaves
    pasta = tmp_path / "origem"
    (pasta / "games").mkdir(parents=True)
    (pasta / "games" / "a.json").write_text("{}", encoding="utf-8")
    antes = _ler(origem)

    arquivos, valores = cd.copiar(pasta, tmp_path / "destino", origem, destino)

    assert (arquivos, valores) == (1, 4)
    assert _ler(origem) == antes
    assert _ler(destino) == antes
    assert (tmp_path / "destino" / "games" / "a.json").read_text(encoding="utf-8") == "{}"
    assert _ler(destino)["grande"][1] == winreg.REG_QWORD


def test_destino_existente_pede_substituir(chaves, tmp_path):
    origem, destino = chaves
    pasta = tmp_path / "origem"
    pasta.mkdir()
    cd.copiar(pasta, tmp_path / "destino", origem, destino)
    (tmp_path / "destino" / "sobra.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SystemExit):
        cd.copiar(pasta, tmp_path / "destino", origem, destino)
    antes = _ler(origem)

    cd.copiar(pasta, tmp_path / "destino", origem, destino, substituir=True)

    assert not (tmp_path / "destino" / "sobra.txt").exists()
    assert _ler(origem) == antes


def test_nao_herda_caminhos_para_os_dados_reais(chaves, tmp_path):
    origem, destino = chaves
    with winreg.OpenKeyEx(cd.RAIZ, origem, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "pasta-dos-saves", 0, winreg.REG_SZ, "C:/real/saves")
    pasta = tmp_path / "origem"
    (pasta / "ludusavi").mkdir(parents=True)
    for nome in ("config.yaml", "cache.yaml", "manifest.yaml"):
        (pasta / "ludusavi" / nome).write_text("x", encoding="utf-8")
    (pasta / "config.yaml").write_text("fica", encoding="utf-8")

    arquivos, valores = cd.copiar(pasta, tmp_path / "destino", origem, destino)

    copiado = _ler(destino)
    assert "pasta-dos-saves" not in copiado
    assert copiado["texto"] == ("olá", winreg.REG_SZ) and copiado["grande"][1] == winreg.REG_QWORD
    assert valores == 4
    assert sorted(p.name for p in (tmp_path / "destino" / "ludusavi").iterdir()) == ["manifest.yaml"]
    assert (tmp_path / "destino" / "config.yaml").read_text(encoding="utf-8") == "fica"
    assert arquivos == 2


def test_isolar_dev_forca_so_os_tres_valores(chaves, tmp_path):
    origem, destino = chaves
    with winreg.OpenKeyEx(cd.RAIZ, origem, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "shortcuts-location", 0, winreg.REG_SZ, r"C:\real\Atalhos")
        winreg.SetValueEx(k, "auto-import", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(k, "remove-missing", 0, winreg.REG_DWORD, 1)
    pasta = tmp_path / "origem"
    pasta.mkdir()
    cd.copiar(pasta, tmp_path / "destino", origem, destino)
    atalhos = tmp_path / "criada" / "atalhos-teste"
    antes_da_origem = _ler(origem)

    cd.isolar_dev(destino, atalhos)

    assert atalhos.is_dir()
    copiado = _ler(destino)
    assert copiado.pop("shortcuts-location") == (str(atalhos), winreg.REG_SZ)
    assert copiado.pop("auto-import") == (0, winreg.REG_DWORD)
    assert copiado.pop("remove-missing") == (0, winreg.REG_DWORD)
    esperado = dict(antes_da_origem)
    for nome in ("shortcuts-location", "auto-import", "remove-missing"):
        esperado.pop(nome)
    assert copiado == esperado  # o resto segue copiado sem mudança
    assert _ler(origem) == antes_da_origem  # a origem nunca é tocada


def test_copia_dev_nao_leva_fitas_nem_conta_tuya(chaves, tmp_path):
    """As chaves locais das fitas reais ficam fora: o app -dev acende fitas ao abrir (D53)."""
    origem, destino = chaves
    pasta = tmp_path / "origem"
    pasta.mkdir()
    for nome in ("fitas.json", "tuya_conta.json", "outro.json"):
        (pasta / nome).write_text("{}", encoding="utf-8")

    cd.copiar(pasta, tmp_path / "destino", origem, destino)

    assert sorted(p.name for p in (tmp_path / "destino").iterdir()) == ["outro.json"]


def test_copia_dev_nao_leva_contas_nem_chave_da_steam(chaves, tmp_path):
    """As contas das lojas (D57) e a chave da Steam ficam só nos dados reais: a -dev não as herda."""
    origem, destino = chaves
    with winreg.OpenKeyEx(cd.RAIZ, origem, 0, winreg.KEY_WRITE) as k:
        winreg.SetValueEx(k, "conquistas-chave-steam", 0, winreg.REG_SZ, "valor-de-teste")
    pasta = tmp_path / "origem"
    (pasta / "contas").mkdir(parents=True)
    (pasta / "contas" / "xbox.json").write_text("x", encoding="utf-8")
    (pasta / "games").mkdir()
    (pasta / "games" / "a.json").write_text("{}", encoding="utf-8")

    cd.copiar(pasta, tmp_path / "destino", origem, destino)

    assert not (tmp_path / "destino" / "contas").exists()
    assert (tmp_path / "destino" / "games" / "a.json").exists()
    assert "conquistas-chave-steam" not in _ler(destino)
