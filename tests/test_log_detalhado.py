"""Testes do rastreio de chamadas do log detalhado (sys.monitoring)."""

import json
import logging
import re
import sys
import threading

import pytest

from cartridges.logging import detalhado

# Módulo de exemplo com __name__ em cartridges.*, para ser reconhecido como do app.
_FONTE = '''
def x(a):
    return a + 1

def v():
    return w()

def w():
    return x(a=1)

def levanta():
    raise ValueError("falhou")

def captura():
    try:
        levanta()
    except ValueError:
        return "ok"

class Ruim:
    def __repr__(self):
        raise RuntimeError("sem repr")

class ReprDoApp:
    def __repr__(self):
        return "<ReprDoApp>"

def recebe(valor):
    return None

def gerador():
    yield 1
    yield 2

def abandona():
    g = gerador()
    next(g)
    g.close()
    return x(1)
'''


@pytest.fixture
def app():
    espaco = {"__name__": "cartridges.teste_rastreio"}
    exec(compile(_FONTE, "<teste>", "exec"), espaco)  # pylint: disable=exec-used
    detalhado.instalar_rastreio()
    try:
        yield type("Modulo", (), espaco)
    finally:
        detalhado.remover_rastreio()


def _linhas(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "cartridges.rastreio"]


def _com_log(caplog):
    caplog.set_level(logging.DEBUG, logger="cartridges.rastreio")


def test_cadeia_em_ordem_com_profundidade(app, caplog):
    _com_log(caplog)
    app.v()
    linhas = _linhas(caplog)
    esperado = [
        r"^1 > cartridges\.teste_rastreio\.v\(",
        r"^2 > cartridges\.teste_rastreio\.w\(",
        r"^3 > cartridges\.teste_rastreio\.x\(",
        r"^3 < cartridges\.teste_rastreio\.x ",
        r"^2 < cartridges\.teste_rastreio\.w ",
        r"^1 < cartridges\.teste_rastreio\.v ",
    ]
    assert len(linhas) == 6
    for linha, padrao in zip(linhas, esperado):
        assert re.search(padrao, linha), linha


def test_argumentos_e_retorno_aparecem(app, caplog):
    _com_log(caplog)
    app.x(1)
    linhas = _linhas(caplog)
    assert "x(a=1)" in linhas[0]
    assert " = 2 (" in linhas[1] and linhas[1].endswith(" ms)")


def test_excecao_registrada_e_profundidade_volta(app, caplog):
    _com_log(caplog)
    assert app.captura() == "ok"
    linhas = _linhas(caplog)
    assert any(" ! cartridges.teste_rastreio.levanta levantou ValueError" in l for l in linhas)
    caplog.clear()
    app.v()
    assert _linhas(caplog)[0].startswith("1 > ")


def test_thread_secundaria_e_rastreada(app, caplog):
    _com_log(caplog)
    t = threading.Thread(target=app.x, args=(1,), name="fio-de-teste")
    t.start()
    t.join()
    nomes = {r.threadName for r in caplog.records if r.name == "cartridges.rastreio"}
    assert nomes == {"fio-de-teste"}


def test_repr_que_levanta_nao_quebra(app, caplog):
    _com_log(caplog)
    assert app.recebe(app.Ruim()) is None
    assert "<repr falhou>" in _linhas(caplog)[0]


def test_repr_do_app_nao_gera_linha_aninhada(app, caplog):
    _com_log(caplog)
    app.recebe(app.ReprDoApp())
    linhas = _linhas(caplog)
    assert len(linhas) == 2
    assert "<ReprDoApp>" in linhas[0]
    assert not any("__repr__" in l for l in linhas)


def test_valor_longo_cortado_em_500(app, caplog):
    _com_log(caplog)
    app.recebe("a" * 10_000)
    assert len(_linhas(caplog)[0]) < 500 + 100
    assert "a" * 501 not in _linhas(caplog)[0]


def test_quebra_de_linha_nao_abre_outra_linha(app, caplog):
    _com_log(caplog)
    app.recebe("a\nb")
    linha = _linhas(caplog)[0]
    assert "\n" not in linha and "\r" not in linha


def test_gerador_nao_acumula_profundidade(app, caplog):
    _com_log(caplog)
    assert list(app.gerador()) == [1, 2]
    caplog.clear()
    app.x(1)
    assert _linhas(caplog)[0].startswith("1 > ")


def test_gerador_abandonado_nao_acumula_profundidade(app, caplog):
    _com_log(caplog)
    # Dentro de outra função: um `close()` que desempilhasse a mais comeria a profundidade dela.
    app.abandona()
    assert [l for l in _linhas(caplog) if ".x(" in l][0].startswith("2 > ")


def test_codigo_de_fora_nao_aparece(app, caplog):
    _com_log(caplog)
    json.dumps({"a": 1})
    assert _linhas(caplog) == []


def test_remover_libera_a_ferramenta(app, caplog):
    detalhado.remover_rastreio()
    assert sys.monitoring.get_tool(sys.monitoring.PROFILER_ID) is None
    _com_log(caplog)
    app.x(1)
    assert _linhas(caplog) == []


def test_ativo_variavel_vence_constante(monkeypatch):
    monkeypatch.setattr(detalhado, "ATIVO", True)
    monkeypatch.setenv("CARTRIDGES_LOG_DETALHADO", "0")
    assert detalhado.ativo() is False
    monkeypatch.setattr(detalhado, "ATIVO", False)
    monkeypatch.setenv("CARTRIDGES_LOG_DETALHADO", "1")
    assert detalhado.ativo() is True
    monkeypatch.delenv("CARTRIDGES_LOG_DETALHADO")
    assert detalhado.ativo() is False
    monkeypatch.setattr(detalhado, "ATIVO", True)
    assert detalhado.ativo() is True
