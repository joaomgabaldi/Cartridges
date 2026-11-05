"""Ler e gravar os .ini dos emuladores sem mexer no resto do arquivo."""

import os
import shutil
from pathlib import Path

import pytest

from cartridges.emuladores import ini
from cartridges.emuladores.ini import Valores

DADOS = Path(__file__).parent / "dados" / "emuladores"


def _copia(tmp_path, nome, destino=None):
    alvo = tmp_path / (destino or nome)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(DADOS / nome, alvo)
    return alvo


def test_le_os_quatro_formatos(tmp_path):
    assert ini.ler(_copia(tmp_path, "steam_emu.ini")) == Valores("1643320", "Player", "brazilian")
    assert ini.ler(_copia(tmp_path, "ALI213.ini")).appid == "214490"
    gse = ini.ler(_copia(tmp_path, "configs.user.ini"))
    assert (gse.appid, gse.nome, gse.idioma) == (None, "Player", "english")
    txt = tmp_path / "steam_appid.txt"
    txt.write_bytes(b"1091500\r\n")
    assert ini.ler(txt) == Valores("1091500", None, None)


def test_ausente_ou_desconhecido(tmp_path):
    assert ini.ler(tmp_path / "steam_emu.ini") == Valores(None, None, None)
    assert ini.ler(_copia(tmp_path, "codex.ini", "outro.ini")) == Valores(None, None, None)
    # modelo do language.changer: outro nome, mesmo formato
    assert ini.ler(tmp_path / "outro.ini", "steam_emu.ini").nome == "Player"


def test_comentario_nao_conta(tmp_path):
    f = tmp_path / "steam_emu.ini"
    f.write_bytes(b"[Settings]\r\n#UserName=x\r\n;Language=y\r\n//AppId=3\r\nUserName=Real\r\n")
    assert ini.ler(f) == Valores(None, "Real", None)


@pytest.mark.parametrize("nome", ["codex.ini", "ALI213.ini"])
def test_aplicar_preserva_bytes(tmp_path, nome):
    f = _copia(tmp_path, nome)
    antes = f.read_bytes()
    assert ini.aplicar(f, "Player2", "english") is True
    depois = f.read_bytes()
    trocas = [(b"UserName=Player", b"UserName=Player2"), (b"PlayerName = Player", b"PlayerName = Player2"),
              (b"Language=brazilian", b"Language=english"), (b"Language = brazilian", b"Language = english")]
    for velho, novo in trocas:
        depois = depois.replace(novo, velho)
    assert depois == antes
    assert b"\r\n" in antes and depois.count(b"\n") == depois.count(b"\r\n")
    assert ini.ler(f).nome == "Player2"


def test_aplicar_sem_mudanca_nao_grava(tmp_path):
    f = _copia(tmp_path, "steam_emu.ini")
    os.utime(f, (1000, 1000))
    assert ini.aplicar(f, "Player", "brazilian") is False
    assert ini.aplicar(f, None, None) is False
    assert f.stat().st_mtime == 1000


def test_chave_ausente_entra_abaixo_da_secao(tmp_path):
    f = tmp_path / "codex.ini"
    f.write_bytes(b"[settings]\r\nAppId=5\r\n[Interfaces]\r\nX=1\r\n")
    assert ini.aplicar(f, "Ana", "english") is True
    assert f.read_bytes() == b"[settings]\r\nLanguage=english\r\nUserName=Ana\r\nAppId=5\r\n[Interfaces]\r\nX=1\r\n"
    # seção ausente: acrescenta no fim, em LF, mesmo sem quebra final
    g = tmp_path / "configs.user.ini"
    g.write_bytes(b"[outra]\na=1")
    assert ini.aplicar(g, "Ana", None) is True
    assert g.read_bytes() == b"[outra]\na=1\n[user::general]\naccount_name=Ana\n"


def test_cria_configs_user_em_steam_settings(tmp_path):
    f = tmp_path / "steam_settings" / "configs.user.ini"
    f.parent.mkdir()
    assert ini.aplicar(f, "Ana", "latam") is True
    assert f.read_bytes() == b"[user::general]\naccount_name=Ana\nlanguage=latam\n"
    outro = tmp_path / "pasta" / "configs.user.ini"
    outro.parent.mkdir()
    assert ini.aplicar(outro, "Ana", "latam") is False
    assert not outro.exists()


def test_primeira_ocorrencia_na_secao_certa(tmp_path):
    f = tmp_path / "steam_emu.ini"
    f.write_bytes(
        b"\xef\xbb\xbf[Settings]\r\nUserName=A\r\n[Outra]\r\nUserName=B\r\n[Settings]\r\nUserName=C\r\n"
    )
    assert ini.ler(f).nome == "A"
    assert ini.aplicar(f, "Z", None) is True
    assert f.read_bytes() == (
        b"\xef\xbb\xbf[Settings]\r\nUserName=Z\r\n[Outra]\r\nUserName=B\r\n[Settings]\r\nUserName=C\r\n"
    )
    # chave só em outra seção: não é a da seção certa
    g = tmp_path / "codex.ini"
    g.write_bytes(b"[Outra]\nUserName=B\n[Settings]\nAppId=1\n")
    assert ini.ler(g).nome is None
    ini.aplicar(g, "Z", None)
    assert g.read_bytes() == b"[Outra]\nUserName=B\n[Settings]\nUserName=Z\nAppId=1\n"


def test_nome_valido():
    assert ini.nome_valido("Player")
    assert ini.nome_valido("a" * 32)
    for ruim in ["João", "a" * 33, "a=b", " x", "x ", "", "a\n"]:
        assert not ini.nome_valido(ruim)


@pytest.mark.parametrize("cabecalho", [b"[Settings] ; x", b"[Settings] # x", b"[Settings]\t;"])
def test_cabecalho_com_comentario_no_fim(tmp_path, cabecalho):
    f = tmp_path / "steam_emu.ini"
    f.write_bytes(cabecalho + b"\nUserName=Velho\n")
    assert ini.ler(f).nome == "Velho"
    assert ini.aplicar(f, "Ana", None) is True
    assert f.read_bytes() == cabecalho + b"\nUserName=Ana\n"


@pytest.mark.parametrize("valor", ["a=b", "a;b", "a#b", "a\rb", "a\nb", "Ação", "a\x00b"])
def test_aplicar_recusa_valor_que_quebra_o_formato(tmp_path, valor):
    f = tmp_path / "steam_emu.ini"
    f.write_bytes(b"[Settings]\nUserName=Velho\n")
    with pytest.raises(ValueError):
        ini.aplicar(f, valor, None)
    with pytest.raises(ValueError):
        ini.aplicar(f, None, valor)
    assert f.read_bytes() == b"[Settings]\nUserName=Velho\n"


def test_nome_aceito():
    assert ini.nome_aceito("") and ini.nome_aceito("  ") and ini.nome_aceito(" Ana ")
    assert not ini.nome_aceito("Ação") and not ini.nome_aceito("x" * 33)


def test_guarda_nome_ou_idioma_pelo_nome_do_arquivo():
    assert ini.guarda_nome_ou_idioma("C:/j/steam_emu.ini")
    assert ini.guarda_nome_ou_idioma("C:/j/steam_settings/configs.user.ini")
    assert ini.guarda_nome_ou_idioma("C:/j/steam_emu_x.ini")  # modelo do language.changer
    assert not ini.guarda_nome_ou_idioma("C:/j/steam_appid.txt")
