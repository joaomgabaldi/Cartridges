# conftest.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Test harness for the parts of Cartridges that need the app's own runtime.

Runs against the **real** GTK stack from MSYS2 (``C:\\msys64\\ucrt64``), not a
stub. That was a choice between two costs: a stub of ``gi`` runs anywhere and is
fast, but it has to reimplement GObject signals, ``Gtk.Template`` and the GLib
main loop well enough that a test failure means something — and everything the
stub gets subtly wrong turns into a test that passes while the app breaks. The
real stack is already installed here (it is what the app runs on), so the stub
would be inventing a second, worse copy of something we have.

Two things still have to be faked, and both for the same reason: they are
generated at build time and would otherwise point at the user's real data.

* ``cartridges.shared`` is produced by meson from ``shared.py.in`` and does not
  exist in the source tree. It is synthesised here instead of being read from
  ``_build``, because the real one calls ``Gio.Settings.new`` (which aborts the
  process when the schema is not installed) and resolves ``games_dir`` to the
  live library. A test that deletes a game must never be able to delete a real
  one.
* ``shared.win`` is the application window. Only the two mappings the store
  touches are provided; anything else is a test reaching further than it should.

The gresource has to be registered before ``cartridges.game`` is imported —
its ``Gtk.Template`` reads the .ui out of it at class-creation time.
"""

import builtins
import json
import sys
import types
from enum import IntEnum, auto
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The UI is hardcoded in pt-BR and `cartridges.in` installs these as builtins;
# module bodies call `_()` at class-definition time, so they must exist first.
builtins._ = lambda message: message  # type: ignore[attr-defined]
builtins.ngettext = (  # type: ignore[attr-defined]
    lambda singular, plural, n: singular if n == 1 else plural
)

import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio, GLib  # noqa: E402

_GRESOURCE = ROOT / "_build" / "data" / "cartridges.gresource"
if not _GRESOURCE.is_file():  # pragma: no cover - environment guard
    raise RuntimeError(
        f"{_GRESOURCE} is missing. Build once with `meson setup _build && "
        "ninja -C _build` so the templates can be loaded."
    )
Gio.Resource.load(str(_GRESOURCE))._register()  # pylint: disable=protected-access

# Both are needed before any template class is *instantiated*: the .ui files
# name Adwaita types, and a GType that has not been registered yet makes
# Gtk.Builder fail with "Invalid object type 'AdwClamp'" — which surfaces much
# later as an attribute being None, not as the template error it really is.
from gi.repository import Adw, Gtk  # noqa: E402

Gtk.init()
Adw.init()


# Defaults copied from data/page.kramo.Cartridges.gschema.xml.in. Copied rather
# than parsed so a test that depends on one of these values fails loudly when
# the schema changes underneath it, instead of quietly following it.
_SCHEMA_DEFAULTS = {
    "auto-import": False,
    "minimize-after-launch": False,
    "cover-launches-game": False,
    "playtime-tracking": True,
    "process-tracking-grace": 5,
    "session-move-window": False,
    "session-monitor": "",
    "session-wallpaper": False,
    "session-wallpaper-saved": "",
    "fita-brilho-padrao": 180,
    "fita-matiz-app": 284,
    "fita-saturacao-app": 620,
    "session-fita": False,
    "fita-estado-anterior": "",
    "wallhaven-key": "",
    "remove-missing": True,
    "shortcuts": True,
    "shortcuts-location": "",
    "shortcuts-recursive": True,
    "steam-metadata": True,
    "hltb-metadata": True,
    "sgdb-key": "",
    "sgdb": False,
    "sgdb-prefer": False,
    "sgdb-animated": False,
    "library-rows": 0,
    "gamepad": False,
    "gamepad-rumble": True,
    "updates-check-interval": 12,
    "news-check-interval": 6,
    "sort-mode": "last_played",
}

_STATE_DEFAULTS = {
    "width": 1170,
    "height": 795,
    "is-maximized": False,
    "x": -2147483648,
    "y": -2147483648,
    "steam-limiter-tokens-history": "[]",
    "news-last-seen-ts": 0,
}


class FakeSchema:
    """Dict-backed stand-in for ``Gio.Settings``.

    Typed getters are kept separate (rather than one ``get``) so a test that
    asks for the wrong type fails here instead of somewhere downstream.
    """

    def __init__(self, values: dict) -> None:
        self._values = dict(values)
        self.handlers: list[tuple[str, object]] = []

    def list_keys(self) -> list[str]:
        return list(self._values)

    def get_boolean(self, key: str) -> bool:
        return bool(self._values[key])

    def get_int(self, key: str) -> int:
        return int(self._values[key])

    def get_uint(self, key: str) -> int:
        return int(self._values[key])

    def get_int64(self, key: str) -> int:
        return int(self._values[key])

    def get_string(self, key: str) -> str:
        return str(self._values[key])

    def set_boolean(self, key: str, value: bool) -> None:
        self._values[key] = bool(value)

    def set_int(self, key: str, value: int) -> None:
        self._values[key] = int(value)

    def set_int64(self, key: str, value: int) -> None:
        self._values[key] = int(value)

    def set_string(self, key: str, value: str) -> None:
        self._values[key] = str(value)

    def __setitem__(self, key: str, value) -> None:
        self._values[key] = value

    def connect(self, signal: str, callback) -> int:
        self.handlers.append((signal, callback))
        return len(self.handlers)

    def bind(self, *_args, **_kwargs) -> None:
        return None


class FakeToastQueue:
    def __init__(self) -> None:
        self.added: list = []
        self.dismissed: list = []

    def add(self, toast) -> None:
        self.added.append(toast)

    def dismiss(self, toast) -> None:
        self.dismissed.append(toast)

    def dismiss_after(self, toast, _seconds) -> None:
        self.dismissed.append(toast)


class FakeAction:
    def __init__(self) -> None:
        self.enabled = True

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeApplication:
    """``Game.__init__`` takes a reference to the application."""

    def __init__(self) -> None:
        self.state = AppState.DEFAULT
        self.activated: list = []
        self._actions: dict = {}

    def activate_action(self, name, target=None) -> None:
        self.activated.append((name, target))

    def lookup_action(self, name) -> FakeAction:
        return self._actions.setdefault(name, FakeAction())


class FakeWindow:
    """Only what the store, the session and a Game reach for."""

    def __init__(self) -> None:
        self.game_covers: dict = {}
        self.toasts: dict = {}
        self.toast_queue = FakeToastQueue()
        self.session_blocker_shown: list = []
        self.notes_toast_games: list = []
        self.presented = 0
        self.application = FakeApplication()

    def get_application(self) -> FakeApplication:
        return self.application

    # DetailsDialog snapshots and restores the library's scroll position so
    # editing a game does not move the grid underneath the user.
    def store_library_scroll(self) -> None:
        self.scroll_stored = True

    def restore_library_scroll(self) -> None:
        self.scroll_restored = True

    def show_session_blocker(self, game: Any) -> None:
        self.session_blocker_shown.append(game)

    def hide_session_blocker(self) -> None:
        self.session_blocker_shown.append(None)

    def session_toast(self, game: Any, seconds: int) -> None:
        """O aviso de fim de sessão é montado pela janela de verdade.

        Delegado em vez de imitado: é ali que mora a regra de não interpretar o
        título como markup, e um duplo aqui a testaria no lugar dela.
        """
        from cartridges.window import CartridgesWindow  # noqa: PLC0415

        CartridgesWindow.session_toast(self, game, seconds)

    def on_session_toast_notes(self, _toast: Any, game: Any) -> None:
        self.notes_toast_games.append(game)

    def present(self) -> None:
        self.presented += 1


class AppState(IntEnum):
    DEFAULT = auto()
    LOAD_FROM_DISK = auto()
    IMPORT = auto()


def _install_shared() -> types.ModuleType:
    """Put a synthetic ``cartridges.shared`` in place before anything imports it."""
    import cartridges  # noqa: PLC0415

    shared = types.ModuleType("cartridges.shared")
    shared.AppState = AppState
    shared.APP_ID = "page.kramo.Cartridges"
    shared.VERSION = "0000.00.00"
    # Must match the real build: `game_cover` resolves gresource paths off it,
    # and a wrong value aborts the process with a Gdk-ERROR on import.
    shared.PREFIX = "/page/kramo/Cartridges"
    shared.PROFILE = "development"
    shared.TIFF_COMPRESSION = "webp"
    shared.SPEC_VERSION = 1.6
    shared.APP_DIR_NAME = "Cartridges"
    shared.image_size = (600, 900)
    shared.scale_factor = 1
    shared.display_size = (200, 300)
    shared.details_size = (280, 420)
    # Repointed per test by the `app_dirs` fixture. Deliberately left as a path
    # that does not exist, so a test that skips the fixture and writes anyway
    # fails instead of touching the real library.
    placeholder = Path(__file__).resolve().parent / "_unset"
    shared.home = placeholder
    shared.data_dir = placeholder
    shared.config_dir = placeholder
    shared.app_dir = placeholder / "Cartridges"
    shared.games_dir = placeholder / "games"
    shared.covers_dir = placeholder / "covers"
    shared.logos_dir = placeholder / "logos"
    shared.wallpapers_dir = placeholder / "wallpapers"
    shared.fitas_dir = placeholder / "fitas"
    shared.fitas_arquivo = placeholder / "fitas.json"
    shared.cache_dir = placeholder / "cache"
    shared.log_dir = placeholder / "logs"
    shared.schema = FakeSchema(_SCHEMA_DEFAULTS)
    shared.state_schema = FakeSchema(_STATE_DEFAULTS)
    shared.win = None
    shared.importer = None
    shared.import_time = 1_700_000_000
    shared.store = None
    shared.log_files = []

    sys.modules["cartridges.shared"] = shared
    cartridges.shared = shared  # type: ignore[attr-defined]
    return shared


shared = _install_shared()


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def app_dirs(tmp_path, monkeypatch):
    """Point every data directory at a fresh tmp dir, for every test.

    Autouse on purpose: forgetting it would mean a test writing into the real
    library, and that failure mode is silent and unrecoverable.
    """
    games = tmp_path / "games"
    covers = tmp_path / "covers"
    logos = tmp_path / "logos"
    wallpapers = tmp_path / "wallpapers"
    cache = tmp_path / "cache"
    logs = tmp_path / "logs"
    for directory in (games, covers, logos, wallpapers, cache, logs):
        directory.mkdir(parents=True)

    monkeypatch.setattr(shared, "home", tmp_path, raising=False)
    monkeypatch.setattr(shared, "data_dir", tmp_path, raising=False)
    monkeypatch.setattr(shared, "config_dir", tmp_path, raising=False)
    monkeypatch.setattr(shared, "app_dir", tmp_path, raising=False)
    monkeypatch.setattr(shared, "games_dir", games, raising=False)
    monkeypatch.setattr(shared, "covers_dir", covers, raising=False)
    monkeypatch.setattr(shared, "logos_dir", logos, raising=False)
    monkeypatch.setattr(shared, "wallpapers_dir", wallpapers, raising=False)
    monkeypatch.setattr(shared, "cache_dir", cache, raising=False)
    monkeypatch.setattr(shared, "log_dir", logs, raising=False)
    return types.SimpleNamespace(
        root=tmp_path,
        games=games,
        covers=covers,
        logos=logos,
        wallpapers=wallpapers,
        cache=cache,
        logs=logs,
    )


@pytest.fixture(autouse=True)
def schema(monkeypatch):
    """A schema reset to the shipped defaults for each test."""
    fake = FakeSchema(_SCHEMA_DEFAULTS)
    monkeypatch.setattr(shared, "schema", fake, raising=False)
    return fake


@pytest.fixture(autouse=True)
def state_schema(monkeypatch):
    fake = FakeSchema(_STATE_DEFAULTS)
    monkeypatch.setattr(shared, "state_schema", fake, raising=False)
    return fake


@pytest.fixture(autouse=True)
def win(monkeypatch):
    fake = FakeWindow()
    monkeypatch.setattr(shared, "win", fake, raising=False)
    return fake


@pytest.fixture
def flush_idle():
    """Drain everything ``GLib.idle_add`` has queued.

    The store defers work that touches widgets (re-keying ``game_covers``) to
    the main loop. Under test there is no loop running, so the callbacks sit in
    the default context until something iterates it — which is exactly what
    lets a test assert that the work was deferred rather than done inline.
    """

    def drain(limit: int = 1000) -> int:
        context = GLib.MainContext.default()
        iterations = 0
        while context.pending() and iterations < limit:
            context.iteration(False)
            iterations += 1
        return iterations

    yield drain
    # Leftover sources would otherwise fire during an unrelated later test.
    drain()


class FakeGame:
    """Duck-type standing in for ``Game`` in store tests.

    A real ``Game`` is a ``Gtk.Template`` widget that reaches for
    ``shared.win.get_application()`` in its constructor. The store never needs
    any of that — it reads a handful of fields and calls ``save``/``update`` —
    so the fake keeps these tests about the store rather than about widget
    construction. ``saves`` is a counter because several tests are precisely
    about how *many* times a scan writes a record.
    """

    def __init__(self, **overrides) -> None:
        self.source = overrides.pop("source", "shortcuts")
        self.game_id = overrides.pop("game_id", "shortcuts_0000000000000000")
        self.name = overrides.pop("name", "Test Game")
        self.executable = overrides.pop("executable", 'start "" "C:\\g\\game.exe"')
        self.shortcut_path = overrides.pop("shortcut_path", "")
        self.shortcut_mtime = overrides.pop("shortcut_mtime", 0)
        self.removed = overrides.pop("removed", False)
        self.blacklisted = overrides.pop("blacklisted", False)
        self.hidden = overrides.pop("hidden", False)
        self.playtime = overrides.pop("playtime", 0)
        self.version = overrides.pop("version", shared.SPEC_VERSION)
        self.added = overrides.pop("added", 0)
        self.last_played = overrides.pop("last_played", 0)
        self.developer = overrides.pop("developer", None)
        self.run_as_admin = overrides.pop("run_as_admin", False)
        self.track_process = overrides.pop("track_process", False)
        self.process_executable = overrides.pop("process_executable", "")
        self.status = overrides.pop("status", "")
        self.notes = overrides.pop("notes", "")
        for key, value in overrides.items():
            setattr(self, key, value)
        # Derived exactly the way Game.__init__ derives it.
        self.base_source = self.source.split("_")[0]
        self.saves = 0
        self.updates = 0
        self.signals: list = []

    def save(self) -> None:
        self.saves += 1

    def update(self) -> None:
        self.updates += 1

    def connect(self, signal, callback) -> None:
        self.signals.append((signal, callback))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FakeGame {self.game_id} removed={self.removed}>"


@pytest.fixture
def make_game():
    """Factory for store-facing game records."""

    def factory(**overrides) -> FakeGame:
        return FakeGame(**overrides)

    return factory


@pytest.fixture
def store():
    """A clean ``Store`` with no managers registered.

    No managers means ``add_game`` connects no signals and runs no pipeline
    work, which is what keeps these tests about bookkeeping.
    """
    from cartridges.store.store import Store  # noqa: PLC0415

    instance = Store()
    shared.store = instance
    yield instance
    shared.store = None


@pytest.fixture
def real_window(store, monkeypatch):
    """A genuine ``CartridgesWindow``, widgets and all.

    Used where the thing under test *is* the widget wiring — which grid a
    filter reads its search box from, for instance. Building it is cheap enough
    (no display is presented, only realised) that faking it would cost more
    fidelity than it saves.
    """
    from cartridges.window import CartridgesWindow  # noqa: PLC0415

    instance = CartridgesWindow()
    monkeypatch.setattr(shared, "win", instance, raising=False)
    yield instance


@pytest.fixture
def details_dialog(win):
    """A ``DetailsDialog`` for the Apply-button bookkeeping."""
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    return DetailsDialog()


@pytest.fixture
def write_record(app_dirs):
    """Write a game's JSON record the way ``FileManager`` would."""

    def writer(game_id: str, **fields) -> Path:
        path = app_dirs.games / f"{game_id}.json"
        data = {"game_id": game_id, "source": "shortcuts", "name": "Test Game"}
        data.update(fields)
        path.write_text(json.dumps(data, indent=4, sort_keys=True), encoding="utf-8")
        return path

    return writer


@pytest.fixture
def write_asset(app_dirs):
    """Drop a cover/logo file so migrations have something real to move."""

    def writer(directory: str, name: str, content: bytes = b"x") -> Path:
        target = getattr(app_dirs, directory) / name
        target.write_bytes(content)
        return target

    return writer
