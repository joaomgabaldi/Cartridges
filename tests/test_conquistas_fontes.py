"""A fonte de cada jogo: de onde vêm as conquistas, ou nenhuma (cartão oculto)."""

import pytest

from cartridges.conquistas import fontes, historico
from cartridges.conquistas.fontes import Fonte
from cartridges.conquistas.xbox import api, conta
from tests.apoio_conquistas import criar, pastas  # noqa: F401

_AUMID = 'start "" "shell:AppsFolder\\Microsoft.Cod_8wekyb3d8bbwe!Game"'


@pytest.fixture
def conectada(monkeypatch):
    monkeypatch.setattr(conta, "conectada", lambda: True)


@pytest.fixture
def desconectada(monkeypatch):
    monkeypatch.setattr(conta, "conectada", lambda: False)


def test_texto_ida_e_volta():
    assert Fonte.de_texto("xbox:123") == Fonte("xbox", "123")
    assert Fonte("steam", "570").texto == "steam:570"


@pytest.mark.parametrize("texto", [None, "", "xbox:", "epic:1", "steam:12a", "xbox", "xbox:1:2"])
def test_texto_estranho_e_none(texto):
    assert Fonte.de_texto(texto) is None


def test_xbox_pelo_aumid_com_conta(make_game, conectada, monkeypatch, pastas):  # noqa: F811
    monkeypatch.setattr(
        api, "titulo_local", lambda pfn, bases: "999" if pfn == "Microsoft.Cod_8wekyb3d8bbwe" else None
    )
    assert fontes.do_jogo(make_game(executable=_AUMID, steam_appid="1938090")) == Fonte("xbox", "999")


def test_xbox_sem_titulo_ainda_fica_pendente(make_game, conectada, monkeypatch, pastas):  # noqa: F811
    monkeypatch.setattr(api, "titulo_local", lambda *_a: None)
    assert fontes.do_jogo(make_game(executable=_AUMID)) == Fonte("xbox", "")


def test_xbox_sem_conta_e_nenhuma_mesmo_com_appid(make_game, desconectada, pastas):  # noqa: F811
    assert fontes.do_jogo(make_game(executable=_AUMID, steam_appid="1938090")) is None


def test_pacote_sem_xbox_live_segue_a_regra_da_steam(make_game, conectada, monkeypatch, pastas):  # noqa: F811
    monkeypatch.setattr(api, "titulo_local", lambda *_a: "")
    assert fontes.do_jogo(make_game(executable=_AUMID, steam_appid="570")) is None


def test_exe_com_microsoftgame_config_e_xbox(make_game, conectada, tmp_path, monkeypatch, pastas):  # noqa: F811
    exe = criar(tmp_path / "XboxGames" / "Jogo" / "Content" / "gamelaunchhelper.exe")
    criar(exe.parent / "MicrosoftGame.config", "<Game><TitleId>0000000A</TitleId></Game>")
    game = make_game(executable=f'"{exe}"')
    assert fontes.eh_do_xbox(game)
    assert fontes.do_jogo(game) == Fonte("xbox", "10")


def test_steam_pelo_atalho(make_game, pastas):  # noqa: F811
    assert fontes.do_jogo(make_game(executable="steam://rungameid/570", steam_appid="570")) == Fonte("steam", "570")


def test_steam_pelo_arquivo_do_emulador(make_game, pastas):  # noqa: F811
    criar(pastas.appdata / "GSE Saves" / "570" / "achievements.json", "{}")
    assert fontes.do_jogo(make_game(steam_appid="570")) == Fonte("steam", "570")


@pytest.mark.parametrize("sinal", sorted(fontes.SINAIS_DE_EMULADOR))
def test_steam_pelo_sinal_na_pasta(make_game, tmp_path, pastas, sinal):  # noqa: F811
    exe = criar(tmp_path / "Jogo" / "jogo.exe")
    if "." in sinal:
        criar(exe.parent / sinal.upper())
    else:
        (exe.parent / sinal).mkdir()
    assert fontes.do_jogo(make_game(executable=f'"{exe}"', steam_appid="570")) == Fonte("steam", "570")


def test_diablo_iv_pelo_launcher_e_nenhuma(make_game, tmp_path, pastas):  # noqa: F811
    exe = criar(tmp_path / "Diablo IV" / "Diablo IV Launcher.exe")
    assert fontes.do_jogo(make_game(executable=f'"{exe}"', steam_appid="2344520")) is None


def test_sem_appid_e_nenhuma(make_game, pastas):  # noqa: F811
    assert fontes.do_jogo(make_game()) is None


def test_erro_de_disco_e_nenhuma(make_game, monkeypatch, pastas):  # noqa: F811
    def quebra(*_a):
        raise OSError("disco")

    monkeypatch.setattr(fontes.arquivos, "arquivos_do_jogo", quebra)
    assert fontes.do_jogo(make_game(steam_appid="570")) is None


def test_gravada_e_ativa(make_game, monkeypatch):
    game = make_game()
    assert fontes.gravada(game) is None and not fontes.ativa(None)
    historico.registrar(game.game_id, [], fonte="xbox:7")
    monkeypatch.setattr(conta, "conectada", lambda: True)
    assert fontes.ativa(fontes.gravada(game))
    monkeypatch.setattr(conta, "conectada", lambda: False)
    assert not fontes.ativa(fontes.gravada(game))
    assert fontes.ativa(Fonte("steam", "570"))


def test_chave_do_catalogo():
    assert fontes.chave_do_catalogo(Fonte("steam", "570")) == "570"
    assert fontes.chave_do_catalogo(Fonte("xbox", "7")) == "xbox-7"
