# test_auditoria_0923_backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auditoria de 23/09: backup (A1, B1, B6, M1, M2, B8, B11)."""

import json
import zipfile
from types import SimpleNamespace

import pytest

from cartridges import shared
from cartridges.utils import backup, session_log
from tests.test_backup import settings  # noqa: F401 - reaproveitado como fixture


def _zip(caminho, jogos, settings=None):
    manifesto = {"version": backup.VERSAO, "settings": settings or {}, "state": {}, "jogos": jogos}
    with zipfile.ZipFile(caminho, "w") as arquivo:
        arquivo.writestr("backup.json", json.dumps(manifesto))
    return caminho


def test_a1_entrada_zerado_casa_so_com_a_tumba_zerada(store, make_game, tmp_path, settings):
    zerado = make_game(game_id="a", removed=True, status="beaten", steam_appid="9")
    comum = make_game(game_id="b", removed=True, status="", steam_appid="9")
    for g in (zerado, comum):
        store.add_game(g, {}, run_pipeline=False)
    chave = backup._hash_identidade("steam:9")
    caminho = _zip(tmp_path / "b.zip", {chave: {
        "zerado": True, "status": "beaten", "playtime": 100,
        "sessoes": [{"end": 1_700_000_000, "seconds": 100}],
    }})
    backup.restaurar(caminho)
    assert zerado.playtime == 100
    assert comum.status == "" and comum.playtime == 0
    assert session_log.load("b") == []


def test_a1_entrada_zerado_casa_com_tumba_comum_unica(store, make_game, tmp_path, settings):
    """Sem tumba zerada da mesma identidade, uma tumba comum única recebe a
    entrada — só quando é a única do grupo."""
    comum = make_game(game_id="b", removed=True, status="", steam_appid="9")
    store.add_game(comum, {}, run_pipeline=False)
    chave = backup._hash_identidade("steam:9")
    caminho = _zip(tmp_path / "b.zip", {chave: {"zerado": True, "status": "beaten", "playtime": 100}})

    resultado = backup.restaurar(caminho)

    assert resultado.casados == 1
    assert comum.playtime == 100


def test_a1_entrada_zerado_com_duas_tumbas_comuns_fica_ambigua(store, make_game, tmp_path, settings):
    um = make_game(game_id="b", removed=True, status="", name="Jogo")
    outro = make_game(game_id="c", removed=True, status="", name="Jogo")
    for g in (um, outro):
        store.add_game(g, {}, run_pipeline=False)
    chave = backup._hash_identidade("nome:jogo")
    caminho = _zip(tmp_path / "b.zip", {chave: {
        "zerado": True, "status": "beaten", "playtime": 100, "identidade_exibicao": "Jogo",
    }})

    resultado = backup.restaurar(caminho)

    assert resultado.casados == 0
    assert resultado.ambiguos == ["Jogo"]
    assert um.playtime == 0 and outro.playtime == 0


def test_a1_varios_zerados_da_mesma_identidade_aplica_so_no_mais_recente(
    store, make_game, tmp_path, settings
):
    """Duas tumbas zeradas da mesma identidade: a entrada só toca a jogada por
    último (espelho de `exportar`, que também colapsa nisso)."""
    antigo = make_game(
        game_id="a", removed=True, status="beaten", steam_appid="9",
        last_played=100, playtime=10,
    )
    recente = make_game(
        game_id="b", removed=True, status="beaten", steam_appid="9",
        last_played=200, playtime=20,
    )
    for g in (antigo, recente):
        store.add_game(g, {}, run_pipeline=False)
    chave = backup._hash_identidade("steam:9")
    caminho = _zip(tmp_path / "b.zip", {chave: {"zerado": True, "status": "beaten", "playtime": 999}})

    resultado = backup.restaurar(caminho)

    assert resultado.casados == 1
    assert resultado.ambiguos == []
    assert recente.playtime == 999
    assert antigo.playtime == 10


def test_b1_entrada_que_nao_e_objeto_invalida_o_backup(tmp_path):
    caminho = _zip(tmp_path / "b.zip", {"0123456789abcdef": "x"})
    with pytest.raises(ValueError):
        backup.validar(caminho)


def test_b1_sessoes_que_nao_sao_lista_invalidam(tmp_path):
    caminho = _zip(tmp_path / "b.zip", {"0123456789abcdef": {"sessoes": 7}})
    with pytest.raises(ValueError):
        backup.validar(caminho)


def test_b6_ficha_de_zerado_descarta_inf_nan_e_capitulo_errado(store, tmp_path, flush_idle, settings):
    chave = backup._hash_identidade("nome:jogo x")
    caminho = _zip(tmp_path / "b.zip", {chave: {
        "zerado": True, "status": "beaten",
        "ficha": {"name": "Jogo X", "metacritic": float("inf"), "hltb_main": float("nan"),
                  "hltb_id": True,
                  "hltb_chapters": [{"hltb_main": "x"}]},
    }})
    backup.restaurar(caminho)
    flush_idle()
    criado = next(g for g in store if g.name == "Jogo X")
    assert criado.metacritic in (None, 0)
    assert criado.hltb_main in (None, 0)
    assert criado.hltb_id in (None, 0)
    assert not criado.hltb_chapters


def test_b6_ficha_de_zerado_mantem_capitulo_valido(store, tmp_path, flush_idle, settings):
    chave = backup._hash_identidade("nome:jogo y")
    caminho = _zip(tmp_path / "b.zip", {chave: {
        "zerado": True, "status": "beaten",
        "ficha": {
            "name": "Jogo Y",
            "hltb_chapters": [{"number": 1, "name": "Capítulo 1", "hltb_main": 3600}],
        },
    }})
    backup.restaurar(caminho)
    flush_idle()
    criado = next(g for g in store if g.name == "Jogo Y")
    assert criado.hltb_chapters == [{"number": 1, "name": "Capítulo 1", "hltb_main": 3600}]


def test_m1_cancelar_antes_de_aplicar_nao_toca_nos_jogos(store, make_game, tmp_path, settings):
    vivo = make_game(game_id="v", steam_appid="1")
    store.add_game(vivo, {}, run_pipeline=False)
    chave = backup._hash_identidade("steam:1")
    caminho = _zip(tmp_path / "b.zip", {chave: {"playtime": 999}})
    assert backup.restaurar(caminho, cancelado=lambda: True) is None
    assert vivo.playtime == 0


def test_m2_fita_que_sai_da_lista_e_devolvida(store, tmp_path, monkeypatch, settings):
    from cartridges.utils import session_fita  # noqa: PLC0415

    session_fita.gravar_fitas([
        session_fita.Fita("A", "a", "1", "k"), session_fita.Fita("C", "c", "3", "k"),
    ])
    devolvidas = []
    monkeypatch.setattr(session_fita, "devolver_removidas", lambda l: devolvidas.extend(l))
    caminho = tmp_path / "b.zip"
    _zip(caminho, {})
    with zipfile.ZipFile(caminho, "a") as arquivo:
        arquivo.writestr("fitas.json", json.dumps(
            {"fitas": [{"nome": "A", "id": "a", "ip": "1", "key": "k"}]}))
    backup.restaurar(caminho)
    assert [f.id for f in devolvidas] == ["c"]


def test_b11_pasta_de_atalhos_e_monitor_nao_viajam():
    """`FakeSchema` (autouse) não tem `props.settings_schema`, então
    `_chaves_do_app` não dá para testar direto aqui — testa o filtro puro que
    ela usa por baixo, com uma lista fixa em vez do schema de verdade."""
    chaves = ["shortcuts-location", "session-monitor", "gamepad", "sort-mode"]
    filtradas = backup._filtrar_chaves(chaves)
    assert "shortcuts-location" not in filtradas
    assert "session-monitor" not in filtradas
    assert filtradas == ["gamepad", "sort-mode"]


def test_b8_varredura_forcada_usa_only_missing_sem_ligacao(store, make_game, monkeypatch):
    from cartridges.store.managers.steam_api_manager import SteamAPIManager  # noqa: PLC0415

    chamadas = []

    class Gerente:
        def run(self, jogo, dados):
            chamadas.append(dados)

    store.managers[SteamAPIManager] = Gerente()
    backup._forcar_appids([make_game(game_id="x")], None, None)
    assert chamadas == [{"only_missing": True, "sem_ligacao": True}]


def test_m3_export_devolve_as_colisoes(store, make_game, tmp_path):
    for game_id in ("s1", "s2"):
        store.add_game(make_game(game_id=game_id, name="Dota", steam_appid="570"), {},
                       run_pipeline=False)
    excluidos = backup.exportar(tmp_path / "b.zip", {"settings": {}, "state": {}})
    assert excluidos == ["Dota"]


def test_b4_teto_total_descomprimido(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "_TAMANHO_MAXIMO_TOTAL", 10)
    caminho = _zip(tmp_path / "b.zip", {})
    with pytest.raises(ValueError):
        backup.validar(caminho)


def test_b2_oserror_num_jogo_nao_aborta_os_outros(store, make_game, tmp_path, monkeypatch, settings):
    from cartridges.utils import save_cover  # noqa: PLC0415

    a = make_game(game_id="a", steam_appid="1")
    b = make_game(game_id="b", steam_appid="2")
    for g in (a, b):
        store.add_game(g, {}, run_pipeline=False)
    ha, hb = backup._hash_identidade("steam:1"), backup._hash_identidade("steam:2")
    caminho = _zip(tmp_path / "b.zip", {ha: {"playtime": 1}, hb: {"playtime": 2}})
    with zipfile.ZipFile(caminho, "a") as arquivo:
        arquivo.writestr(f"jogos/{ha}/capa.tiff", b"x")

    def explode(*_a):
        raise OSError("travado")

    monkeypatch.setattr(save_cover, "save_cover", explode)
    backup.restaurar(caminho)
    assert (a.playtime, b.playtime) == (1, 2)


def test_b7_nao_trocar_e_usar_titulo_viajam(store, make_game, tmp_path, monkeypatch, settings):
    from cartridges.utils import game_logo, session_wallpaper  # noqa: PLC0415

    jogo = make_game(game_id="j", steam_appid="3")
    store.add_game(jogo, {}, run_pipeline=False)
    monkeypatch.setattr(session_wallpaper, "escolha", lambda _g: "none")
    monkeypatch.setattr(game_logo, "logo_choice", lambda _g: "title")
    entrada = backup._entrada_do_jogo(jogo, [])
    assert entrada["wallpaper_escolha"] == "none"
    assert entrada["logo_escolha"] == "title"

    chamadas = []
    monkeypatch.setattr(session_wallpaper, "nao_trocar", lambda *a: chamadas.append("parede"))
    monkeypatch.setattr(game_logo, "use_title_instead", lambda *a: chamadas.append("logo"))
    caminho = _zip(tmp_path / "b.zip", {backup._hash_identidade("steam:3"): entrada})
    backup.restaurar(caminho)
    assert sorted(chamadas) == ["logo", "parede"]


def test_b9_entrada_steam_cai_para_o_nome(store, make_game, tmp_path, settings):
    """Uma entrada `steam:` que não casou tenta a identidade `nome:` do mesmo
    jogo (`identidade_nome`, gravada pelo export) — aqui o jogo local nunca
    teve appID, então a entrada só pode casar pelo nome."""
    jogo = make_game(game_id="n", name="Hades", steam_appid=None)
    store.add_game(jogo, {}, run_pipeline=False)
    entrada = {"playtime": 50, "identidade_nome": backup._hash_identidade("nome:hades")}
    caminho = _zip(
        tmp_path / "b.zip",
        {backup._hash_identidade("steam:1145360"): entrada},
        settings={"steam-metadata": False},
    )
    backup.restaurar(caminho)
    assert jogo.playtime == 50


def test_b9_entrada_nome_cai_para_o_appid_resolvido_depois(store, make_game, tmp_path, settings):
    """O inverso: backup feito sem appID (entrada `nome:`), jogo que ganhou
    appID depois — casa pela própria chave do hash em `grupos_por_nome`."""
    jogo = make_game(game_id="n", name="Hades", steam_appid="1145360")
    store.add_game(jogo, {}, run_pipeline=False)
    caminho = _zip(
        tmp_path / "b.zip",
        {backup._hash_identidade("nome:hades"): {"playtime": 30}},
        settings={"steam-metadata": False},
    )
    backup.restaurar(caminho)
    assert jogo.playtime == 30


def test_b9_entrada_direta_nao_e_roubada_pelo_fallback_de_nome(store, make_game, tmp_path, settings):
    """Achado da revisão: um jogo com entrada própria no backup (a identidade
    real dele é uma chave do manifesto) nunca pode virar reserva de OUTRA
    entrada — a entrada órfã não pode roubar o dado que já tem dono certo."""
    a = make_game(game_id="a", name="Dota 2", steam_appid="570")
    store.add_game(a, {}, run_pipeline=False)
    direta = backup._hash_identidade("steam:570")
    orfa = backup._hash_identidade("nome:dota 2")
    caminho = _zip(
        tmp_path / "b.zip",
        {direta: {"playtime": 999}, orfa: {"playtime": 111}},
        settings={"steam-metadata": False},
    )
    resultado = backup.restaurar(caminho)
    assert a.playtime == 999
    assert resultado.casados == 1


def test_b9_fallback_inverso_ambiguo_entra_em_ambiguos(store, make_game, tmp_path, settings):
    """A mesma regra de ambiguidade da reserva `identidade_nome` vale para o
    fallback inverso: mais de um jogo vivo com o mesmo nome não pode ser
    escolhido às cegas — entra em `ambiguos`, não é descartado em silêncio."""
    um = make_game(game_id="a", name="Jogo", steam_appid="1")
    outro = make_game(game_id="b", name="Jogo", steam_appid="2")
    for g in (um, outro):
        store.add_game(g, {}, run_pipeline=False)
    chave = backup._hash_identidade("nome:jogo")
    caminho = _zip(tmp_path / "b.zip", {chave: {"playtime": 50, "identidade_exibicao": "Jogo"}})

    resultado = backup.restaurar(caminho)

    assert resultado.casados == 0
    assert resultado.ambiguos == ["Jogo"]
    assert um.playtime == 0 and outro.playtime == 0


def test_b5_id_ocupado_na_hora_do_registro_nao_grava_nada(
    store, make_game, tmp_path, monkeypatch, settings
):
    ocupado = make_game(game_id="imported_1", source="imported")
    store.add_game(ocupado, {}, run_pipeline=False)
    monkeypatch.setattr(store, "proximo_id_importado", lambda: "imported_1")
    chave = backup._hash_identidade("nome:novo")
    caminho = _zip(
        tmp_path / "b.zip",
        {chave: {
            "zerado": True, "status": "beaten", "ficha": {"name": "Novo"},
            "sessoes": [{"end": 1_700_000_000, "seconds": 10}],
        }},
        settings={"steam-metadata": False},
    )
    with zipfile.ZipFile(caminho, "a") as arquivo:
        arquivo.writestr(f"jogos/{chave}/capa.tiff", b"x")
    resultado = backup.restaurar(caminho)
    assert resultado.casados == 0
    assert not (shared.covers_dir / "imported_1.tiff").exists()
    assert session_log.load("imported_1") == []


def test_b5_zerado_normal_ainda_e_criado_com_capa(store, tmp_path, flush_idle, settings):
    """Sem corrida nenhuma, o caminho feliz continua funcionando: o zerado é
    registrado e a capa chega ao disco, com o id reservado no registro."""
    chave = backup._hash_identidade("nome:jogo z")
    caminho = _zip(tmp_path / "b.zip", {chave: {
        "zerado": True, "status": "beaten", "ficha": {"name": "Jogo Z"},
    }})
    with zipfile.ZipFile(caminho, "a") as arquivo:
        arquivo.writestr(f"jogos/{chave}/capa.tiff", b"x")
    resultado = backup.restaurar(caminho)
    flush_idle()
    assert resultado.casados == 1
    criado = next(g for g in store if g.name == "Jogo Z")
    assert (shared.covers_dir / f"{criado.game_id}.tiff").exists()


def test_b10_preferencias_releem_depois_do_restore():
    from cartridges.preferences import CartridgesPreferences  # noqa: PLC0415

    chamadas = []
    prefs = SimpleNamespace(
        reler_do_schema=lambda: chamadas.append(1),
        add_toast=lambda _t: None,
        _show_ambiguity_alert=lambda _n: None,
    )
    toast = SimpleNamespace(dismiss=lambda: None)
    CartridgesPreferences._restore_done(prefs, toast, backup.ResultadoRestauracao(1, 1, []), None)
    assert chamadas == [1]


def test_b10_preferencias_releem_tambem_no_erro():
    """Achado 10: um erro depois de `validar` pode vir com as configurações já
    aplicadas por `restaurar()` — a tela não pode ficar com as linhas sem
    `bind` desatualizadas só porque o restante da restauração falhou."""
    from cartridges.preferences import CartridgesPreferences  # noqa: PLC0415

    chamadas = []
    prefs = SimpleNamespace(reler_do_schema=lambda: chamadas.append(1))
    toast = SimpleNamespace(dismiss=lambda: None)
    with pytest.MonkeyPatch().context() as monkeypatch:
        monkeypatch.setattr("cartridges.preferences.create_dialog", lambda *a, **k: None)
        CartridgesPreferences._restore_done(prefs, toast, None, "erro qualquer")
    assert chamadas == [1]


def test_b10_preferencias_releem_no_cancelamento():
    from cartridges.preferences import CartridgesPreferences  # noqa: PLC0415

    chamadas = []
    prefs = SimpleNamespace(reler_do_schema=lambda: chamadas.append(1), add_toast=lambda _t: None)
    toast = SimpleNamespace(dismiss=lambda: None)
    CartridgesPreferences._restore_done(prefs, toast, None, None)
    assert chamadas == [1]


def test_ligar_zerado_recusa_durante_a_restauracao(store, make_game, real_window, monkeypatch):
    """Achado 2: uma ligação de zerado por appID não pode fundir no meio de
    uma restauração de backup em andamento — o restore já casa zerados com
    jogos vivos por identidade, por conta própria."""
    from cartridges.utils.ligacao_zerado import ligar_zerado  # noqa: PLC0415

    zerado = make_game(game_id="z", removed=True, status="beaten", steam_appid="55")
    vivo = make_game(game_id="v", steam_appid="55")
    for g in (zerado, vivo):
        store.add_game(g, {}, run_pipeline=False)

    backup.RESTAURANDO.set()
    try:
        assert ligar_zerado(vivo) is False
    finally:
        backup.RESTAURANDO.clear()
    assert store.get("z") is not None


def test_salvar_e_atualizar_ignora_jogo_que_saiu_da_store(store, make_game):
    """Achado 2: entre o agendamento em thread de fundo e a execução na main,
    a store pode ter substituído/apagado o registro (Excluir, ligação de
    zerado). Gravar por cima ressuscitaria um jogo apagado."""
    jogo = make_game(game_id="g")
    store.add_game(jogo, {}, run_pipeline=False)
    store.excluir(jogo)  # some da store, como um Excluir concorrente faria

    salvou = []
    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setattr(jogo, "save", lambda: salvou.append(1))
        assert backup._salvar_e_atualizar(jogo) is False
    finally:
        monkeypatch.undo()
    assert salvou == []


def test_backup_invalido_e_subtipo_de_valueerror():
    assert issubclass(backup.BackupInvalido, ValueError)


def test_validar_levanta_backup_invalido(tmp_path):
    caminho = _zip(tmp_path / "b.zip", {"0123456789abcdef": "x"})
    with pytest.raises(backup.BackupInvalido):
        backup.validar(caminho)


def test_erro_depois_de_validar_nao_e_backup_invalido(store, make_game, tmp_path, monkeypatch, settings):
    """Achado 10: um `ValueError` que não vem de `validar` (um bug em outro
    passo da restauração) não pode ser confundido com "arquivo inválido" — a
    essa altura as configurações já podem ter sido aplicadas."""
    vivo = make_game(game_id="v", steam_appid="1")
    store.add_game(vivo, {}, run_pipeline=False)
    caminho = _zip(tmp_path / "b.zip", {})

    def explode(_manifesto):
        raise ValueError("bug qualquer, não é sobre o arquivo")

    monkeypatch.setattr(backup, "_aplicar_configuracoes_fora_da_main", explode)
    with pytest.raises(ValueError) as excinfo:
        backup.restaurar(caminho)
    assert not isinstance(excinfo.value, backup.BackupInvalido)
