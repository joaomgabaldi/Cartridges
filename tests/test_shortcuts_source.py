# test_shortcuts_source.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Identity derivation and the batch guards around it.

A game id is a hash of the game's launch identity, so what goes into that
identity decides whether a library survives a bad scan. The rule the whole
design turns on: **an id must not depend on anything that can fail.** A Store
shortcut's AUMID is resolved through ``Get-StartApps``; when that PowerShell
call timed out, the resolved value changed, the id changed with it, the game
looked new, its old record looked missing, and ``remove_games`` deleted the
playtime, cover, logo and update tracking — permanently.

So the identity is the AUMID the shortcut *carries*, which is a property of the
file, and the resolved one is only a launch detail.

These tests drive the real ``__iter__`` with the two PowerShell calls replaced,
because the guards being tested live in the generator, not in the builders.
"""

import pytest

from cartridges.importer import shortcuts_source as ss
from cartridges.importer.source import SourceScanError
from cartridges.store.store import _is_derived_command

# A real Xbox layout: the .lnk carries a grouping id, and Get-StartApps is the
# only thing that knows the launchable one.
GROUPING_AUMID = "XboxGames.Halo_Halo"
REAL_AUMID = "Microsoft.HaloInfinite_8wekyb3d8bbwe!Game"


@pytest.fixture
def scan(tmp_path, schema, monkeypatch):
    """Run a real scan over real files with both PowerShell calls stubbed."""

    def runner(files, lnk_data=None, start_apps=(), recursive=True, raw=False):
        for name, content in files.items():
            (tmp_path / name).write_text(content, encoding="utf-8")

        schema["shortcuts-location"] = str(tmp_path)
        schema["shortcuts-recursive"] = recursive

        resolved = {}
        for name, data in (lnk_data or {}).items():
            resolved[str(tmp_path / name)] = {"File": str(tmp_path / name), **data}

        monkeypatch.setattr(ss, "resolve_lnk_targets", lambda paths: dict(resolved))
        monkeypatch.setattr(ss, "resolve_start_apps", lambda: list(start_apps))

        source = ss.ShortcutsSource()
        if raw:
            # The live generator, so a test can keep what was yielded before an
            # exception — materialising the list would discard exactly that.
            return iter(source)
        return [result for result in iter(source) if result is not None]

    return runner


def only_game(results):
    assert len(results) == 1, results
    return results[0]


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_uwp_identity_is_stable_across_a_failed_resolution(scan, tmp_path):
    """T3.1 The central test of the whole design.

    The same shortcut file must hash to the same id whether or not the Start
    menu could tell us how to launch it.
    """
    files = {"Halo.lnk": "x"}
    data = {"Halo.lnk": {"Aumid": GROUPING_AUMID}}

    resolved_run = only_game(
        scan(files, data, start_apps=[("Halo", REAL_AUMID)])
    )
    # The list comes back, but without an entry for this game: resolution is
    # working, it simply cannot answer for this title.
    unresolved_run = only_game(
        scan(files, data, start_apps=[("Solitaire", "Microsoft.Solitaire_x!App")])
    )

    assert resolved_run[0].game_id == unresolved_run[0].game_id
    # ...and the commands legitimately differ, which is the point of splitting them.
    assert resolved_run[0].executable != unresolved_run[0].executable


def test_legacy_id_offered_only_when_resolution_changed_the_value(scan):
    """T3.2 Nothing to adopt when the raw and resolved AUMIDs agree."""
    files = {"Halo.lnk": "x"}

    changed = only_game(
        scan(files, {"Halo.lnk": {"Aumid": GROUPING_AUMID}},
             start_apps=[("Halo", REAL_AUMID)])
    )
    assert changed[1]["legacy_game_ids"]

    unchanged = only_game(
        scan(files, {"Halo.lnk": {"Aumid": REAL_AUMID}},
             start_apps=[("Halo", REAL_AUMID)])
    )
    assert "legacy_game_ids" not in unchanged[1]


def test_legacy_id_is_the_id_the_old_derivation_produced(scan, tmp_path):
    """T3.2 The offered id must be the one the record is actually filed under."""
    result = only_game(
        scan({"Halo.lnk": "x"}, {"Halo.lnk": {"Aumid": GROUPING_AUMID}},
             start_apps=[("Halo", REAL_AUMID)])
    )
    iterable = ss.ShortcutsSourceIterable(ss.ShortcutsSource())
    expected = iterable._game_id(f"uwp:{REAL_AUMID}")

    assert result[1]["legacy_game_ids"] == [expected]


def test_identity_anchor_is_set_for_every_packaged_game(scan, tmp_path):
    """T3.3 Including the case with no legacy id, which is the one that needs it."""
    unresolvable = only_game(
        scan({"Halo.lnk": "x"}, {"Halo.lnk": {"Aumid": GROUPING_AUMID}},
             start_apps=[("Other", "Other_x!App")])
    )

    assert "legacy_game_ids" not in unresolvable[1]
    assert unresolvable[1]["identity_anchor"] == str(tmp_path / "Halo.lnk")


def test_resolved_aumid_becomes_an_appsfolder_command(scan):
    """T3.4"""
    result = only_game(
        scan({"Halo.lnk": "x"}, {"Halo.lnk": {"Aumid": GROUPING_AUMID}},
             start_apps=[("Halo", REAL_AUMID)])
    )
    assert result[0].executable == f"explorer.exe shell:AppsFolder\\{REAL_AUMID}"


def test_grouping_id_falls_back_to_launching_the_shortcut(scan, tmp_path):
    """T3.5 And the string must match what the store rebuilds, byte for byte.

    ``shell:AppsFolder`` with a grouping id just opens the Apps folder, which
    looks like a game that starts and does nothing. Launching the .lnk itself is
    what the user would double-click.

    The literal comparison against ``_is_derived_command`` is the contract that
    keeps the fallback from becoming absorbing: if these two expressions ever
    drift apart, the store stops recognising the fallback as its own and a
    degraded command can never be replaced.
    """
    result = only_game(
        scan({"Halo.lnk": "x"}, {"Halo.lnk": {"Aumid": GROUPING_AUMID}},
             start_apps=[("Other", "Other_x!App")])
    )
    game = result[0]

    assert game.executable == f'start "" "{tmp_path / "Halo.lnk"}"'
    assert _is_derived_command(game) is True


def test_unsafe_aumid_is_ignored(scan):
    """T3.6 The AUMID lands unquoted in a shell command.

    ``start_apps`` has to be non-empty or the batch guard fires first and this
    never reaches the per-shortcut validation.
    """
    results = scan(
        {"Bad.lnk": "x"},
        {"Bad.lnk": {"Aumid": "Evil&calc.exe"}},
        start_apps=[("Unrelated", "Unrelated_x!App")],
    )
    assert results == []


def test_unsafe_shortcut_path_is_ignored(tmp_path):
    """T3.7 The grouping-id fallback embeds the .lnk path in a quoted argument.

    Called directly rather than through a scan: NTFS cannot hold a file whose
    name contains a quote, so the only way to reach this guard is to hand the
    builder the path a bug (or a non-Windows filesystem) could produce.
    """
    iterable = make_iterable([])
    entry = tmp_path / 'Quote".lnk'

    assert iterable.build_from_lnk(entry, {"Aumid": GROUPING_AUMID}) is None


# ---------------------------------------------------------------------------
# Batch guards
# ---------------------------------------------------------------------------


def test_empty_lnk_resolution_for_a_non_empty_batch_is_a_failure(scan):
    """T3.8 Treated as "no games", this marked every .lnk game as removed."""
    with pytest.raises(SourceScanError):
        scan({"Halo.lnk": "x", "Doom.lnk": "x"}, lnk_data={})


def test_empty_lnk_resolution_for_an_empty_batch_is_fine(scan):
    """T3.9 A folder with no .lnk files did not fail at anything."""
    results = scan({"Steam.url": "[InternetShortcut]\nURL=steam://rungameid/440\n"})
    assert len(results) == 1


def test_url_games_survive_a_failed_lnk_batch(scan):
    """T3.10 A scan that has to give up still counts what it did see.

    The .url shortcuts are parsed in process and cannot be taken down by a
    PowerShell failure, so they are yielded before the risky part. Combined with
    the importer refusing to mark a failed source as scanned, this is what makes
    a broken PowerShell cost nothing instead of half the library.
    """
    produced = []
    generator = scan(
        {
            "Steam.url": "[InternetShortcut]\nURL=steam://rungameid/440\n",
            "Halo.lnk": "x",
        },
        lnk_data={},
        raw=True,
    )

    with pytest.raises(SourceScanError):
        for result in generator:
            if result is not None:
                produced.append(result)

    assert len(produced) == 1
    assert produced[0][0].executable == 'start "" "steam://rungameid/440"'


def test_empty_start_apps_with_packaged_shortcuts_is_a_failure(scan):
    """T3.11 A machine with Store shortcuts always has Start apps."""
    with pytest.raises(SourceScanError):
        scan({"Halo.lnk": "x"}, {"Halo.lnk": {"Aumid": GROUPING_AUMID}}, start_apps=[])


def test_no_packaged_shortcuts_never_asks_for_start_apps(scan, tmp_path, monkeypatch):
    """T3.12 Get-StartApps spawns a whole PowerShell; do not pay for it blindly."""
    calls = []

    def counting():
        calls.append(1)
        return []

    exe = tmp_path / "game.exe"
    exe.write_text("x", encoding="utf-8")
    monkeypatch.setattr(ss, "resolve_start_apps", counting)

    results = scan({"Halo.lnk": "x"}, {"Halo.lnk": {"Target": str(exe)}})

    assert calls == []
    assert len(results) == 1


# ---------------------------------------------------------------------------
# The PowerShell resolver's own separator handling
#
# Not reachable from Python: what breaks is inside the script text. These pin
# the two decisions in it that look like noise and are not.
# ---------------------------------------------------------------------------


def _script_lines():
    """The PowerShell script's own lines, with Python comments stripped.

    The comments around this script name the operators it must not use, so a
    plain substring search over the source finds the warning and reads it as
    the mistake.
    """
    import inspect

    return [
        line
        for line in inspect.getsource(ss.resolve_lnk_targets).splitlines()
        if not line.strip().startswith("#")
    ]


def test_the_namespace_path_is_backslashed_with_a_literal_replace():
    """Defence in depth, and the reason it is only that.

    Two true facts that do *not* compose into a bug. `str(path)` is
    slash-separated on this interpreter, and `IShellDispatch::NameSpace` really
    does return null for a slash-separated path where `CreateShortcut` opens the
    same file happily. But the script never hands `$p` to `Namespace` — it hands
    `Split-Path $p`, and `Split-Path` normalises separators on the way out, so
    the strict parser only ever sees backslashes.

    Measured rather than reasoned: the pre-`Replace` script, run against 59 real
    shortcuts, returned the same 29 AUMIDs as the current one.

    The `.Replace` is kept because it costs nothing and would matter if
    `Split-Path` were ever swapped for string handling that does not normalise.
    If it is kept it has to be `.Replace` and not `-replace`, which is a regex
    operator where a lone backslash is an escape and the substitution silently
    does nothing.
    """
    code = _script_lines()

    assert any(".Replace('/','\\\\')" in line for line in code)
    # Only the code: the comment above it names `-replace` precisely to say why
    # it is the wrong operator.
    assert not any("-replace" in line for line in code)


def test_the_result_key_is_echoed_unchanged():
    """`File=$p` has to stay the path exactly as written.

    It is the key `lnk_data` is looked up by on the Python side, so normalising
    it in the script — or normalising the lookup in Python — would desynchronise
    the two halves and resolve every shortcut to nothing.
    """
    assert any("File=$p;" in line for line in _script_lines())


# ---------------------------------------------------------------------------
# Command injection
# ---------------------------------------------------------------------------


def test_shell_metacharacter_in_arguments_is_refused(scan, tmp_path):
    """T3.13 Arguments are appended unquoted, so they need no quote to break out."""
    exe = tmp_path / "game.exe"
    exe.write_text("x", encoding="utf-8")

    results = scan(
        {"Evil.lnk": "x"},
        {"Evil.lnk": {"Target": str(exe), "Arguments": "& calc.exe"}},
    )
    assert results == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("Target", 'C:\\g\\"; calc.exe'),
        ("WorkingDirectory", 'C:\\g\\"evil'),
        ("Target", "C:\\g\\game\x00.exe"),
    ],
)
def test_quotes_and_control_chars_are_refused(scan, field, value):
    """T3.14 Windows paths cannot legitimately contain either."""
    assert scan({"Evil.lnk": "x"}, {"Evil.lnk": {field: value}}) == []


# ---------------------------------------------------------------------------
# The other two identities
# ---------------------------------------------------------------------------


def test_classic_identity_is_target_and_arguments(scan, tmp_path):
    """T3.15 Renaming the .lnk must not change the id.

    Both names are scanned at once rather than in two runs, because the scan
    fixture reuses one folder — and because two files naming one game is the
    real-world shape of this anyway.
    """
    exe = tmp_path / "game.exe"
    exe.write_text("x", encoding="utf-8")
    target = {"Target": str(exe), "Arguments": "-dx11"}

    results = scan(
        {"Halo.lnk": "x", "Halo Renamed.lnk": "x"},
        {"Halo.lnk": target, "Halo Renamed.lnk": target},
    )

    assert len(results) == 2
    assert results[0][0].game_id == results[1][0].game_id


def test_url_identity_is_the_url(scan):
    """T3.16"""
    body = "[InternetShortcut]\nURL=steam://rungameid/440\n"
    results = scan({"Steam.url": body, "Renamed.url": body})

    assert len(results) == 2
    assert results[0][0].game_id == results[1][0].game_id


def test_a_retarget_changes_the_id_but_offers_the_anchor(scan, tmp_path):
    """The bug this anchor was widened for, stated as the two halves it has.

    Installing a patch repoints the .lnk, and the id is a hash of the target, so
    the id moves — that half is by design and is not what to fix. What must hold
    is the second half: the scan hands the store the shortcut file, which is the
    only thing tying the two ids together. Without it the store saw a new game
    plus a missing one and ``remove_games`` deleted the record.
    """
    before = tmp_path / "abc.exe"
    after = tmp_path / "abc_patched.exe"
    for exe in (before, after):
        exe.write_text("x", encoding="utf-8")

    original = only_game(scan({"X.lnk": "x"}, {"X.lnk": {"Target": str(before)}}))
    patched = only_game(scan({"X.lnk": "x"}, {"X.lnk": {"Target": str(after)}}))

    assert original[0].game_id != patched[0].game_id
    assert patched[1]["identity_anchor"] == str(tmp_path / "X.lnk")
    assert original[1]["identity_anchor"] == patched[1]["identity_anchor"]


def test_identity_anchor_is_set_for_a_protocol_target(scan, tmp_path):
    """A .lnk whose target is a URI never resolves to a file, and still anchors."""
    result = only_game(
        scan({"Epic.lnk": "x"}, {"Epic.lnk": {"Target": "com.epicgames.launcher://apps/x"}})
    )

    assert result[1]["identity_anchor"] == str(tmp_path / "Epic.lnk")


def test_identity_anchor_is_set_for_a_url_shortcut(scan, tmp_path):
    """The .url file is the stable thing; the URL inside it is not."""
    result = only_game(
        scan({"Steam.url": "[InternetShortcut]\nURL=steam://rungameid/440\n"})
    )

    assert result[1]["identity_anchor"] == str(tmp_path / "Steam.url")


def test_game_id_shape(scan, tmp_path):
    """T3.17"""
    import re

    exe = tmp_path / "game.exe"
    exe.write_text("x", encoding="utf-8")
    result = only_game(scan({"Halo.lnk": "x"}, {"Halo.lnk": {"Target": str(exe)}}))

    assert re.fullmatch(r"shortcuts_[0-9a-f]{16}", result[0].game_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_iterable(start_apps):
    iterable = ss.ShortcutsSourceIterable(ss.ShortcutsSource())
    iterable._aumid_by_name = {name.casefold(): appid for name, appid in start_apps}
    iterable._aumid_by_pkgkey = {}
    for _name, appid in start_apps:
        if "!" in appid and "_" in (pfn := appid.split("!", 1)[0]):
            pkgname = pfn.rsplit("_", 1)[0]
            key = f"{pkgname}_{appid.split('!', 1)[1]}".casefold()
            iterable._aumid_by_pkgkey[key] = appid
    return iterable


def test_real_aumid_matches_by_display_name():
    """T3.18"""
    iterable = make_iterable([("Halo Infinite", REAL_AUMID)])
    assert iterable._real_aumid("Halo Infinite", GROUPING_AUMID) == REAL_AUMID


def test_real_aumid_matches_by_package_key():
    """T3.18 The grouping id encodes the package and app names."""
    iterable = make_iterable([("Something Else", REAL_AUMID)])
    grouping = "Microsoft.HaloInfinite_Game"
    assert iterable._real_aumid("no match", grouping) == REAL_AUMID


def test_real_aumid_falls_back_to_the_raw_value():
    """T3.18"""
    iterable = make_iterable([])
    assert iterable._real_aumid("nothing", GROUPING_AUMID) == GROUPING_AUMID


@pytest.mark.parametrize(
    "stem", ["Uninstall Halo", "Halo Readme", "Read Me", "Halo Benchmark", "Support"]
)
def test_non_game_shortcuts_are_skipped(scan, tmp_path, stem):
    """T3.19"""
    exe = tmp_path / "game.exe"
    exe.write_text("x", encoding="utf-8")
    assert scan({f"{stem}.lnk": "x"}, {f"{stem}.lnk": {"Target": str(exe)}}) == []


@pytest.mark.parametrize(
    "url,expected",
    [
        ("steam://rungameid/440", "440"),
        ("steam://run/570", "570"),
        ("steam://rungameid/76561198000000000", None),
        ("com.epicgames.launcher://apps/foo", None),
    ],
)
def test_steam_appid_extraction(url, expected):
    """T3.20 Composite 64-bit ids belong to mods, not to store pages."""
    assert ss.steam_appid_from_url(url) == expected
