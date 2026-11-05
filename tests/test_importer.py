# test_importer.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When it is safe to mark a game as missing.

``remove_games`` is licensed only by the source's id being in ``scanned_source_ids``, granted only for a scan that ran to the end.
A generator that raises is closed, so the loop ends with the same ``StopIteration`` as a clean finish: it needs its own flag.
"""

import pytest

from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.errors.friendly_error import FriendlyError
from cartridges.importer.importer import Importer
from cartridges.importer.source import SourceScanError


@pytest.fixture(autouse=True)
def tarefas_vazias(app_qt, flush_idle):  # noqa: ARG001
    from cartridges.modelos import tarefas  # noqa: PLC0415

    yield
    flush_idle(0.05)
    for tarefa in list(tarefas.lista._tarefas):  # noqa: SLF001
        tarefas.lista.remover(tarefa)


class FakeSource:
    """A source whose scan behaviour each test dictates."""

    def __init__(
        self,
        source_id="shortcuts",
        games=(),
        raises=None,
        raise_after=0,
        available=True,
    ):
        self.source_id = source_id
        self.name = source_id
        self._games = list(games)
        self._raises = raises
        self._raise_after = raise_after
        self.is_available = available

    def __iter__(self):
        return self._generate()

    def _generate(self):
        # Yielded as ``(game, additional_data)`` tuples, as every real source does: a duck-typed game would be skipped by the importer.
        for index, game in enumerate(self._games):
            if self._raises is not None and index == self._raise_after:
                raise self._raises
            yield (game, {})
        if self._raises is not None and self._raise_after >= len(self._games):
            raise self._raises


@pytest.fixture
def importer(store):
    """An Importer wired to a clean store (``Importer.__init__`` resets the store's id bookkeeping, so the store fixture comes first)."""
    return Importer(Aplicativo())


def scan(importer_, source):
    importer_.source_task_thread_func((source,))


def test_clean_scan_marks_the_source(importer, make_game):
    scan(importer, FakeSource(games=[make_game(game_id="shortcuts_1")]))
    assert "shortcuts" in importer.scanned_source_ids


def test_generic_exception_does_not_mark_the_source(importer, make_game):
    """The regression: a failed scan reaching the same StopIteration."""
    source = FakeSource(
        games=[make_game(game_id="shortcuts_1")],
        raises=OSError("drive went away mid-scan"),
        raise_after=1,
    )
    scan(importer, source)

    assert "shortcuts" not in importer.scanned_source_ids
    assert any(isinstance(error, OSError) for error in importer.errors)


def test_source_scan_error_does_not_mark_and_reaches_the_user(importer):
    """A scan that quietly produces half a library is worse than one that says so."""
    source = FakeSource(
        raises=SourceScanError("Não foi possível ler os atalhos", "PowerShell ausente")
    )
    scan(importer, source)

    assert "shortcuts" not in importer.scanned_source_ids
    errors = [e for e in importer.errors if isinstance(e, SourceScanError)]
    assert errors
    # A FriendlyError is what makes the importer's warning dialog show it.
    assert isinstance(errors[0], FriendlyError)
    assert errors[0].title == "Não foi possível ler os atalhos"


def test_unavailable_source_does_not_mark(importer):
    """A disconnected drive is not "every game was uninstalled"."""
    scan(importer, FakeSource(available=False))
    assert importer.scanned_source_ids == set()


def test_partial_scan_keeps_its_games_but_not_the_licence(importer, make_game, store):
    """Progress is kept; the authority to delete is not."""
    games = [make_game(game_id=f"shortcuts_{i}") for i in range(3)]
    source = FakeSource(games=games, raises=RuntimeError("boom"), raise_after=3)

    scan(importer, source)

    assert len(store) == 3
    assert "shortcuts" not in importer.scanned_source_ids


def test_remove_games_skips_an_unscanned_source(importer, make_game, store):
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()

    importer.remove_games()

    assert game.removed is False


def test_remove_games_removes_a_missing_game_of_a_scanned_source(
    importer, make_game, store
):
    """The positive control for every skip below."""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    importer.scanned_source_ids.add("shortcuts")

    importer.remove_games()

    assert game.removed is True
    assert "shortcuts_1" in importer.removed_game_ids


def test_remove_games_leaves_a_zerado_alone(importer, make_game, store):
    game = make_game(game_id="shortcuts_1", removed=True, status="beaten")
    store.add_game(game, {"skip_save": True})
    importer.scanned_source_ids.add("shortcuts")

    importer.remove_games()

    assert game.saves == 0
    assert "shortcuts_1" not in importer.removed_game_ids


@pytest.mark.parametrize("bucket", ["duplicate_game_ids", "new_game_ids"])
def test_remove_games_skips_games_seen_this_run(importer, make_game, store, bucket):
    """A game the scan just saw is not missing."""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()
    getattr(store, bucket).add("shortcuts_1")
    importer.scanned_source_ids.add("shortcuts")

    importer.remove_games()

    assert game.removed is False


def test_remove_games_skips_manually_added_games(importer, make_game, store):
    """"imported" games have no source to go missing from."""
    game = make_game(game_id="imported_1", source="imported")
    store.add_game(game, {})
    store.new_game_ids = set()
    importer.scanned_source_ids.add("imported")

    importer.remove_games()

    assert game.removed is False


def test_remove_games_skips_a_source_disabled_in_the_schema(
    importer, make_game, store, schema
):
    """A source the user turned off did not scan, whatever the ids say."""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    importer.scanned_source_ids.add("shortcuts")
    schema["shortcuts"] = False

    importer.remove_games()

    assert game.removed is False


def test_remove_missing_disabled_removes_nothing(importer, make_game, store, schema):
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    importer.scanned_source_ids.add("shortcuts")
    schema["remove-missing"] = False

    importer.remove_games()

    assert game.removed is False


def test_a_successful_empty_scan_still_removes(importer, make_game, store):
    """An emptied folder is a real answer, not a failure: only the completion flag tells it from a source that failed."""
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()

    scan(importer, FakeSource(games=[]))
    assert "shortcuts" in importer.scanned_source_ids

    importer.remove_games()

    assert game.removed is True


def test_a_tombstone_is_not_removed_again(importer, make_game, store):
    """Already-removed games are skipped, so undo history stays meaningful."""
    game = make_game(game_id="shortcuts_1", removed=True)
    store.add_game(game, {})
    importer.scanned_source_ids.add("shortcuts")

    importer.remove_games()

    assert importer.removed_game_ids == set()


# region Tarefas em andamento


def test_importacao_sem_jogo_novo_nao_vira_tarefa(importer, monkeypatch, flush_idle):
    from cartridges.modelos import tarefas  # noqa: PLC0415

    monkeypatch.setattr(importer, "finish_import", lambda: None)
    importer.n_source_tasks_created = 1
    importer.n_source_tasks_done = 0
    importer.monitor_import()
    importer.n_source_tasks_done = 1  # a verificação acabou sem achar nada
    importer.monitor_import()
    flush_idle()
    assert tarefas.lista.rowCount() == 0


def test_jogo_novo_vira_tarefa_que_termina_com_a_importacao(importer, monkeypatch, flush_idle):
    from cartridges.modelos import tarefas  # noqa: PLC0415

    monkeypatch.setattr(importer, "finish_import", lambda: None)
    importer.n_source_tasks_created = 1
    importer.game_pipelines.update({object(), object()})
    importer.monitor_import()
    flush_idle()
    lista = tarefas.lista
    assert [lista.data(lista.index(0), papel) for papel in (lista.NOME, lista.FEITOS, lista.TOTAL)] == ["Importação", 0, 2]

    importer.n_pipelines_done = 2
    importer.n_source_tasks_done = 1
    assert importer.monitor_import() is False
    flush_idle()
    assert tarefas.lista.rowCount() == 0


def test_monitor_so_atualiza_a_tarefa_quando_o_progresso_muda(importer, monkeypatch, flush_idle):
    from cartridges.modelos import tarefas  # noqa: PLC0415

    monkeypatch.setattr(importer, "finish_import", lambda: None)
    importer.n_source_tasks_created = 1
    importer.game_pipelines.update({object(), object()})
    importer.monitor_import()
    flush_idle()
    tarefa = tarefas.lista._tarefas[0]  # noqa: SLF001
    chamadas = []
    monkeypatch.setattr(tarefa, "atualizar", lambda *args: chamadas.append(args))

    importer.monitor_import()
    importer.monitor_import()
    assert chamadas == []  # o par (0, 2) já foi entregue

    importer.n_pipelines_done = 1
    importer.monitor_import()
    importer.monitor_import()
    assert chamadas == [(1, 2)]


# endregion


# region Conquistas dos jogos importados


def _terminar_importacao(importer, monkeypatch, varredura, importados, na_store):
    for jogo in na_store:
        shared.store.add_game(jogo, {}, run_pipeline=False)
    shared.store.new_game_ids = set(importados)
    app = importer.aplicativo
    app.varredura_conquistas = varredura
    app.definir_importando(True)
    importer.finish_import()
    return app


def test_fim_da_importacao_pede_a_varredura_dos_jogos_importados(
    importer, make_game, monkeypatch
):
    a = make_game(game_id="shortcuts_a", steam_appid="570")
    b = make_game(game_id="shortcuts_b", steam_appid="620")
    antigo = make_game(game_id="shortcuts_c", steam_appid="730")
    pedidos = []
    varredura = type("V", (), {"varrer_jogos": lambda _s, jogos: pedidos.append(list(jogos))})()
    app = _terminar_importacao(
        importer, monkeypatch, varredura, {"shortcuts_a", "shortcuts_b", "x_sumido"},
        [a, b, antigo],
    )
    assert len(pedidos) == 1
    assert {j.game_id for j in pedidos[0]} == {"shortcuts_a", "shortcuts_b"}
    assert app.importando is False  # depois de o estado voltar ao normal


def test_fim_da_importacao_sem_jogo_novo_nao_pede_varredura(
    importer, make_game, monkeypatch
):
    pedidos = []
    varredura = type("V", (), {"varrer_jogos": lambda _s, jogos: pedidos.append(list(jogos))})()
    _terminar_importacao(
        importer, monkeypatch, varredura, set(), [make_game(game_id="shortcuts_c")]
    )
    assert pedidos == []


def test_varredura_que_estoura_nao_derruba_o_fim_da_importacao(
    importer, make_game, monkeypatch
):
    def estoura(_s, _jogos):
        raise RuntimeError("falhou")

    varredura = type("V", (), {"varrer_jogos": estoura})()
    terminou = []
    importer.ao_terminar = lambda: terminou.append(1)
    _terminar_importacao(
        importer, monkeypatch, varredura, {"shortcuts_a"},
        [make_game(game_id="shortcuts_a", steam_appid="570")],
    )
    assert terminou == [1]


def test_fim_da_importacao_sem_varredura_nao_levanta(importer, make_game, monkeypatch):
    terminou = []
    importer.ao_terminar = lambda: terminou.append(1)
    _terminar_importacao(
        importer, monkeypatch, None, {"shortcuts_a"}, [make_game(game_id="shortcuts_a")]
    )
    assert terminou == [1]


# endregion


# region Fim da importação e jogo adicionado à mão


def test_fim_da_importacao_roda_uma_vez_mesmo_com_erro(importer, monkeypatch):
    from PySide6.QtCore import QTimer  # noqa: PLC0415

    chamadas, terminou = [], []

    def estoura():
        chamadas.append(1)
        raise RuntimeError("falhou")

    monkeypatch.setattr(importer, "resolver_pendencias", estoura)
    importer.ao_terminar = lambda: terminou.append(1)
    importer._relogio = QTimer()  # noqa: SLF001
    importer._relogio.start(100)  # noqa: SLF001
    importer.aplicativo.definir_importando(True)

    importer._tic()  # noqa: SLF001
    importer._tic()  # noqa: SLF001

    assert chamadas == [1]
    assert not importer._relogio.isActive()  # noqa: SLF001
    assert importer.aplicativo.importando is False
    assert terminou == [1]


def test_erro_no_fim_nao_perde_os_jogos_importados(importer, make_game, monkeypatch):
    def estoura():
        raise RuntimeError("falhou")

    monkeypatch.setattr(importer, "resolver_pendencias", estoura)
    pedidos = []
    varredura = type("V", (), {"varrer_jogos": lambda _s, jogos: pedidos.append(list(jogos))})()
    _terminar_importacao(
        importer, monkeypatch, varredura, {"shortcuts_a"},
        [make_game(game_id="shortcuts_a", steam_appid="570")],
    )
    assert importer.imported_game_ids == {"shortcuts_a"}
    assert shared.store.new_game_ids == set()
    assert [[j.game_id for j in p] for p in pedidos] == [["shortcuts_a"]]


def test_terminar_que_levanta_nao_prende_a_importacao(importer, monkeypatch):
    from PySide6.QtCore import QTimer  # noqa: PLC0415

    class Tarefa:
        def atualizar(self, *_):
            pass

        def terminar(self):
            raise RuntimeError("falhou")

    terminou = []
    importer.ao_terminar = lambda: terminou.append(1)
    importer.tarefa = Tarefa()
    importer._relogio = QTimer()  # noqa: SLF001
    importer._relogio.start(100)  # noqa: SLF001
    importer.aplicativo.definir_importando(True)
    monkeypatch.setattr(type(importer), "finished", property(lambda _: True))
    importer._tic()  # noqa: SLF001
    assert not importer._relogio.isActive()  # noqa: SLF001
    assert importer.tarefa is None
    assert importer.aplicativo.importando is False
    assert terminou == [1]


# endregion
