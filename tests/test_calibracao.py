# test_calibracao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As contas da calibração: como a correção de cada dispositivo muda uma cor."""

import pytest

from cartridges.utils import calibracao
from cartridges.utils.calibracao import NEUTRA, Calibracao, corrigir
from cartridges.utils.session_fita import Cor


def _com(indice=0, tom=0, fator=1.0, branco=(0, 0)):
    cores = [(0, 1.0)] * 6
    cores[indice] = (tom, fator)
    return Calibracao(tuple(cores), branco)


@pytest.mark.parametrize(
    "cor", [Cor(0, 1000, 500), Cor(123, 456, 789), Cor(359, 0, 10), Cor(200, 300, 1000)]
)
def test_neutra_nao_muda_nada(cor):
    assert corrigir(cor, NEUTRA) == cor


def test_referencia_corrigida_e_exata_no_centro():
    assert corrigir(Cor(0, 1000, 500), _com(0, tom=-8)) == Cor(352, 1000, 500)


def test_a_meio_caminho_vale_metade():
    assert corrigir(Cor(30, 1000, 500), _com(0, tom=-8)) == Cor(26, 1000, 500)


def test_vermelho_perto_da_emenda_usa_as_duas_vizinhas():
    # 330° fica no meio entre a referência de 300° e a de 0°.
    assert corrigir(Cor(330, 1000, 500), _com(0, tom=-8)) == Cor(326, 1000, 500)


def test_intensidade_multiplica_a_saturacao_sem_passar_do_maximo():
    assert corrigir(Cor(120, 500, 500), _com(2, fator=1.2)) == Cor(120, 600, 500)
    assert corrigir(Cor(120, 1000, 500), _com(2, fator=1.2)) == Cor(120, 1000, 500)


def test_branco_quente_puxa_a_cor_palida_e_nao_a_saturada():
    quente = _com(branco=(30, 300))
    assert corrigir(Cor(0, 0, 700), quente) == Cor(30, 300, 700)
    assert corrigir(Cor(200, 1000, 700), quente) == Cor(200, 1000, 700)


def test_branco_pesa_menos_quanto_mais_saturada():
    quente = _com(branco=(30, 300))
    # Saturação 200: metade do peso do branco (faixa de 400).
    corrigida = corrigir(Cor(30, 200, 700), quente)
    assert corrigida.matiz == 30
    assert corrigida.saturacao == 350


@pytest.mark.parametrize(
    "dados", [None, "x", 3, {}, {"cores": [[0, 1.0]]}, {"cores": "x", "branco": [0, 0]}]
)
def test_json_ilegivel_vale_neutra(dados):
    assert calibracao.de_json(dados) == NEUTRA


def test_json_fora_dos_limites_e_limitado():
    dados = {"cores": [[99, 9.0]] + [[0, 1.0]] * 5, "branco": [400, 999]}
    lida = calibracao.de_json(dados)
    assert lida.cores[0] == (30, 1.5)
    assert lida.branco == (40, 300)


def test_json_ida_e_volta():
    original = _com(3, tom=12, fator=0.8, branco=(210, 150))
    assert calibracao.de_json(calibracao.para_json(original)) == original


def test_temperatura_vai_do_quente_ao_frio():
    assert calibracao.branco_da_temperatura(-1) == (30, 300)
    assert calibracao.branco_da_temperatura(1) == (210, 300)
    assert calibracao.branco_da_temperatura(0)[1] == 0
    assert calibracao.temperatura_do_branco((30, 150)) == -0.5
    assert calibracao.temperatura_do_branco((210, 300)) == 1.0


@pytest.mark.parametrize(
    "dados",
    [
        {"cores": [[0, 1.0]] * 6, "branco": [float("inf"), 100]},
        {"cores": [[0, 1.0]] * 6, "branco": [float("nan"), 0]},
        {"cores": [[10**400, 1.0]] + [[0, 1.0]] * 5, "branco": [0, 0]},
        {"cores": [[float("nan"), 1.0]] + [[0, 1.0]] * 5, "branco": [0, 0]},
    ],
)
def test_json_com_numero_absurdo_vale_neutra(dados):
    """Roda em toda troca de cor: número infinito, enorme ou NaN vira neutra,
    e não uma exceção na thread que pinta a fita."""
    assert calibracao.de_json(dados) == NEUTRA
