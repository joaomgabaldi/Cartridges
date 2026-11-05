"""Varredura única dos .ini e reaplicação em massa do padrão."""

from pathlib import Path

import pytest

from cartridges import shared
from cartridges.emuladores import varredura
from cartridges.jogo import Jogo
from cartridges.utils import ligacao_zerado


def _jogo(exe, jid="shortcuts_1", **campos) -> Jogo:
    dados = {"game_id": jid, "source": "shortcuts", "name": "J", "executable": str(exe), "added": 0}
    return Jogo({**dados, **campos})


def _pasta(tmp_path, nome="Jogo", appid="620") -> Path:
    pasta = tmp_path / nome
    pasta.mkdir()
    (pasta / "j.exe").write_bytes(b"")
    (pasta / "steam_emu.ini").write_bytes(f"[Settings]\nAppId={appid}\nUserName=Velho\nLanguage=english\n".encode())
    return pasta


@pytest.fixture(autouse=True)
def _sem_fila(monkeypatch):
    """Entrega direta (sem laço de eventos) e sem rede: os pedidos à principal viram chamadas."""
    monkeypatch.setattr(varredura, "na_thread_principal", lambda f, *a: f(*a))
    monkeypatch.setattr(varredura.tarefas, "comecar", lambda *a: type("T", (), {"atualizar": lambda *_: None, "terminar": lambda *_: None})())
    monkeypatch.setattr(Jogo, "save", lambda self: None)


@pytest.fixture
def refresh(monkeypatch):
    chamadas = []
    falso = type("R", (), {"start": lambda self, jogos: chamadas.append(list(jogos))})()
    monkeypatch.setattr("cartridges.metadata_refresh.get_metadata_refresh", lambda: falso)
    ligados = []
    monkeypatch.setattr(ligacao_zerado, "agendar", ligados.append)
    return chamadas, ligados


def test_varrer_troca_appid_manda_ao_refresh_e_marca(store, tmp_path, monkeypatch, refresh):
    chamadas, ligados = refresh
    jogo = _jogo(_pasta(tmp_path) / "j.exe", steam_appid="10", idiomas_steam=["english"])
    manual = _jogo(_pasta(tmp_path, "B") / "j.exe", "shortcuts_2", steam_appid="10", appid_manual=True)
    store.add_game(jogo, {}, run_pipeline=False)
    store.add_game(manual, {}, run_pipeline=False)
    varredura.varrer([jogo, manual]).join()
    assert jogo.steam_appid == "620"
    assert manual.steam_appid == "10"
    assert jogo.inis
    assert chamadas == [[jogo]] and ligados == [jogo]
    assert shared.schema.get_boolean("inis-varridos")


def test_varrer_sem_rede_segue_e_deixa_idiomas_none(store, tmp_path, refresh):
    jogo = _jogo(_pasta(tmp_path) / "j.exe")
    store.add_game(jogo, {}, run_pipeline=False)
    varredura.varrer([jogo]).join()  # `sem_rede` do conftest faz o fetch falhar
    assert jogo.steam_appid == "620" and jogo.idiomas_steam is None
    assert shared.schema.get_boolean("inis-varridos")


def test_varrer_pula_removidos(store, tmp_path, refresh):
    jogo = _jogo(_pasta(tmp_path) / "j.exe", removed=True)
    varredura.varrer([jogo]).join()
    assert jogo.inis is None


def test_reaplicar_pula_jogo_com_idioma_proprio(store, tmp_path, schema):
    schema.set_string("idioma-do-jogador", "german")
    pa, pb = _pasta(tmp_path, "A"), _pasta(tmp_path, "B")
    a = _jogo(pa / "j.exe", inis=[str(pa / "steam_emu.ini")], idioma_proprio="french")
    b = _jogo(pb / "j.exe", "shortcuts_2", inis=[str(pb / "steam_emu.ini")])
    varredura.reaplicar([a, b], ["idioma"]).join()
    assert b"Language=german" in (pb / "steam_emu.ini").read_bytes()
    assert b"Language=english" in (pa / "steam_emu.ini").read_bytes()


def test_reaplicar_nova_cancela_a_anterior(store, tmp_path, schema, monkeypatch):
    schema.set_string("nome-do-jogador", "Ana")
    vistos = []
    monkeypatch.setattr(varredura, "_reaplicar_um", lambda j: vistos.append(j))
    jogo = _jogo("x.exe", inis=["a.ini"])
    varredura.reaplicar([jogo]).join()
    assert vistos == [jogo]
    varredura._cancelar_reaplicacao.set()  # a seguinte marcaria isto
    antigo = varredura._cancelar_reaplicacao
    varredura.reaplicar([jogo]).join()
    assert antigo.is_set()
