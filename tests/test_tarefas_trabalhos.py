"""Cada trabalho em segundo plano aparece no quadro de tarefas enquanto roda."""

from types import SimpleNamespace

from cartridges.utils import tarefas


def _thread_em_linha(modulo, monkeypatch):
    monkeypatch.setattr(
        modulo.threading,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
    )


def _tarefas_vistas(monkeypatch):
    """Registra cada tarefa começada, com o total, e a última contagem."""
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
    assert tarefas.lista.get_n_items() == 0


def test_metadados_vira_tarefa_e_termina(monkeypatch, flush_idle):
    from tests.test_metadata_refresh import FakeManager, drive, make_game  # noqa: PLC0415
    from cartridges import shared  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415
    from tests.test_metadata_refresh import FakeStore  # noqa: PLC0415

    monkeypatch.setattr(shared, "store", FakeStore(), raising=False)
    refresh = MetadataRefresh()
    monkeypatch.setattr(refresh, "_announce", lambda *_a: None)
    vistas = _tarefas_vistas(monkeypatch)

    games = [make_game() for _ in range(2)]
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = 2
    refresh.running = True
    refresh._tarefa = tarefas.comecar("Metadados", 2)  # o que `start` faz
    flush_idle()
    drive(refresh, [FakeManager()])
    flush_idle()

    assert vistas == [("Metadados", 2)]
    assert tarefas.lista.get_n_items() == 0
