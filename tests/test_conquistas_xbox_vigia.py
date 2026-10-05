"""O vigia do Xbox: consulta a conta a cada 15 s durante a sessão; só pulso."""

import pytest

from cartridges.conquistas import catalogo, historico
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.xbox import api, conta
from cartridges.conquistas.xbox import vigia as vigia_xbox

_INICIO = 1_800_000_000


def _sincrono(trabalho, entregar):
    entregar(trabalho())


@pytest.fixture
def ambiente(monkeypatch, make_game):
    estado = {"lidos": [], "falha": None, "conectada": True, "pedidos": 0}
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])

    def desbloqueadas(titulo):
        estado["pedidos"] += 1
        if estado["falha"] is not None:
            raise estado["falha"]
        return list(estado["lidos"]) if estado["conectada"] else None

    monkeypatch.setattr(api, "desbloqueadas", desbloqueadas)
    cat = Catalogo(tuple(ConquistaInfo(f"XBOX:{n}", f"T{n}", "", "", "", False) for n in (1, 2)), 0, False)
    catalogo.guardar("xbox-7", cat)
    game = make_game()
    historico.registrar(game.game_id, [], fonte="xbox:7")
    avisos: list = []
    v = vigia_xbox.Vigia(game, avisos.append, relogio=lambda: _INICIO, em_thread=_sincrono)
    return v, estado, avisos, game


def test_base_entra_em_silencio(ambiente):
    v, estado, avisos, game = ambiente
    estado["lidos"] = [Desbloqueio("XBOX:1", _INICIO - 3600)]
    v.iniciar()
    try:
        assert historico.ler(game.game_id) == {"XBOX:1": _INICIO - 3600}
        assert avisos == []
    finally:
        v.parar()


def test_nova_avisa_e_completa(ambiente):
    v, estado, avisos, game = ambiente
    estado["lidos"] = [Desbloqueio("XBOX:1", _INICIO - 3600)]
    v.iniciar()
    estado["lidos"].append(Desbloqueio("XBOX:2", _INICIO + 60))
    v._olhar()
    v.parar()
    assert [(d.nome, d.completou) for d in avisos[0]] == [("XBOX:2", True)]
    assert avisos[0][0].info.titulo == "T2"


def test_de_outro_aparelho_entra_em_silencio(ambiente):
    v, estado, avisos, game = ambiente
    v.iniciar()
    estado["lidos"] = [Desbloqueio("XBOX:1", _INICIO - 10 * 60)]
    v._olhar()
    v.parar()
    assert avisos == [] and "XBOX:1" in historico.ler(game.game_id)


def test_sem_data_conta_como_nova(ambiente):
    v, estado, avisos, _game = ambiente
    v.iniciar()
    estado["lidos"] = [Desbloqueio("XBOX:1", 0)]
    v._olhar()
    v.parar()
    assert [d.nome for d in avisos[0]] == ["XBOX:1"]


def test_falha_de_rede_tenta_no_proximo_tique(ambiente):
    v, estado, avisos, _game = ambiente
    estado["falha"] = api.FalhaDeRede()
    v.iniciar()  # a base falhou: continua pendente
    estado["falha"] = None
    estado["lidos"] = [Desbloqueio("XBOX:1", _INICIO + 5)]
    v._olhar()  # esta vira a base (silêncio): o que já estava não pode virar aviso
    estado["lidos"].append(Desbloqueio("XBOX:2", _INICIO + 30))
    v._olhar()
    v.parar()
    assert [d.nome for lote in avisos for d in lote] == ["XBOX:2"]


def test_vigia_para_quando_a_conta_cai(ambiente):
    v, estado, _avisos, _game = ambiente
    v.iniciar()
    estado["conectada"] = False
    v._olhar()
    assert not v.ativo


def test_um_pedido_por_vez(ambiente):
    v, estado, _avisos, _game = ambiente
    guardados = []
    v._em_thread = lambda trabalho, entregar: guardados.append((trabalho, entregar))
    v.iniciar()
    v._olhar()
    v._olhar()
    assert len(guardados) == 1
    v.parar()


def test_resposta_depois_de_parar_e_descartada(ambiente):
    v, estado, avisos, game = ambiente
    guardados = []
    v._em_thread = lambda trabalho, entregar: guardados.append((trabalho, entregar))
    v.iniciar()
    v.parar()
    trabalho, entregar = guardados[0]
    estado["lidos"] = [Desbloqueio("XBOX:1", _INICIO + 5)]
    entregar(trabalho())
    assert historico.ler(game.game_id) == {}


def test_resposta_de_uma_sessao_anterior_nao_vale_na_nova(ambiente):
    v, estado, avisos, game = ambiente
    guardados = []
    v._em_thread = lambda trabalho, entregar: guardados.append((trabalho, entregar))
    v.iniciar()
    v.parar()
    v.iniciar()  # nova sessão: novo pedido
    estado["lidos"] = [Desbloqueio("XBOX:1", _INICIO + 5)]
    trabalho, entregar = guardados[0]  # a resposta do pedido antigo
    entregar(trabalho())
    assert historico.ler(game.game_id) == {}
    trabalho, entregar = guardados[1]
    entregar(trabalho())
    assert historico.ler(game.game_id) == {"XBOX:1": _INICIO + 5}
    v.parar()


def test_sem_fonte_xbox_nao_inicia(monkeypatch, make_game):
    game = make_game()
    historico.registrar(game.game_id, [], fonte="steam:570")
    v = vigia_xbox.Vigia(game, lambda _a: None, em_thread=_sincrono)
    v.iniciar()
    assert not v.ativo


def test_conta_desconectada_nao_inicia(ambiente):
    v, estado, _avisos, _game = ambiente
    estado["conectada"] = False
    v.iniciar()
    assert not v.ativo and estado["pedidos"] == 0


def test_falha_inesperada_na_consulta_nao_levanta(ambiente):
    v, estado, avisos, _game = ambiente
    estado["falha"] = RuntimeError("falha de teste")
    v.iniciar()  # não levanta
    assert v._tique() is True
    estado["falha"] = None
    estado["lidos"] = [Desbloqueio("XBOX:1", _INICIO + 5)]
    v._olhar()  # base: o vigia continua vivo e o pedido não ficou preso
    assert v.ativo and avisos == []
    v.parar()


def test_base_que_nao_foi_gravada_continua_em_silencio(ambiente, monkeypatch):
    v, estado, avisos, game = ambiente
    estado["lidos"] = [Desbloqueio("XBOX:1", _INICIO + 5)]
    original = historico.registrar
    monkeypatch.setattr(historico, "registrar", lambda *_a, **_k: ([], False))  # histórico indisponível
    v.iniciar()
    monkeypatch.setattr(historico, "registrar", original)
    v._olhar()  # esta é a base de verdade
    assert avisos == [] and historico.ler(game.game_id) == {"XBOX:1": _INICIO + 5}
    v.parar()


def test_tique_devolve_true_e_nao_levanta(ambiente):
    v, _estado, _avisos, _game = ambiente
    v.iniciar()
    v._em_thread = lambda *_a: 1 / 0
    assert v._tique() is True
    assert not v._pedindo  # o pedido que não saiu não trava os seguintes
    v.parar()
