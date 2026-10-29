# test_sessao_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `ModeloDaSessao`: o que os rastreadores pedem no lugar do `shared.win` (D48)."""

import pytest
from PySide6.QtCore import Qt

from cartridges import process_session as ps
from cartridges import session_window as sw
from cartridges import shared
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.sessao import ModeloDaSessao, pode_anotar
from cartridges.process_session import ProcessSession
from cartridges.session_window import SessionWindow
from cartridges.utils import session_log

CLASSICO = r'start "" "D:\Jogos\halo.exe"'


class RelogioFalso:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def relogio(monkeypatch):
    instancia = RelogioFalso()
    monkeypatch.setattr(ps, "monotonic", instancia)
    monkeypatch.setattr(sw, "monotonic", instancia)
    return instancia


@pytest.fixture
def modelo(monkeypatch):
    fila = FilaDeAvisos()
    instancia = ModeloDaSessao(fila)
    monkeypatch.setattr(shared, "sessao", instancia, raising=False)
    instancia.fila = fila
    return instancia


class JanelaQueNaoSeToca:
    """Fechar o app não pode chamar a janela: qualquer acesso é erro."""

    def __getattr__(self, nome):
        raise AssertionError(f"a janela foi tocada: {nome}")


class JanelaFalsa:
    def __init__(self, estados):
        self.estados, self.chamadas = estados, []

    def windowStates(self):
        return self.estados

    def setWindowStates(self, estados):
        self.estados = estados
        self.chamadas.append("estados")

    def raise_(self):
        self.chamadas.append("raise")

    def requestActivate(self):
        self.chamadas.append("ativar")


def test_aviso_do_fim_em_texto_puro_e_anotar_so_quando_pode(modelo, make_game):
    jogando = make_game(name="Sam & Max <Salvar o Mundo>", status="playing")
    modelo.session_toast(jogando, 3600)

    assert modelo.fila.texto == "Sam & Max <Salvar o Mundo>: 1 hora de jogo"
    assert modelo.fila.botao == "Anotar"

    modelo.fila.fechar()
    modelo.session_toast(make_game(name="Outro", status=""), 30)
    assert modelo.fila.texto == "Outro: menos de 1 min de jogo" and modelo.fila.botao == ""

    assert pode_anotar(make_game(status="", notes="  onde parei  ")) is True
    assert pode_anotar(make_game(status="beaten", removed=True, notes="x")) is False  # zerado: só leitura


def test_anotar_pede_os_detalhes_do_jogo(modelo, make_game):
    pedidos = []
    modelo.anotarPedido.connect(pedidos.append, Qt.ConnectionType.DirectConnection)
    modelo.session_toast(make_game(game_id="shortcuts_9", status="playing"), 90)

    modelo.fila.clicar()

    assert pedidos == ["shortcuts_9"]


def test_mesma_sessao_trocando_de_rastreador_nao_reveste(modelo, make_game, relogio):
    jogo = make_game(executable=CLASSICO)
    mudancas = []
    modelo.alterado.connect(lambda: mudancas.append(1), Qt.ConnectionType.DirectConnection)
    processo = ProcessSession(jogo)
    processo.start()
    assert (modelo.emAndamento, modelo.jogoId, modelo.nome) == (True, jogo.game_id, jogo.name)
    assert modelo.tituloDaJanela == f"Jogando {jogo.name}"

    processo.stop(record=False, fall_back=True)  # o jogo nunca apareceu: passa à janela manual

    assert len(mudancas) == 2  # a camada (uma vez) e a janela manual; nada de esconder e mostrar de novo
    assert modelo.emAndamento is True and modelo.janelaManual is True
    assert ProcessSession.active is None and SessionWindow.active is not None
    modelo.terminar()
    assert modelo.emAndamento is False and modelo.janelaManual is False


@pytest.mark.parametrize("rastreador", ["manual", "processo"])
def test_encerrar_no_meio_da_sessao_grava_e_registra(modelo, make_game, relogio, rastreador):
    """Review Focus 1: o tempo vai ao jogo e ao histórico, e nenhuma chamada chega à janela."""
    modelo.definir_janela(JanelaQueNaoSeToca())
    jogo = make_game(game_id="shortcuts_5", executable=CLASSICO)
    if rastreador == "manual":
        SessionWindow(jogo).present()
    else:
        processo = ProcessSession(jogo)
        processo.start()
        processo.started = processo.counting = True
        processo.last_tick = relogio.now
    relogio.now += 30

    modelo.encerrar()

    assert jogo.playtime == 30
    assert [linha["seconds"] for linha in session_log.load("shortcuts_5")] == [30]
    assert SessionWindow.active is None and ProcessSession.active is None
    assert modelo.fila.visivel is False  # nenhum aviso: a interface já está indo embora


def test_trazer_de_volta_nao_desmaximiza(modelo):
    """Review Focus 4: maximizada e minimizada volta maximizada."""
    janela = JanelaFalsa(Qt.WindowState.WindowMaximized)
    modelo.definir_janela(janela)
    modelo.minimizar()
    assert janela.estados == Qt.WindowState.WindowMaximized | Qt.WindowState.WindowMinimized
    janela.chamadas.clear()

    modelo.present()

    assert janela.estados == Qt.WindowState.WindowMaximized
    assert janela.chamadas == ["estados", "raise", "ativar"]


def test_terminar_encerra_os_dois(modelo, make_game, relogio):
    jogo = make_game(game_id="shortcuts_6", executable=CLASSICO)
    manual = SessionWindow(jogo)
    processo = ProcessSession(jogo)
    ProcessSession.active = processo
    processo.started = processo.counting = True
    processo.last_tick = relogio.now
    relogio.now += 30

    modelo.terminar()

    assert SessionWindow.active is None and ProcessSession.active is None
    assert manual.game.playtime == 60
    assert [linha["seconds"] for linha in session_log.load("shortcuts_6")] == [30, 30]
