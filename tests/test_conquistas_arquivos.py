"""Onde cada emulador grava as conquistas de um jogo."""

import winreg

import pytest

from cartridges.conquistas import arquivos, formatos
from cartridges.conquistas.arquivos import ArquivoDeConquista
from tests.apoio_conquistas import criar, pastas  # noqa: F401


def test_acha_os_caminhos_fixos_do_appid(pastas):
    gse = criar(pastas.appdata / "GSE Saves" / "570" / "achievements.json")
    codex = criar(pastas.documentos_publicos / "Steam" / "CODEX" / "570" / "achievements.ini")
    criar(pastas.appdata / "GSE Saves" / "999" / "achievements.json")  # outro jogo
    assert arquivos.arquivos_do_jogo("570", "") == [
        ArquivoDeConquista(gse, formatos.GOLDBERG),
        ArquivoDeConquista(codex, formatos.PADRAO),
    ]


def test_goldberg_numa_subpasta_do_appid(pastas):
    aninhado = criar(
        pastas.appdata / "Goldberg SteamEmu Saves" / "570" / "perfil" / "achievements.json"
    )
    assert ArquivoDeConquista(aninhado, formatos.GOLDBERG) in arquivos.arquivos_do_jogo("570", "")


def test_rld_e_skidrow(pastas):
    rld = criar(pastas.programdata / "Steam" / "dodi" / "570" / "stats" / "achievements.ini")
    skidrow = criar(
        pastas.localappdata / "SKIDROW" / "570" / "SteamEmu" / "UserStats" / "achiev.ini"
    )
    achados = arquivos.arquivos_do_jogo("570", "")
    assert ArquivoDeConquista(rld, formatos.RLD) in achados
    assert ArquivoDeConquista(skidrow, formatos.SKIDROW) in achados


def test_sobe_so_por_pastas_de_binarios(tmp_path, pastas):
    raiz = tmp_path / "Jogos" / "Jogo"
    exe = criar(raiz / "Binaries" / "Win64" / "jogo.exe")
    stats = criar(raiz / "SteamData" / "user_stats.ini")
    criar(tmp_path / "Jogos" / "SteamData" / "user_stats.ini")  # vizinho: não entra
    comando = f'"{exe}"'

    bases = arquivos.bases_do_jogo(comando)
    assert bases[0].name == "Win64"
    assert bases[1:] == [bases[0].parent, bases[0].parent.parent]

    achados = arquivos.arquivos_do_jogo("570", comando)
    assert [a.formato for a in achados] == [formatos.USERSTATS]
    assert achados[0].caminho.samefile(stats)


def test_pastas_de_perfil_do_3dm_e_do_ali213(tmp_path, pastas):
    raiz = tmp_path / "Jogo"
    exe = criar(raiz / "jogo.exe")
    tres = criar(raiz / "3DMGAME" / "perfil1" / "stats" / "achievements.ini")
    ali = criar(raiz / "Profile" / "fulano" / "Stats" / "Achievements.Bin")
    local = criar(raiz / "steam_settings" / "570" / "achievements.json")
    achados = {(a.caminho.name, a.formato) for a in arquivos.arquivos_do_jogo("570", f'"{exe}"')}
    assert (tres.name, formatos.TRES_DM) in achados
    assert (ali.name, formatos.ALI213) in achados
    assert (local.name, formatos.GOLDBERG) in achados


def test_jogo_sem_pasta_so_usa_os_caminhos_fixos(pastas):
    gse = criar(pastas.appdata / "GSE Saves" / "570" / "achievements.json")
    for comando in ("", "steam://rungameid/570", '"C:\\naoexiste\\jogo.exe"'):
        assert arquivos.bases_do_jogo(comando) == []
        assert arquivos.arquivos_do_jogo("570", comando) == [
            ArquivoDeConquista(gse, formatos.GOLDBERG)
        ]


def test_cache_da_steam_so_nos_jogos_da_steam(tmp_path, pastas, monkeypatch):
    steam = tmp_path / "Steam"
    cache = criar(steam / "userdata" / "123" / "config" / "librarycache" / "570.json")
    monkeypatch.setattr(arquivos, "pasta_da_steam", lambda: steam)
    exe = criar(tmp_path / "Jogo" / "jogo.exe")

    assert arquivos.arquivos_do_jogo("570", "steam://rungameid/570") == [
        ArquivoDeConquista(cache, formatos.STEAM)
    ]
    assert arquivos.arquivos_do_jogo("570", f'"{exe}"') == []


def _registro(monkeypatch, valores):
    """``valores``: {(raiz, nome_do_valor): texto}."""
    monkeypatch.setattr(
        arquivos, "_valor_do_registro", lambda raiz, _caminho, nome: valores.get((raiz, nome))
    )


def test_pasta_da_steam_pelo_registro_do_usuario(tmp_path, monkeypatch):
    steam = tmp_path / "Onde Quiser" / "Steam"
    steam.mkdir(parents=True)
    _registro(monkeypatch, {(winreg.HKEY_CURRENT_USER, "SteamPath"): str(steam).replace("\\", "/")})
    assert arquivos.pasta_da_steam() == steam


def test_pasta_da_steam_pela_chave_da_maquina(tmp_path, monkeypatch):
    steam = tmp_path / "D" / "Steam"
    steam.mkdir(parents=True)
    _registro(
        monkeypatch,
        {
            (winreg.HKEY_CURRENT_USER, "SteamPath"): str(tmp_path / "nao_existe"),
            (winreg.HKEY_LOCAL_MACHINE, "InstallPath"): str(steam),
        },
    )
    assert arquivos.pasta_da_steam() == steam


def test_sem_steam_no_registro():
    assert arquivos.pasta_da_steam() is None


def _steam_com_contas(tmp_path, monkeypatch, *contas):
    steam = tmp_path / "Steam"
    for conta in contas:
        (steam / "userdata" / conta).mkdir(parents=True)
    (steam / "appcache" / "stats").mkdir(parents=True)
    monkeypatch.setattr(arquivos, "pasta_da_steam", lambda: steam)
    return steam


def test_arquivos_da_steam_por_conta(tmp_path, pastas, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456", "anonymous")
    stats = steam / "appcache" / "stats"
    stats_123 = criar(stats / "UserGameStats_123_570.bin")
    stats_456 = criar(stats / "UserGameStats_456_570.bin")
    criar(stats / "UserGameStats_anonymous_570.bin")
    cache_123 = criar(steam / "userdata" / "123" / "config" / "librarycache" / "570.json")
    criar(steam / "userdata" / "anonymous" / "config" / "librarycache" / "570.json")
    assert arquivos.arquivos_do_jogo("570", "steam://rungameid/570") == [
        arquivos.ArquivoDeConquista(stats_123, formatos.STEAM_STATS),
        arquivos.ArquivoDeConquista(cache_123, formatos.STEAM),
        arquivos.ArquivoDeConquista(stats_456, formatos.STEAM_STATS),
    ]


def test_jogo_fora_da_steam_nao_recebe_os_arquivos_da_conta(tmp_path, pastas, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123")
    criar(steam / "appcache" / "stats" / "UserGameStats_123_570.bin")
    assert arquivos.arquivos_do_jogo("570", '"C:\\Jogos\\x.exe"') == []
    assert arquivos.da_steam_esperados("570", '"C:\\Jogos\\x.exe"') == []


def test_da_steam_esperados_inclui_os_que_ainda_nao_existem(tmp_path, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    stats = steam / "appcache" / "stats"
    assert arquivos.da_steam_esperados("570", "steam://rungameid/570") == [
        arquivos.ArquivoDeConquista(stats / "UserGameStats_123_570.bin", formatos.STEAM_STATS),
        arquivos.ArquivoDeConquista(stats / "UserGameStats_456_570.bin", formatos.STEAM_STATS),
    ]
    assert arquivos.da_steam_esperados("..\\x", "steam://rungameid/570") == []


def test_da_steam_esperados_sem_steam():
    assert arquivos.da_steam_esperados("570", "steam://rungameid/570") == []


@pytest.mark.parametrize("appid", ["", "..", "../570", "57 0", "abc", "²", "٣"])
def test_appid_que_nao_e_numero_nao_vira_caminho(pastas, appid):
    """O appID vira pedaço de caminho: `..` escaparia da pasta do emulador."""
    criar(pastas.appdata / "achievements.json")  # onde `GSE Saves\..` apontaria
    criar(pastas.appdata / "GSE Saves" / "570" / "achievements.json")
    assert arquivos.arquivos_do_jogo(appid, "") == []


def test_eh_jogo_da_steam():
    assert arquivos.eh_jogo_da_steam("steam://rungameid/570")
    assert not arquivos.eh_jogo_da_steam('"C:\\Jogos\\x.exe"')
    assert not arquivos.eh_jogo_da_steam("")
