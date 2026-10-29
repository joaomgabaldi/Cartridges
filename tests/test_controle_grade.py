# test_controle_grade.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox na grade, com um leitor de XInput falso no lugar da DLL."""

import subprocess
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from cartridges import shared
from cartridges.modelos.controle import ControleDaGrade
from cartridges.xinput import (
    REPEAT_DELAY_US,
    REPEAT_INTERVAL_US,
    RUMBLE_MOVE,
    THUMB_PRESS,
    THUMB_WAKE,
    XINPUT_A,
    XINPUT_B,
    XINPUT_BACK,
    XINPUT_DPAD_RIGHT,
    XINPUT_START,
    XINPUT_Y,
    intervalo_de_repeticao_us,
)

ATIVO = Qt.ApplicationState.ApplicationActive
INATIVO = Qt.ApplicationState.ApplicationInactive


class LeitorFalso:
    disponivel = True

    def __init__(self):
        self.botoes = 0
        self.lx = 0
        self.ly = 0
        self.leituras = 0
        self.solto = False
        self.vibracoes = []

    def ler(self):
        self.leituras += 1
        return SimpleNamespace(wButtons=self.botoes, sThumbLX=self.lx, sThumbLY=self.ly)

    def vibrar(self, esquerdo=0.0, direito=0.0):
        self.vibracoes.append((esquerdo, direito))

    def soltar(self):
        self.solto = True


class Montagem:
    def __init__(self):
        shared.schema.set_boolean("gamepad", True)  # desligada por padrão
        self.leitor = LeitorFalso()
        self.fabricados = 0
        self.estado = ATIVO
        self.agora = 1_000_000
        self.controle = ControleDaGrade(
            fabrica_do_leitor=self._fabricar,
            estado_do_app=lambda: self.estado,
            relogio=lambda: self.agora,
        )
        self.eventos = []
        c = self.controle
        c.mover.connect(lambda dx, dy: self.eventos.append(("mover", dx, dy)))
        for nome in ("ativar", "voltar", "menuPrincipal", "menuDoJogo", "buscar", "usado"):
            getattr(c, nome).connect(lambda nome=nome: self.eventos.append(nome))

    def _fabricar(self):
        self.fabricados += 1
        return self.leitor

    def tique(self, avanco_us=0):
        self.agora += avanco_us
        self.controle._ler()

    def comandos(self):
        return [e for e in self.eventos if e != "usado"]


@pytest.fixture
def m():
    montagem = Montagem()
    montagem.tique()  # a primeira leitura só fixa a base
    montagem.eventos.clear()
    return montagem


def test_so_le_com_a_janela_ativa():
    montagem = Montagem()
    assert montagem.controle.lendo
    montagem.estado = INATIVO
    montagem.controle.sincronizar()
    assert not montagem.controle.lendo
    assert not montagem.leitor.solto, "como na `main`, a DLL só é solta numa sessão de jogo"
    montagem.estado = ATIVO
    montagem.controle.sincronizar()
    assert montagem.controle.lendo
    assert montagem.fabricados == 1, "o leitor carregado é reaproveitado"


def test_perder_o_foco_deixa_a_vibracao_terminar(m):
    shared.schema.set_boolean("gamepad-rumble", True)
    m.controle.bater()
    m.estado = INATIVO
    m.controle.sincronizar()
    assert m.controle._leitor is m.leitor, "o leitor segue para desligar os motores"
    m.controle._leitor.vibrar()  # o que o desligamento agendado faria
    assert m.leitor.vibracoes[0] == (0.6, 0.2)


def test_borda_de_subida_dos_botoes(m):
    m.leitor.botoes = XINPUT_A
    m.tique()
    m.tique(33_000)
    m.tique(33_000)
    assert m.comandos() == ["ativar"], "segurar A emite um só"
    m.leitor.botoes = 0
    m.tique()
    m.leitor.botoes = XINPUT_A
    m.tique()
    assert m.comandos() == ["ativar", "ativar"]


@pytest.mark.parametrize(
    ("botao", "sinal"),
    [(XINPUT_B, "voltar"), (XINPUT_START, "menuPrincipal"), (XINPUT_Y, "menuDoJogo"), (XINPUT_BACK, "buscar")],
)
def test_cada_botao_tem_o_seu_sinal(m, botao, sinal):
    m.leitor.botoes = botao
    m.tique()
    assert m.comandos() == [sinal]
    assert "usado" in m.eventos


def test_botao_ja_segurado_ao_voltar_o_foco_nao_age():
    montagem = Montagem()
    montagem.leitor.botoes = XINPUT_A
    montagem.tique()  # base
    montagem.tique(33_000)
    assert montagem.comandos() == []


def test_repeticao_do_direcional(m):
    m.leitor.botoes = XINPUT_DPAD_RIGHT
    m.tique()
    assert m.comandos() == [("mover", 1, 0)]
    m.tique(REPEAT_DELAY_US - 1)
    assert len(m.comandos()) == 1, "a repetição espera o atraso"
    m.tique(1)
    assert len(m.comandos()) == 2
    passo = REPEAT_INTERVAL_US
    assert passo == intervalo_de_repeticao_us(0)
    m.tique(passo - 1)
    assert len(m.comandos()) == 2
    m.tique(1)
    assert len(m.comandos()) == 3
    m.leitor.botoes = 0
    m.tique(passo)
    assert len(m.comandos()) == 3, "soltar para a repetição"


def test_direcional_segurado_ao_voltar_o_foco_nao_repete_sozinho():
    montagem = Montagem()
    montagem.leitor.botoes = XINPUT_DPAD_RIGHT
    montagem.tique()  # base
    montagem.tique(REPEAT_DELAY_US * 3)
    assert montagem.comandos() == []


def test_zona_morta_do_analogico(m):
    m.leitor.lx = THUMB_PRESS - 1
    m.tique()
    assert m.comandos() == [], "abaixo da zona morta nada move"
    # Deriva forte não acorda o analógico: só um empurrão quase total ou um botão.
    m.leitor.lx = THUMB_PRESS + 1
    m.tique()
    assert m.comandos() == [], "o analógico dorme até ser acordado"
    m.leitor.lx = THUMB_WAKE
    m.tique()
    assert m.comandos() == [("mover", 1, 0)]
    # Segurar vale até cair abaixo do limite de soltar (mais baixo que o de apertar).
    m.leitor.lx = 11_000
    m.tique()
    m.tique(REPEAT_DELAY_US)
    assert m.comandos()[-1] == ("mover", 1, 0) and len(m.comandos()) == 2
    m.leitor.lx = 9_000
    m.tique(33_000)
    n = len(m.comandos())
    m.tique(REPEAT_DELAY_US * 2)
    assert len(m.comandos()) == n


def test_analogico_escolhe_o_eixo_dominante(m):
    m.leitor.lx = THUMB_WAKE
    m.leitor.ly = THUMB_WAKE + 100
    m.tique()
    assert m.comandos() == [("mover", 0, -1)]


def test_desligado_nas_preferencias_nao_le():
    montagem = Montagem()
    shared.schema.set_boolean("gamepad", False)
    montagem.controle.sincronizar()
    assert not montagem.controle.lendo
    montagem.controle.sincronizar()
    assert not montagem.controle.lendo and montagem.leitor.leituras == 0
    shared.schema.set_boolean("gamepad", True)
    montagem.controle.sincronizar()
    assert montagem.controle.lendo


    shared.schema.set_boolean("gamepad", True)
    leitor = LeitorFalso()
    leitor.disponivel = False
    controle = ControleDaGrade(fabrica_do_leitor=lambda: leitor, estado_do_app=lambda: ATIVO)
    assert not controle.lendo


def test_vibra_na_borda_so_com_a_preferencia(m):
    shared.schema.set_boolean("gamepad-rumble", True)
    m.controle.bater()
    assert m.leitor.vibracoes == [(0.6, 0.2)]
    m.leitor.vibracoes.clear()
    shared.schema.set_boolean("gamepad-rumble", False)
    m.controle.bater()
    assert m.leitor.vibracoes == []


def test_passar_vibra_o_tique_leve_so_com_a_preferencia(m):
    shared.schema.set_boolean("gamepad-rumble", True)
    m.controle.passar()
    assert m.leitor.vibracoes == [RUMBLE_MOVE[:2]]
    m.leitor.vibracoes.clear()
    shared.schema.set_boolean("gamepad-rumble", False)
    m.controle.passar()
    assert m.leitor.vibracoes == []


def test_xinput_nao_importa_gi_nem_qt():
    codigo = (
        "import sys, cartridges.xinput\n"
        "ruins = [n for n in sys.modules if n == 'gi' or n.startswith(('gi.', 'PySide6', 'PyQt'))]\n"
        "print(ruins)\n"
    )
    saida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True).stdout
    assert saida.strip() == "[]"


def test_reconectar_refaz_a_base(m):
    m.leitor.botoes = XINPUT_A
    m.tique()
    assert m.comandos() == ["ativar"]
    m.eventos.clear()
    original = m.leitor.ler
    m.leitor.ler = lambda: None  # o controle some
    m.tique()
    m.leitor.ler = original  # e volta com A ainda segurado e o analógico à deriva
    m.leitor.lx = THUMB_PRESS + 500
    m.tique()
    m.tique(33_000)
    assert m.comandos() == [], "o que já estava pressionado na volta é a base, e a deriva não move"


def test_presente_ao_achar_o_controle():
    montagem = Montagem()
    presentes = []
    montagem.controle.presente.connect(lambda: presentes.append(1))
    montagem.tique()
    montagem.tique(33_000)
    assert presentes == [1], "um só aviso, na leitura que fixa a base"
