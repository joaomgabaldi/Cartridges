# test_steam_appdetails.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O formato da resposta do appdetails da Steam."""

import contextlib

import pytest

from cartridges.utils import steam


def resposta(payload):
    class Falsa:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    return contextlib.contextmanager(lambda *_a, **_k: (yield Falsa()))


def dados(appid):
    return {
        "success": True,
        "data": {"type": "game", "name": "Rise of the Tomb Raider", "steam_appid": appid},
    }


def helper():
    return steam.SteamAPIHelper(contextlib.nullcontext())


def test_chave_diferente_do_appid(monkeypatch):
    """Setembro de 2026: a Steam passou a devolver a entrada sob outra chave
    (391220 veio como "541750"), com o appID certo dentro de ``data``."""
    monkeypatch.setattr(steam, "get_capped", resposta({"541750": dados(391220)}))

    assert helper().get_api_data("391220", skip_genre=True)["name"] == "Rise of the Tomb Raider"


def test_varias_entradas_sem_a_chave_nao_adivinha(monkeypatch):
    monkeypatch.setattr(
        steam, "get_capped", resposta({"1": dados(1), "2": dados(2)})
    )

    with pytest.raises(steam.SteamGameNotFoundError):
        helper().get_api_data("391220", skip_genre=True)
