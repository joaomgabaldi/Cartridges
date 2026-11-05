# test_metadata_refresh.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Whole-library metadata refresh: the queue and its counters, and the preferences view of them."""

import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cartridges.metadata_refresh import MetadataRefresh  # noqa: E402
from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: E402


class FakeManager:
    """Stands in for the Steam and HowLongToBeat managers."""

    def __init__(self, on_process=None) -> None:
        self.processed: list = []
        self.resets = 0
        self._on_process = on_process

    def reset_cancellable(self) -> None:
        self.resets += 1

    def collect_errors(self):
        return []

    def process_game(self, game, additional_data, callback) -> None:
        self.processed.append((game, additional_data))
        if self._on_process:
            self._on_process(game)
        callback(self)


class FakeStore:
    """Only the id lookup the refresh does before saving a game."""

    def __init__(self) -> None:
        self.games_by_id: dict = {}

    def get(self, game_id, default=None):
        return self.games_by_id.get(game_id, default)


_counter = iter(range(1, 10_000))


def make_game(genre=None, appid=None):
    game = SimpleNamespace(
        game_id=f"imported_{next(_counter)}",
        genre=genre,
        steam_appid=appid,
        saved=0,
        updated=0,
    )
    game.save = lambda: setattr(game, "saved", game.saved + 1)
    game.update = lambda: setattr(game, "updated", game.updated + 1)
    return game



def complete_game(**overrides):
    """A game every source has answered for; a test says only what is missing."""
    game = make_game(genre="Metroidvania", appid="367520")
    game.developer = "Team Cherry"
    game.release_date = "Fev 2017"
    game.controller_support = "full"
    game.gamepad_recommended = True
    game.metacritic = 90
    game.steam_review = "Extremamente positivas"
    game.steam_checked = STEAM_METADATA_VERSION
    game.hltb_main = 90000
    game.hltb_chapters = None
    for field, value in overrides.items():
        setattr(game, field, value)
    # Mirrors Game.has_hltb_times, which is what the real rule reads.
    game.has_hltb_times = bool(game.hltb_main) or bool(game.hltb_chapters)
    return game


@pytest.fixture
def refresh(monkeypatch):
    """A refresh whose managers, store and toasts are stubbed out."""
    from cartridges import shared  # noqa: PLC0415

    monkeypatch.setattr(shared, "store", FakeStore(), raising=False)
    instance = MetadataRefresh()
    monkeypatch.setattr(instance, "_announce", lambda *_a: None)
    yield instance
    # `start` abre uma tarefa na lista global; um teste que não termina a fila a deixaria lá.
    from cartridges.modelos import tarefas  # noqa: PLC0415

    for tarefa in list(tarefas.lista._tarefas):  # noqa: SLF001
        tarefas.lista.remover(tarefa)


def drive(refresh_obj, managers, tags=None):
    """Run the queue synchronously; games go into the store first, since the refresh only saves games the library holds."""
    from cartridges import shared  # noqa: PLC0415

    for game in refresh_obj._queue:  # pylint: disable=protected-access
        shared.store.games_by_id[game.game_id] = game
    refresh_obj._managers = managers  # pylint: disable=protected-access
    refresh_obj._run_queue(tags or {})  # pylint: disable=protected-access


# region The run itself


def test_counters_track_the_queue(refresh, monkeypatch) -> None:
    monkeypatch.setattr(refresh, "_finish", lambda: None)
    games = [make_game() for _ in range(4)]
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = 4
    refresh.running = True

    drive(refresh, [FakeManager()])

    assert refresh.done == 4
    assert refresh.fraction == pytest.approx(1)
    assert all(game.saved == 1 and game.updated == 1 for game in games)


def test_every_manager_runs_before_the_game_is_saved(refresh, monkeypatch) -> None:
    """Saving between managers would persist a half-updated record."""
    saves_seen = []
    steam = FakeManager()
    hltb = FakeManager(on_process=lambda game: saves_seen.append(game.saved))
    monkeypatch.setattr(refresh, "_finish", lambda: None)
    refresh._queue = [make_game()]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True

    drive(refresh, [steam, hltb])

    assert saves_seen == [0]
    assert len(steam.processed) == len(hltb.processed) == 1


def test_prefetched_tags_reach_the_managers(refresh, monkeypatch) -> None:
    monkeypatch.setattr(refresh, "_finish", lambda: None)
    manager = FakeManager()
    refresh._queue = [make_game()]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True

    drive(refresh, [manager], tags={"2519060": [1663]})

    assert manager.processed[0][1]["steam_tags"] == {"2519060": [1663]}


def test_cancel_stops_between_games(refresh, monkeypatch) -> None:
    monkeypatch.setattr(refresh, "_finish", lambda: None)
    manager = FakeManager(on_process=lambda _game: refresh.cancel())
    refresh._queue = [make_game() for _ in range(5)]  # pylint: disable=protected-access
    refresh.total = 5
    refresh.running = True

    drive(refresh, [manager])

    assert len(manager.processed) == 1
    assert refresh.done == 1


def test_cancel_while_idle_does_nothing(refresh) -> None:
    refresh.cancel()
    assert not refresh.cancelled


def test_start_refuses_an_empty_selection(refresh) -> None:
    assert refresh.start([]) is False
    assert not refresh.running


def test_a_fully_looked_up_game_needs_nothing(refresh) -> None:
    assert refresh.needs_steam(complete_game()) is False
    assert refresh.needs_hltb(complete_game()) is False
    assert refresh.is_incomplete(complete_game()) is False


def test_each_source_is_asked_for_separately(refresh) -> None:
    """A game short of completion times and another short of genre must not drag each other's lookups."""
    only_hltb = complete_game(hltb_main=0, hltb_chapters=None)
    only_steam = complete_game(genre=None)

    assert (refresh.needs_steam(only_hltb), refresh.needs_hltb(only_hltb)) == (False, True)
    assert (refresh.needs_steam(only_steam), refresh.needs_hltb(only_steam)) == (True, False)


def test_missing_developer_or_release_date_brings_steam_back(refresh) -> None:
    """Fields every successful lookup produces: empty means never looked up."""
    assert refresh.needs_steam(complete_game(developer=None)) is True
    assert refresh.needs_steam(complete_game(release_date=None)) is True


def test_a_game_never_matched_on_steam_is_always_incomplete(refresh) -> None:
    assert refresh.needs_steam(complete_game(steam_appid=None)) is True


def test_an_older_stamp_brings_the_game_back_once(refresh) -> None:
    """How a field added after the game was imported ever gets filled in."""
    assert refresh.needs_steam(complete_game(steam_checked=0)) is True
    assert refresh.needs_steam(complete_game(steam_checked=STEAM_METADATA_VERSION)) is False


def test_legitimately_empty_fields_are_not_treated_as_gaps(refresh) -> None:
    """Fresh from the API most games lack gamepad/controller data; reading that as work would requeue the whole library every run."""
    for field in ("gamepad_recommended", "controller_support", "metacritic", "steam_review"):
        game = complete_game(**{field: None if field != "gamepad_recommended" else False})
        assert refresh.needs_steam(game) is False, field


def test_fraction_is_zero_before_anything_starts(refresh) -> None:
    assert refresh.fraction == pytest.approx(0)


def test_a_wiped_library_is_not_written_back(refresh, monkeypatch) -> None:
    """A refresh still walking its list after a reset must not save the deleted games back to disk."""
    from cartridges import shared  # noqa: PLC0415

    monkeypatch.setattr(refresh, "_finish", lambda: None)
    games = [make_game() for _ in range(3)]
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = 3
    refresh.running = True

    manager = FakeManager(on_process=lambda _game: shared.store.games_by_id.clear())
    drive(refresh, [manager])

    assert all(game.saved == 0 for game in games)
    assert all(game.updated == 0 for game in games)
    # The queue still drains, so the run ends instead of hanging
    assert refresh.done == 3


def test_a_reimported_game_is_not_overwritten(refresh) -> None:
    """Same id, different record: writing it would undo the import that replaced it."""
    from cartridges import shared  # noqa: PLC0415

    game = make_game()
    replacement = make_game()
    replacement.game_id = game.game_id

    refresh._queue = [game]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True
    drive(
        refresh,
        [
            FakeManager(
                on_process=lambda _g: shared.store.games_by_id.update(
                    {game.game_id: replacement}
                )
            )
        ],
    )

    assert game.saved == 0
    assert replacement.saved == 0


def _esperar_a_prefetch(antes):
    """Só a thread que o `start` criou: as do pool de rede do app ficam vivas pelo processo todo."""
    for thread in set(threading.enumerate()) - antes:
        thread.join(timeout=5)


def test_prefetch_failure_does_not_wedge_the_run(refresh, monkeypatch) -> None:
    """Anything escaping the prefetch thread left `running` True, blocking every later refresh."""
    from cartridges import metadata_refresh, shared  # noqa: PLC0415
    from cartridges.store.managers.hltb_manager import HLTBManager  # noqa: PLC0415
    from cartridges.store.managers.steam_api_manager import (  # noqa: PLC0415
        SteamAPIManager,
    )

    class Exploding:
        def reset_cancellable(self) -> None:
            pass

        @property
        def steam_api_helper(self):
            raise AttributeError("boom")

    scheduled: list = []
    monkeypatch.setattr(metadata_refresh, "na_thread_principal", lambda *args: scheduled.append(args))
    shared.store.managers = {
        SteamAPIManager: Exploding(),
        HLTBManager: Exploding(),
    }

    antes = set(threading.enumerate())
    assert refresh.start([make_game(appid="440")]) is True
    _esperar_a_prefetch(antes)

    # A failed bulk request yields the same empty mapping: every genre stays as it is.
    assert scheduled and scheduled[-1][1] == {}


def test_prefetch_stringifies_a_numeric_appid(refresh, monkeypatch) -> None:
    """A hand-edited record can hold the appid unquoted; the manager looks tags up under `str(appid)`."""
    from cartridges import metadata_refresh, shared  # noqa: PLC0415
    from cartridges.store.managers.hltb_manager import HLTBManager  # noqa: PLC0415
    from cartridges.store.managers.steam_api_manager import (  # noqa: PLC0415
        SteamAPIManager,
    )

    asked: list = []

    class Recording:
        def reset_cancellable(self) -> None:
            pass

        @property
        def steam_api_helper(self):
            return SimpleNamespace(
                get_store_tags_bulk=lambda appids, should_stop=None: asked.append(
                    appids
                )
                or {}
            )

    monkeypatch.setattr(metadata_refresh, "na_thread_principal", lambda *args: None)
    shared.store.managers = {
        SteamAPIManager: Recording(),
        HLTBManager: Recording(),
    }

    antes = set(threading.enumerate())
    refresh.start([make_game(appid=440)])
    _esperar_a_prefetch(antes)

    assert asked == [["440"]]


# endregion
# region The preferences as a view onto it


@pytest.fixture
def preferences(monkeypatch):
    """The real preferences model, wired to a refresh under our control."""
    from cartridges import metadata_refresh  # noqa: PLC0415
    from cartridges.modelos.preferencias import Preferencias  # noqa: PLC0415

    instance = MetadataRefresh()
    monkeypatch.setattr(metadata_refresh, "get_metadata_refresh", lambda: instance)
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir()
    yield modelo, instance
    modelo.fechar()


def _contar(biblioteca):
    avisos: list = []
    biblioteca.alterado.connect(lambda: avisos.append(1))
    return avisos


def test_row_starts_idle(preferences) -> None:
    modelo, _refresh = preferences
    biblioteca = modelo.biblioteca

    assert biblioteca.rodando is False
    assert biblioteca.fracao == pytest.approx(0)
    assert biblioteca.baixandoCapas is False


def test_dialog_opened_mid_run_shows_the_current_position(preferences) -> None:
    """Close the dialog at game 12 of 47, reopen it: the bar must still say 12 of 47."""
    from cartridges.modelos.preferencias import Preferencias  # noqa: PLC0415

    _modelo, refresh = preferences
    refresh.running = True
    refresh.done = 12
    refresh.total = 47

    reaberto = Preferencias(None, lambda: True)
    assert reaberto.abrir()
    try:
        assert reaberto.biblioteca.rodando is True
        assert reaberto.biblioteca.progresso == "12 de 47"
        assert reaberto.biblioteca.fracao == pytest.approx(12 / 47)
    finally:
        reaberto.fechar()


def test_progress_signal_updates_an_open_dialog(preferences) -> None:
    modelo, refresh = preferences
    alterados = _contar(modelo.biblioteca)
    refresh.running = True
    refresh.done = 3
    refresh.total = 12
    refresh.progress.emit()

    assert alterados
    assert modelo.biblioteca.progresso == "3 de 12"
    assert modelo.biblioteca.fracao == pytest.approx(0.25)


def test_finishing_returns_the_row_to_idle(preferences) -> None:
    modelo, refresh = preferences
    alterados = _contar(modelo.biblioteca)
    refresh.running = True
    refresh.done = 12
    refresh.total = 12
    refresh.progress.emit()
    assert modelo.biblioteca.rodando is True
    refresh.running = False
    refresh.progress.emit()

    assert modelo.biblioteca.rodando is False
    assert len(alterados) == 2


def test_closed_dialog_stops_following_the_run(preferences) -> None:
    """The handler holds the view alive, so it goes on close; a stale view must not react to later runs."""
    modelo, refresh = preferences
    modelo.fechar()
    alterados = _contar(modelo.biblioteca)
    refresh.running = True
    refresh.done = 9
    refresh.total = 9
    refresh.progress.emit()

    assert not alterados


def test_row_is_insensitive_when_both_sources_are_off(preferences) -> None:
    """Both managers no-op with their setting off, so the button would walk the library and change nothing."""
    from cartridges import shared  # noqa: PLC0415

    modelo, _refresh = preferences
    alterados = _contar(modelo.biblioteca)
    shared.schema.set_boolean("steam-metadata", False)
    shared.schema.set_boolean("hltb-metadata", False)
    assert modelo.biblioteca.metadadosAtivos is False
    assert alterados

    shared.schema.set_boolean("hltb-metadata", True)
    assert modelo.biblioteca.metadadosAtivos is True


def test_cancel_button_greys_out_once_pressed(preferences) -> None:
    modelo, refresh = preferences
    refresh.running = True
    refresh.total = 5
    assert modelo.biblioteca.cancelado is False
    modelo.biblioteca.cancelarMetadados()

    assert refresh.cancelled
    assert modelo.biblioteca.cancelado is True


def test_aviso_do_fim_vai_pela_fila_do_app(avisos) -> None:
    MetadataRefresh._announce(3, 5, False)
    MetadataRefresh._announce(1, 1, False)
    MetadataRefresh._announce(3, 5, True)

    assert avisos.textos == [
        "Metadados atualizados: 3 jogos",
        "Metadados atualizados: 1 jogo",
        "Atualização cancelada após 3 de 5 jogos",
    ]


def test_aviso_do_fim_sem_aplicativo_nao_levanta(monkeypatch) -> None:
    from cartridges import shared  # noqa: PLC0415

    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    MetadataRefresh._announce(2, 2, False)  # não levanta
    assert shared.aplicativo is None


def test_metadata_refresh_sem_gi() -> None:
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; "
        "builtins.ngettext = lambda s, p, n: s if n == 1 else p; "
        "import cartridges.metadata_refresh; "
        "assert 'gi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", codigo], check=True, cwd=Path(__file__).resolve().parent.parent, timeout=60)


# endregion


def test_only_missing_runs_just_the_sources_each_game_needs(refresh) -> None:
    """A (times) costs one HowLongToBeat lookup; B (controller support), C (genre), D (developer) cost Steam only. B shows only through the older stamp."""
    from cartridges import shared  # noqa: PLC0415

    game_a = complete_game(hltb_main=0)
    game_b = complete_game(controller_support=None, steam_checked=0)
    game_c = complete_game(genre=None)
    game_d = complete_game(developer=None)
    games = [game_a, game_b, game_c, game_d]
    for game in games:
        shared.store.games_by_id[game.game_id] = game

    steam, hltb = FakeManager(), FakeManager()
    refresh._managers = [steam, hltb]  # pylint: disable=protected-access
    refresh._only_missing = True  # pylint: disable=protected-access
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = len(games)
    refresh.running = True
    refresh._run_queue({})  # pylint: disable=protected-access

    assert [g for g, _ in steam.processed] == [game_b, game_c, game_d]
    assert [g for g, _ in hltb.processed] == [game_a]


def test_fetch_everything_ignores_what_is_already_there(refresh) -> None:
    """The other half of the promise: "fetch everything" really does."""
    from cartridges import shared  # noqa: PLC0415

    games = [complete_game() for _ in range(3)]
    for game in games:
        shared.store.games_by_id[game.game_id] = game

    steam, hltb = FakeManager(), FakeManager()
    refresh._managers = [steam, hltb]  # pylint: disable=protected-access
    refresh._only_missing = False  # pylint: disable=protected-access
    refresh._queue = list(games)  # pylint: disable=protected-access
    refresh.total = 3
    refresh.running = True
    refresh._run_queue({})  # pylint: disable=protected-access

    assert len(steam.processed) == 3
    assert len(hltb.processed) == 3


def test_steam_stays_ahead_of_hltb_when_both_run(refresh) -> None:
    """HowLongToBeat searches by title and the Steam lookup corrects it: per-game source selection must not reorder them."""
    game = complete_game(developer=None, hltb_main=0)
    steam, hltb = FakeManager(), FakeManager()
    refresh._managers = [steam, hltb]  # pylint: disable=protected-access
    refresh._only_missing = True  # pylint: disable=protected-access

    assert refresh.managers_for(game) == [steam, hltb]


def test_a_game_needing_nothing_gets_no_lookups(refresh) -> None:
    refresh._only_missing = True  # pylint: disable=protected-access
    refresh._managers = [FakeManager(), FakeManager()]  # pylint: disable=protected-access

    assert refresh.managers_for(complete_game()) == []


def test_fetch_everything_forces_the_completion_times_too(refresh) -> None:
    """HowLongToBeat skips games that already have times unless told otherwise, so "fetch everything" needs the flag."""
    from cartridges import shared  # noqa: PLC0415

    game = complete_game()
    shared.store.games_by_id[game.game_id] = game

    manager = FakeManager()
    refresh._managers = [manager]  # pylint: disable=protected-access
    refresh._only_missing = False  # pylint: disable=protected-access
    refresh._queue = [game]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True
    refresh._run_queue({})  # pylint: disable=protected-access

    assert manager.processed[0][1]["refresh_hltb"] is True


def test_only_missing_never_forces_them(refresh) -> None:
    """In only-missing mode games with times are not queued for HowLongToBeat, so forcing a refetch would waste requests."""
    from cartridges import shared  # noqa: PLC0415

    game = complete_game(hltb_main=0)
    shared.store.games_by_id[game.game_id] = game

    manager = FakeManager()
    refresh._managers = [FakeManager(), manager]  # pylint: disable=protected-access
    refresh._only_missing = True  # pylint: disable=protected-access
    refresh._queue = [game]  # pylint: disable=protected-access
    refresh.total = 1
    refresh.running = True
    refresh._run_queue({})  # pylint: disable=protected-access

    assert manager.processed[0][1]["refresh_hltb"] is False


def _fully_looked_up(stamp):
    """A game with everything Steam produces, carrying ``stamp``."""
    game = make_game(genre="g", appid="440")
    game.developer = "d"
    game.release_date = "2020"
    game.steam_checked = stamp
    return game


@pytest.mark.parametrize("stamp", [None, "", [], {}, object(), "abc"])
def test_an_unreadable_version_stamp_reads_as_unchecked(refresh, stamp) -> None:
    """`needs_steam` runs over the whole library on the main thread: one unreadable stamp must not raise; it counts as "never looked up"."""
    assert refresh.needs_steam(_fully_looked_up(stamp)) is True


@pytest.mark.parametrize("as_type,expected", [(str, False), (float, False)])
def test_a_readable_stamp_is_honoured_whatever_its_type(
    refresh, as_type, expected
) -> None:
    """A number written as a string is still a number; derived from the constant so a version bump cannot leave it stale."""
    from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: PLC0415

    stamp = as_type(STEAM_METADATA_VERSION)
    assert refresh.needs_steam(_fully_looked_up(stamp)) is expected


def test_a_fractional_stamp_errs_towards_looking_again(refresh) -> None:
    """Truncation has to round down, never up onto the current version."""
    from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: PLC0415

    assert refresh.needs_steam(_fully_looked_up(STEAM_METADATA_VERSION - 0.5)) is True


def test_a_usable_stamp_still_short_circuits(refresh) -> None:
    """The guard must not turn every game into work."""
    from cartridges.utils.steam import STEAM_METADATA_VERSION

    game = make_game(genre="g", appid="440")
    game.developer = "d"
    game.release_date = "2020"
    game.steam_checked = STEAM_METADATA_VERSION

    assert refresh.needs_steam(game) is False
    game.steam_checked = STEAM_METADATA_VERSION - 1
    assert refresh.needs_steam(game) is True


def test_only_missing_mode_fills_gaps_without_reverting_edits() -> None:
    """Only-missing fills only empty editable fields (name, developer); non-editable ones (Metacritic etc.) always update."""
    from cartridges.store.managers.steam_api_manager import _keep_user_edits

    game = SimpleNamespace(
        name="Witcher 3",
        developer="Editado à mão",
        publisher=None,
        release_date="",
        genre=None,
    )
    online = {
        "name": "The Witcher 3: Wild Hunt",
        "developer": "CD PROJEKT RED",
        "publisher": "CD PROJEKT RED",
        "release_date": "2015",
        "genre": "RPG",
        "metacritic": 93,
    }

    kept = _keep_user_edits(game, online, {"only_missing": True})
    assert kept == {
        "publisher": "CD PROJEKT RED",
        "release_date": "2015",
        "genre": "RPG",
        "metacritic": 93,
    }

    # Fora do modo (importação, "buscar tudo"), nada muda.
    assert _keep_user_edits(game, online, {}) == online
