"""A sessão liga o vigia e decide o que fazer com cada conquista nova."""

import pytest

from cartridges import conquista_aviso
from cartridges.conquistas import sessao
from cartridges.conquistas.catalogo import ConquistaInfo
from cartridges.conquistas.vigia import Desbloqueada
from cartridges.utils import session_fita


class _VigiaFalso:
    criados: list = []

    def __init__(self, game, avisar):
        self.game, self.avisar, self.iniciado, self.parado = game, avisar, False, False
        _VigiaFalso.criados.append(self)

    def iniciar(self):
        self.iniciado = True

    def parar(self):
        self.parado = True


@pytest.fixture(autouse=True)
def isolar(monkeypatch):
    _VigiaFalso.criados = []
    monkeypatch.setattr(sessao, "Vigia", _VigiaFalso)
    monkeypatch.setattr(sessao, "acompanha", lambda _g: True)
    mostrados, pulsos = [], []
    monkeypatch.setattr(conquista_aviso, "mostrar", mostrados.append)
    monkeypatch.setattr(conquista_aviso, "fechar", lambda: mostrados.append("fechar"))
    monkeypatch.setattr(session_fita, "pulsar_conquista", pulsos.append)
    yield mostrados, pulsos
    sessao.parar()


def _info(rara=False):
    return ConquistaInfo("A", "Título", "Desc", "", "", False, 4.0 if rara else 50.0)


def test_comecar_e_parar(make_game, isolar):
    jogo = make_game(name="Jogo")
    sessao.comecar(jogo)
    (vigia_,) = _VigiaFalso.criados
    assert vigia_.iniciado and vigia_.game is jogo
    sessao.parar()
    assert vigia_.parado
    assert isolar[0] == ["fechar"]


def test_jogo_nao_acompanhado_nao_cria_vigia(make_game, monkeypatch):
    monkeypatch.setattr(sessao, "acompanha", lambda _g: False)
    sessao.comecar(make_game())
    assert _VigiaFalso.criados == []


def test_conquista_nova_mostra_cartao_e_pulsa(make_game, isolar):
    mostrados, pulsos = isolar
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(rara=True), False)])
    assert [a.titulo for a in mostrados] == ["Título"]
    assert pulsos == ["rara"]


def test_sem_catalogo_pulsa_sem_cartao(make_game, isolar):
    mostrados, pulsos = isolar
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", None, False)])
    assert mostrados == []
    assert pulsos == ["normal"]


def test_preferencias_desligadas(make_game, isolar, schema):
    mostrados, pulsos = isolar
    schema.set_boolean("conquistas-aviso", False)
    schema.set_boolean("conquistas-iluminacao", False)
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(), False)])
    assert mostrados == [] and pulsos == []


def test_tipo_do_pulso():
    assert sessao.tipo_do_pulso(Desbloqueada("A", _info(rara=True), True)) == "completo"
    assert sessao.tipo_do_pulso(Desbloqueada("A", _info(rara=True), False)) == "rara"
    assert sessao.tipo_do_pulso(Desbloqueada("A", _info(), False)) == "normal"
    assert sessao.tipo_do_pulso(Desbloqueada("A", None, False)) == "normal"


def test_erro_no_despacho_nao_levanta(make_game, isolar, monkeypatch):
    sessao.comecar(make_game())
    monkeypatch.setattr(conquista_aviso.Aviso, "de", classmethod(lambda cls, d: 1 / 0))
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(), False)])  # não levanta


def test_pagina_aberta_do_jogo_e_atualizada(make_game, isolar, win):
    jogo = make_game()
    chamadas = []
    win.active_game = jogo
    win.update_conquistas_block = chamadas.append
    sessao.comecar(jogo)
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", None, False)])
    assert chamadas == [jogo]


def test_a_sessao_da_janela_liga_e_desliga_o_vigia(real_window, make_game, monkeypatch):
    import cartridges.window as window_module  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(window_module.sessao_conquistas, "comecar", chamadas.append)
    monkeypatch.setattr(window_module.sessao_conquistas, "parar", lambda: chamadas.append("parar"))
    jogo = make_game(name="Hollow Knight")
    real_window.show_session_blocker(jogo)
    real_window.hide_session_blocker()
    assert chamadas == [jogo, "parar"]
