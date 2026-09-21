# test_backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os dois backups: o .json de antes, que mescla, e o .zip completo, que substitui.

A primeira metade é a mescla do .json sobre uma biblioteca que já existe.

O backup leva o que veio do usuário e de mais ninguém, e cada campo volta pela
regra da sua natureza: o tempo de jogo é uma parcela e soma, o status, a nota e
a anotação são valores e só preenchem o que está vazio. É a diferença entre
restaurar duas máquinas na mesma biblioteca (soma) e restaurar por cima de uma
biblioteca em uso (não apaga nada).

O arquivo veio de fora e pode ter sido editado à mão, então metade destes
testes é sobre o que ele *não* consegue gravar.
"""

import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest
from gi.repository import Gio

from cartridges import shared
from cartridges.game import Game
from cartridges.preferences import restore_into
from cartridges.utils import backup

_ROOT = Path(__file__).resolve().parent.parent


def game(**fields) -> Game:
    return Game(
        {
            "source": "shortcuts",
            "game_id": "shortcuts_1",
            "name": "Hollow Knight",
            "executable": "x",
            "added": 0,
            **fields,
        }
    )


def test_an_empty_library_gets_everything_back(win) -> None:
    """O caso principal: formatou o computador, reimportou os jogos."""
    fresh = game()
    entry = {
        "playtime": 7200,
        "status": "beaten",
        "rating": 4,
        "notes": "Parei no capítulo 4.",
    }

    assert restore_into(fresh, entry) is True
    assert fresh.playtime == 7200
    assert fresh.status == "beaten"
    assert fresh.rating == 4
    assert fresh.notes == "Parei no capítulo 4."


def test_the_playtime_adds_up(win) -> None:
    """O backup é uma parcela do total, não o total: restaurar o de outra
    máquina na mesma biblioteca tem de dar a soma das duas."""
    played = game(playtime=3600)

    assert restore_into(played, {"playtime": 1800}) is True
    assert played.playtime == 5400


def test_what_is_already_filled_in_survives(win) -> None:
    """O que está na biblioteca agora é mais novo que o que está no arquivo."""
    current = game(status="playing", rating=5, notes="Nota de agora")
    entry = {"status": "dropped", "rating": 1, "notes": "Nota velha"}

    assert restore_into(current, entry) is False
    assert current.status == "playing"
    assert current.rating == 5
    assert current.notes == "Nota de agora"


def test_importing_the_same_file_twice_only_doubles_the_playtime(win) -> None:
    """O preço conhecido do tempo somar. Os outros três ficam de pé."""
    fresh = game()
    entry = {"playtime": 3600, "status": "beaten", "rating": 3, "notes": "Zerei"}

    restore_into(fresh, entry)
    restore_into(fresh, entry)

    assert fresh.playtime == 7200
    assert (fresh.status, fresh.rating, fresh.notes) == ("beaten", 3, "Zerei")


@pytest.mark.parametrize(
    "entry",
    (
        {"status": "zerado"},  # o rótulo, e não a chave
        {"status": 3},
        {"status": ""},
        {"rating": 9},  # fora de 1–5
        {"rating": -1},
        {"rating": "ótimo"},
        {"playtime": "muito"},
        {"playtime": -3600},  # nunca tira tempo de ninguém
        {"notes": "   \n  "},  # espaço não é anotação
        {"notes": 42},
        {},
    ),
)
def test_a_hand_edited_file_cannot_write_nonsense(win, entry) -> None:
    """Um valor que o app não sabe exibir é descartado na entrada, e não
    gravado para quebrar uma tela mais adiante."""
    fresh = game()

    assert restore_into(fresh, entry) is False
    assert (fresh.playtime, fresh.status, fresh.rating, fresh.notes) == (0, "", 0, "")


def test_a_version_1_entry_still_restores(win) -> None:
    """Backups salvos quando o arquivo só levava tempo de jogo continuam
    valendo: eles trazem menos campos, e é só."""
    fresh = game()

    assert restore_into(fresh, {"name": "Hollow Knight", "playtime": 3600}) is True
    assert fresh.playtime == 3600


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


def _populate(app_dirs) -> None:
    (app_dirs.games / "shortcuts_1.json").write_text('{"game_id": "shortcuts_1"}')
    (app_dirs.games / "shortcuts_2.json").write_text('{"removed": true}')
    (app_dirs.games / "shortcuts_1.json.tmp").write_text("sobra")
    (app_dirs.covers / "shortcuts_1.tiff").write_bytes(b"capa")
    (app_dirs.logos / "shortcuts_1.json").write_text('{"locked": true}')
    (app_dirs.logos / "shortcuts_1.png").write_bytes(b"logo")
    (app_dirs.wallpapers / "shortcuts_1.json").write_text('{"position_portrait": 0.2}')
    (app_dirs.wallpapers / "shortcuts_1.jpg").write_bytes(b"parede")
    shared.fitas_dir.mkdir()
    (shared.fitas_dir / "shortcuts_1.json").write_text('{"brilho": 500}')
    shared.fitas_arquivo.write_text('{"fitas": [{"nome": "Monitor"}]}')
    (shared.app_dir / "sessions.jsonl").write_text('{"game_id": "shortcuts_1"}\n')
    shared.tuya_conta_arquivo.write_text("blob-dpapi")


def _snapshot() -> dict[str, bytes]:
    """Tudo o que o backup deve levar e trazer de volta, byte a byte."""
    files = {}
    for folder in ("games", "covers", "logos", "wallpapers", "fitas"):
        directory = shared.app_dir / folder
        if directory.is_dir():
            for path in directory.iterdir():
                if path.suffix != ".tmp":
                    files[f"{folder}/{path.name}"] = path.read_bytes()
    for name in ("fitas.json", "sessions.jsonl"):
        if (shared.app_dir / name).is_file():
            files[name] = (shared.app_dir / name).read_bytes()
    return files


def test_restoring_brings_back_the_whole_library(app_dirs, settings, tmp_path) -> None:
    """O caso principal: tudo volta como era, arquivos e configurações."""
    main, state = settings
    _populate(app_dirs)
    main.set_string("sgdb-key", "chave-sgdb")
    main.set_uint("library-rows", 3)
    main.set_int("fita-brilho-padrao", 400)
    state.set_string("sort-mode", "playtime")
    before = _snapshot()

    target = tmp_path / "export" / "backup.zip"
    target.parent.mkdir()
    backup.exportar(target, backup.ler_configuracoes())

    with zipfile.ZipFile(target) as archive:
        names = archive.namelist()
    assert "tuya_conta.json" not in names
    assert "games/shortcuts_1.json.tmp" not in names

    # Bagunça: some capa, chega jogo novo, muda a fita e as configurações.
    (app_dirs.covers / "shortcuts_1.tiff").unlink()
    (app_dirs.games / "novo.json").write_text("{}")
    shared.fitas_arquivo.write_text('{"fitas": []}')
    main.set_string("sgdb-key", "")
    main.set_uint("library-rows", 0)
    main.set_boolean("gamepad", True)
    state.set_string("sort-mode", "a-z")

    assert backup.aplicar_pendente() is None
    backup.agendar(target)
    assert backup.aplicar_pendente() is True

    assert _snapshot() == before
    assert main.get_string("sgdb-key") == "chave-sgdb"
    assert main.get_uint("library-rows") == 3
    assert main.get_int("fita-brilho-padrao") == 400
    assert main.get_boolean("gamepad") is False  # voltou ao padrão
    assert state.get_string("sort-mode") == "playtime"
    assert shared.tuya_conta_arquivo.read_text() == "blob-dpapi"
    assert not (shared.app_dir / "restaurar.zip").exists()
    assert not (shared.app_dir / "restaurar.tmp").exists()


def test_session_keys_stay_on_this_machine(app_dirs, settings, tmp_path) -> None:
    """O caminho de volta de uma sessão em andamento não viaja no backup nem
    é sobrescrito por ele: "desfaria" uma troca que nunca aconteceu."""
    main, _state = settings
    main.set_string("session-wallpaper-saved", "antes")
    main.set_string("fita-estado-anterior", "antes")
    target = tmp_path / "b.zip"
    backup.exportar(target, backup.ler_configuracoes())
    saved = backup.validar(target)["settings"]
    assert "session-wallpaper-saved" not in saved
    assert "fita-estado-anterior" not in saved

    main.set_string("session-wallpaper-saved", "sessao-em-curso")
    backup.agendar(target)
    assert backup.aplicar_pendente() is True
    assert main.get_string("session-wallpaper-saved") == "sessao-em-curso"


def test_a_zip_escaping_its_folders_is_refused(app_dirs, settings, tmp_path) -> None:
    """O zip veio de fora: um nome com `..` gravaria fora da pasta do app."""
    _populate(app_dirs)
    bad = tmp_path / "ruim.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("backup.json", json.dumps({"version": 3, "settings": {}}))
        archive.writestr("games/../../fora.txt", "x")
    with pytest.raises(ValueError):
        backup.validar(bad)

    before = _snapshot()
    backup.agendar(bad)
    assert backup.aplicar_pendente() is False
    assert _snapshot() == before
    assert not (shared.app_dir / "restaurar.zip").exists()


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


def test_a_corrupted_entry_is_caught_before_anything_is_touched(
    app_dirs, settings, tmp_path
) -> None:
    """Um byte trocado numa capa passa pelo manifesto; o CRC de cada entrada
    é conferido antes, e a biblioteca atual não é tocada."""
    _populate(app_dirs)
    target = tmp_path / "b.zip"
    backup.exportar(target, backup.ler_configuracoes())
    data = target.read_bytes()
    assert data.count(b"parede") == 1
    target.write_bytes(data.replace(b"parede", b"pArede"))

    with pytest.raises(ValueError):
        backup.validar(target)
    before = _snapshot()
    backup.agendar(target)
    assert backup.aplicar_pendente() is False
    assert _snapshot() == before
    assert not (shared.app_dir / "restaurar.zip").exists()


def test_a_swap_that_fails_midway_puts_everything_back(
    app_dirs, settings, tmp_path, monkeypatch
) -> None:
    """Um arquivo em uso trava a troca no meio: o que já foi movido volta, a
    biblioteca atual fica inteira, e o zip sai para não travar de novo."""
    _populate(app_dirs)
    target = tmp_path / "b.zip"
    backup.exportar(target, backup.ler_configuracoes())
    (app_dirs.covers / "shortcuts_1.tiff").write_bytes(b"capa nova")
    (app_dirs.games / "depois.json").write_text("{}")
    before = _snapshot()
    backup.agendar(target)

    replace = Path.replace

    def locked(self, destination):
        if self.name == "wallpapers" and self.parent.name == "restaurar.tmp":
            raise PermissionError("arquivo em uso")
        return replace(self, destination)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", locked)
        assert backup.aplicar_pendente() is False

    assert _snapshot() == before
    assert not (shared.app_dir / "restaurar.zip").exists()
    assert not (shared.app_dir / "restaurar.old").exists()
    assert not (shared.app_dir / "restaurar.tmp").exists()


def test_the_preferences_export_then_schedule_a_restore(
    monkeypatch, app_dirs, settings, tmp_path, win, flush_idle
) -> None:
    """A tela de verdade: exportar numa thread até o toast final, depois
    importar o mesmo arquivo, confirmar, e o app agenda e fecha."""
    import time  # noqa: PLC0415

    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from tests.test_auditoria_0918_fitas import _dialogo_de_arquivo  # noqa: PLC0415
    from tests.test_session_fita import _preferencias  # noqa: PLC0415

    (app_dirs.games / "a.json").write_text("{}")
    target = tmp_path / "export" / "b.zip"
    target.parent.mkdir()
    _dialogo_de_arquivo(monkeypatch, target)
    preferences = _preferencias(monkeypatch)
    toasts = []
    monkeypatch.setattr(preferences, "add_toast", toasts.append)

    preferences.export_backup()
    deadline = time.monotonic() + 10
    while not any(toast.get_title() == "Backup exportado" for toast in toasts):
        assert time.monotonic() < deadline, [toast.get_title() for toast in toasts]
        flush_idle()
        time.sleep(0.01)
    with zipfile.ZipFile(target) as archive:
        assert "games/a.json" in archive.namelist()

    answers = []

    class Question:
        def connect(self, _signal, callback) -> None:
            answers.append(callback)

    monkeypatch.setattr(preferences_module, "create_dialog", lambda *_a, **_k: Question())
    closed = []
    monkeypatch.setattr(win.application, "quit", lambda: closed.append(True), raising=False)

    preferences.import_backup()
    answers[0](None, "restore")

    assert closed == [True]
    assert (shared.app_dir / "restaurar.zip").is_file()
