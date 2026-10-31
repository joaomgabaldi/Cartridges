"""Cada trabalho em segundo plano aparece no quadro de tarefas enquanto roda."""

from types import SimpleNamespace

import pytest

from cartridges.modelos import tarefas


@pytest.fixture(autouse=True)
def _lista_limpa():
    """A lista é global: cada teste começa e termina sem tarefa nenhuma."""
    _esvaziar()
    yield
    _esvaziar()


def _esvaziar():
    for tarefa in list(tarefas.lista._tarefas):  # noqa: SLF001
        tarefas.lista.remover(tarefa)


class FakeManager:
    """No lugar dos managers da Steam e do HowLongToBeat."""

    steam_api_helper = None

    def reset_cancellable(self) -> None:
        pass

    def collect_errors(self):
        return []

    def process_game(self, game, additional_data, callback) -> None:  # noqa: ARG002
        callback(self)


class FakeStore:
    """Só a busca por id que o refresh faz antes de salvar um jogo."""

    def __init__(self) -> None:
        self.games_by_id: dict = {}

    def get(self, game_id, default=None):
        return self.games_by_id.get(game_id, default)


_contador = iter(range(1, 10_000))


def _jogo():
    jogo = SimpleNamespace(game_id=f"imported_{next(_contador)}", genre=None, steam_appid=None)
    jogo.save = lambda: None
    jogo.update = lambda: None
    return jogo


def _thread_em_linha(modulo, monkeypatch):
    monkeypatch.setattr(
        modulo.threading,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
    )


def _tarefas_vistas(monkeypatch):
    """Registra o (nome, total) de cada tarefa começada, na ordem."""
    vistas = []
    comecar = tarefas.comecar

    def espiar(nome, total):
        tarefa = comecar(nome, total)
        vistas.append((nome, total))
        return tarefa

    monkeypatch.setattr(tarefas, "comecar", espiar)
    return vistas


def test_hltb_vira_tarefa_com_a_fila_e_termina(monkeypatch, store, make_game, flush_idle):
    from cartridges.utils import hltb_backfill  # noqa: PLC0415

    for game_id in ("a", "b", "c"):
        store.add_game(make_game(game_id=game_id, has_hltb_times=False, hltb_id=None), {})
    vistas = _tarefas_vistas(monkeypatch)

    def nao_acha(*_args):
        raise hltb_backfill.HLTBGameNotFoundError("x")

    monkeypatch.setattr(hltb_backfill, "fetch_times", nao_acha)
    monkeypatch.setattr(hltb_backfill, "shared_helper", lambda: None)
    _thread_em_linha(hltb_backfill, monkeypatch)

    sweep = hltb_backfill.HLTBBackfill()
    try:
        sweep.run_async()
    finally:
        sweep.stop()
    flush_idle()

    assert vistas == [("HowLongToBeat", 3)]
    assert tarefas.lista.rowCount() == 0


def _refresh_com_managers(monkeypatch):
    """Um MetadataRefresh sem rede: managers falsos, thread em linha e o
    prefetch de tags sem nada a buscar."""
    from cartridges import metadata_refresh, shared  # noqa: PLC0415
    from cartridges.store.managers.hltb_manager import HLTBManager  # noqa: PLC0415
    from cartridges.store.managers.steam_api_manager import (  # noqa: PLC0415
        SteamAPIManager,
    )

    monkeypatch.setattr(shared, "store", FakeStore(), raising=False)
    shared.store.managers = {SteamAPIManager: FakeManager(), HLTBManager: FakeManager()}
    # `metadata_refresh` importa `Thread` direto, então não serve o helper acima.
    monkeypatch.setattr(
        metadata_refresh,
        "Thread",
        lambda target, daemon: SimpleNamespace(start=target),
    )
    refresh = metadata_refresh.MetadataRefresh()
    monkeypatch.setattr(refresh, "_announce", lambda *_a: None)
    return refresh


def test_metadados_vira_tarefa_e_termina(monkeypatch, flush_idle):
    refresh = _refresh_com_managers(monkeypatch)
    vistas = _tarefas_vistas(monkeypatch)

    assert refresh.start([_jogo(), _jogo()]) is True
    flush_idle()

    assert vistas == [("Metadados", 2)]
    assert tarefas.lista.rowCount() == 0


def test_metadados_cancelado_tambem_sai_do_quadro(monkeypatch, flush_idle):
    refresh = _refresh_com_managers(monkeypatch)
    vistas = _tarefas_vistas(monkeypatch)

    assert refresh.start([_jogo(), _jogo()]) is True
    refresh.cancel()
    flush_idle()

    assert vistas == [("Metadados", 2)]
    assert tarefas.lista.rowCount() == 0


def test_tamanho_conta_so_jogos_com_pasta(monkeypatch, store, make_game, win, flush_idle):
    from cartridges.utils import install_size  # noqa: PLC0415

    win.sort_state = "name"
    store.add_game(make_game(game_id="com", executable="com", install_size=0, install_size_ts=0), {})
    store.add_game(make_game(game_id="sem", executable="sem", install_size=0, install_size_ts=0), {})
    vistas = _tarefas_vistas(monkeypatch)
    monkeypatch.setattr(
        install_size, "install_size_folder", lambda cmd: "C:/jogo" if cmd == "com" else ""
    )
    monkeypatch.setattr(install_size, "folder_size", lambda _pasta: 10)
    _thread_em_linha(install_size, monkeypatch)

    install_size.InstallSizeSweep().run_async()
    flush_idle()

    assert vistas == [("Tamanho em disco", 1)]
    assert tarefas.lista.rowCount() == 0


def test_tamanho_so_com_jogos_sem_pasta_nao_vira_tarefa(
    monkeypatch, store, make_game, win, flush_idle
):
    from cartridges.utils import install_size  # noqa: PLC0415

    win.sort_state = "name"
    jogo = make_game(game_id="sem", install_size=5000, install_size_ts=0)
    store.add_game(jogo, {})
    vistas = _tarefas_vistas(monkeypatch)
    monkeypatch.setattr(install_size, "install_size_folder", lambda _cmd: "")
    _thread_em_linha(install_size, monkeypatch)

    install_size.InstallSizeSweep().run_async()
    flush_idle()

    assert vistas == []
    assert jogo.install_size == 0  # o tamanho antigo continua sendo zerado
