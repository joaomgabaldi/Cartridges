# test_auditoria_0918_ui.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressões da auditoria de 18/09/2026, grupo ui.

Um teste por achado de comportamento; cada um falha sem o conserto.
"""

import hashlib
import json
import threading
import types
from datetime import datetime

import pytest
from gi.repository import Adw

from cartridges import shared
from cartridges.process_session import ProcessSession
from cartridges.session_window import SessionWindow


@pytest.fixture(autouse=True)
def sem_sessao(monkeypatch):
    monkeypatch.setattr(ProcessSession, "active", None)
    monkeypatch.setattr(SessionWindow, "active", None)


@pytest.fixture
def sessao_sem_efeitos(monkeypatch):
    """O bloqueador da janela de verdade, sem parede, fita nem controle."""
    import cartridges.window as window_module

    vestidas = []
    monkeypatch.setattr(window_module.session_fita, "comecar", vestidas.append)
    monkeypatch.setattr(window_module.session_fita, "voltar", lambda: None)
    monkeypatch.setattr(window_module.session_wallpaper, "comecar", lambda _g: None)
    monkeypatch.setattr(window_module.session_wallpaper, "restaurar", lambda: None)
    monkeypatch.setattr(
        window_module.window_geometry, "restore_from_monitor", lambda _w: None
    )
    return vestidas


def _app_falso(window, monkeypatch):
    # Não importar o FakeApplication de `tests.conftest`: importado de novo como
    # módulo, o conftest reinstala um `cartridges.shared` novo por cima do atual.
    acao = types.SimpleNamespace(enabled=True)
    acao.set_enabled = lambda valor: setattr(acao, "enabled", valor)
    app = types.SimpleNamespace(lookup_action=lambda _nome: acao)
    monkeypatch.setattr(window, "get_application", lambda: app, raising=False)
    return app


# -- M1 -----------------------------------------------------------------------


def test_m1_o_bloqueador_barra_o_teclado(real_window, make_game, sessao_sem_efeitos):
    """Enter no "Jogar" que ficou com o foco não pode agir por trás do overlay."""
    real_window.show_session_blocker(make_game())
    assert real_window.navigation_view.get_sensitive() is False

    real_window.hide_session_blocker()
    assert real_window.navigation_view.get_sensitive() is True


# -- M2 -----------------------------------------------------------------------


def test_m2_delete_so_vale_com_os_detalhes_a_vista(
    real_window, make_game, sessao_sem_efeitos, monkeypatch
):
    app = _app_falso(real_window, monkeypatch)
    delete = app.lookup_action("remove_game_details_view")

    real_window.set_show_hidden(real_window.navigation_view)
    assert delete.enabled is False, "na biblioteca, Delete é da caixa de busca"

    monkeypatch.setattr(
        real_window.navigation_view,
        "get_visible_page",
        lambda: real_window.details_page,
        raising=False,
    )
    real_window.set_show_hidden(real_window.navigation_view)
    assert delete.enabled is True

    real_window.show_session_blocker(make_game())
    assert delete.enabled is False, "com a sessão aberta, apagaria o jogo rodando"


def test_m2_ctrl_z_num_campo_desfaz_a_digitacao(real_window, store, monkeypatch):
    texto = real_window.search_entry.get_delegate()
    pedidos = []
    monkeypatch.setattr(
        texto, "activate_action", lambda nome, _p: pedidos.append(nome), raising=False
    )
    monkeypatch.setattr(real_window, "get_focus", lambda: texto, raising=False)
    importer = types.SimpleNamespace(
        imported_game_ids={"g1"},
        removed_game_ids=set(),
        undo_import=lambda: pytest.fail("Ctrl+Z na busca desfez a importação"),
    )
    monkeypatch.setattr(shared, "importer", importer)

    real_window.on_undo_action(None)

    assert pedidos == ["text.undo"]


# -- M3 -----------------------------------------------------------------------


def test_m3_o_desfazer_da_importacao_morre_com_o_aviso(store, make_game):
    from cartridges.importer.importer import Importer

    importer = Importer()
    game = make_game(game_id="g1", name="Removido")
    store.add_game(game, {}, run_pipeline=False)
    importer.imported_game_ids = {"novo"}
    importer.removed_game_ids = {"g1"}

    toast = importer.create_summary_toast()
    toast.emit("dismissed")

    assert importer.imported_game_ids == set()
    assert importer.removed_game_ids == set()


# -- M4 -----------------------------------------------------------------------


def test_m4_a_queda_para_a_janela_manual_nao_despe_a_sessao(
    make_game, monkeypatch, win
):
    import cartridges.session_window as sw

    criadas = []
    monkeypatch.setattr(
        sw,
        "SessionWindow",
        lambda game: types.SimpleNamespace(present=lambda: criadas.append(game)),
    )
    session = ProcessSession(make_game())

    session.stop(record=False, fall_back=True)

    assert None not in win.session_blocker_shown, "hide_session_blocker foi chamado"
    assert criadas == [session.game]


def test_m4_o_mesmo_jogo_nao_e_vestido_de_novo(
    real_window, make_game, sessao_sem_efeitos
):
    jogo = make_game()
    real_window.show_session_blocker(jogo)
    real_window.show_session_blocker(jogo)  # o SessionWindow que assume

    assert sessao_sem_efeitos == [jogo], "as fitas foram vestidas duas vezes"


# -- M5 -----------------------------------------------------------------------


def test_m5_fechar_o_app_grava_a_sessao_no_historico(monkeypatch, make_game):
    import cartridges.main as main_module

    anotadas = []
    monkeypatch.setattr(
        main_module.session_log,
        "record",
        lambda game_id, seconds: anotadas.append((game_id, seconds)),
    )
    monkeypatch.setattr(main_module.session_fita, "fechar", lambda: None)
    monkeypatch.setattr(main_module.session_wallpaper, "restaurar", lambda: None)
    monkeypatch.setattr(shared, "win", None)
    monkeypatch.setattr(shared, "store", shared.store)

    manual = types.SimpleNamespace(
        game=make_game(game_id="manual"), session_seconds=300, flush=lambda: None
    )
    auto = types.SimpleNamespace(
        game=make_game(game_id="auto"),
        session_seconds=120,
        started=True,
        flush=lambda: None,
    )
    monkeypatch.setattr(SessionWindow, "active", manual)
    monkeypatch.setattr(ProcessSession, "active", auto)

    main_module.CartridgesApplication().do_shutdown()

    assert anotadas == [("manual", 300), ("auto", 120)]


# -- M6 -----------------------------------------------------------------------


def test_m6_a_noite_dormindo_nao_vira_tempo_de_jogo(make_game, monkeypatch):
    import cartridges.process_session as ps

    agora = [1000.0]
    monkeypatch.setattr(ps, "monotonic", lambda: agora[0])
    monkeypatch.setattr(ps, "is_package_running", lambda _f: True)
    session = ProcessSession(
        make_game(executable="explorer.exe shell:AppsFolder\\Pkg_h!App")
    )
    session._poll()

    agora[0] += 8 * 3600
    session._poll()

    assert session.session_seconds == ProcessSession.POLL_INTERVAL


def test_m6_a_noite_dormindo_nao_vira_tempo_de_jogo_na_janela_manual(monkeypatch):
    import cartridges.session_window as sw

    agora = [1000.0]
    monkeypatch.setattr(sw, "monotonic", lambda: agora[0])
    game = types.SimpleNamespace(playtime=0, save=lambda: None)
    ativa = types.SimpleNamespace(
        game=game,
        session_start=1000.0,
        session_seconds=0,
        MAX_GAP=SessionWindow.MAX_GAP,
        TICK_INTERVAL=SessionWindow.TICK_INTERVAL,
    )

    agora[0] += 8 * 3600
    SessionWindow.flush(ativa)

    assert game.playtime == SessionWindow.TICK_INTERVAL
    assert ativa.session_start == agora[0]


# -- M7 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("directory", "expected"),
    [
        (
            "C:\\Program Files\\Epic Games\\GTAV",
            "C:\\Program Files\\Epic Games\\GTAV",
        ),
        (
            "C:\\Program Files\\EA Games\\Battlefield 6\\SP",
            "C:\\Program Files\\EA Games\\Battlefield 6",
        ),
        (
            "C:\\Program Files (x86)\\Rockstar Games\\Red Dead Redemption 2",
            "C:\\Program Files (x86)\\Rockstar Games\\Red Dead Redemption 2",
        ),
        # Um jogo direto em Program Files continua na própria pasta.
        ("C:\\Program Files (x86)\\Steam", "C:\\Program Files (x86)\\Steam"),
        # Os contêineres de antes não mudam.
        (
            "C:\\Program Files\\Steam\\steamapps\\common\\Halo\\bin",
            "C:\\Program Files\\Steam\\steamapps\\common\\Halo",
        ),
    ],
)
def test_m7_pasta_de_editora_nao_e_pasta_de_jogo(directory, expected):
    from cartridges.utils import process_monitor as pm

    assert pm._game_root(directory).replace("/", "\\") == expected


# -- M10 ----------------------------------------------------------------------


def test_m10_tipo_errado_custa_o_campo_e_nao_a_janela(
    store, write_record, monkeypatch
):
    import cartridges.main as main_module

    base = {"executable": "x.exe", "source": "imported"}
    write_record(
        "imported_1",
        **base,
        version=None,
        shortcut_path=5,
        shortcut_mtime=None,
        removed="false",
        notes=5,
        developer=1,
        hltb_chapters="x",
    )
    write_record("imported_2", **base, name="Estoura")
    write_record("imported_3", **base, name="Fica")

    real_add = store.add_game

    def add_game(game, *args, **kwargs):
        if game.game_id == "imported_2":
            raise TypeError("escapou da limpeza")
        return real_add(game, *args, **kwargs)

    monkeypatch.setattr(store, "add_game", add_game)

    main_module.CartridgesApplication.load_games_from_disk(None)

    game = store.get("imported_1")
    assert game is not None
    assert game.version == shared.SPEC_VERSION
    assert game.shortcut_path == ""
    assert game.shortcut_mtime == 0
    assert game.removed is False
    assert game.notes == ""
    assert game.developer is None
    assert game.hltb_chapters is None
    assert store.get("imported_3") is not None, "um arquivo ruim levou os outros"


# -- B1 -----------------------------------------------------------------------


def test_b1_a_pergunta_da_versao_nova_espera_a_sessao(monkeypatch):
    from cartridges.utils import app_updater

    adiadas = []
    monkeypatch.setattr(
        app_updater.GLib,
        "timeout_add_seconds",
        lambda _s, fn, *args: adiadas.append((fn, args)),
    )
    monkeypatch.setattr(
        app_updater.Adw,
        "AlertDialog",
        lambda **_kw: pytest.fail("perguntou com o jogo aberto"),
    )
    monkeypatch.setattr(ProcessSession, "active", object())
    release = app_updater.Release("2026.09.30", "", "https://x", 1, "ab")

    assert app_updater.AppUpdater()._ask(release) is False
    assert len(adiadas) == 1 and adiadas[0][1] == (release,)


# -- B25 ----------------------------------------------------------------------


class _Corpo:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self._payload), 8):
            yield self._payload[start : start + 8]


@pytest.mark.parametrize("informado", [8, 0])
def test_b25_o_download_do_instalador_tem_teto(
    tmp_path, monkeypatch, informado
):
    from cartridges.utils import app_updater

    payload = b"x" * 64
    monkeypatch.setattr(app_updater.requests, "get", lambda *_a, **_k: _Corpo(payload))
    monkeypatch.setattr(app_updater, "MAX_INSTALLER_BYTES", 16)
    release = app_updater.Release(
        "2026.09.30", "", "https://x", informado, hashlib.sha256(payload).hexdigest()
    )
    target = tmp_path / "update" / "setup.exe"

    with pytest.raises(ValueError):
        app_updater.download_installer(
            release, target, lambda _f: None, threading.Event()
        )
    assert list(target.parent.iterdir()) == []


# -- B17 ----------------------------------------------------------------------


def test_b17_apagar_sessao_com_byte_nao_utf8_no_arquivo(app_dirs):
    from cartridges.utils import session_log

    alheia = b'{"game_id": "caf\xe9", "end": 5, "seconds": 5}\n'
    alvo = json.dumps({"game_id": "g", "end": 10, "seconds": 60}).encode() + b"\n"
    path = app_dirs.root / "sessions.jsonl"
    path.write_bytes(alheia + alvo)

    assert session_log.delete("g", 10, 60) is True
    # O texto volta ao disco com o fim de linha do sistema; o que importa é o
    # byte não-UTF-8 da linha alheia voltar igual.
    assert path.read_bytes().replace(b"\r\n", b"\n") == alheia


# -- B26 ----------------------------------------------------------------------


def test_b26_busca_que_falhou_nao_diz_atualizadas():
    from cartridges.utils.news_checker import NewsChecker
    from cartridges.utils.news_feed import NewsPost

    checker = NewsChecker()
    checker._posts = (NewsPost("a", 1, "t", "", "", ""),)
    resultados = []
    checker.connect("poll-finished", lambda _c, ok: resultados.append(ok))

    checker._apply(None)

    assert resultados == [False]
    assert checker._posts, "o cache fica"


# -- B27 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("hoje", "data", "esperado"),
    [
        ((2026, 9, 18), (2026, 8, 31), "Mês passado"),
        ((2026, 1, 5), (2024, 12, 31), "2024"),
        ((2026, 3, 31), (2026, 1, 31), "Janeiro"),
    ],
)
def test_b27_mes_e_ano_pelo_calendario(monkeypatch, hoje, data, esperado):
    from cartridges.utils import relative_date as rd

    congelado = datetime(*hoje, 12)

    class Congelado(datetime):
        @classmethod
        def today(cls):
            return congelado

    monkeypatch.setattr(rd, "datetime", Congelado)
    assert rd.relative_date(int(datetime(*data, 12).timestamp())) == esperado


# -- H7 -----------------------------------------------------------------------


def test_h7_apagar_sessao_tem_cancelar_e_apagar_destrutivo(
    real_window, make_game, monkeypatch
):
    from cartridges import session_history
    from cartridges.utils.create_dialog import create_dialog

    criados = []

    def captura(_janela, *args, **kwargs):
        # `choose` precisa de uma janela de verdade; o `self` daqui é um dublê.
        criados.append(create_dialog(real_window, *args, **kwargs))
        return criados[-1]

    monkeypatch.setattr(session_history, "create_dialog", captura)
    dialogo_falso = types.SimpleNamespace(
        game=make_game(), on_delete_response=lambda *_a: None
    )

    session_history.SessionHistoryDialog.confirm_delete(
        dialogo_falso, None, {"seconds": 60, "end": 1_700_000_000}
    )

    dialog = criados[0]
    assert dialog.get_response_label("dismiss") == "Cancelar"
    assert (
        dialog.get_response_appearance("delete") == Adw.ResponseAppearance.DESTRUCTIVE
    )
