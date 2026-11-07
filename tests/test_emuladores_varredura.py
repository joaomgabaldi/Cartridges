"""Varredura única dos .ini e reaplicação em massa do padrão."""

from pathlib import Path

import pytest

from kyron import shared
from kyron.emuladores import varredura
from kyron.jogo import Jogo
from kyron.utils import ligacao_zerado


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
    monkeypatch.setattr("kyron.metadata_refresh.get_metadata_refresh", lambda: falso)
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


def test_reaplicar_nova_cancela_a_anterior(store, monkeypatch):
    import threading  # noqa: PLC0415

    preso, solto = threading.Event(), threading.Event()
    vistos = []

    def um(jogo):
        vistos.append(jogo.game_id)
        if jogo.game_id == "a":
            preso.set()
            solto.wait(5)

    monkeypatch.setattr(varredura, "_reaplicar_um", um)
    jogos = [_jogo("x.exe", jid, inis=["a.ini"]) for jid in ("a", "b", "c")]
    primeira = varredura.reaplicar(jogos)
    assert preso.wait(5)
    primeiro_cancelar = varredura._cancelar_reaplicacao
    assert not primeiro_cancelar.is_set()
    segunda = varredura.reaplicar([])
    assert primeiro_cancelar.is_set()  # foi o `reaplicar` quem cancelou
    solto.set()
    primeira.join()
    segunda.join()
    assert vistos == ["a"]


def test_reaplicar_so_nome_processa_jogo_so_com_idioma_proprio(store, monkeypatch):
    vistos = []
    monkeypatch.setattr(varredura, "_reaplicar_um", vistos.append)
    jogo = _jogo("x.exe", inis=["a.ini"], idioma_proprio="french")
    varredura.reaplicar([jogo], ("nome",)).join()
    assert vistos == [jogo]


def test_varrer_erro_num_jogo_nao_para_a_varredura(store, tmp_path, monkeypatch, refresh):
    chamadas, ligados = refresh
    ruim = _jogo(_pasta(tmp_path, "A") / "j.exe", "shortcuts_1", steam_appid="10")
    bom = _jogo(_pasta(tmp_path, "B") / "j.exe", "shortcuts_2", steam_appid="10")
    store.add_game(ruim, {}, run_pipeline=False)
    store.add_game(bom, {}, run_pipeline=False)
    original = varredura.aplicacao.atualizar_inis

    def falha_no_primeiro(jogo, outros):
        if jogo is ruim:
            raise ValueError("boom")
        return original(jogo, outros)

    monkeypatch.setattr(varredura.aplicacao, "atualizar_inis", falha_no_primeiro)
    varredura.varrer([ruim, bom]).join()
    assert bom.steam_appid == "620"
    assert chamadas == [[bom]] and ligados == [bom]
    assert shared.schema.get_boolean("inis-varridos")


def test_varrer_nao_salva_jogo_que_saiu_da_store(store, tmp_path, monkeypatch, refresh):
    salvos = []
    monkeypatch.setattr(Jogo, "save", lambda self: salvos.append(self))
    fora = _jogo(_pasta(tmp_path) / "j.exe")  # nunca entrou na store
    varredura.varrer([fora]).join()
    assert fora.steam_appid == "620" and salvos == []


def test_procurar_jogo_adota_appid_busca_idiomas_e_despacha(store, tmp_path, monkeypatch, refresh, schema):
    chamadas, ligados = refresh
    schema.set_string("idioma-do-jogador", "german")
    pasta = _pasta(tmp_path)
    jogo = _jogo(pasta / "j.exe", steam_appid="10")
    store.add_game(jogo, {}, run_pipeline=False)
    monkeypatch.setattr(varredura, "_buscar_idiomas", lambda j: setattr(j, "idiomas_steam", ["german"]))
    assert varredura.procurar_jogo(jogo) == varredura.aplicacao.APLICADO
    assert jogo.steam_appid == "620" and jogo.inis == [str(pasta / "steam_emu.ini")]
    assert b"Language=german" in (pasta / "steam_emu.ini").read_bytes()
    assert chamadas == [[jogo]] and ligados == [jogo]


def test_abertura_busca_idiomas_que_faltam_e_reaplica(store, tmp_path, monkeypatch, schema):
    schema.set_string("idioma-do-jogador", "german")
    pa, pb = _pasta(tmp_path, "A"), _pasta(tmp_path, "B")
    falta = _jogo(pa / "j.exe", steam_appid="620", inis=[str(pa / "steam_emu.ini")])
    tem = _jogo(pb / "j.exe", "shortcuts_2", steam_appid="620", inis=[str(pb / "steam_emu.ini")], idiomas_steam=["french"])
    sem_ini = _jogo(pb / "j.exe", "shortcuts_3", steam_appid="620", inis=[])
    for j in (falta, tem, sem_ini):
        store.add_game(j, {}, run_pipeline=False)
    buscados = []
    monkeypatch.setattr(varredura, "_buscar_idiomas", lambda j: buscados.append(j) or setattr(j, "idiomas_steam", ["german"]))
    varredura.buscar_idiomas_que_faltam([falta, tem, sem_ini]).join()
    assert buscados == [falta]
    assert b"Language=german" in (pa / "steam_emu.ini").read_bytes()
    assert b"Language=english" in (pb / "steam_emu.ini").read_bytes()


@pytest.mark.parametrize("varridos", [False, True])
def test_ligar_ao_app_varre_uma_vez_ou_busca_os_idiomas(store, monkeypatch, schema, varridos):
    schema.set_boolean("inis-varridos", varridos)
    monkeypatch.setattr(varredura, "_espera", None)
    feitos = []
    monkeypatch.setattr(varredura, "varrer", lambda j: feitos.append("varrer"))
    monkeypatch.setattr(varredura, "buscar_idiomas_que_faltam", lambda j: feitos.append("idiomas"))
    varredura.ligar_ao_app()
    assert feitos == (["idiomas"] if varridos else ["varrer"])


def test_ligar_ao_app_liga_o_aviso_dos_jogos_ja_achados_uma_vez(store, tmp_path, monkeypatch, schema):
    schema.set_boolean("inis-varridos", True)
    monkeypatch.setattr(varredura, "_espera", None)
    monkeypatch.setattr(varredura, "buscar_idiomas_que_faltam", lambda j: None)
    consultas = []
    verificador = type("V", (), {"check_async": lambda _s: consultas.append(1)})()
    monkeypatch.setattr(shared, "aplicativo", type("A", (), {"verificador_de_atualizacoes": verificador})(), raising=False)
    achado = _jogo(_pasta(tmp_path) / "j.exe", inis=["x.ini"])
    sem_ini = _jogo(_pasta(tmp_path, "B") / "j.exe", "shortcuts_2", inis=[])
    store.add_game(achado, {}, run_pipeline=False)
    store.add_game(sem_ini, {}, run_pipeline=False)

    varredura.ligar_ao_app()
    assert achado.track_updates is True and sem_ini.track_updates is False
    assert consultas == [1]

    achado.track_updates = False  # o usuário desligou: a próxima abertura não religa
    monkeypatch.setattr(varredura, "_espera", None)
    varredura.ligar_ao_app()
    assert achado.track_updates is False
    assert consultas == [1]
