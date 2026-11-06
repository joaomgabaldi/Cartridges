# test_emuladores_idiomas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os idiomas da Steam e a leitura do ``supported_languages``."""

import contextlib

from kyron.emuladores import idiomas
from kyron.utils import steam

# Resposta real do appdetails do Cyberpunk 2077 (l=brazilian).
CYBERPUNK = 'Inglês<strong>*</strong>, Francês<strong>*</strong>, Italiano<strong>*</strong>, Alemão<strong>*</strong>, Espanhol (Espanha)<strong>*</strong>, Árabe, Tcheco, Húngaro, Japonês<strong>*</strong>, Coreano<strong>*</strong>, Polonês<strong>*</strong>, Português (Brasil)<strong>*</strong>, Russo<strong>*</strong>, Chinês simplificado<strong>*</strong>, Espanhol (América Latina), Tailandês, Chinês tradicional, Turco, Ucraniano<br><strong>*</strong>idiomas com suporte total de áudio'


def test_ordem_e_tamanho():
    assert next(iter(idiomas.IDIOMAS)) == "brazilian"
    assert len(idiomas.IDIOMAS) == 30


def test_le_supported_languages_real():
    codigos = idiomas.do_appdetails(CYBERPUNK)

    assert codigos[0] == "english"
    assert {"brazilian", "latam", "schinese", "tchinese", "ukrainian"} <= set(codigos)
    assert len(codigos) == 19


def test_nome_desconhecido_e_ignorado():
    assert idiomas.do_appdetails("Malaio, Inglês<strong>*</strong>") == ["english"]


def test_vazio():
    assert idiomas.do_appdetails("") == []


def _resposta(data):
    class Falsa:
        def raise_for_status(self):
            pass

        def json(self):
            return {"1": {"success": True, "data": data}}

    return contextlib.contextmanager(lambda *_a, **_k: (yield Falsa()))


def test_get_api_data_traz_idiomas(monkeypatch):
    base = {"type": "game", "name": "X", "supported_languages": CYBERPUNK}
    monkeypatch.setattr(steam, "get_capped", _resposta(base))
    h = steam.SteamAPIHelper(contextlib.nullcontext())
    monkeypatch.setattr(h, "get_review_summary", lambda _a: None)

    assert "brazilian" in h.get_api_data("1", skip_genre=True)["idiomas_steam"]

    del base["supported_languages"]
    assert "idiomas_steam" not in h.get_api_data("1", skip_genre=True)


def test_texto_sem_nenhum_nome_conhecido_e_desconhecido(monkeypatch):
    assert idiomas.do_appdetails("Malaio, Klingon") is None
    base = {"type": "game", "name": "X", "supported_languages": "Malaio, Klingon"}
    monkeypatch.setattr(steam, "get_capped", _resposta(base))
    h = steam.SteamAPIHelper(contextlib.nullcontext())
    monkeypatch.setattr(h, "get_review_summary", lambda _a: None)
    assert "idiomas_steam" not in h.get_api_data("1", skip_genre=True)
