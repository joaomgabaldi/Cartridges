"""O config do Ludusavi: puro, sem rodar o Ludusavi."""

import json
from pathlib import Path

from cartridges.saves import config
from cartridges.saves.config import JogoNoConfig


def jogo(nome="X", appid="123", executavel="C:/Jogos/X/x.exe", no_manifesto=True):
    return JogoNoConfig(nome, appid, executavel, no_manifesto)


def test_dezessete_pastas_de_emulador():
    pastas = config.pastas_de_emulador("3669870")
    assert len(pastas) == 17 and len(set(pastas)) == 17
    assert "<winPublic>/Documents/Steam/RUNE/3669870" in pastas
    assert "<winAppData>/GSE Saves/3669870" in pastas
    assert "<winLocalAppData>/SKIDROW/3669870" in pastas
    assert "<winDocuments>/Player/3669870" in pastas
    assert "<winProgramData>/Steam/dodi/3669870" in pastas
    assert not any("achievements" in p.lower() or "achiev" in p.lower() for p in pastas)
    assert all(p.endswith("3669870") for p in pastas)


def test_na_pasta_do_jogo(monkeypatch):
    monkeypatch.setattr(config.arquivos, "bases_do_jogo", lambda exe: [Path("C:/Jogos/X")])
    assert config.na_pasta_do_jogo("C:/Jogos/X/x.exe", "9") == [
        "C:/Jogos/X/steam_settings/9",
        "C:/Jogos/X/coldclient/steam_settings/9",
        "C:/Jogos/X/SteamData/user_stats.ini",
        "C:/Jogos/X/3DMGAME/*",
        "C:/Jogos/X/Profile/*",
    ]


def test_na_pasta_do_jogo_com_subida(monkeypatch):
    monkeypatch.setattr(
        config.arquivos, "bases_do_jogo", lambda exe: [Path("C:/Jogos/X/bin"), Path("C:/Jogos/X")]
    )
    caminhos = config.na_pasta_do_jogo("C:/Jogos/X/bin/x.exe", "9")
    assert "C:/Jogos/X/bin/steam_settings/9" in caminhos
    assert "C:/Jogos/X/steam_settings/9" in caminhos
    assert "C:/Jogos/X/Profile/*" in caminhos


def test_extend_quando_no_manifesto(monkeypatch):
    monkeypatch.setattr(config.arquivos, "bases_do_jogo", lambda exe: [Path("C:/Jogos/X")])
    cfg = config.montar([jogo("Control")], Path("C:/saves"), [])
    arquivos = config.pastas_de_emulador("123") + config.na_pasta_do_jogo("C:/Jogos/X/x.exe", "123")
    assert cfg["customGames"][0] == {"name": "Control", "integration": "extend", "files": arquivos}


def test_entrada_propria_fora_do_manifesto(monkeypatch):
    monkeypatch.setattr(config.arquivos, "bases_do_jogo", lambda exe: [Path("C:/Jogos/X")])
    cfg = config.montar([jogo("Meu Jogo", no_manifesto=False)], Path("C:/saves"), [])
    entrada = cfg["customGames"][0]
    assert entrada["integration"] == "override" and entrada["name"] == "Meu Jogo"
    assert entrada["files"][: 17] == config.pastas_de_emulador("123")


def test_sem_appid_sem_custom_game():
    assert config.montar([jogo(appid=None), jogo(appid="../x")], Path("C:/saves"), [])["customGames"] == []


def test_montar_campos_fixos():
    raizes = [("steam", Path("C:/Steam")), ("otherWindows", Path("D:/Jogos"))]
    cfg = config.montar([], Path("C:/saves"), raizes)
    pasta = str(Path("C:/saves"))
    assert cfg["backup"]["path"] == cfg["restore"]["path"] == pasta
    assert cfg["backup"]["format"]["chosen"] == "zip"
    assert cfg["backup"]["retention"] == {"full": 5, "differential": 0}
    assert cfg["release"]["check"] is False
    assert cfg["roots"] == [{"store": "steam", "path": str(Path("C:/Steam"))},
                            {"store": "otherWindows", "path": str(Path("D:/Jogos"))}]


def test_raizes_sem_repeticao(monkeypatch):
    monkeypatch.setattr(config.arquivos, "pasta_da_steam", lambda: None)
    monkeypatch.setattr(config.arquivos, "_valor_do_registro", lambda *a: None)
    jogos = [jogo("A", executavel="D:/Jogos/A/a.exe"), jogo("B", executavel="D:/Jogos/B/b.exe"),
             jogo("C", executavel="")]
    monkeypatch.setattr(
        config.arquivos, "bases_do_jogo", lambda exe: [Path(exe).parent] if exe else []
    )
    assert config.raizes(jogos) == [("otherWindows", Path("D:/Jogos"))]


def test_raizes_com_steam_e_ubisoft(monkeypatch, tmp_path):
    monkeypatch.setattr(config.arquivos, "pasta_da_steam", lambda: Path("C:/Steam"))
    monkeypatch.setattr(config.arquivos, "_valor_do_registro", lambda *a: "C:/Ubi/")
    assert config.raizes([]) == [("steam", Path("C:/Steam")), ("uplay", Path("C:/Ubi/"))]


def test_gravar_eh_json(tmp_path):
    cfg = config.montar([], Path("C:/saves"), [])
    config.gravar(cfg, tmp_path / "ludusavi")
    assert json.loads((tmp_path / "ludusavi" / "config.yaml").read_text(encoding="utf-8")) == cfg
