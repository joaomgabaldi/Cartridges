"""Managers dos .ini no pipeline: busca (antes da Steam) e aplicação (depois)."""

from cartridges.jogo import Jogo
from cartridges.store.managers.aplicacao_dos_inis_manager import AplicacaoDosInisManager
from cartridges.store.managers.emulador_manager import EmuladorManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager, _keep_user_edits


def _jogo(executavel, **campos) -> Jogo:
    dados = {"game_id": "shortcuts_1", "source": "shortcuts", "name": "J", "executable": str(executavel), "added": 0}
    return Jogo({**dados, **campos})


def _montar(tmp_path):
    pasta = tmp_path / "Jogo"
    pasta.mkdir()
    (pasta / "j.exe").write_bytes(b"")
    (pasta / "steam_emu.ini").write_bytes(b"[Settings]\nAppId=620\nUserName=Velho\nLanguage=english\n")
    return pasta


def test_ordem_no_pipeline():
    assert EmuladorManager in SteamAPIManager.run_after
    assert SteamAPIManager in AplicacaoDosInisManager.run_after


def test_busca_poe_o_appid_nos_dados_adicionais(store, tmp_path):
    pasta = _montar(tmp_path)
    jogo = _jogo(pasta / "j.exe")
    dados = {}
    EmuladorManager().main(jogo, dados)
    assert dados["steam_appid"] == "620"
    assert jogo.steam_appid == "620"
    assert jogo.inis == [str(pasta / "steam_emu.ini")]


def test_appid_manual_nao_muda(store, tmp_path):
    jogo = _jogo(_montar(tmp_path) / "j.exe", steam_appid="10", appid_manual=True)
    dados = {}
    EmuladorManager().main(jogo, dados)
    assert "steam_appid" not in dados
    assert jogo.steam_appid == "10"


def test_removido_e_blacklisted_sao_pulados(store, tmp_path):
    exe = _montar(tmp_path) / "j.exe"
    for campos in ({"removed": True}, {"blacklisted": True}):
        jogo = _jogo(exe, **campos)
        EmuladorManager().main(jogo, {})
        assert jogo.inis is None


def test_aplicacao_grava_o_nome(store, tmp_path, schema):
    pasta = _montar(tmp_path)
    schema.set_string("nome-do-jogador", "Ana")
    jogo = _jogo(pasta / "j.exe")
    EmuladorManager().main(jogo, {})
    AplicacaoDosInisManager().main(jogo, {})
    assert b"UserName=Ana" in (pasta / "steam_emu.ini").read_bytes()


def test_aplicacao_sem_busca_previa_nao_grava(store, tmp_path, schema):
    pasta = _montar(tmp_path)
    schema.set_string("nome-do-jogador", "Ana")
    AplicacaoDosInisManager().main(_jogo(pasta / "j.exe"), {})
    assert b"UserName=Velho" in (pasta / "steam_emu.ini").read_bytes()


def test_idiomas_steam_sobrevive_ao_so_o_que_falta():
    jogo = _jogo("x.exe")
    dados = {"idiomas_steam": ["german"], "name": "Outro"}
    resultado = _keep_user_edits(jogo, dados, {"only_missing": True})
    assert resultado["idiomas_steam"] == ["german"]
