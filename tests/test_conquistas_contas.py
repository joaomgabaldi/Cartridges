"""A "loja com conta": o registro e o que fontes/vigia/varredura pedem a ela."""

from types import SimpleNamespace

import pytest

from cartridges.conquistas import contas, fontes
from cartridges.conquistas.fontes import Fonte
from tests.apoio_conquistas import pastas  # noqa: F401


def test_xbox_esta_no_registro():
    from cartridges.conquistas.xbox import loja  # noqa: PLC0415

    assert contas.lojas()["xbox"] is loja
    assert loja.TIPO == "xbox"


def test_da_fonte():
    assert contas.da_fonte(None) is None
    assert contas.da_fonte(Fonte("steam", "570")) is None
    assert contas.da_fonte(Fonte("xbox", "7")) is contas.lojas()["xbox"]


@pytest.fixture
def loja_falsa(monkeypatch):
    estado = SimpleNamespace(conectada=True)
    falsa = SimpleNamespace(
        TIPO="xbox",
        FalhaDeRede=RuntimeError,
        conectada=lambda: estado.conectada,
        chave_do_catalogo=lambda id_: f"falsa-{id_}",
    )
    monkeypatch.setitem(contas.lojas(), "xbox", falsa)
    return estado


def test_ativa_pergunta_a_loja(loja_falsa):
    assert fontes.ativa(Fonte("xbox", "7"))
    loja_falsa.conectada = False
    assert not fontes.ativa(Fonte("xbox", "7"))
    assert fontes.ativa(Fonte("steam", "570"))
    assert not fontes.ativa(None)


def test_chave_do_catalogo_pergunta_a_loja(loja_falsa):
    assert fontes.chave_do_catalogo(Fonte("xbox", "7")) == "falsa-7"
    assert fontes.chave_do_catalogo(Fonte("steam", "570")) == "570"


def test_epic_esta_no_registro():
    from cartridges.conquistas.epic import loja  # noqa: PLC0415

    assert contas.lojas()["epic"] is loja and loja.TIPO == "epic"


def test_historico_guarda_conta_de_toda_loja_do_registro():
    from cartridges.conquistas import historico  # noqa: PLC0415

    assert {prefixo.rstrip(":") for prefixo in historico._FONTES_COM_CONTA_GUARDADA} == set(contas.lojas()) | {"ubisoft"}


def test_resolver_da_epic(make_game, monkeypatch, pastas):  # noqa: F811
    from cartridges.conquistas.epic import api, loja  # noqa: PLC0415

    monkeypatch.setattr(api, "namespace_do_app", lambda app: "n1" if app == "Sugar" else "")
    url = 'start "" "com.epicgames.launcher://apps/Sugar?action=launch"'
    assert loja.resolver(make_game(executable=url), Fonte("epic", "")) == "n1"
    assert loja.resolver(make_game(executable="x.exe"), Fonte("epic", "")) == ""
