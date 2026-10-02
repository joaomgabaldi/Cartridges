"""Onde cada emulador grava as conquistas de um jogo."""

import winreg

import pytest

from cartridges.conquistas import arquivos, formatos
from cartridges.conquistas.arquivos import ArquivoDeConquista
from tests.apoio_conquistas import criar, pastas  # noqa: F401

# A fixture autouse de `conftest.py` troca o leitor por um que devolve None.
_INTEIRO_REAL = arquivos._inteiro_do_registro


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


def test_pasta_do_usuario_vence_a_da_maquina_quando_as_duas_existem(tmp_path, monkeypatch):
    do_usuario = tmp_path / "Usuario" / "Steam"
    da_maquina = tmp_path / "Maquina" / "Steam"
    do_usuario.mkdir(parents=True)
    da_maquina.mkdir(parents=True)
    _registro(
        monkeypatch,
        {
            (winreg.HKEY_CURRENT_USER, "SteamPath"): str(do_usuario),
            (winreg.HKEY_LOCAL_MACHINE, "InstallPath"): str(da_maquina),
        },
    )
    assert arquivos.pasta_da_steam() == do_usuario


def test_valor_relativo_do_registro_e_ignorado(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "Steam").mkdir()  # existiria, se "Steam" valesse a partir da pasta atual
    _registro(monkeypatch, {(winreg.HKEY_CURRENT_USER, "SteamPath"): "Steam"})
    assert arquivos.pasta_da_steam() is None
    absoluta = tmp_path / "D" / "Steam"
    absoluta.mkdir(parents=True)
    _registro(
        monkeypatch,
        {
            (winreg.HKEY_CURRENT_USER, "SteamPath"): "Steam",
            (winreg.HKEY_LOCAL_MACHINE, "InstallPath"): str(absoluta),
        },
    )
    assert arquivos.pasta_da_steam() == absoluta


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


# --- a conta Steam do usuário: a conectada, a última que entrou, ou todas ---

_BASE_STEAMID64 = 76561197960265728


def _conta_ativa(monkeypatch, conta):
    """O ``ActiveUser`` do registro (0 com a Steam fechada, None sem a chave)."""
    chamadas = []

    def inteiro(raiz, caminho, nome):
        chamadas.append((raiz, caminho, nome))
        return conta

    monkeypatch.setattr(arquivos, "_inteiro_do_registro", inteiro)
    return chamadas


def _loginusers(steam, *usuarios):
    """``usuarios``: (conta, mais_recente, timestamp); o arquivo traz o steamid64."""
    blocos = []
    for conta, recente, carimbo in usuarios:
        campos = f'\t\t"AccountName"\t\t"nome{conta}"\n\t\t"PersonaName"\t\t"Pessoa \\"{conta}\\""\n'
        if recente is not None:
            campos += f'\t\t"MostRecent"\t\t"{recente}"\n'
        if carimbo is not None:
            campos += f'\t\t"Timestamp"\t\t"{carimbo}"\n'
        blocos.append(f'\t"{int(conta) + _BASE_STEAMID64}"\n\t{{\n{campos}\t}}\n')
    destino = steam / "config" / "loginusers.vdf"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text('"users"\n{\n' + "".join(blocos) + "}\n", encoding="utf-8")
    return destino


def _caminhos_do_stats(arquivos_achados):
    return [a.caminho.name for a in arquivos_achados if a.formato == formatos.STEAM_STATS]


def test_conta_conectada_agora_vence(tmp_path, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    _loginusers(steam, ("123", 1, 100), ("456", 0, 50))
    chamadas = _conta_ativa(monkeypatch, 456)
    esperados = arquivos.da_steam_esperados("570", "steam://rungameid/570")
    assert [a.caminho.name for a in esperados] == ["UserGameStats_456_570.bin"]
    assert chamadas == [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess", "ActiveUser")
    ]


def test_arquivos_do_jogo_seguem_a_conta_conectada(tmp_path, pastas, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    stats = steam / "appcache" / "stats"
    criar(stats / "UserGameStats_123_570.bin")
    stats_456 = criar(stats / "UserGameStats_456_570.bin")
    cache_123 = criar(steam / "userdata" / "123" / "config" / "librarycache" / "570.json")
    cache_456 = criar(steam / "userdata" / "456" / "config" / "librarycache" / "570.json")
    _conta_ativa(monkeypatch, 456)
    assert arquivos.arquivos_do_jogo("570", "steam://rungameid/570") == [
        arquivos.ArquivoDeConquista(stats_456, formatos.STEAM_STATS),
        arquivos.ArquivoDeConquista(cache_456, formatos.STEAM),
    ]
    assert cache_123.exists()


def test_steam_fechada_usa_a_conta_mais_recente_do_loginusers(tmp_path, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    # A de maior Timestamp não é a marcada: o que vale é o MostRecent.
    _loginusers(steam, ("123", 1, 100), ("456", 0, 999))
    _conta_ativa(monkeypatch, 0)
    assert _caminhos_do_stats(arquivos.da_steam_esperados("570", "steam://rungameid/570")) == [
        "UserGameStats_123_570.bin"
    ]


def test_sem_most_recent_vale_o_maior_timestamp(tmp_path, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456", "789")
    _loginusers(steam, ("123", None, 100), ("456", 0, 900), ("789", None, 300))
    _conta_ativa(monkeypatch, None)
    assert _caminhos_do_stats(arquivos.da_steam_esperados("570", "steam://rungameid/570")) == [
        "UserGameStats_456_570.bin"
    ]


def test_conta_achada_sem_pasta_em_userdata_cai_para_todas(tmp_path, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    _loginusers(steam, ("999", 1, 100))
    _conta_ativa(monkeypatch, None)
    assert len(arquivos.da_steam_esperados("570", "steam://rungameid/570")) == 2
    _conta_ativa(monkeypatch, 888)  # a conectada também não tem pasta
    assert len(arquivos.da_steam_esperados("570", "steam://rungameid/570")) == 2


@pytest.mark.parametrize(
    "conteudo",
    [
        b"\x00\xff\xfe nao e vdf \x80",
        b'"users" { "7656119" ',  # cortado
        b'"users" } } {',
        b'"users" { "76561197960265851" { "MostRecent" "1" ',
        b"",
        # Válido (a conta 123), mas além de 1 MB: ilegível.
        b'"users" {' + b" " * (1024 * 1024) + b'"76561197960265851" { "MostRecent" "1" } }',
    ],
    ids=["binario", "cortado", "chaves_soltas", "sem_fechar", "vazio", "maior_que_1MB"],
)
def test_loginusers_ilegivel_cai_para_todas(tmp_path, monkeypatch, conteudo):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    (steam / "config").mkdir()
    (steam / "config" / "loginusers.vdf").write_bytes(conteudo)
    _conta_ativa(monkeypatch, None)
    assert len(arquivos.da_steam_esperados("570", "steam://rungameid/570")) == 2


def test_loginusers_com_steamid_estranho_cai_para_todas(tmp_path, monkeypatch):
    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    (steam / "config").mkdir()
    (steam / "config" / "loginusers.vdf").write_text(
        '"users" { "abc" { "MostRecent" "1" } "5" { "MostRecent" "1" } '
        '"76561197960265728" { "MostRecent" "1" } }',
        encoding="utf-8",
    )
    _conta_ativa(monkeypatch, None)
    assert len(arquivos.da_steam_esperados("570", "steam://rungameid/570")) == 2


def test_sem_loginusers_nem_conta_ativa_vale_todas(tmp_path, monkeypatch):
    _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    assert len(arquivos.da_steam_esperados("570", "steam://rungameid/570")) == 2


def test_nada_do_loginusers_vai_ao_log(tmp_path, monkeypatch, caplog):
    import logging  # noqa: PLC0415

    steam = _steam_com_contas(tmp_path, monkeypatch, "123", "456")
    _loginusers(steam, ("123", 1, 100))
    (steam / "config" / "loginusers.vdf").write_text('"users" { "nome_secreto"', encoding="utf-8")
    _conta_ativa(monkeypatch, None)
    with caplog.at_level(logging.DEBUG):
        arquivos.da_steam_esperados("570", "steam://rungameid/570")
    assert "nome_secreto" not in caplog.text


def test_inteiro_do_registro_nunca_levanta(monkeypatch):
    # Chave que não existe: o OSError do winreg vira None.
    assert _INTEIRO_REAL(winreg.HKEY_CURRENT_USER, r"Software\Nada\Aqui", "x") is None


def test_inteiro_do_registro_so_aceita_inteiro(monkeypatch):
    class Chave:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    for valor, esperado in ((456, 456), ("456", None), (None, None)):
        monkeypatch.setattr(arquivos.winreg, "OpenKey", lambda *_a: Chave())
        monkeypatch.setattr(arquivos.winreg, "QueryValueEx", lambda *_a, v=valor: (v, winreg.REG_DWORD))
        assert _INTEIRO_REAL(winreg.HKEY_CURRENT_USER, "x", "y") == esperado


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
