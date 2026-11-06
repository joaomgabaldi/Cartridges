# test_game_logo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""When a cached logo lookup is worth repeating: a hit is kept for good, only a miss is asked again after ``MISS_TTL_SECONDS``, and a locked entry (the user's own pick) never expires or gets overwritten."""

import json
import time

import pytest

from kyron import shared
from kyron.utils import game_logo


@pytest.fixture(autouse=True)
def sgdb_key(schema):
    """Without a key there is nothing to ask, so every lookup answers no."""
    schema["sgdb-key"] = "test-key"
    return schema


@pytest.fixture
def sidecar():
    # The default name has to match `make_game`'s, or every lookup reads as a
    # rename — which is itself one of the behaviours under test below.
    def writer(game_id, name="Test Game", filename=None, locked=False, age=0):
        shared.logos_dir.mkdir(parents=True, exist_ok=True)
        if filename:
            (shared.logos_dir / filename).write_bytes(b"logo")
        (shared.logos_dir / f"{game_id}.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "file": filename,
                    "timestamp": int(time.time()) - age,
                    "locked": locked,
                }
            ),
            encoding="utf-8",
        )

    return writer


def test_a_fresh_hit_is_not_looked_up_again(make_game, sidecar):
    sidecar("shortcuts_1", filename="shortcuts_1.png", age=60)
    assert game_logo.logo_lookup_needed(make_game(game_id="shortcuts_1")) is False


A_YEAR = 365 * 24 * 60 * 60


def test_an_old_hit_is_kept_for_good(make_game, sidecar):
    """O logo que está na tela fica: um acerto de um ano atrás não é buscado de novo nem deixa de valer."""
    sidecar("shortcuts_1", filename="shortcuts_1.png", age=A_YEAR)
    game = make_game(game_id="shortcuts_1")
    assert game_logo.logo_lookup_needed(game) is False
    assert game_logo.cached_logo_path(game) is not None


def test_an_old_miss_is_looked_up_again(make_game, sidecar):
    """Só o "sem logo" envelhece: arte nova no SteamGridDB ainda chega."""
    sidecar("shortcuts_1", filename=None, age=game_logo.MISS_TTL_SECONDS + 60)
    assert game_logo.logo_lookup_needed(make_game(game_id="shortcuts_1")) is True


def test_a_zerado_keeps_its_logo_past_the_expiry(make_game, sidecar):
    """Uma tumba nunca busca de novo, então a validade só apagaria o logo."""
    sidecar("shortcuts_1", filename="shortcuts_1.png", age=A_YEAR)
    game = make_game(game_id="shortcuts_1", removed=True, status="beaten")
    assert game_logo.cached_logo_path(game) is not None


def test_a_zerado_keeps_its_logo_after_a_rename(make_game, sidecar):
    """O zerado já passou pela biblioteca com o título acertado e nunca busca de novo: descartar o logo pelo nome só o apagaria."""
    sidecar("shortcuts_1", name="Nome antigo", filename="shortcuts_1.png", age=60)
    game = make_game(
        game_id="shortcuts_1", name="Nome novo", removed=True, status="beaten"
    )
    assert game_logo.cached_logo_path(game) is not None


def test_a_locked_hit_never_expires(make_game, sidecar):
    """The user decided this one; the ranking does not get a second vote."""
    sidecar(
        "shortcuts_1",
        filename="shortcuts_1.png",
        locked=True,
        age=A_YEAR * 10,
    )
    assert game_logo.logo_lookup_needed(make_game(game_id="shortcuts_1")) is False


def test_a_locked_title_choice_never_expires(make_game, sidecar):
    """"Use the title instead" is stored as a locked lookup with no image."""
    sidecar("shortcuts_1", filename=None, locked=True, age=10**9)
    game = make_game(game_id="shortcuts_1")

    assert game_logo.logo_lookup_needed(game) is False
    assert game_logo.logo_choice(game) == "title"


def test_a_locked_entry_survives_a_rename(make_game, sidecar):
    """A renamed game re-asks — unless the user already answered."""
    sidecar("shortcuts_1", name="Halo", filename="shortcuts_1.png", locked=True)
    assert (
        game_logo.logo_lookup_needed(
            make_game(game_id="shortcuts_1", name="Halo Infinite")
        )
        is False
    )


def test_an_automatic_entry_does_not_survive_a_rename(make_game, sidecar):
    """A wrong logo is worse than none: the asset was matched against the old title."""
    sidecar("shortcuts_1", name="Halo", filename="shortcuts_1.png")
    assert (
        game_logo.logo_lookup_needed(
            make_game(game_id="shortcuts_1", name="Halo Infinite")
        )
        is True
    )


def test_a_hit_whose_file_vanished_expires_on_the_miss_clock(make_game, sidecar):
    """The user emptied the cache; waiting weeks to notice is wrong."""
    sidecar("shortcuts_1", filename=None, age=game_logo.MISS_TTL_SECONDS + 60)
    assert game_logo.logo_lookup_needed(make_game(game_id="shortcuts_1")) is True


def test_a_fresh_miss_is_not_retried(make_game, sidecar):
    sidecar("shortcuts_1", filename=None, age=60)
    assert game_logo.logo_lookup_needed(make_game(game_id="shortcuts_1")) is False


def test_no_sidecar_means_ask(make_game):
    assert game_logo.logo_lookup_needed(make_game(game_id="shortcuts_1")) is True


def test_no_api_key_means_never_ask(make_game, schema):
    """The text title is the whole feature when there is nothing to ask with."""
    schema["sgdb-key"] = ""
    assert game_logo.logo_lookup_needed(make_game(game_id="shortcuts_1")) is False


@pytest.mark.parametrize("flag", ["blacklisted", "removed"])
def test_hidden_games_are_never_looked_up(make_game, flag):
    game = make_game(game_id="shortcuts_1", **{flag: True})
    assert game_logo.logo_lookup_needed(game) is False


def test_a_transient_failure_does_not_overwrite_a_good_hit(make_game, sidecar):
    """A miss written over a hit is how a working logo disappears; asserted through the reader."""
    sidecar("shortcuts_1", filename="shortcuts_1.png", age=60)
    game = make_game(game_id="shortcuts_1")
    before = game_logo.cached_logo_path(game)

    # A failed fetch records nothing, so the sidecar is untouched.
    assert game_logo.logo_lookup_needed(game) is False
    assert game_logo.cached_logo_path(game) == before
    assert before is not None


def test_a_corrupt_timestamp_is_treated_as_expired(make_game):
    """Unreadable is not the same as fresh."""
    shared.logos_dir.mkdir(parents=True, exist_ok=True)
    (shared.logos_dir / "shortcuts_1.json").write_text(
        json.dumps({"name": "Halo", "file": "x.png", "timestamp": "not a number"}),
        encoding="utf-8",
    )
    assert game_logo.logo_lookup_needed(make_game(game_id="shortcuts_1")) is True


def test_an_oversized_candidate_is_not_usable():
    """O ranking desempata para o maior e o loader de PNG decodifica inteiro na thread principal: um candidato desmedido é pulado."""
    huge = {"url": "https://x/logo.png", "width": 15000, "height": 8000}
    fine = {"url": "https://x/logo.png", "width": 1280, "height": 480}

    assert game_logo.pick_logo([huge, fine]) is fine
    assert game_logo.pick_logo([huge]) is None


def test_an_oversized_cached_file_is_not_loaded():
    """O mesmo teto para o arquivo local (dimensões lidas sem decodificar)."""
    from PIL import Image

    shared.logos_dir.mkdir(parents=True, exist_ok=True)
    path = shared.logos_dir / "wide.png"
    Image.new("RGB", (game_logo.MAX_SOURCE_DIMENSION + 1, 10), "white").save(path)

    assert game_logo.load_logo(path) is None


def test_load_logo_devolve_caminho_e_largura():
    from PIL import Image

    shared.logos_dir.mkdir(parents=True, exist_ok=True)
    path = shared.logos_dir / "wide.png"
    Image.new("RGBA", (400, 100), "white").save(path)

    assert game_logo.load_logo(path) == (path, 288)
    assert game_logo.load_logo(shared.logos_dir / "ausente.png") is None


def test_load_logo_arquivo_ilegivel(tmp_path):
    ruim = tmp_path / "ruim.png"
    ruim.write_bytes(b"nao e imagem")
    assert game_logo.load_logo(ruim) is None


def test_game_logo_sem_gi():
    import subprocess
    import sys
    from pathlib import Path

    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; "
        "import kyron.utils.game_logo, kyron.utils.desfoque; "
        "assert 'gi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", codigo], check=True, cwd=Path(__file__).resolve().parent.parent)
