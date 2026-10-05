"""A janela de login da Epic: colar o código e conectar."""

import pytest

from cartridges.conquistas.epic import conta, janela

_COD = "0123456789abcdef0123456789abcdef"


def _sincrono(trabalho, entregar):
    entregar(trabalho())


@pytest.fixture
def abertas():
    return []


def _janela(abertas, ao_conectar=lambda: None):
    j = janela.JanelaDeLogin(ao_conectar, abrir=abertas.append, em_thread=_sincrono)
    # Registra o fechamento sem precisar apresentar a janela.
    j.close = lambda: abertas.append("fechou")
    return j


def test_abrir_a_pagina_novamente(abertas):
    j = _janela(abertas)
    j.botao_abrir.emit("clicked")
    assert abertas == [conta.PAGINA_DE_LOGIN]


def test_conectar_fica_insensivel_sem_codigo(abertas):
    j = _janela(abertas)
    assert not j.botao_conectar.get_sensitive()
    j.campo.set_text("lixo")
    assert not j.botao_conectar.get_sensitive()
    j.campo.set_text(f'{{"authorizationCode": "{_COD}"}}')
    assert j.botao_conectar.get_sensitive()


def test_sucesso_fecha_e_avisa(abertas, monkeypatch):
    recebidos = []
    monkeypatch.setattr(conta, "conectar", recebidos.append)
    conectados = []
    j = _janela(abertas, lambda: conectados.append(1))
    j.campo.set_text(_COD)
    j.botao_conectar.emit("clicked")
    assert recebidos == [_COD] and conectados == [1] and "fechou" in abertas


def test_codigo_recusado_fica_aberta_e_limpa(abertas, monkeypatch):
    def recusa(_codigo):
        raise conta.CodigoRecusado()

    monkeypatch.setattr(conta, "conectar", recusa)
    j = _janela(abertas)
    j.campo.set_text(_COD)
    j.botao_conectar.emit("clicked")
    assert "fechou" not in abertas
    assert j.erro.get_visible()
    assert j.erro.get_label() == "O código não foi aceito. Gere um novo código na página da Epic e tente novamente."
    assert j.campo.get_text() == ""


def test_outra_falha_fica_aberta(abertas, monkeypatch):
    def quebra(_codigo):
        raise OSError("rede")

    monkeypatch.setattr(conta, "conectar", quebra)
    j = _janela(abertas)
    j.campo.set_text(_COD)
    j.botao_conectar.emit("clicked")
    assert j.erro.get_label() == "Não foi possível entrar na conta Epic."
    assert j.campo.get_text() == _COD and j.botao_conectar.get_sensitive()


def test_resultado_depois_de_fechada_e_descartado(abertas, monkeypatch):
    pendente = []
    monkeypatch.setattr(conta, "conectar", lambda _c: None)
    conectados = []
    j = janela.JanelaDeLogin(
        lambda: conectados.append(1), abrir=abertas.append, em_thread=lambda t, e: pendente.append((t, e))
    )
    j.campo.set_text(_COD)
    j.botao_conectar.emit("clicked")
    j.emit("closed")
    trabalho, entregar = pendente[0]
    entregar(trabalho())
    assert conectados == []


def test_texto_colado_nao_vai_ao_log(abertas, monkeypatch, caplog):
    caplog.set_level("DEBUG")

    def quebra(_codigo):
        raise ValueError("x")

    monkeypatch.setattr(conta, "conectar", quebra)
    j = _janela(abertas)
    j.campo.set_text(_COD)
    j.botao_conectar.emit("clicked")
    assert _COD not in caplog.text
