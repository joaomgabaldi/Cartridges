"""Idioma e nome do jogador por jogo: valores efetivos e gravação nos .ini."""

import os
import stat
from pathlib import Path

import pytest

from cartridges.emuladores import aplicacao
from cartridges.jogo import Jogo


def _jogo(**campos) -> Jogo:
    dados = {"game_id": "shortcuts_1", "source": "shortcuts", "name": "J", "executable": "x.exe", "added": 0}
    return Jogo({**dados, **campos})


def _ini(pasta: Path, nome="steam_emu.ini", texto="[Settings]\nUserName=Velho\nLanguage=english\n") -> Path:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome
    caminho.write_bytes(texto.encode("latin-1"))
    return caminho


def test_valores_padrao_do_kyron(schema):
    schema.set_string("nome-do-jogador", "Ana")
    schema.set_string("idioma-do-jogador", "german")
    assert aplicacao.valores_para(_jogo()) == ("Ana", "german")


def test_valores_do_jogo_mandam_no_padrao(schema):
    schema.set_string("nome-do-jogador", "Ana")
    schema.set_string("idioma-do-jogador", "german")
    assert aplicacao.valores_para(_jogo(nome_proprio="Bia", idioma_proprio="french")) == ("Bia", "french")


def test_valores_invalidos_viram_none(schema):
    schema.set_string("nome-do-jogador", "Ação")
    schema.set_string("idioma-do-jogador", "klingon")
    assert aplicacao.valores_para(_jogo()) == (None, None)
    assert aplicacao.valores_para(_jogo(nome_proprio="x" * 33)) == (None, None)


def test_idioma_com_appid_exige_confirmacao_da_steam(schema):
    schema.set_string("idioma-do-jogador", "german")
    assert aplicacao.valores_para(_jogo(steam_appid="620")) == (None, None)  # idiomas_steam None
    assert aplicacao.valores_para(_jogo(steam_appid="620", idiomas_steam=["french"])) == (None, None)
    assert aplicacao.valores_para(_jogo(steam_appid="620", idiomas_steam=["german"])) == (None, "german")
    assert aplicacao.valores_para(_jogo(idiomas_steam=["french"])) == (None, "german")  # sem appid grava


def test_aplicar_grava_em_todos(schema, tmp_path):
    schema.set_string("nome-do-jogador", "Ana")
    schema.set_string("idioma-do-jogador", "german")
    a, b = _ini(tmp_path / "a"), _ini(tmp_path / "b", "codex.ini")
    assert aplicacao.aplicar_no_jogo(_jogo(inis=[str(a), str(b)])) is True
    for c in (a, b):
        assert b"UserName=Ana" in c.read_bytes() and b"Language=german" in c.read_bytes()


def test_aplicar_sem_busca_ou_com_arquivo_ausente_nao_grava(schema, tmp_path):
    schema.set_string("nome-do-jogador", "Ana")
    existente = _ini(tmp_path)
    antes = existente.read_bytes()
    assert aplicacao.aplicar_no_jogo(_jogo()) is False
    assert aplicacao.aplicar_no_jogo(_jogo(inis=[str(existente), str(tmp_path / "sumiu.ini")])) is False
    assert existente.read_bytes() == antes


def test_aplicar_sem_valores_nao_toca_o_disco(schema, tmp_path):
    existente = _ini(tmp_path)
    antes, mtime = existente.read_bytes(), existente.stat().st_mtime_ns
    assert aplicacao.aplicar_no_jogo(_jogo(inis=[str(existente)])) is True
    assert (existente.read_bytes(), existente.stat().st_mtime_ns) == (antes, mtime)


def test_aplicar_somente_leitura_nao_levanta(schema, tmp_path, caplog):
    schema.set_string("nome-do-jogador", "Ana")
    bloqueado, livre = _ini(tmp_path / "a"), _ini(tmp_path / "b")
    original = bloqueado.read_bytes()
    os.chmod(bloqueado, stat.S_IREAD)
    try:
        assert aplicacao.aplicar_no_jogo(_jogo(inis=[str(bloqueado), str(livre)])) is True
    finally:
        os.chmod(bloqueado, stat.S_IWRITE | stat.S_IREAD)
    assert b"UserName=Ana" in livre.read_bytes()
    assert bloqueado.read_bytes() == original
    assert [r.levelname for r in caplog.records].count("WARNING") == 1


def test_modelo_do_language_changer_com_marcador_so_muda_o_nome(schema, tmp_path):
    schema.set_string("nome-do-jogador", "Ana")
    schema.set_string("idioma-do-jogador", "german")
    (tmp_path / "language.changer.ini").write_text("LanguageFileTemplate=steam_emu_\n")
    modelo = _ini(tmp_path, "steam_emu_x.ini", "[Settings]\nUserName=Velho\nLanguage=&LANG&\n")
    aplicacao.aplicar_no_jogo(_jogo(inis=[str(modelo)]))
    dados = modelo.read_bytes()
    assert b"UserName=Ana" in dados and b"Language=&LANG&" in dados


def test_atualizar_inis_grava_lista_e_devolve_appid(tmp_path):
    exe = tmp_path / "Jogo" / "x.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    ini_ = _ini(exe.parent, texto="[Settings]\nAppId=620\n")
    jogo = _jogo(executable=str(exe))
    assert aplicacao.atualizar_inis(jogo, []) == "620"
    assert jogo.inis == [str(ini_)]
    jogo.executable = ""
    assert aplicacao.atualizar_inis(jogo, []) is None and jogo.inis == []


def test_adotar_appid(tmp_path):
    jogo = _jogo(steam_appid="10", ludusavi_nome="X", saves_local_desconhecido_avisado=True)
    jogo.idiomas_steam = ["german"]
    assert aplicacao.adotar_appid(jogo, "620") is True
    assert jogo.idiomas_steam is None
    assert (jogo.steam_appid, jogo.ludusavi_nome, jogo.saves_local_desconhecido_avisado) == ("620", "", False)
    assert aplicacao.adotar_appid(jogo, "620") is False
    assert aplicacao.adotar_appid(jogo, None) is False
    jogo.appid_manual = True
    assert aplicacao.adotar_appid(jogo, "400") is False and jogo.steam_appid == "620"
