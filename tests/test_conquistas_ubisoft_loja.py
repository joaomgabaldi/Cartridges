"""Qual jogo é da Ubisoft Connect, e qual é o productId dele."""

import pytest

from cartridges.conquistas.ubisoft import locais, loja
from tests.apoio_conquistas import criar


@pytest.mark.parametrize(
    ("executavel", "esperado"),
    [
        ('start "" "uplay://launch/65043/0"', "65043"),
        ("UPLAY://LAUNCH/274/0", "274"),
        ("uplay://launch/274", "274"),
        ("uplay://launch/", None),
        ("uplay://launch/12345678901/0", None),
        ("steam://rungameid/570", None),
        ("", None),
    ],
)
def test_de_url(executavel, esperado):
    assert loja.de_url(executavel) == esperado


def _registro(monkeypatch, instalacoes):
    monkeypatch.setattr(locais, "_do_registro", lambda: {p: str(c) for p, c in instalacoes.items()})


def test_url_vence_sem_olhar_o_registro(make_game, monkeypatch):
    monkeypatch.setattr(locais, "_do_registro", lambda: 1 / 0)
    assert loja.do_jogo(make_game(executable='start "" "uplay://launch/65043/0"')) == "65043"


def test_exe_dentro_da_pasta_de_instalacao(make_game, tmp_path, monkeypatch):
    exe = criar(tmp_path / "AC Black Flag" / "ACBlackFlag.exe")
    _registro(monkeypatch, {"65043": tmp_path / "AC BLACK FLAG"})
    assert loja.do_jogo(make_game(executable=f'"{exe}"')) == "65043"


def test_exe_numa_subpasta_e_a_pasta_mais_funda_vence(make_game, tmp_path, monkeypatch):
    exe = criar(tmp_path / "Ubi" / "Far Cry" / "bin" / "FarCry.exe")
    _registro(monkeypatch, {"1": tmp_path / "Ubi", "2010": tmp_path / "Ubi" / "Far Cry"})
    assert loja.do_jogo(make_game(executable=f'"{exe}"')) == "2010"


def test_pasta_de_nome_parecido_nao_conta(make_game, tmp_path, monkeypatch):
    exe = criar(tmp_path / "AC2" / "AC.exe")
    _registro(monkeypatch, {"65043": tmp_path / "AC"})
    assert loja.do_jogo(make_game(executable=f'"{exe}"')) is None


def test_raiz_do_disco_no_registro_nao_pega_todo_jogo(make_game, tmp_path, monkeypatch):
    exe = criar(tmp_path / "Jogo" / "Jogo.exe")
    monkeypatch.setattr(locais, "_do_registro", lambda: {"65043": tmp_path.anchor})
    assert loja.do_jogo(make_game(executable=f'"{exe}"')) is None


def test_sem_pasta_nem_url_nao_le_o_registro(make_game, monkeypatch):
    monkeypatch.setattr(locais, "_do_registro", lambda: 1 / 0)
    assert loja.do_jogo(make_game(executable="steam://rungameid/570")) is None
