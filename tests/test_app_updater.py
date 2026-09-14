# test_app_updater.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checagem de versão nova, notas da release e download do instalador."""

import sys
import xml.etree.ElementTree as ET

import pytest

from cartridges.utils import app_updater
from cartridges.utils.app_updater import (
    Release,
    installed_root,
    is_newer,
    notes_to_markup,
    parse_release,
)

_SHA = "932503f6ff3c8714d7c45d862134365a1b8ae064abbb0f4ba8d44ab7b2d9fb9b"

# Formato real de releases/latest em 13/09/2026, só com os campos lidos.
_API = {
    "tag_name": "v2026.09.10",
    "body": "## Novidades\r\n\r\n- Uma aba nova\r\n\r\n## Instalação\r\n\r\nBaixe o exe.",
    "assets": [
        {"name": "notas.txt", "browser_download_url": "https://x/notas.txt", "size": 1},
        {
            "name": "Cartridges.Windows.exe",
            "browser_download_url": "https://x/Cartridges.Windows.exe",
            "size": 63701150,
            "digest": f"sha256:{_SHA.upper()}",
        },
    ],
}


def _is_valid_markup(markup: str) -> bool:
    try:
        ET.fromstring(f"<markup>{markup}</markup>")
    except ET.ParseError:
        return False
    return True


# -- parse_release ------------------------------------------------------------


def test_parse_release_picks_the_exe_and_strips_prefixes():
    release = parse_release(_API)
    assert release == Release(
        version="2026.09.10",
        notes=_API["body"],
        url="https://x/Cartridges.Windows.exe",
        size=63701150,
        sha256=_SHA,
    )


def test_parse_release_without_exe_is_none():
    data = dict(_API, assets=[_API["assets"][0]])
    assert parse_release(data) is None


def test_parse_release_without_digest_keeps_empty_hash():
    exe = {k: v for k, v in _API["assets"][1].items() if k != "digest"}
    release = parse_release(dict(_API, assets=[exe]))
    assert release is not None
    assert release.sha256 == ""


# -- is_newer -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "current", "expected"),
    [
        ("2026.09.13", "2026.09.12", True),
        ("2026.09.12", "2026.09.12", False),
        ("2026.09.01", "2026.09.12", False),
        ("2026.10.01", "2026.09.30", True),
        ("latest", "2026.09.12", False),
        ("2026.9.13", "2026.09.12", False),
        ("2026.09.13", "0.0.1-dev", False),
    ],
)
def test_is_newer(version, current, expected):
    assert is_newer(version, current) is expected


# -- notes_to_markup ----------------------------------------------------------


def test_notes_markup_formats_headings_bold_code_and_bullets():
    notes = "## Novidades\n\n- A aba **Sessão** mostra `0:00:00`"
    assert notes_to_markup(notes) == (
        "<b>Novidades</b>\n\n• A aba <b>Sessão</b> mostra <tt>0:00:00</tt>"
    )


def test_notes_markup_drops_the_installation_section():
    markup = notes_to_markup(_API["body"])
    assert "Instalação" not in markup
    assert "Baixe" not in markup
    assert markup == "<b>Novidades</b>\n\n• Uma aba nova"


def test_notes_markup_keeps_sections_after_installation():
    notes = "## Instalação\nBaixe.\n## Correções\n- Uma"
    assert notes_to_markup(notes) == "<b>Correções</b>\n• Uma"


def test_notes_markup_escapes_pango_special_characters():
    markup = notes_to_markup("- 800<600 & **R&D**")
    assert markup == "• 800&lt;600 &amp; <b>R&amp;D</b>"
    assert _is_valid_markup(markup)


def test_notes_markup_of_real_body_is_valid():
    assert _is_valid_markup(notes_to_markup(_API["body"]))


# -- installed_root -----------------------------------------------------------


def test_installed_root_finds_the_uninstaller(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pythonw.exe").write_bytes(b"")
    (tmp_path / "unins000.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "pythonw.exe"))
    assert installed_root() == tmp_path.resolve()


def test_installed_root_is_none_from_source(tmp_path, monkeypatch):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "python.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "python.exe"))
    assert installed_root() is None
