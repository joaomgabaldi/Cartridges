# apoio_fita.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apoio dos testes das fitas de LED: a pasta descartável, o módulo Tuya falso e as fixtures comuns.

Módulo à parte, e não um teste: importar um `test_*.py` de outro arquivo roda a coleta de novo.
"""

import time
from typing import NamedTuple, Optional

import pytest

from cartridges import shared
from cartridges.utils import session_fita


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    """Tudo o que o módulo grava vai para uma pasta descartável."""
    monkeypatch.setattr(shared, "fitas_dir", tmp_path / "fitas")
    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    # As conexões abertas, a contagem de falhas e as suspensões também são
    # estado de módulo: um teste que suspendeu uma fita não pode deixá-la
    # suspensa para o seguinte.
    _esquecer_conexoes()
    yield tmp_path
    _esquecer_conexoes()


def _esquecer_conexoes():
    session_fita.fechar_conexoes()
    session_fita._falhas.clear()
    session_fita._suspensas.clear()
    session_fita._mostrada.clear()
    # O pulso de conquista também: sessão e fila não passam para o teste seguinte.
    session_fita._jogo_da_sessao = None
    session_fita._fila_de_pulsos.clear()
    session_fita._pulsando = False
    session_fita._teste_do_pulso = None
    # O acompanhamento da tela também.
    session_fita._acompanhamento = None
    session_fita._cor_ambiente = session_fita._teto_da_sessao = None
    session_fita._candidata = session_fita._ultima_troca = None
    session_fita._amostras_validas = session_fita._amostras_bloqueadas = 0
    session_fita._suspensa_em.clear()
    session_fita._fora_do_ar.clear()
    # A prévia também: um id que ficou em "_previa_vivas" (uma thread de outro
    # teste ainda servindo, ou uma tarefa espionada que ninguém rodou) faz o
    # pedido seguinte achar que já há quem pinte e não agendar nada.
    session_fita._previa_vivas.clear()
    session_fita._previa_alvos.clear()


@pytest.fixture(autouse=True)
def sem_vigia(monkeypatch):
    """A vigia das fitas fora do ar roda em laço a sessão inteira: nos testes
    ela não sobe sozinha. Os dela chamam uma rodada de cada vez."""
    monkeypatch.setattr(session_fita, "_comecar_vigia", lambda _sessao: None)


@pytest.fixture(autouse=True)
def sem_fade(monkeypatch):
    """Fade de 1,5 s em todo teste deixaria a suíte lenta e mudaria o que os
    testes antigos contam. Os testes do fade ligam de volta."""
    monkeypatch.setattr(session_fita, "DURACAO_FADE", 0)


class Msg(NamedTuple):
    """Uma mensagem da fita: o código do protocolo e o que veio dentro."""

    cmd: int
    payload: Optional[dict] = None


RECEBI, AVISO, BATIMENTO, CONSULTA = 7, 8, 9, 10


class SoqueteFalso:
    """O que chegou da fita e ainda não foi lido, em ordem de chegada.

    ``a_caminho`` são respostas que a fita ainda vai mandar: a fita aplica
    mais devagar do que recebe, e só quem espera por elas as vê chegar.
    """

    def __init__(self):
        self.fila = []
        self.a_caminho = []
        self.espera = session_fita.ESPERA

    def chegar(self):
        self.fila += self.a_caminho
        self.a_caminho = []

    def gettimeout(self):
        return self.espera

    def settimeout(self, segundos):
        self.espera = segundos

    def recv(self, _tamanho):
        if not self.fila:
            raise BlockingIOError("nada por ler")
        self.fila.pop(0)
        return b"mensagem"


class FitaFalsa:
    """Um módulo Tuya de mentira, que anota o que mandaram nele.

    Como o de verdade, cada comando volta um "recebi" e depois um aviso com os
    valores aplicados — menos o modo (21), que a fita nunca avisa.
    """

    def __init__(self, dps=None, quebrada=False, demora=0.0):
        self.dps = dps or {"20": False, "21": "colour", "24": "000003e800b4"}
        self.quebrada = quebrada
        # Quanto cada comando custa. Serve para provar que as fitas falam ao
        # mesmo tempo: em fila, três fitas de 0,1s levariam 0,3s.
        self.demora = demora
        self.recebidos = []
        # Quantas conversas correram ao mesmo tempo NESTA fita. O módulo Tuya
        # aceita uma sessão por vez, então este número não pode passar de um.
        self.simultaneos = 0
        self.pico = 0
        self.socket = SoqueteFalso()
        # A fita sobrecarregada às vezes não avisa: medido a 40 degraus/s.
        self.sem_aviso = False
        # Quantos dos próximos comandos a fita joga fora: chegam, ganham o
        # "recebi" e não são aplicados nem avisados.
        self.perder = 0

    def status(self, nowait=False):
        if self.quebrada:
            return {"Error": "Network Error: Device Unreachable", "Err": "905"}
        if nowait:
            self.socket.a_caminho.append(Msg(CONSULTA, {"dps": dict(self.dps)}))
            return None
        return {"dps": dict(self.dps)}

    def close(self):
        self.fechada = True

    def _receive(self):
        self.socket.chegar()
        if not self.socket.fila:
            raise TimeoutError("a fita não respondeu")
        return self.socket.fila.pop(0)

    def _decode_payload(self, payload):
        return payload

    def set_multiple_values(self, valores, nowait=False):
        self.simultaneos += 1
        self.pico = max(self.pico, self.simultaneos)
        try:
            if self.demora:
                time.sleep(self.demora)
            if self.quebrada:
                return {"Error": "Network Error: Device Unreachable", "Err": "905"}
            if self.perder:
                self.perder -= 1
                self.socket.a_caminho.append(Msg(RECEBI))
                return None
            self.recebidos.append(dict(valores))
            self.dps.update({str(k): v for k, v in valores.items()})
            self.socket.a_caminho.append(Msg(RECEBI))
            if not self.sem_aviso:
                aviso = {chave: valor for chave, valor in valores.items() if chave != "21"}
                self.socket.a_caminho.append(Msg(AVISO, {"dps": aviso}))
            return None
        finally:
            self.simultaneos -= 1


def cor_mandada(modulo):
    """A última cor que chegou nesta fita, em qualquer um dos comandos.

    Acender vai em dois passos, a cor antes do liga, para a fita não piscar na
    cor de ontem — então o último comando recebido é o do liga, e quem quer
    conferir a cor tem de procurá-la.
    """
    comandos = [comando for comando in modulo.recebidos if "24" in comando]
    return comandos[-1]["24"] if comandos else None


def estado_mandado(modulo):
    """O último liga/desliga que chegou nesta fita."""
    comandos = [comando for comando in modulo.recebidos if "20" in comando]
    return comandos[-1]["20"] if comandos else None


@pytest.fixture
def falsas(monkeypatch):
    """Troca as fitas de verdade por módulos de mentira, por id."""
    modulos = {}

    def montar(*fitas_falsas, demora=0.0):
        lista = []
        for indice, quebrada in enumerate(fitas_falsas):
            fita = session_fita.Fita(f"Fita {indice}", f"eb{indice}", "1.2.3.4", "k")
            modulos[fita.id] = FitaFalsa(quebrada=quebrada, demora=demora)
            lista.append(fita)
        session_fita.gravar_fitas(lista)
        monkeypatch.setattr(session_fita, "_dispositivo", lambda f: modulos[f.id])
        return modulos

    return montar
