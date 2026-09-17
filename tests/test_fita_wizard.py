# test_fita_wizard.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que o assistente faz com a resposta da nuvem da Tuya."""

import logging

from cartridges.fita_wizard import fitas_da_nuvem
from cartridges.logging.setup import LIB_LOGGERS
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


# A `getdevices` da tinytuya não levanta quando a credencial está errada: ela
# devolve um dicionário de erro no lugar da lista. Sem estas três, um
# `AttributeError` dentro da thread deixaria o assistente parado para sempre na
# página "Buscando…".


def test_dicionario_de_erro_da_nuvem_nao_vira_fita():
    assert fitas_da_nuvem({"Error": "Invalid Key", "Err": "901"}) == []


def test_resposta_que_e_texto_nao_vira_fita():
    assert fitas_da_nuvem("Unable to get device list") == []


def test_item_que_nao_e_dicionario_e_pulado():
    resposta = ["lixo", None, {"name": "X", "id": "eb5", "key": "k"}]
    assert [fita.id for fita in fitas_da_nuvem(resposta)] == ["eb5"]


def test_a_tinytuya_fica_calada_no_arquivo_de_log():
    """A API Secret da conta não pode acabar no `cartridges.log`.

    Em DEBUG a tinytuya loga o dicionário de cabeçalhos de cada chamada à
    nuvem, e enquanto ela não tem token esse dicionário traz a Secret em claro.
    O `file_handler` do app grava tudo que chega em DEBUG, então o silenciamento
    da biblioteca é o que separa o segredo do arquivo que vai anexado a
    relatório de bug — e não pode sumir numa refatoração.
    """
    nivel = logging.getLevelNamesMapping()[LIB_LOGGERS["tinytuya"]["level"]]
    assert nivel >= logging.WARNING
