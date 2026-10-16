"""A EA como "loja com conta": adapta `api`, `conta` e `jogo`; o resolver acha o conjunto."""

from types import SimpleNamespace

import pytest

from cartridges.conquistas import fontes
from cartridges.conquistas.ea import api, jogo, loja
from cartridges.conquistas.fontes import Fonte


@pytest.fixture
def ea(monkeypatch):
    estado = SimpleNamespace(
        candidato=jogo.Candidato(pasta="c:\\ea\\jogo", titulo="Jogo: Edição"),
        ofertas=["o1"],
        conjuntos={"o1": "1_2_3"},
        falha=None,
        guardado=[],
        pedidos=[],
    )
    monkeypatch.setattr(fontes, "candidato_da_ea", lambda _game: estado.candidato)

    def ofertas(titulo):
        estado.pedidos.append(titulo)
        if estado.falha is not None:
            raise estado.falha
        return estado.ofertas

    monkeypatch.setattr(api, "ofertas", ofertas)
    monkeypatch.setattr(api, "conjunto_da_oferta", lambda oferta: estado.conjuntos.get(oferta, ""))
    monkeypatch.setattr(api, "guardar_conjunto", lambda pasta, conjunto: estado.guardado.append((pasta, conjunto)))
    return estado


def test_resolver_pela_biblioteca(ea):
    assert loja.resolver(object(), Fonte("ea", "")) == "1_2_3"
    assert ea.pedidos == [jogo.normalizar("Jogo: Edição")]
    assert ea.guardado == [("c:\\ea\\jogo", "1_2_3")]


def test_resolver_tenta_cada_titulo_em_ordem(ea, monkeypatch):
    ea.candidato = jogo.Candidato(pasta="c:\\ea\\jogo", titulo="Titulo PT", titulos=("Titulo PT", "Title EN"))
    monkeypatch.setattr(api, "ofertas", lambda t: ea.pedidos.append(t) or (["o1"] if t == "titleen" else []))
    assert loja.resolver(object(), Fonte("ea", "")) == "1_2_3"
    assert ea.pedidos == ["titulopt", "titleen"]
    assert ea.guardado == [("c:\\ea\\jogo", "1_2_3")]


def test_resolver_nenhum_titulo_na_biblioteca_guarda_vazio(ea, monkeypatch):
    ea.candidato = jogo.Candidato(pasta="c:\\ea\\jogo", titulo="A", titulos=("A", "B"))
    monkeypatch.setattr(api, "ofertas", lambda t: ea.pedidos.append(t) or [])
    assert loja.resolver(object(), Fonte("ea", "")) == ""
    assert ea.pedidos == ["a", "b"] and ea.guardado == [("c:\\ea\\jogo", "")]


def test_resolver_fora_da_biblioteca(ea):
    ea.ofertas = []
    assert loja.resolver(object(), Fonte("ea", "")) == ""
    assert ea.guardado == [("c:\\ea\\jogo", "")]


def test_resolver_tenta_as_ofertas_em_ordem(ea):
    ea.ofertas = ["o0", "o1"]  # o0 não tem conquistas
    assert loja.resolver(object(), Fonte("ea", "")) == "1_2_3"


def test_resolver_sem_ofertas_com_conquistas_guarda_vazio(ea):
    ea.ofertas = ["o0"]
    assert loja.resolver(object(), Fonte("ea", "")) == ""
    assert ea.guardado == [("c:\\ea\\jogo", "")]


def test_resolver_oferta_sem_resposta_nao_guarda_sem_fonte(ea):
    ea.ofertas = ["o0", "o9"]
    ea.conjuntos = {"o0": None, "o9": ""}  # o0 não respondeu (None), o9 não tem conquistas
    assert loja.resolver(object(), Fonte("ea", "")) is None
    assert ea.guardado == []


def test_resolver_conjunto_achado_vale_mesmo_com_oferta_sem_resposta(ea):
    ea.ofertas = ["o0", "o1"]
    ea.conjuntos = {"o0": None, "o1": "1_2_3"}
    assert loja.resolver(object(), Fonte("ea", "")) == "1_2_3"


def test_resolver_sem_conta(ea):
    ea.ofertas = None
    assert loja.resolver(object(), Fonte("ea", "")) is None
    assert ea.guardado == []


def test_resolver_falha_de_rede_propaga(ea):
    ea.falha = api.FalhaDeRede()
    with pytest.raises(loja.FalhaDeRede):
        loja.resolver(object(), Fonte("ea", ""))
    assert ea.guardado == []


def test_resolver_nao_candidato(ea):
    ea.candidato = None
    assert loja.resolver(object(), Fonte("ea", "")) == ""
    assert ea.pedidos == []


def test_adaptador(monkeypatch):
    from cartridges.conquistas.ea import conta  # noqa: PLC0415

    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "persona", lambda: "p1")
    monkeypatch.setattr(api, "ler", lambda id_: f"ler-{id_}")
    monkeypatch.setattr(api, "desbloqueadas", lambda id_: f"desb-{id_}")
    assert loja.TIPO == "ea" and loja.conectada() and loja.id_da_conta() == "p1"
    assert loja.ler("x") == "ler-x" and loja.desbloqueadas("x") == "desb-x"
    assert loja.chave_do_catalogo("1_2") == api.chave_do_catalogo("1_2")
