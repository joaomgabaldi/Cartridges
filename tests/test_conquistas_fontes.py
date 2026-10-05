"""A fonte de cada jogo: de onde vêm as conquistas, ou nenhuma (cartão oculto)."""

import json

import pytest

from cartridges.conquistas import fontes, historico
from cartridges.conquistas.epic import api as epic_api, conta as epic_conta
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


@pytest.mark.parametrize(
    "texto",
    [None, "", "xbox:", "outra:1", "epic:", "epic:a b", "epic:" + "a" * 65, "steam:12a", "xbox", "xbox:1:2"],
)
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


_URL = 'start "" "com.epicgames.launcher://apps/{}?action=launch&silent=true"'
_NS = "4fe75bbc5a674f4f9b356b5c90567da5"


@pytest.fixture
def epic_conectada(monkeypatch):
    monkeypatch.setattr(epic_conta, "conectada", lambda: True)


def _manifest(pastas, app, ns, instalado=None):  # noqa: F811
    pasta = pastas.programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    dados = {"AppName": app, "CatalogNamespace": ns}
    if instalado is not None:
        dados["InstallLocation"] = str(instalado)
    criar(pasta / f"{app}.item", json.dumps(dados))


def test_texto_da_epic():
    assert Fonte.de_texto("epic:fn") == Fonte("epic", "fn")
    assert Fonte.de_texto(f"epic:{_NS}") == Fonte("epic", _NS)


def test_atalho_com_namespace(make_game, epic_conectada, pastas):  # noqa: F811
    game = make_game(executable=_URL.format(f"{_NS}%3Aitem%3ASugar"), steam_appid="570")
    assert fontes.da_epic(game) == (_NS, "Sugar")
    assert fontes.do_jogo(game) == Fonte("epic", _NS)


def test_epic_sem_conta_e_nenhuma_mesmo_com_appid(make_game, monkeypatch, pastas):  # noqa: F811
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    criar(pastas.appdata / "GSE Saves" / "570" / "achievements.json", "{}")  # sinal real da Steam
    game = make_game(executable=_URL.format(f"{_NS}%3Aitem%3ASugar"), steam_appid="570")
    assert fontes._da_steam(game) == Fonte("steam", "570")  # sem a regra da Epic, a Steam casaria
    assert fontes.do_jogo(game) is None


def test_atalho_so_com_appname_pelo_manifest(make_game, epic_conectada, pastas):  # noqa: F811
    _manifest(pastas, "Sugar", _NS)
    assert fontes.do_jogo(make_game(executable=_URL.format("sugar"))) == Fonte("epic", _NS)


def test_atalho_so_com_appname_pelo_cache_da_biblioteca(make_game, epic_conectada, monkeypatch, pastas):  # noqa: F811
    monkeypatch.setattr(epic_api, "namespace_local_do_app", lambda app: "fn" if app == "Fortnite" else None)
    assert fontes.do_jogo(make_game(executable=_URL.format("Fortnite"))) == Fonte("epic", "fn")


def test_atalho_so_com_appname_sem_manifest_fica_pendente(make_game, epic_conectada, pastas):  # noqa: F811
    assert fontes.do_jogo(make_game(executable=_URL.format("Sugar"))) == Fonte("epic", "")


def test_exe_dentro_da_pasta_de_um_manifest(make_game, epic_conectada, tmp_path, pastas):  # noqa: F811
    exe = criar(tmp_path / "FallGuys" / "RunFallGuys.exe")
    _manifest(pastas, "0a2d9f6403244d12969e11da6713137b", _NS, instalado=tmp_path / "FALLGUYS")
    game = make_game(executable=f'"{exe}"')
    assert fontes.eh_da_epic(game)
    assert fontes.do_jogo(game) == Fonte("epic", _NS)


def test_pasta_de_nome_parecido_nao_conta(make_game, epic_conectada, tmp_path, pastas):  # noqa: F811
    exe = criar(tmp_path / "FallGuys2" / "Jogo.exe")
    _manifest(pastas, "app", _NS, instalado=tmp_path / "FallGuys")
    assert not fontes.eh_da_epic(make_game(executable=f'"{exe}"'))


def test_manifest_ruim_e_ignorado(make_game, epic_conectada, tmp_path, pastas):  # noqa: F811
    exe = criar(tmp_path / "Jogo" / "Jogo.exe")
    pasta = pastas.programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    criar(pasta / "a.item", "não é json")
    criar(
        pasta / "b.item",
        json.dumps({"AppName": "x", "CatalogNamespace": "../x", "InstallLocation": str(tmp_path / "Jogo")}),
    )
    assert not fontes.eh_da_epic(make_game(executable=f'"{exe}"'))


def test_url_da_epic_e_so_texto(make_game):
    assert fontes.url_da_epic(make_game(executable=_URL.format("Sugar")))
    assert not fontes.url_da_epic(make_game(executable="steam://rungameid/570"))


def test_xbox_vem_antes_da_epic(make_game, conectada, epic_conectada, monkeypatch, pastas):  # noqa: F811
    monkeypatch.setattr(api, "titulo_local", lambda *_a: "999")
    monkeypatch.setattr(fontes, "da_epic", lambda _game: (_NS, "x"))
    assert fontes.do_jogo(make_game(executable=_AUMID)) == Fonte("xbox", "999")


def test_chave_do_catalogo_da_epic():
    assert fontes.chave_do_catalogo(Fonte("epic", "fn")) == "epic-fn"


def test_manifest_com_raiz_do_disco_nao_pega_todo_jogo(make_game, epic_conectada, tmp_path, pastas):  # noqa: F811
    exe = criar(tmp_path / "Jogo" / "Jogo.exe")
    _manifest(pastas, "app", _NS, instalado=tmp_path.anchor)
    assert not fontes.eh_da_epic(make_game(executable=f'"{exe}"'))


def test_manifest_com_pasta_relativa_e_ignorado(make_game, epic_conectada, tmp_path, monkeypatch, pastas):  # noqa: F811
    monkeypatch.chdir(tmp_path)  # sem o filtro, "Jogo" viraria `tmp_path/Jogo`
    exe = criar(tmp_path / "Jogo" / "Jogo.exe")
    _manifest(pastas, "app", _NS, instalado="Jogo")
    assert not fontes.eh_da_epic(make_game(executable=f'"{exe}"'))


def test_vence_o_manifest_da_pasta_mais_funda(make_game, epic_conectada, tmp_path, pastas):  # noqa: F811
    exe = criar(tmp_path / "Games" / "FallGuys" / "Game" / "Binaries" / "Win64" / "x.exe")
    _manifest(pastas, "AppA", "nsA", instalado=tmp_path / "Games")
    _manifest(pastas, "AppB", "nsB", instalado=tmp_path / "Games" / "FallGuys")
    assert fontes.do_jogo(make_game(executable=f'"{exe}"')) == Fonte("epic", "nsB")
