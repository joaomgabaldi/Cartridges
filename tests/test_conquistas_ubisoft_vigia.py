"""O vigia da Ubisoft: o `.spool` do jogo durante a partida."""

import os

import pytest

from cartridges.conquistas import catalogo, historico, vigia
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.ubisoft import pacote, vigia as vigia_ubisoft
from tests.apoio_conquistas import gravar_pacote, gravar_spool, pastas  # noqa: F401

INICIO = 1_791_243_000
CAT = Catalogo(
    (
        ConquistaInfo("UBI:12", "Silêncio!", "", "", "", False),
        ConquistaInfo("UBI:23", "A Vivaz Havana", "", "", "", False),
    ),
    0,
    False,
)


@pytest.fixture(autouse=True)
def sem_timeout(monkeypatch):
    """O tique é chamado à mão; nada de GLib.timeout de verdade nos testes."""
    fontes_ = []
    monkeypatch.setattr(vigia.GLib, "timeout_add_seconds", lambda _s, f: fontes_.append(f) or 7)
    monkeypatch.setattr(vigia.GLib, "source_remove", lambda _id: None)
    return fontes_


def _passo(caminho, segundos):
    os.utime(caminho, ns=(10**18 + segundos * 10**9, 10**18 + segundos * 10**9))


def _vigia(make_game, fonte="ubisoft:65043", **campos):
    campos.setdefault("executable", 'start "" "uplay://launch/65043/0"')
    game = make_game(game_id="u1", name="AC", **campos)
    if fonte:
        historico.registrar(game.game_id, [], fonte=fonte)
    avisos = []
    instancia = vigia_ubisoft.Vigia(game, avisos.append, relogio=lambda: INICIO)
    return instancia, avisos


def test_base_em_silencio_e_desbloqueio_avisa(pastas, make_game, sem_timeout):  # noqa: F811
    catalogo.guardar("ubisoft-65043", CAT)
    caminho = gravar_spool(pastas, "65043", [(23, 1785102639)])
    _passo(caminho, 1)
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    assert instancia.ativo and historico.ler("u1") == {"UBI:23": 1785102639}
    gravar_spool(pastas, "65043", [(23, 1785102639), (12, INICIO + 60)])
    _passo(caminho, 2)
    instancia._olhar()
    assert historico.ler("u1") == {"UBI:23": 1785102639, "UBI:12": INICIO + 60}
    (lista,) = avisos
    (nova,) = lista
    assert nova.nome == "UBI:12" and nova.info.titulo == "Silêncio!"
    assert nova.completou is True  # 2 de 2


def test_sem_catalogo_avisa_sem_info(pastas, make_game):  # noqa: F811
    caminho = gravar_spool(pastas, "65043", [])
    _passo(caminho, 1)
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    gravar_spool(pastas, "65043", [(12, INICIO + 60)])
    _passo(caminho, 2)
    instancia._olhar()
    (lista,) = avisos
    assert lista[0].info is None and lista[0].completou is False


def test_vigia_nunca_abre_o_zip(pastas, make_game, monkeypatch):  # noqa: F811
    gravar_pacote(pastas, "65043", {"pt-BR": {12: ("Silêncio!", "")}})
    monkeypatch.setattr(pacote, "obter", lambda *_a: pytest.fail("o vigia abriu o ZIP"))
    caminho = gravar_spool(pastas, "65043", [])
    _passo(caminho, 1)
    instancia, _avisos = _vigia(make_game)
    instancia.iniciar()
    gravar_spool(pastas, "65043", [(12, INICIO + 60)])
    _passo(caminho, 2)
    instancia._olhar()


def test_spool_que_nasce_na_partida_entra_em_silencio(pastas, make_game):  # noqa: F811
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()  # jogo aberto aqui pela primeira vez: ainda sem `.spool`
    assert instancia.ativo
    gravar_spool(pastas, "65043", [(23, 1785102639), (12, INICIO + 30)], conta="aaa")
    for _tique in range(vigia.REBUSCA):
        instancia._olhar()
    assert historico.ler("u1") == {"UBI:23": 1785102639, "UBI:12": INICIO + 30}
    assert avisos == []


def test_hora_anterior_ao_inicio_nao_avisa(pastas, make_game):  # noqa: F811
    caminho = gravar_spool(pastas, "65043", [])
    _passo(caminho, 1)
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    gravar_spool(pastas, "65043", [(5, INICIO - vigia.MARGEM_DA_STEAM - 1), (12, INICIO + 60)])
    _passo(caminho, 2)
    instancia._olhar()
    assert set(historico.ler("u1")) == {"UBI:5", "UBI:12"}
    (lista,) = avisos
    assert [d.nome for d in lista] == ["UBI:12"]


def test_spool_ilegivel_tenta_de_novo_no_proximo_tique(pastas, make_game):  # noqa: F811
    caminho = gravar_spool(pastas, "65043", [])
    _passo(caminho, 1)
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    caminho.write_bytes(b"\x8a")  # o launcher gravando
    _passo(caminho, 2)
    instancia._olhar()
    assert avisos == []
    gravar_spool(pastas, "65043", [(12, INICIO + 60)])
    _passo(caminho, 3)
    instancia._olhar()
    (lista,) = avisos
    assert lista[0].nome == "UBI:12"


def test_duas_contas_sao_acompanhadas(pastas, make_game):  # noqa: F811
    um = gravar_spool(pastas, "65043", [], conta="aaa")
    dois = gravar_spool(pastas, "65043", [], conta="bbb")
    _passo(um, 1)
    _passo(dois, 1)
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    gravar_spool(pastas, "65043", [(12, INICIO + 60)], conta="bbb")
    _passo(dois, 2)
    instancia._olhar()
    assert len(avisos) == 1


def test_sem_fonte_ubisoft_nao_acompanha(pastas, make_game, sem_timeout):  # noqa: F811
    instancia, _avisos = _vigia(make_game, fonte="steam:570", steam_appid="570")
    instancia.iniciar()
    assert not instancia.ativo and sem_timeout == []


def test_interruptor_desligado_nao_acompanha(pastas, make_game, sem_timeout):  # noqa: F811
    instancia, _avisos = _vigia(make_game, conquistas=False)
    instancia.iniciar()
    assert not instancia.ativo and sem_timeout == []


def test_nao_troca_a_fonte_gravada(pastas, make_game):  # noqa: F811
    caminho = gravar_spool(pastas, "65043", [(23, 1785102639)])
    _passo(caminho, 1)
    instancia, _avisos = _vigia(make_game)
    instancia.iniciar()
    assert historico.fonte("u1") == "ubisoft:65043"
