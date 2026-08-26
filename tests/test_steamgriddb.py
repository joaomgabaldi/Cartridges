# test_steamgriddb.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Telling the user their API key is wrong.

The API answers 401 with a JSON ``errors`` list, but the 401 a user actually
hits — a bad or expired key — is often served by Cloudflare in front of it, as
an HTML page. Reading that as JSON raised ``JSONDecodeError``, which is in
``SgdbManager.retryable_on``: the wrong-key case was retried three times and
then reported as a generic failure, so the one dialog that would have told them
what to fix was the one they never saw.
"""

import json

import pytest
import requests

from cartridges.utils import steamgriddb as sgdb
from cartridges.utils.steamgriddb import SgdbAuthError, SgdbGameNotFound


class FakeResponse:
    def __init__(self, status_code, body, is_json=True):
        self.status_code = status_code
        self._body = body
        self._is_json = is_json

    def json(self):
        if not self._is_json:
            raise requests.exceptions.JSONDecodeError("no json", "", 0)
        return self._body


@pytest.fixture(autouse=True)
def key(schema):
    schema["sgdb-key"] = "test-key"
    return schema


@pytest.fixture
def responses(monkeypatch):
    """Script the HTTP answers ``get_game_id`` will see."""
    queue: list = []

    def fake_get(*_args, **_kwargs):
        return queue.pop(0)

    monkeypatch.setattr(sgdb.requests, "get", fake_get)
    return queue


def test_html_401_becomes_an_auth_error(responses, make_game):
    """T6.24 A Cloudflare page is not JSON, and must not be read as one."""
    responses.append(
        FakeResponse(401, "<html><body>Access denied</body></html>", is_json=False)
    )

    with pytest.raises(SgdbAuthError):
        sgdb.SgdbHelper().get_game_id(make_game(name="Halo"))


def test_json_401_without_an_errors_key_becomes_an_auth_error(responses, make_game):
    """T6.25 A body of another shape used to raise KeyError instead."""
    responses.append(FakeResponse(401, {"message": "unauthorized"}))

    with pytest.raises(SgdbAuthError):
        sgdb.SgdbHelper().get_game_id(make_game(name="Halo"))


def test_a_well_formed_401_keeps_its_message(responses, make_game):
    """The good path still carries the API's own wording."""
    responses.append(FakeResponse(401, {"errors": ["Invalid API key"]}))

    with pytest.raises(SgdbAuthError, match="Invalid API key"):
        sgdb.SgdbHelper().get_game_id(make_game(name="Halo"))


def test_an_exact_title_match_wins_over_the_first_result(responses, make_game):
    """T6.26 This is an autocomplete endpoint, so the first hit is fuzzy.

    Taking ``results[0]`` blindly attaches another game's art, and — with the
    logo hit cached — makes that permanent.
    """
    responses.append(
        FakeResponse(
            200,
            {
                "data": [
                    {"id": 111, "name": "Halo Infinite Multiplayer"},
                    {"id": 222, "name": "Halo"},
                ]
            },
        )
    )

    assert sgdb.SgdbHelper().get_game_id(make_game(name="Halo")) == 222


def test_the_exact_match_is_case_insensitive(responses, make_game):
    responses.append(
        FakeResponse(200, {"data": [{"id": 111, "name": "other"}, {"id": 222, "name": "HALO"}]})
    )

    assert sgdb.SgdbHelper().get_game_id(make_game(name="halo")) == 222


def test_without_an_exact_match_the_first_result_is_used(responses, make_game):
    """The documented fallback: a real residual risk, but better than nothing."""
    responses.append(
        FakeResponse(200, {"data": [{"id": 111, "name": "Halo: The Master Chief"}]})
    )

    assert sgdb.SgdbHelper().get_game_id(make_game(name="Halo")) == 111


def test_no_results_is_a_not_found(responses, make_game):
    responses.append(FakeResponse(200, {"data": []}))

    with pytest.raises(SgdbGameNotFound):
        sgdb.SgdbHelper().get_game_id(make_game(name="Nonexistent"))


def test_a_200_with_an_unexpected_shape_is_a_sgdb_error(responses, make_game):
    """Auditoria 26/08, M9: um 200 de shape inesperado (proxy devolvendo
    `{"success": false}`) estourava KeyError fora dos excepts dos pickers —
    a thread morria e o spinner ficava eterno. Shape errado agora é SgdbError."""
    responses.append(FakeResponse(200, {"success": False}))

    with pytest.raises(sgdb.SgdbBadRequest):
        sgdb.SgdbHelper().get_game_id(make_game(name="Celeste"))


def test_a_200_whose_items_lack_ids_is_a_sgdb_error(responses, make_game):
    responses.append(FakeResponse(200, {"data": [{"name": "Celeste"}]}))

    with pytest.raises(sgdb.SgdbBadRequest):
        sgdb.SgdbHelper().get_game_id(make_game(name="Celeste"))
