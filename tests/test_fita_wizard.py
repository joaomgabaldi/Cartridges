# test_fita_wizard.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que o assistente faz com a resposta da nuvem da Tuya."""

from cartridges.fita_wizard import fitas_da_nuvem
from cartridges.utils.session_fita import Fita


def test_dispositivo_com_chave_vira_fita():
    resposta = [
        {
            "name": "Fita Centro",
            "id": "eb1",
            "key": "abc",
            "ip": "192.168.0.150",
            "version": "3.3",
        }
    ]
    assert fitas_da_nuvem(resposta) == [
        Fita("Fita Centro", "eb1", "192.168.0.150", "abc", "3.3")
    ]


def test_dispositivo_sem_chave_fica_de_fora():
    assert fitas_da_nuvem([{"name": "X", "id": "eb2", "ip": "1.2.3.4"}]) == []


def test_sem_ip_a_fita_entra_com_ip_vazio_para_a_busca_achar():
    (fita,) = fitas_da_nuvem([{"name": "X", "id": "eb3", "key": "k"}])
    assert fita.ip == ""


def test_versao_ausente_assume_a_do_modulo_mais_comum():
    (fita,) = fitas_da_nuvem([{"name": "X", "id": "eb4", "key": "k", "ip": "1.2.3.4"}])
    assert fita.versao == "3.3"
