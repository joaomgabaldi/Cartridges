# test_tuya_conta.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A conta da Tuya salva pelo assistente, criptografada com o DPAPI de verdade."""

from cartridges import shared
from cartridges.utils import tuya_conta
from cartridges.utils.tuya_conta import Conta


def test_ida_e_volta_recupera_as_credenciais():
    conta = Conta("chave-123", "segredo-xyz", "us")
    tuya_conta.salvar(conta)
    assert tuya_conta.carregar() == conta


def test_arquivo_gravado_nao_traz_o_segredo_em_claro():
    tuya_conta.salvar(Conta("chave-123", "segredo-super-secreto", "eu"))
    assert b"segredo-super-secreto" not in shared.tuya_conta_arquivo.read_bytes()


def test_sem_arquivo_carregar_devolve_none():
    assert tuya_conta.carregar() is None


def test_arquivo_corrompido_devolve_none():
    shared.tuya_conta_arquivo.parent.mkdir(parents=True, exist_ok=True)
    shared.tuya_conta_arquivo.write_bytes(b"nao e um blob dpapi")
    assert tuya_conta.carregar() is None
