"""A "loja com conta": o registro e o que fontes/vigia/varredura pedem a ela."""

from types import SimpleNamespace

import pytest

from cartridges.conquistas import contas, fontes
from cartridges.conquistas.fontes import Fonte


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
