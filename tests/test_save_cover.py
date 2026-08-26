# test_save_cover.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A troca de capa não pode destruir a atual antes da nova existir.

Auditoria 26/08, M8: a ordem antiga — apagar toda forma existente e então
copiar — deixava a capa ausente ou truncada num disco cheio ou numa queda, e
uma truncada passa no ``is_file()`` do SGDB, que então nunca mais re-busca.
"""

from types import SimpleNamespace

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils.save_cover import save_cover


@pytest.fixture(autouse=True)
def stub_win(monkeypatch):
    """save_cover consulta shared.win.game_covers no fim; nos testes não há
    janela, e um stub vazio é exatamente o caso "jogo sem widget na grade"."""
    monkeypatch.setattr(shared, "win", SimpleNamespace(game_covers={}))


def make_image(path, color="blue"):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (60, 90), color).save(path)
    return path


def test_a_failed_copy_keeps_the_current_cover(tmp_path):
    current = make_image(shared.covers_dir / "g1.tiff", "red")
    before = current.read_bytes()

    with pytest.raises(FileNotFoundError):
        save_cover("g1", tmp_path / "inexistente.tiff")

    assert current.read_bytes() == before, "a capa atual sobrevive à cópia falhada"
    assert list(shared.covers_dir.glob("*.tmp")) == []


def test_a_replaced_cover_drops_the_other_formats_afterwards(tmp_path):
    old_gif = make_image(shared.covers_dir / "g1.gif")
    new = make_image(tmp_path / "novo.tiff", "green")

    save_cover("g1", new)

    assert (shared.covers_dir / "g1.tiff").is_file()
    assert not old_gif.exists(), "a forma antiga sai depois que a nova está no lugar"
    assert list(shared.covers_dir.glob("*.tmp")) == []


def test_passing_none_still_clears_every_format():
    make_image(shared.covers_dir / "g1.tiff")

    save_cover("g1", None)

    assert not (shared.covers_dir / "g1.tiff").exists()
