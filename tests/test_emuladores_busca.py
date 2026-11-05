"""Achar a raiz do jogo e os .ini dos emuladores."""

import os
from pathlib import Path

import pytest

from cartridges.emuladores import busca


def _exe(pasta: Path, nome="x.exe") -> str:
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome
    caminho.write_bytes(b"MZ")
    return str(caminho)


def _arq(caminho: Path, texto="") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="latin-1")
    return caminho


def test_raiz_unreal_com_engine_sobe_alem_de_binaries(tmp_path):
    (tmp_path / "Root" / "ENGINE").mkdir(parents=True)
    exe = _exe(tmp_path / "Root" / "Proj" / "Binaries" / "Win64")
    assert busca.raiz_do_jogo(exe, []) == tmp_path / "Root"


def test_raiz_unreal_sem_engine_fica_no_projeto(tmp_path):
    exe = _exe(tmp_path / "Root" / "Proj" / "Binaries" / "Win64")
    assert busca.raiz_do_jogo(exe, []) == tmp_path / "Root" / "Proj"


def test_raiz_binaries_direto_fica_no_jogo(tmp_path):
    assert busca.raiz_do_jogo(_exe(tmp_path / "Jogo" / "Binaries"), []) == tmp_path / "Jogo"


def test_raiz_binaries_win64_sem_engine_fica_no_jogo(tmp_path):
    exe = _exe(tmp_path / "Jogo" / "Binaries" / "Win64")
    assert busca.raiz_do_jogo(exe, []) == tmp_path / "Jogo"


def test_raiz_bin_sobe_um_nivel(tmp_path):
    exe = _exe(tmp_path / "Jogo" / "bin")
    assert busca.raiz_do_jogo(exe, []) == tmp_path / "Jogo"


def test_raiz_exe_na_raiz(tmp_path):
    exe = _exe(tmp_path / "Jogo")
    assert busca.raiz_do_jogo(exe, [exe]) == tmp_path / "Jogo"


def test_raiz_com_exe_de_outro_jogo_nao_vale(tmp_path):
    exe = _exe(tmp_path / "Jogos")
    outro = _exe(tmp_path / "Jogos" / "Outro", "y.exe")
    assert busca.raiz_do_jogo(exe, [outro]) is None


def test_raiz_comando_de_loja_nao_tem_pasta():
    assert busca.raiz_do_jogo("steam://rungameid/440", []) is None


def test_raiz_de_unidade_nao_vale(tmp_path):
    drive = Path(tmp_path.anchor)
    assert busca._raiz_valida(drive) is None


def test_procurar_acha_inis_fundos(tmp_path):
    raiz = tmp_path / "Jogo"
    fundo = _arq(raiz / "a/b/c/d/e/steam_emu.ini")
    gse = _arq(raiz / "steam_settings/configs.user.ini")
    _arq(raiz / "leia.txt")
    assert busca.procurar(raiz) == sorted([fundo, gse])


def test_procurar_para_na_profundidade(tmp_path):
    raiz = tmp_path / "Jogo"
    dentro = _arq(raiz.joinpath(*"abcdefgh") / "codex.ini")  # pasta de nível 8
    _arq(raiz.joinpath(*"abcdefghi") / "codex.ini")  # nível 9
    assert busca.procurar(raiz) == [dentro]


def test_procurar_para_no_limite_de_entradas(tmp_path, monkeypatch):
    monkeypatch.setattr(busca, "_LIMITE_DE_ENTRADAS", 5)
    raiz = tmp_path / "Jogo"
    for i in range(10):
        _arq(raiz / f"f{i}.txt")
    _arq(raiz / "zz" / "codex.ini")
    assert busca.procurar(raiz) == []


def _link(origem: Path, alvo: Path):
    try:
        os.symlink(alvo, origem, target_is_directory=True)
        return
    except OSError:
        pass
    try:
        import _winapi

        _winapi.CreateJunction(str(alvo), str(origem))
    except (ImportError, AttributeError, OSError):
        pytest.skip("sem privilégio para criar link de diretório")


def test_procurar_nao_entra_em_link_para_a_propria_raiz(tmp_path):
    raiz = tmp_path / "Jogo"
    achado = _arq(raiz / "codex.ini")
    _link(raiz / "laco", raiz)
    assert busca.procurar(raiz) == [achado]


def test_procurar_nao_entra_em_juncao(tmp_path):
    raiz = tmp_path / "Jogo"
    raiz.mkdir()
    fora = tmp_path / "Fora"
    _arq(fora / "codex.ini")
    try:
        import _winapi

        _winapi.CreateJunction(str(fora), str(raiz / "juncao"))
    except (ImportError, AttributeError, OSError):
        pytest.skip("sem junção")
    assert busca.procurar(raiz) == []


def test_modelos_do_language_changer(tmp_path):
    raiz = tmp_path / "Jogo"
    _arq(raiz / "language.changer.ini", "; c\r\nLanguageFileTemplate = steam_emu_\r\n")
    modelo = _arq(raiz / "STEAM_EMU_brazilian.ini")
    _arq(raiz / "outro.ini")
    achados = busca.procurar(raiz)
    assert modelo in achados
    assert all(p.name != "outro.ini" for p in achados)
    assert busca.formato_de(modelo) == "steam_emu.ini"


@pytest.mark.parametrize("valor", ["..\\x", "a/b", "", "../.."])
def test_language_changer_rejeita_valor_com_caminho(tmp_path, valor):
    raiz = tmp_path / "Jogo"
    _arq(raiz / "language.changer.ini", f"LanguageFileTemplate={valor}\n")
    _arq(raiz / "qualquer.ini")
    assert busca.procurar(raiz) == []


def test_modelos_so_ini_e_bom_no_changer(tmp_path):
    raiz = tmp_path / "Jogo"
    raiz.mkdir()
    (raiz / "language.changer.ini").write_bytes(b"\xef\xbb\xbf# c\r\nLanguageFileTemplate=steam\r\n")
    modelo = _arq(raiz / "steam_pt.ini")
    _arq(raiz / "steam_api64.dll")
    _arq(raiz / "steam_notas.txt")
    assert busca.procurar(raiz) == [modelo]


def test_formato_de_comum(tmp_path):
    assert busca.formato_de(tmp_path / "ALI213.ini") == "ali213.ini"


def _ini(caminho, appid):
    return _arq(caminho, f"[Settings]\nAppId={appid}\n")


def test_appid_ignora_480(tmp_path):
    assert busca.appid_dos([_ini(tmp_path / "steam_emu.ini", "480")]) is None


def test_appid_ini_discordantes(tmp_path):
    a = _ini(tmp_path / "a/steam_emu.ini", "111")
    b = _ini(tmp_path / "b/codex.ini", "222")
    assert busca.appid_dos([a, b]) is None


def test_appid_ini_vence_txt(tmp_path):
    a = _ini(tmp_path / "steam_emu.ini", "111")
    t = _arq(tmp_path / "steam_appid.txt", "222")
    assert busca.appid_dos([t, a]) == "111"


def test_appid_settings_vence_txt_solto(tmp_path):
    a = _arq(tmp_path / "steam_settings/steam_appid.txt", "111\n")
    t = _arq(tmp_path / "steam_appid.txt", "222")
    assert busca.appid_dos([t, a]) == "111"


def test_appid_nivel_so_com_480_cai_para_o_proximo(tmp_path):
    a = _ini(tmp_path / "steam_emu.ini", "480")
    t = _arq(tmp_path / "steam_appid.txt", "333")
    assert busca.appid_dos([a, t]) == "333"


def test_appid_modelo_nao_conta(tmp_path):
    m = _ini(tmp_path / "steam_emu_brazilian.ini", "999")
    assert busca.appid_dos([m]) is None


def test_procurar_lista_configs_user_ini_do_gse_que_falta(tmp_path):
    raiz = tmp_path / "Jogo"
    txt = _arq(raiz / "steam_settings/steam_appid.txt", "620")
    assert busca.procurar(raiz) == sorted([txt, raiz / "steam_settings/configs.user.ini"])


def test_raiz_e_a_pasta_do_desinstalador(tmp_path):
    _arq(tmp_path / "Jogo" / "unins000.exe")
    exe = _exe(tmp_path / "Jogo" / "Proj" / "Binaries" / "Win64")
    assert busca.raiz_do_jogo(exe, []) == tmp_path / "Jogo"


def test_desinstalador_na_pasta_do_exe(tmp_path):
    _arq(tmp_path / "Jogo" / "bin" / "UNINS001.EXE")
    exe = _exe(tmp_path / "Jogo" / "bin")
    assert busca.raiz_do_jogo(exe, []) == tmp_path / "Jogo" / "bin"


def test_desinstalador_com_outro_jogo_dentro_nao_vale(tmp_path):
    _arq(tmp_path / "Pacote" / "unins000.exe")
    exe = _exe(tmp_path / "Pacote" / "A")
    outro = _exe(tmp_path / "Pacote" / "B")
    assert busca.raiz_do_jogo(exe, [outro]) is None


@pytest.mark.parametrize(
    "comando",
    [
        "steam://rungameid/440",
        "com.epicgames.launcher://apps/x%3Ay%3AZ?action=launch",
        "uplay://launch/635/0",
        "goggalaxy://openGameView/1207658924",
        "\"itch://games/123\"",
        r'"C:\Program Files (x86)\Steam\steam.exe" -applaunch 440',
        r"C:\Program Files (x86)\Steam\steam.exe -applaunch 440",
        r"shell:AppsFolder\Microsoft.Halo_8wekyb3d8bbwe!App",
    ],
)
def test_jogo_de_loja_nao_procura(comando):
    assert busca.eh_de_loja(comando) is True
    assert busca.raiz_do_jogo(comando, []) is None


def test_exe_comum_nao_e_de_loja(tmp_path):
    exe = _exe(tmp_path / "Jogo")
    assert busca.eh_de_loja(exe) is False
    assert busca.eh_de_loja(f'"{exe}" -url https://exemplo.com') is False
    assert busca.eh_de_loja("http://exemplo.com/jogo") is False  # URI que não é de loja


def test_desinstalador_seis_pastas_acima(tmp_path):
    _arq(tmp_path / "Jogo" / "unins000.exe")
    exe = _exe(tmp_path / "Jogo" / "a" / "b" / "c" / "d" / "e" / "f")
    assert busca.raiz_do_jogo(exe, []) == tmp_path / "Jogo"
