"""Onde cada emulador grava as conquistas de um jogo."""

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


def test_eh_jogo_da_steam():
    assert arquivos.eh_jogo_da_steam("steam://rungameid/570")
    assert not arquivos.eh_jogo_da_steam('"C:\\Jogos\\x.exe"')
    assert not arquivos.eh_jogo_da_steam("")
