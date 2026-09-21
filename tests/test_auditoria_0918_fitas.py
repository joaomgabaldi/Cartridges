# test_auditoria_0918_fitas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressões da auditoria de 18/09/2026, grupo das fitas (e vizinhos).

Cada teste falha sem o conserto do achado cujo id está no nome.
"""

import json
import threading
import time
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from cartridges import shared
from cartridges.utils import backup, session_fita
from tests.test_session_fita import (  # noqa: F401 - fixtures reusadas
    FitaFalsa,
    Msg,
    _jogo,
    _preferencias,
    cor_mandada,
    estado_mandado,
    falsas,
    pastas,
    sem_fade,
)

ANTES = {"ligada": False, "cor": "000003e800b4"}


def _em_linha(monkeypatch):
    """Roda cada `_em_thread` na hora, na própria thread do teste."""
    monkeypatch.setattr(session_fita, "_em_thread", lambda tarefa: tarefa())


# region A3 — os quatro caminhos


def test_a3_reacender_das_preferencias_nao_devolve_nem_perde_fita(
    falsas, monkeypatch, schema
):
    """Fechar o assistente com o app aberto não é arranque: sem piscar no
    estado de antes, e a fita que não responde à releitura segue na chave."""
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, False)
    session_fita._guardar_e_vestir()
    guardado = schema.get_string(session_fita.CHAVE_ESTADO)
    antes = [len(modulo.recebidos) for modulo in modulos.values()]

    modulos["eb1"].quebrada = True
    _em_linha(monkeypatch)
    preferencias = _preferencias(monkeypatch)
    preferencias.fitas_configuradas()

    assert schema.get_string(session_fita.CHAVE_ESTADO) == guardado
    novos = modulos["eb0"].recebidos[antes[0]:]
    assert ANTES["cor"] not in [c.get("24") for c in novos]
    assert estado_mandado(modulos["eb0"]) is True


def test_a3_fechamento_devolve_a_fita_suspensa(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita._guardar_e_vestir()
    session_fita._suspensas.add("eb0")

    session_fita.fechar()

    assert estado_mandado(modulos["eb0"]) is False
    assert schema.get_string(session_fita.CHAVE_ESTADO) == ""


def test_a3_fita_que_nao_respondeu_a_leitura_nao_e_pintada(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, False)
    modulos["eb1"].status = lambda nowait=False: {"Error": "sem resposta"}

    session_fita._arrancar()

    assert list(json.loads(schema.get_string(session_fita.CHAVE_ESTADO))) == ["eb0"]
    assert modulos["eb1"].recebidos == []

    # Nenhuma lida: a chave fica vazia, e não "{}".
    schema.set_string(session_fita.CHAVE_ESTADO, "")
    session_fita.fechar_conexoes()
    modulos["eb0"].status = lambda nowait=False: {"Error": "sem resposta"}
    session_fita._falhas.clear()
    session_fita._guardar_e_vestir()
    assert schema.get_string(session_fita.CHAVE_ESTADO) == ""


def test_a3_fechamento_espera_o_arranque_em_curso(falsas, monkeypatch, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita._guardar_e_vestir()
    monkeypatch.setattr(session_fita, "PRAZO_FECHAMENTO", 3)

    # O arranque segura a trava enquanto veste as fitas.
    session_fita._TRAVA_ARRANQUE.acquire()
    fechamento = threading.Thread(target=session_fita.fechar)
    fechamento.start()
    try:
        time.sleep(0.2)
        assert schema.get_string(session_fita.CHAVE_ESTADO)
        assert estado_mandado(modulos["eb0"]) is True
    finally:
        session_fita._TRAVA_ARRANQUE.release()
    fechamento.join(5)

    assert schema.get_string(session_fita.CHAVE_ESTADO) == ""
    assert estado_mandado(modulos["eb0"]) is False


# endregion


def test_b2_ja_terminei_rapido_vence_a_cor_do_jogo(falsas, tmp_path, monkeypatch, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita._guardar_e_vestir()
    jogo = _jogo(tmp_path)
    tarefas = []
    monkeypatch.setattr(session_fita, "_em_thread", tarefas.append)

    session_fita.comecar(jogo)
    session_fita.voltar()
    # A cor do app fica pronta antes da do jogo, que ainda lia a capa.
    tarefas[1]()
    tarefas[0]()

    assert cor_mandada(modulos["eb0"]) == session_fita.hsv_hex(session_fita.cor_do_app())


def test_b3_descarte_nao_derruba_a_conexao_que_tomou_o_lugar():
    fita = session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")
    velha, nova = FitaFalsa(), FitaFalsa()
    session_fita._conexoes[fita.id] = (fita.ip, nova)

    session_fita._descartar(fita, velha)

    assert session_fita._conexoes[fita.id][1] is nova
    assert getattr(velha, "fechada", False)
    assert not getattr(nova, "fechada", False)


def test_b4_versao_da_varredura_e_resposta_da_consulta_nova(monkeypatch, schema):
    from cartridges.fita_wizard import com_enderecos  # noqa: PLC0415

    achados = {"192.168.0.150": {"gwId": "eb0", "version": "3.4"}}
    (fita,) = com_enderecos(
        [session_fita.Fita("Centro", "eb0", "", "k")],
        session_fita.ips_da_varredura(achados),
        session_fita.versoes_da_varredura(achados),
    )
    assert fita.versao == "3.4"

    class Fita34(FitaFalsa):
        def status(self, nowait=False):
            self.socket.a_caminho.append(Msg(16, {"dps": dict(self.dps)}))

    session_fita.gravar_fitas([fita._replace(ip="192.168.0.150")])
    monkeypatch.setattr(session_fita, "_dispositivo", lambda _fita: Fita34())
    assert session_fita.ler_estado(session_fita.fitas()[0]) == ANTES


def test_b15_sidecar_com_tipo_errado_vale_o_automatico(tmp_path, schema):
    jogo = _jogo(tmp_path)
    shared.fitas_dir.mkdir(parents=True, exist_ok=True)
    (shared.fitas_dir / f"{jogo.game_id}.json").write_text(
        json.dumps({"locked": True, "matiz": None}), encoding="utf-8"
    )

    assert session_fita.cor_do_jogo(jogo) == session_fita.cor_do_jogo(jogo, True)


# region Preferências


def _com_bind(monkeypatch, schema):
    monkeypatch.setattr(
        schema,
        "bind",
        lambda chave, widget, prop, _flags: widget.set_property(
            prop, schema.get_boolean(chave)
        ),
    )


def test_m14_sem_contar_horas_as_fitas_seguem_configuraveis(monkeypatch, schema):
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    schema.set_boolean("playtime-tracking", False)
    _com_bind(monkeypatch, schema)

    preferencias = _preferencias(monkeypatch)

    assert preferencias.session_fita_switch.is_sensitive()
    assert preferencias.fita_configurar_button.is_sensitive()
    assert not preferencias.session_wallpaper_switch.is_sensitive()


class _Janela:
    """O que o reset e a restauração do backup pedem da janela."""

    def __init__(self, win):
        vazio = SimpleNamespace(
            remove_all=lambda: None,
            invalidate_sort=lambda: None,
            invalidate_filter=lambda: None,
        )
        win.navigation_view = SimpleNamespace(get_visible_page=lambda: None)
        win.details_page = object()
        win.library = vazio
        win.hidden_library = vazio
        win.set_library_child = lambda: None


def test_m9_reset_apaga_papel_de_parede_e_cor_da_fita_dos_jogos(
    monkeypatch, schema, store, win, app_dirs
):
    _Janela(win)
    (app_dirs.wallpapers / "jogo.json").write_text("{}", encoding="utf-8")
    (app_dirs.wallpapers / "jogo.png").write_bytes(b"x")
    (app_dirs.wallpapers / "cache").mkdir()
    (app_dirs.wallpapers / "cache" / "a.jpg").write_bytes(b"x")
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    session_fita.salvar_cor("jogo", "Jogo", session_fita.Cor(1, 2, 3))

    _preferencias(monkeypatch).reset_app_data()

    assert not (app_dirs.wallpapers / "jogo.json").exists()
    assert not (app_dirs.wallpapers / "jogo.png").exists()
    assert (app_dirs.wallpapers / "cache" / "a.jpg").exists()
    assert not session_fita.escolhida("jogo")
    assert session_fita.fitas()


def test_m8_lote_de_capas_nao_repinta_jogo_apagado(monkeypatch, store, make_game):
    from cartridges.store.managers.sgdb_manager import SgdbManager  # noqa: PLC0415

    chamadas = []

    class Stub:
        signals: set = set()

        def reset_cancellable(self):
            pass

        def collect_errors(self):
            return []

        def process_game(self, _game, _data, callback):
            chamadas.append(callback)

    jogo = make_game(game_id="a")
    store.add_game(jogo, {})
    store.managers[SgdbManager] = Stub()
    preferencias = _preferencias(monkeypatch)

    preferencias.sgdb_fetch_button.emit("clicked")
    store.clear()  # o reset chegou com o lote em voo
    for callback in chamadas:
        callback(store.managers.get(SgdbManager) or Stub())

    assert jogo.updates == 0


def test_m8_tarefa_enfileirada_ve_o_cancelamento_do_reset(monkeypatch, make_game):
    from cartridges.store.managers import sgdb_manager  # noqa: PLC0415
    from cartridges.store.managers.async_manager import AsyncManager  # noqa: PLC0415

    enfileiradas = []
    monkeypatch.setattr(
        AsyncManager,
        "process_game",
        lambda _self, game, data, _callback: enfileiradas.append((game, data)),
    )
    ajudas = []
    monkeypatch.setattr(sgdb_manager, "SgdbHelper", lambda: ajudas.append(1))

    manager = sgdb_manager.SgdbManager()
    manager.process_game(make_game(), {}, lambda _m: None)
    manager.cancel_tasks()
    manager.reset_cancellable()
    game, data = enfileiradas[0]
    manager.main(game, data)

    assert ajudas == []


def _dialogo_de_arquivo(monkeypatch, caminho):
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    class Dialogo:
        def __init__(self, *_a, **_k):
            pass

        def __getattr__(self, _nome):
            return lambda *_a, **_k: None

        def save(self, _win, _c, finish):
            finish(self, None)

        def open(self, _win, _c, finish):
            finish(self, None)

        def save_finish(self, _r):
            return SimpleNamespace(get_path=lambda: str(caminho))

        open_finish = save_finish

    monkeypatch.setattr(preferences_module.Gtk, "FileDialog", Dialogo)
    return preferences_module


def test_b7_exportar_por_cima_nao_trunca_o_backup_antigo(
    monkeypatch, store, make_game, tmp_path
):
    """Hoje o backup é o .zip de `utils/backup.py`; a garantia é a mesma."""
    destino = tmp_path / "backup.zip"
    destino.write_bytes(b"backup antigo")
    store.add_game(make_game(game_id="a"), {})
    (shared.covers_dir / "a.tiff").write_bytes(b"capa")

    def cai_no_meio(*_args, **_kwargs):
        raise OSError("disco cheio")

    monkeypatch.setattr(zipfile.ZipFile, "write", cai_no_meio)
    with pytest.raises(OSError):
        backup.exportar(destino, {"settings": {}, "state": {}})

    assert destino.read_bytes() == b"backup antigo"
    assert not destino.with_name("backup.zip.tmp").exists()


def test_b8_backup_com_infinito_e_lapide(monkeypatch, store, make_game, win, tmp_path):
    _Janela(win)
    vivo = make_game(game_id="vivo")
    lapide = make_game(game_id="lapide", removed=True)
    store.add_game(vivo, {})
    store.add_game(lapide, {})
    arquivo = tmp_path / "backup.json"
    arquivo.write_text(
        '{"version": 2, "games": {"vivo": {"playtime": Infinity, "notes": "oi"},'
        ' "lapide": {"playtime": 60}}}',
        encoding="utf-8",
    )
    _dialogo_de_arquivo(monkeypatch, arquivo)
    preferencias = _preferencias(monkeypatch)
    toasts = []
    monkeypatch.setattr(preferencias, "add_toast", toasts.append)

    preferencias.import_backup()

    assert vivo.notes == "oi" and vivo.playtime == 0
    assert lapide.playtime == 0
    assert toasts[-1].get_title() == "1 jogo restaurado"


# endregion
# region Varreduras de fundo


def _thread_em_linha(modulo, monkeypatch):
    monkeypatch.setattr(
        modulo.threading,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
    )


def test_b11_varredura_do_hltb_reiniciada_no_reset_para(monkeypatch, store, make_game):
    from cartridges.utils import hltb_backfill  # noqa: PLC0415

    for game_id in ("a", "b"):
        store.add_game(make_game(game_id=game_id, has_hltb_times=False, hltb_id=None), {})
    sweep = hltb_backfill.HLTBBackfill()
    buscas = []

    def buscar(*_args):
        buscas.append(1)
        sweep.stop()  # o reset no meio da varredura
        sweep.start()
        raise hltb_backfill.HLTBError("nada")

    monkeypatch.setattr(hltb_backfill, "fetch_times", buscar)
    monkeypatch.setattr(hltb_backfill, "shared_helper", lambda: None)
    _thread_em_linha(hltb_backfill, monkeypatch)
    try:
        sweep.run_async()
    finally:
        sweep.stop()

    assert len(buscas) == 1


def test_b11_varredura_de_tamanho_reiniciada_no_reset_para(monkeypatch, store, make_game):
    from cartridges.utils import install_size  # noqa: PLC0415

    for game_id in ("a", "b"):
        store.add_game(make_game(game_id=game_id, install_size=0, install_size_ts=0), {})
    sweep = install_size.InstallSizeSweep()
    medidas = []

    def medir(_pasta):
        medidas.append(1)
        sweep.stop()
        sweep.start()
        return 0

    monkeypatch.setattr(install_size, "install_size_folder", lambda _cmd: "C:/jogo")
    monkeypatch.setattr(install_size, "folder_size", medir)
    _thread_em_linha(install_size, monkeypatch)
    try:
        sweep.run_async()
    finally:
        sweep.stop()

    assert len(medidas) == 1


def test_b12_resultado_tardio_do_hltb_nao_sobrescreve_a_correcao(store, make_game):
    from cartridges.utils.hltb_backfill import HLTBBackfill  # noqa: PLC0415

    jogo = make_game(game_id="a", has_hltb_times=True)
    jogo.update_values = lambda valores: setattr(jogo, "sobrescrito", valores)
    store.add_game(jogo, {})

    HLTBBackfill()._apply(jogo, {"hltb_main": 1})

    assert not hasattr(jogo, "sobrescrito")


def test_b16_jogo_que_saiu_do_disco_perde_o_tamanho(
    monkeypatch, store, make_game, win, flush_idle
):
    from cartridges.utils import install_size  # noqa: PLC0415

    win.sort_state = "name"
    jogo = make_game(game_id="a", install_size=5000, install_size_ts=0)
    store.add_game(jogo, {})
    monkeypatch.setattr(install_size, "install_size_folder", lambda _cmd: "C:/sumiu")
    monkeypatch.setattr(install_size, "folder_size", lambda _pasta: 0)
    _thread_em_linha(install_size, monkeypatch)

    install_size.InstallSizeSweep().run_async()
    flush_idle()

    assert jogo.install_size == 0
    assert jogo.install_size_ts == 0


# endregion
