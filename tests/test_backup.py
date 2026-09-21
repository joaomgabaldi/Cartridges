# test_backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup completo (.zip): a biblioteca inteira e as configurações, por identidade.

O backup leva só a opinião do usuário sobre cada jogo (tempo, status, nota,
anotação, capa/logo/parede/fita escolhidos à mão) e as configurações do app —
nunca identidade nem metadado que o próprio app recarrega sozinho. `restaurar`
casa cada entrada do backup com um jogo já existente na biblioteca local pela
identidade portátil (`identidade`) e sobrescreve; nunca cria jogo, nunca apaga,
nunca mexe em quem não casou. O formato `.json` de versões antigas (que
mesclava só tempo/status/nota/anotação) não é mais aceito.
"""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from gi.repository import Gio

from cartridges import shared
from cartridges.utils import backup

_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# Backup completo (.zip)
# --------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path, monkeypatch):
    """GSettings de verdade, com backend em memória.

    O backup lê e grava GVariant, e é o tipo de cada chave no schema que
    decide o que um valor do arquivo vira — um dicionário no lugar dele não
    testaria nada disso.
    """
    schemas = tmp_path / "_schemas"
    schemas.mkdir()
    shutil.copy(_ROOT / "_build" / "data" / "page.kramo.Cartridges.gschema.xml", schemas)
    compiler = shutil.which("glib-compile-schemas") or (
        "C:/msys64/ucrt64/bin/glib-compile-schemas.exe"
    )
    subprocess.run([compiler, str(schemas)], check=True)
    source = Gio.SettingsSchemaSource.new_from_directory(str(schemas), None, False)
    memory = Gio.memory_settings_backend_new()
    main = Gio.Settings.new_full(source.lookup("page.kramo.Cartridges", False), memory, None)
    state = Gio.Settings.new_full(
        source.lookup("page.kramo.Cartridges.State", False), memory, None
    )
    monkeypatch.setattr(shared, "schema", main)
    monkeypatch.setattr(shared, "state_schema", state)
    return main, state


def test_an_old_json_backup_is_not_a_full_backup(tmp_path) -> None:
    old = tmp_path / "antigo.zip"
    with zipfile.ZipFile(old, "w") as archive:
        archive.writestr("backup.json", json.dumps({"version": 2, "games": {}}))
    with pytest.raises(ValueError):
        backup.validar(old)


def test_a_setting_the_schema_does_not_accept_falls_back_to_default(settings) -> None:
    """Um valor editado à mão com tipo errado, ou fora das opções do schema,
    volta ao padrão em vez de ser gravado; o resto do backup entra; a chave
    que o backup não tem também volta ao padrão."""
    main, state = settings
    main.set_uint("library-rows", 2)
    main.set_boolean("gamepad-rumble", False)
    main.set_boolean("gamepad", True)
    state.set_string("sort-mode", "a-z")
    backup.aplicar_configuracoes(
        {
            "settings": {"library-rows": "três", "sgdb": True, "gamepad-rumble": "sim"},
            "state": {"sort-mode": "inexistente"},
        }
    )
    assert main.get_uint("library-rows") == 0
    assert main.get_boolean("sgdb") is True
    assert main.get_boolean("gamepad-rumble") is True
    assert main.get_boolean("gamepad") is False
    assert state.get_string("sort-mode") == "last_played"


# --------------------------------------------------------------------------
# Identidade e agrupamento
# --------------------------------------------------------------------------


def test_identidade_prefere_o_appid_da_steam(store, make_game) -> None:
    jogo = make_game(steam_appid="367520", name="Hollow Knight")
    assert backup.identidade(jogo) == "steam:367520"


def test_identidade_cai_para_o_nome_limpo_sem_appid(store, make_game) -> None:
    jogo = make_game(name="Legacy (PC)")
    assert backup.identidade(jogo) == "nome:legacy"


def test_hash_da_identidade_e_estavel_e_curto(store) -> None:
    primeiro = backup._hash_identidade("steam:367520")
    segundo = backup._hash_identidade("steam:367520")
    assert primeiro == segundo
    assert len(primeiro) == 16
    assert backup._hash_identidade("nome:legacy") != primeiro


def test_agrupar_junta_dois_jogos_no_mesmo_appid(store, make_game) -> None:
    original = make_game(game_id="a", steam_appid="1", name="Jogo Steam")
    pirata = make_game(game_id="b", steam_appid="1", name="Jogo Pirata")
    grupos = backup._agrupar_por_identidade([original, pirata])

    chave = backup._hash_identidade("steam:1")
    tipo, alvos = grupos[chave]
    assert tipo == "steam"
    assert {jogo.game_id for jogo in alvos} == {"a", "b"}


def test_agrupar_junta_dois_jogos_no_mesmo_nome_sem_appid(store, make_game) -> None:
    um = make_game(game_id="a", name="Rush (PC)")
    outro = make_game(game_id="b", name="Rush™")
    grupos = backup._agrupar_por_identidade([um, outro])

    chave = backup._hash_identidade("nome:rush")
    tipo, alvos = grupos[chave]
    assert tipo == "nome"
    assert len(alvos) == 2


def test_agrupar_mantem_jogos_sem_colisao_separados(store, make_game) -> None:
    um = make_game(game_id="a", name="Celeste")
    outro = make_game(game_id="b", name="Hades")
    grupos = backup._agrupar_por_identidade([um, outro])
    assert len(grupos) == 2


# --------------------------------------------------------------------------
# Exportação por identidade
# --------------------------------------------------------------------------


def test_exportar_leva_so_campos_de_opiniao_por_identidade(
    store, make_game, settings, tmp_path
) -> None:
    jogo = make_game(
        game_id="a", steam_appid="367520", name="Hollow Knight",
        playtime=7200, status="beaten", rating=4, notes="Bom jogo",
        hidden=True, run_as_admin=True, track_process=True,
        process_executable="hk.exe", track_updates=True, last_played=123,
        # campos que NUNCA devem ir para o backup:
        executable="C:\\jogo\\hk.exe", source="shortcuts",
        developer="Team Cherry", steam_checked=99,
    )
    store.add_game(jogo, {})

    destino = tmp_path / "b.zip"
    backup.exportar(destino, backup.ler_configuracoes())

    manifesto = backup.validar(destino)
    chave = backup._hash_identidade("steam:367520")
    entrada = manifesto["jogos"][chave]

    assert entrada["playtime"] == 7200
    assert entrada["status"] == "beaten"
    assert entrada["rating"] == 4
    assert entrada["notes"] == "Bom jogo"
    assert entrada["hidden"] is True
    assert entrada["run_as_admin"] is True
    assert entrada["track_process"] is True
    assert entrada["process_executable"] == "hk.exe"
    assert entrada["track_updates"] is True
    assert entrada["last_played"] == 123
    assert entrada["identidade_exibicao"] == "367520"
    for campo_proibido in ("executable", "source", "developer", "steam_checked", "game_id"):
        assert campo_proibido not in entrada


def test_exportar_ignora_jogos_removidos(store, make_game, settings, tmp_path) -> None:
    tumba = make_game(game_id="a", name="Jogo Removido", removed=True)
    store.add_game(tumba, {})

    destino = tmp_path / "b.zip"
    backup.exportar(destino, backup.ler_configuracoes())
    manifesto = backup.validar(destino)
    assert manifesto["jogos"] == {}


def test_exportar_exclui_identidade_colidida_mesmo_com_appid(
    store, make_game, settings, tmp_path
) -> None:
    """Duas cópias locais do mesmo jogo: não dá pra saber de qual exportar a
    opinião, então nenhuma das duas entra no backup."""
    um = make_game(game_id="a", steam_appid="1", name="Jogo A", playtime=10)
    outro = make_game(game_id="b", steam_appid="1", name="Jogo B", playtime=99)
    store.add_game(um, {})
    store.add_game(outro, {})

    destino = tmp_path / "b.zip"
    backup.exportar(destino, backup.ler_configuracoes())
    manifesto = backup.validar(destino)
    assert manifesto["jogos"] == {}


def test_exportar_leva_capa_logo_parede_e_fita_quando_escolhidos(
    store, make_game, app_dirs, settings, tmp_path
) -> None:
    from cartridges.utils import game_logo, session_fita, session_wallpaper

    jogo = make_game(game_id="a", steam_appid="1", name="Jogo")
    store.add_game(jogo, {})

    (app_dirs.covers / "a.tiff").write_bytes(b"capa")
    origem_logo = tmp_path / "origem_logo.png"
    origem_logo.write_bytes(b"logo")
    game_logo.save_manual_logo("a", "Jogo", origem_logo)
    origem_parede = tmp_path / "origem_parede.jpg"
    origem_parede.write_bytes(b"parede")
    session_wallpaper.salvar_escolha(
        "a", "Jogo", origem_parede, session_wallpaper.Posicoes(0.3, 0.7)
    )
    session_fita.salvar_cor("a", "Jogo", session_fita.Cor(100, 500, 900))

    destino = tmp_path / "b.zip"
    backup.exportar(destino, backup.ler_configuracoes())

    chave = backup._hash_identidade("steam:1")
    with zipfile.ZipFile(destino) as arquivo:
        nomes = arquivo.namelist()
    assert f"jogos/{chave}/capa.tiff" in nomes
    assert any(nome.startswith(f"jogos/{chave}/logo.") for nome in nomes)
    assert any(nome.startswith(f"jogos/{chave}/wallpaper.") for nome in nomes)

    manifesto = backup.validar(destino)
    entrada = manifesto["jogos"][chave]
    assert entrada["wallpaper_posicao_retrato"] == 0.3
    assert entrada["wallpaper_posicao_paisagem"] == 0.7
    assert entrada["fita_matiz"] == 100
    assert entrada["fita_saturacao"] == 500
    assert entrada["fita_brilho"] == 900


def test_exportar_traduz_sessoes_para_identidade(
    store, make_game, app_dirs, settings, tmp_path
) -> None:
    from cartridges.utils import session_log

    jogo = make_game(game_id="a", steam_appid="1", name="Jogo")
    store.add_game(jogo, {})
    session_log.record("a", 3600, end=1_700_000_000)

    destino = tmp_path / "b.zip"
    backup.exportar(destino, backup.ler_configuracoes())
    manifesto = backup.validar(destino)

    chave = backup._hash_identidade("steam:1")
    assert manifesto["jogos"][chave]["sessoes"] == [{"end": 1_700_000_000, "seconds": 3600}]


# --------------------------------------------------------------------------
# Validação do novo formato
# --------------------------------------------------------------------------


def test_validar_aceita_um_backup_por_identidade(store, make_game, settings, tmp_path) -> None:
    jogo = make_game(game_id="a", steam_appid="1", name="Jogo")
    store.add_game(jogo, {})
    destino = tmp_path / "b.zip"
    backup.exportar(destino, backup.ler_configuracoes())
    manifesto = backup.validar(destino)
    assert manifesto["version"] == 4
    assert isinstance(manifesto["jogos"], dict)


def test_validar_recusa_a_versao_3_de_ontem(tmp_path) -> None:
    velho = tmp_path / "velho.zip"
    with zipfile.ZipFile(velho, "w") as arquivo:
        arquivo.writestr("backup.json", json.dumps({"version": 3, "settings": {}}))
    with pytest.raises(ValueError):
        backup.validar(velho)


def test_validar_recusa_entrada_fora_da_pasta_jogos(tmp_path) -> None:
    ruim = tmp_path / "ruim.zip"
    with zipfile.ZipFile(ruim, "w") as arquivo:
        arquivo.writestr(
            "backup.json", json.dumps({"version": 4, "settings": {}, "jogos": {}})
        )
        arquivo.writestr("jogos/../../fora.txt", "x")
    with pytest.raises(ValueError):
        backup.validar(ruim)


def test_validar_recusa_hash_com_formato_estranho(tmp_path) -> None:
    ruim = tmp_path / "ruim.zip"
    with zipfile.ZipFile(ruim, "w") as arquivo:
        arquivo.writestr(
            "backup.json", json.dumps({"version": 4, "settings": {}, "jogos": {}})
        )
        arquivo.writestr("jogos/nao-e-um-hash/capa.tiff", "x")
    with pytest.raises(ValueError):
        backup.validar(ruim)


def test_validar_recusa_extensao_fora_da_lista(tmp_path) -> None:
    ruim = tmp_path / "ruim.zip"
    hash_valido = backup._hash_identidade("steam:1")
    with zipfile.ZipFile(ruim, "w") as arquivo:
        arquivo.writestr(
            "backup.json", json.dumps({"version": 4, "settings": {}, "jogos": {}})
        )
        arquivo.writestr(f"jogos/{hash_valido}/capa.exe", "x")
    with pytest.raises(ValueError):
        backup.validar(ruim)


def _backup_com_um_jogo(
    tmp_path, *, appid=None, nome="Jogo", configuracoes=None, **campos
) -> tuple[Path, str]:
    """Monta um .zip válido com uma entrada só, sem passar pelo `exportar`
    (útil para testar `restaurar` isolado de `exportar`).

    ``configuracoes``: o bloco ``settings`` do manifesto. Vazio por padrão —
    o que ``aplicar_configuracoes`` não recebe explicitamente ela reseta para
    o padrão do schema (``steam-metadata`` é ``true`` por padrão), então um
    teste que precisa que a varredura forçada fique desligada tem de dizer
    isso aqui, não só ajustar o schema antes de chamar `restaurar`.
    """
    identidade_str = f"steam:{appid}" if appid else f"nome:{nome.casefold()}"
    chave = backup._hash_identidade(identidade_str)
    entrada = {campo: 0 if campo != "notes" and campo != "status" and
               campo != "process_executable" else "" for campo in backup.CAMPOS_OPINIAO}
    entrada.update(campos)
    entrada["identidade_exibicao"] = appid or nome
    entrada["sessoes"] = []
    manifesto = {
        "version": backup.VERSAO,
        "settings": configuracoes or {},
        "state": {},
        "jogos": {chave: entrada},
    }
    destino = tmp_path / "b.zip"
    with zipfile.ZipFile(destino, "w") as arquivo:
        arquivo.writestr("backup.json", json.dumps(manifesto))
    return destino, chave


def test_restaurar_aplica_campos_no_jogo_que_casa_por_appid(
    store, make_game, tmp_path, settings
) -> None:
    main, _state = settings
    main.set_boolean("steam-metadata", False)  # sem varredura forçada aqui
    jogo = make_game(game_id="a", steam_appid="1", name="Jogo")
    store.add_game(jogo, {})
    destino, _chave = _backup_com_um_jogo(
        tmp_path, appid="1", playtime=3600, status="beaten", rating=5, notes="Ótimo"
    )

    resultado = backup.restaurar(destino)

    assert resultado.casados == 1
    assert resultado.total == 1
    assert resultado.ambiguos == []
    assert jogo.playtime == 3600
    assert jogo.status == "beaten"
    assert jogo.rating == 5
    assert jogo.notes == "Ótimo"


def test_restaurar_sobrescreve_mesmo_com_dado_mais_novo(store, make_game, tmp_path, settings) -> None:
    main, _state = settings
    main.set_boolean("steam-metadata", False)
    jogo = make_game(game_id="a", steam_appid="1", name="Jogo", playtime=99999, notes="Anotação de hoje")
    store.add_game(jogo, {})
    destino, _chave = _backup_com_um_jogo(tmp_path, appid="1", playtime=10, notes="Do backup")

    backup.restaurar(destino)

    assert jogo.playtime == 10
    assert jogo.notes == "Do backup"


def test_restaurar_nao_toca_jogo_sem_correspondencia(store, make_game, tmp_path, settings) -> None:
    main, _state = settings
    main.set_boolean("steam-metadata", False)
    jogo = make_game(game_id="a", steam_appid="2", name="Outro Jogo", playtime=5)
    store.add_game(jogo, {})
    destino, _chave = _backup_com_um_jogo(tmp_path, appid="1", playtime=999)

    resultado = backup.restaurar(destino)

    assert resultado.casados == 0
    assert jogo.playtime == 5


def test_restaurar_ignora_jogo_removido(store, make_game, tmp_path, settings) -> None:
    main, _state = settings
    main.set_boolean("steam-metadata", False)
    tumba = make_game(game_id="a", steam_appid="1", name="Jogo", removed=True, playtime=5)
    store.add_game(tumba, {})
    destino, _chave = _backup_com_um_jogo(tmp_path, appid="1", playtime=999)

    resultado = backup.restaurar(destino)

    assert resultado.casados == 0
    assert tumba.playtime == 5


def test_restaurar_aplica_nos_dois_jogos_com_mesmo_appid(store, make_game, tmp_path, settings) -> None:
    main, _state = settings
    main.set_boolean("steam-metadata", False)
    original = make_game(game_id="a", steam_appid="1", name="Steam")
    pirata = make_game(game_id="b", steam_appid="1", name="Pirata")
    store.add_game(original, {})
    store.add_game(pirata, {})
    destino, _chave = _backup_com_um_jogo(tmp_path, appid="1", playtime=42)

    resultado = backup.restaurar(destino)

    assert resultado.casados == 1
    assert original.playtime == 42
    assert pirata.playtime == 42


def test_restaurar_nao_aplica_em_nome_ambiguo_e_reporta(store, make_game, tmp_path, settings) -> None:
    main, _state = settings
    main.set_boolean("steam-metadata", False)
    um = make_game(game_id="a", name="Legacy (PC)")
    outro = make_game(game_id="b", name="Legacy™")
    store.add_game(um, {})
    store.add_game(outro, {})
    destino, _chave = _backup_com_um_jogo(
        tmp_path, nome="Legacy", playtime=42, configuracoes={"steam-metadata": False}
    )

    resultado = backup.restaurar(destino)

    assert resultado.casados == 0
    assert resultado.ambiguos == ["Legacy"]
    assert um.playtime == 0
    assert outro.playtime == 0


def test_restaurar_aplica_as_configuracoes_antes_da_varredura(
    store, make_game, tmp_path, settings, monkeypatch
) -> None:
    """steam-metadata é 'da instalação anterior': o backup pode religá-la, e
    a varredura forçada tem de respeitar o valor já restaurado, não o de
    antes de restaurar."""
    main, _state = settings
    main.set_boolean("steam-metadata", False)
    jogo = make_game(game_id="a", name="Jogo")
    store.add_game(jogo, {})

    destino = tmp_path / "b.zip"
    chave = backup._hash_identidade("nome:jogo")
    entrada = {campo: (0 if campo not in ("notes", "status", "process_executable") else "")
               for campo in backup.CAMPOS_OPINIAO}
    entrada["identidade_exibicao"] = "Jogo"
    entrada["sessoes"] = []
    manifesto = {
        "version": backup.VERSAO,
        "settings": {"steam-metadata": True},
        "state": {},
        "jogos": {chave: entrada},
    }
    with zipfile.ZipFile(destino, "w") as arquivo:
        arquivo.writestr("backup.json", json.dumps(manifesto))

    chamado = []

    def _fake(_jogos, _progresso, _cancelado):
        chamado.append(True)
        return True

    monkeypatch.setattr(backup, "_forcar_appids", _fake)
    backup.restaurar(destino)

    assert main.get_boolean("steam-metadata") is True
    assert chamado == [True]


def test_restaurar_pula_a_varredura_se_steam_metadata_desligado(
    store, make_game, tmp_path, settings, monkeypatch
) -> None:
    main, _state = settings
    main.set_boolean("steam-metadata", False)
    jogo = make_game(game_id="a", name="Jogo")
    store.add_game(jogo, {})
    destino, _chave = _backup_com_um_jogo(
        tmp_path, nome="Jogo", playtime=7, configuracoes={"steam-metadata": False}
    )

    chamado = []
    monkeypatch.setattr(
        backup, "_forcar_appids", lambda *a, **k: chamado.append(True) or True
    )
    backup.restaurar(destino)

    assert chamado == []


def test_restaurar_cancelado_nao_aplica_nada(
    store, make_game, tmp_path, settings, monkeypatch
) -> None:
    main, _state = settings
    main.set_boolean("steam-metadata", True)
    jogo = make_game(game_id="a", name="Jogo")  # sem appid -> entra na varredura
    store.add_game(jogo, {})
    destino, _chave = _backup_com_um_jogo(tmp_path, nome="Jogo", playtime=7)

    monkeypatch.setattr(backup, "_forcar_appids", lambda *a, **k: False)
    resultado = backup.restaurar(destino)

    assert resultado is None
    assert jogo.playtime == 0


def test_restaurar_traduz_sessoes_de_volta_ao_game_id_local(store, make_game, tmp_path, settings, app_dirs) -> None:
    from cartridges.utils import session_log

    main, _state = settings
    main.set_boolean("steam-metadata", False)
    jogo = make_game(game_id="local-x", steam_appid="1", name="Jogo")
    store.add_game(jogo, {})
    destino, _chave = _backup_com_um_jogo(tmp_path, appid="1")
    with zipfile.ZipFile(destino) as arquivo:
        manifesto = json.loads(arquivo.read("backup.json"))
    chave = next(iter(manifesto["jogos"]))
    manifesto["jogos"][chave]["sessoes"] = [{"end": 1_700_000_000, "seconds": 1800}]
    with zipfile.ZipFile(destino, "w") as arquivo:
        arquivo.writestr("backup.json", json.dumps(manifesto))

    backup.restaurar(destino)

    sessoes = session_log.load("local-x")
    assert sessoes == [{"game_id": "local-x", "end": 1_700_000_000, "seconds": 1800}]


def test_restaurar_nao_duplica_sessao_ja_existente(store, make_game, tmp_path, settings) -> None:
    from cartridges.utils import session_log

    main, _state = settings
    main.set_boolean("steam-metadata", False)
    jogo = make_game(game_id="local-x", steam_appid="1", name="Jogo")
    store.add_game(jogo, {})
    session_log.record("local-x", 1800, end=1_700_000_000)

    destino, _chave = _backup_com_um_jogo(tmp_path, appid="1")
    with zipfile.ZipFile(destino) as arquivo:
        manifesto = json.loads(arquivo.read("backup.json"))
    chave = next(iter(manifesto["jogos"]))
    manifesto["jogos"][chave]["sessoes"] = [{"end": 1_700_000_000, "seconds": 1800}]
    with zipfile.ZipFile(destino, "w") as arquivo:
        arquivo.writestr("backup.json", json.dumps(manifesto))

    backup.restaurar(destino)

    assert len(session_log.load("local-x")) == 1


def test_aplicar_configuracoes_fora_da_main_aplica_direto_na_thread_principal(
    settings, monkeypatch
) -> None:
    """`restaurar()` roda no thread do pytest em todo o resto desta suíte —
    é o caso comum hoje, e continua idêntico: sem GLib.idle_add nenhum."""
    assert backup.is_main_thread() is True
    main, _state = settings
    main.set_boolean("steam-metadata", False)

    chamado = []
    monkeypatch.setattr(backup.GLib, "idle_add", lambda *a, **k: chamado.append(a))

    backup._aplicar_configuracoes_fora_da_main(
        {"settings": {"steam-metadata": True}, "state": {}}
    )

    assert chamado == []
    assert main.get_boolean("steam-metadata") is True


def test_aplicar_configuracoes_fora_da_main_funciona_fora_da_thread_principal(
    settings, flush_idle
) -> None:
    """O caso real de `restaurar()` chamado de uma thread de fundo (a Task 9
    vai rodar assim): aplicar_configuracoes só é seguro na thread principal
    (sinais changed::<chave> do Gio.Settings de verdade têm handler que toca
    GTK direto), então isto marshalla via GLib.idle_add e espera — sem travar
    quando o teste bombeia a fila a partir da thread principal."""
    import threading  # noqa: PLC0415
    import time  # noqa: PLC0415

    main, _state = settings
    main.set_boolean("steam-metadata", False)

    def rodar() -> None:
        backup._aplicar_configuracoes_fora_da_main(
            {"settings": {"steam-metadata": True}, "state": {}}
        )

    trabalhador = threading.Thread(target=rodar)
    trabalhador.start()

    deadline = time.monotonic() + 5
    while trabalhador.is_alive():
        assert time.monotonic() < deadline, "a thread de fundo não terminou a tempo"
        flush_idle()
        time.sleep(0.01)
    trabalhador.join(timeout=5)

    assert not trabalhador.is_alive()
    assert main.get_boolean("steam-metadata") is True


def test_validar_confere_o_crc_de_cada_entrada(
    store, make_game, app_dirs, settings, tmp_path
) -> None:
    """Um byte trocado num asset de jogo (gravado sem compressão) passa pelo
    manifesto; o CRC de cada entrada é conferido antes.

    (Corromper o texto de ``backup.json`` não serve: ele é gravado com
    ``ZIP_DEFLATED``, então o JSON em claro não aparece nos bytes do zip.)
    """
    jogo = make_game(game_id="a", steam_appid="1", name="Jogo")
    store.add_game(jogo, {})
    (app_dirs.covers / "a.tiff").write_bytes(b"bytes-da-capa")
    destino = tmp_path / "b.zip"
    backup.exportar(destino, backup.ler_configuracoes())
    dados = destino.read_bytes()
    assert dados.count(b"bytes-da-capa") == 1
    destino.write_bytes(dados.replace(b"bytes-da-capa", b"bytes-da-cApa"))
    with pytest.raises(ValueError):
        backup.validar(destino)


class _GerenteFalso:
    """Substitui o SteamAPIManager real: sem rede, sem rate limiter."""

    def __init__(self) -> None:
        self.chamados: list[str] = []

    def run(self, jogo, _dados) -> None:
        self.chamados.append(jogo.game_id)
        jogo.steam_appid = f"resolvido-{jogo.game_id}"


def test_forcar_appids_roda_o_gerente_em_cada_jogo(store, make_game, monkeypatch, flush_idle) -> None:
    from cartridges.store.managers.steam_api_manager import SteamAPIManager

    jogos = [make_game(game_id="a"), make_game(game_id="b")]
    for jogo in jogos:
        store.add_game(jogo, {})
    gerente = _GerenteFalso()
    monkeypatch.setitem(shared.store.managers, SteamAPIManager, gerente)

    progresso_visto = []

    def coletar(indice, total):
        progresso_visto.append((indice, total))

    ok = backup._forcar_appids(jogos, coletar, None)
    flush_idle()

    assert ok is True
    assert gerente.chamados == ["a", "b"]
    assert progresso_visto == [(1, 2), (2, 2)]
    assert jogos[0].steam_appid == "resolvido-a"


def test_forcar_appids_cancelado_para_no_meio(store, make_game, monkeypatch, flush_idle) -> None:
    from cartridges.store.managers.steam_api_manager import SteamAPIManager

    jogos = [make_game(game_id="a"), make_game(game_id="b"), make_game(game_id="c")]
    for jogo in jogos:
        store.add_game(jogo, {})
    gerente = _GerenteFalso()
    monkeypatch.setitem(shared.store.managers, SteamAPIManager, gerente)

    cancelar_no_segundo = iter([False, True])
    ok = backup._forcar_appids(jogos, None, lambda: next(cancelar_no_segundo))
    flush_idle()

    assert ok is False
    assert gerente.chamados == ["a"]  # parou antes do segundo


def test_forcar_appids_salva_e_atualiza_cada_jogo(store, make_game, monkeypatch, flush_idle) -> None:
    from cartridges.store.managers.steam_api_manager import SteamAPIManager

    jogo = make_game(game_id="a")
    store.add_game(jogo, {})
    monkeypatch.setitem(shared.store.managers, SteamAPIManager, _GerenteFalso())

    backup._forcar_appids([jogo], None, None)
    flush_idle()

    assert jogo.saves == 1
    assert jogo.updates == 1


# --------------------------------------------------------------------------
# A tela de verdade (Preferências)
# --------------------------------------------------------------------------


def test_import_backup_confirma_e_restaura_ao_vivo(
    monkeypatch, app_dirs, settings, store, make_game, tmp_path, win, flush_idle
) -> None:
    import cartridges.preferences as preferences_module
    from tests.test_auditoria_0918_fitas import _dialogo_de_arquivo
    from tests.test_session_fita import _preferencias

    main, _state = settings
    main.set_boolean("steam-metadata", False)

    jogo = make_game(game_id="a", steam_appid="1", name="Jogo")
    store.add_game(jogo, {})
    # `configuracoes` explícito, e não só o `steam-metadata` do schema acima:
    # sem appid pendente (o jogo já tem um), quem mantém a varredura desligada
    # de fato é o schema — mas deixar isso implícito faria este teste passar
    # a bater rede de verdade (`SteamAPIManager`, sem fake aqui) se algum dia
    # o jogo perder o appid. A intenção — sem varredura forçada — fica
    # explícita nos dois lugares, não só num efeito colateral.
    destino, _chave = _backup_com_um_jogo(
        tmp_path, appid="1", playtime=42, configuracoes={"steam-metadata": False}
    )

    _dialogo_de_arquivo(monkeypatch, destino)
    preferences = _preferencias(monkeypatch)
    toasts = []
    monkeypatch.setattr(preferences, "add_toast", toasts.append)

    respostas = []

    class Pergunta:
        def connect(self, _sinal, callback) -> None:
            respostas.append(callback)

    monkeypatch.setattr(preferences_module, "create_dialog", lambda *_a, **_k: Pergunta())

    preferences.import_backup()
    respostas[0](None, "restore")

    import time  # noqa: PLC0415

    # Esperar só `jogo.playtime == 42` não basta: entre `update_values`
    # gravar o campo (direto na thread de fundo, sem `idle_add`) e o
    # `GLib.idle_add(self._restore_done, ...)` do `work()` rodar, ainda
    # acontecem `GLib.idle_add(_salvar_e_atualizar)`, `_extrair_asset` (3x),
    # `_aplicar_sessoes` (I/O), o fechamento do zip, a limpeza do
    # `TemporaryDirectory` e `_invalidar_listas` — uma janela real onde o
    # laço poderia ver o playtime certo e sair antes do toast de resumo
    # estar sequer enfileirado. Espera o toast diretamente, mesmo molde de
    # `test_aplicar_configuracoes_fora_da_main_funciona_fora_da_thread_principal`
    # (mais abaixo neste arquivo) esperando `trabalhador.is_alive()`.
    deadline = time.monotonic() + 10
    while not any("Restaurado" in toast.get_title() for toast in toasts):
        assert time.monotonic() < deadline, "o toast de resumo não chegou"
        flush_idle()
        time.sleep(0.01)

    assert jogo.playtime == 42
