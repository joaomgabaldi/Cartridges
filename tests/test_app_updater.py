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


# -- download_installer -------------------------------------------------------

import hashlib  # noqa: E402
import threading  # noqa: E402

from cartridges.utils.app_updater import (  # noqa: E402
    DownloadCancelled,
    download_installer,
)

_PAYLOAD = b"instalador de mentira"


class _FakeResponse:
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


def _release(sha256: str) -> Release:
    return Release("2026.09.13", "", "https://x/setup.exe", len(_PAYLOAD), sha256)


@pytest.fixture
def fake_get(monkeypatch):
    calls: list[str] = []

    def get(url, **_kwargs):
        calls.append(url)
        return _FakeResponse(_PAYLOAD)

    monkeypatch.setattr(app_updater.requests, "get", get)
    return calls


def test_download_writes_verified_installer(tmp_path, fake_get):
    target = tmp_path / "update" / "Cartridges-2026.09.13.exe"
    fractions: list[float] = []

    download_installer(
        _release(hashlib.sha256(_PAYLOAD).hexdigest()),
        target,
        fractions.append,
        threading.Event(),
    )

    assert target.read_bytes() == _PAYLOAD
    assert not target.with_name(target.name + ".part").exists()
    assert fractions[-1] == 1.0
    assert fractions == sorted(fractions)


# O `app_dirs` do conftest cria pastas dentro do tmp_path; o download vai para
# uma subpasta própria para "não sobrou nada" poder olhar a pasta inteira.


def test_download_with_wrong_hash_leaves_nothing(tmp_path, fake_get):
    target = tmp_path / "update" / "Cartridges-2026.09.13.exe"

    with pytest.raises(ValueError):
        download_installer(_release("0" * 64), target, lambda _f: None, threading.Event())

    assert list(target.parent.iterdir()) == []


def test_download_without_hash_refuses_before_downloading(tmp_path, fake_get):
    with pytest.raises(ValueError):
        download_installer(
            _release(""), tmp_path / "x.exe", lambda _f: None, threading.Event()
        )
    assert fake_get == []


def test_download_cancelled_leaves_nothing(tmp_path, fake_get):
    cancelled = threading.Event()
    cancelled.set()
    target = tmp_path / "update" / "Cartridges-2026.09.13.exe"

    with pytest.raises(DownloadCancelled):
        download_installer(
            _release(hashlib.sha256(_PAYLOAD).hexdigest()),
            target,
            lambda _f: None,
            cancelled,
        )

    assert list(target.parent.iterdir()) == []
