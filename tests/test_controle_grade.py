# test_controle_grade.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox na grade, com um leitor de XInput falso no lugar da DLL."""

import subprocess
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt, Signal

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
    XINPUT_DPAD_DOWN,
    XINPUT_DPAD_LEFT,
    XINPUT_DPAD_RIGHT,
    XINPUT_DPAD_UP,
    XINPUT_LEFT_SHOULDER,
    XINPUT_START,
    XINPUT_Y,
    intervalo_de_repeticao_us,
)
from tests.apoio_controle_grade import ATIVO, INATIVO, LeitorFalso, Montagem


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


def test_releasing_and_pressing_again_moves():
    """Depois da trava da volta do foco, soltar e apertar de novo é entrada de verdade."""
    montagem = Montagem()
    montagem.leitor.botoes = XINPUT_DPAD_DOWN
    montagem.tique()  # base: travado
    montagem.leitor.botoes = 0
    montagem.tique(100_000)
    assert montagem.comandos() == []
    montagem.leitor.botoes = XINPUT_DPAD_DOWN
    montagem.tique(100_000)
    assert montagem.comandos() == [("mover", 0, 1)]


def test_changing_direction_without_releasing_moves():
    """Trocar uma direção por outra sem soltar também é entrada de verdade."""
    montagem = Montagem()
    montagem.leitor.botoes = XINPUT_DPAD_DOWN
    montagem.tique()  # base: travado
    montagem.leitor.botoes = XINPUT_DPAD_UP
    montagem.tique(100_000)
    assert montagem.comandos() == [("mover", 0, -1)]


def test_the_dpad_beats_the_stick(m):
    """Os dois ao mesmo tempo: uma direção só, a do direcional."""
    m.leitor.botoes = XINPUT_DPAD_LEFT
    m.leitor.lx = 30_000
    m.tique()
    assert m.comandos() == [("mover", -1, 0)]


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


def test_repeticao_na_grade_segue_a_agenda_absoluta(m):
    # Como a `main` (`gamepad.py:645-648`): o passo n vence em atraso + n · 120 ms desde o aperto, sem esperar mais 120 ms do
    # passo anterior; leitura de 33 ms não deixa a repetição 10% mais lenta (C-19). Um tique, no máximo um passo.
    ms = 1000
    m.leitor.botoes = XINPUT_DPAD_RIGHT
    m.tique()  # aperto em 0 ms
    m.tique(400 * ms)
    assert len(m.comandos()) == 2
    m.tique(1050 * ms)  # 1450 ms: um tique muito atrasado move uma vez só
    assert len(m.comandos()) == 3
    m.tique(33 * ms)  # 1483 ms: ainda atrasado na agenda, anda um passo por tique até alcançar
    assert len(m.comandos()) == 4
    for _ in range(40):  # alcançada a agenda, os passos saem a cada 120 ms de relógio, não a cada 4 leituras
        m.tique(33 * ms)
    desde_o_aperto_ms = 400 + 1050 + 33 + 40 * 33
    assert len(m.comandos()) == 2 + (desde_o_aperto_ms - 400) // 120


class _JanelaFalsa(QObject):
    """A janela principal: o `isActive` e o `activeChanged` de uma `QWindow`."""

    activeChanged = Signal()  # noqa: N815

    def __init__(self, ativa=True):
        super().__init__()
        self.ativa = ativa

    def isActive(self):  # noqa: N802
        return self.ativa


def test_so_a_janela_principal_ativa_da_o_controle():
    # C-24: com Tarefas, Login ou o assistente em foco o app segue "ativo" no Qt, mas a principal não: o controle para.
    montagem = Montagem()
    janela = _JanelaFalsa(ativa=False)
    montagem.controle.definir_janela(janela)
    assert not montagem.controle.lendo, "o app está ativo, a principal não"
    janela.ativa = True
    janela.activeChanged.emit()
    assert montagem.controle.lendo
    janela.ativa = False
    janela.activeChanged.emit()
    assert not montagem.controle.lendo


def test_encerrar_para_a_leitura_e_os_motores(m):
    # C-25: o app fecha no meio de uma vibração; os motores não ficam ligados.
    shared.schema.set_boolean("gamepad-rumble", True)
    m.controle.bater()
    m.leitor.vibracoes.clear()
    m.controle.encerrar()
    assert not m.controle.lendo
    assert m.leitor.vibracoes == [(0.0, 0.0)]


def test_no_big_picture_outro_botao_junto_nao_anula_o_salto(m):
    # C-26: só A, B e os ombros valem; Start junto com LB não toma o lugar do salto.
    m.controle.modoBigPicture = True
    pulos = []
    m.controle.pular.connect(pulos.append)
    m.leitor.botoes = XINPUT_LEFT_SHOULDER | XINPUT_START
    m.tique()
    assert pulos == [-10]
    assert "menuPrincipal" not in m.eventos
    # Fora do Big Picture a cadeia é a de sempre: o Start vence.
    m.leitor.botoes = 0
    m.tique()
    m.controle.modoBigPicture = False
    m.leitor.botoes = XINPUT_LEFT_SHOULDER | XINPUT_START
    m.tique()
    assert "menuPrincipal" in m.eventos and pulos == [-10]
