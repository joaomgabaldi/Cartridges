# test_configuracoes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
import time
import uuid
import winreg

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from cartridges import shared
from cartridges.configuracoes import Configuracoes
from cartridges.utils.thread_principal import eh_thread_principal


@pytest.fixture
def subchave():
    # Dentro da chave da sessão: o `pytest_sessionfinish` do conftest apaga tudo.
    return shared.chave_do_registro + "\\" + str(uuid.uuid4())


@pytest.fixture
def conf(subchave):
    return Configuracoes(subchave, "@APP_ID@")


@pytest.fixture
def estado(subchave):
    return Configuracoes(subchave + r"\State", "@APP_ID@.State")


def _ler(subchave, nome):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subchave) as chave:
        return winreg.QueryValueEx(chave, nome)


def _gravar(subchave, nome, valor, tipo):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, subchave, 0, winreg.KEY_SET_VALUE) as c:
        winreg.SetValueEx(c, nome, 0, tipo, valor)


def test_padrao_quando_a_chave_nao_existe(conf, subchave):
    assert conf.get_boolean("playtime-tracking") is True
    assert conf.get_int("process-tracking-grace") == 5
    assert conf.get_string("conquistas-aviso-posicao") == "inferior-direito"
    assert conf.get_uint("library-rows") == 0
    with pytest.raises(FileNotFoundError):  # nem a subchave foi criada
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, subchave)


def test_padrao_nao_e_gravado_com_a_subchave_existente(conf, subchave):
    conf.set_boolean("auto-import", True)
    conf.get_int("process-tracking-grace")
    with pytest.raises(FileNotFoundError):
        _ler(subchave, "process-tracking-grace")


def test_booleano_vira_dword(conf, subchave):
    conf.set_boolean("auto-import", True)
    assert _ler(subchave, "auto-import") == (1, winreg.REG_DWORD)
    assert conf.get_boolean("auto-import") is True
    conf.set_boolean("auto-import", False)
    assert _ler(subchave, "auto-import") == (0, winreg.REG_DWORD)


def test_int_negativo_volta_negativo(estado, subchave):
    estado.set_int("x", -1200)
    valor, tipo = _ler(subchave + r"\State", "x")
    assert tipo == winreg.REG_DWORD
    assert valor == 0xFFFFFFFF - 1199
    assert estado.get_int("x") == -1200


def test_set_int_positivo(conf, subchave):
    conf.set_int("process-tracking-grace", 7)
    assert conf.get_int("process-tracking-grace") == 7


def test_int64_vira_qword(estado, subchave):
    estado.set_int64("news-last-seen-ts", 1_700_000_000_123)
    assert _ler(subchave + r"\State", "news-last-seen-ts") == (
        1_700_000_000_123,
        winreg.REG_QWORD,
    )
    assert estado.get_int64("news-last-seen-ts") == 1_700_000_000_123
    estado.set_int64("news-last-seen-ts", -5)
    assert estado.get_int64("news-last-seen-ts") == -5


def test_string(conf, subchave):
    conf.set_string("sgdb-key", "ação")
    assert _ler(subchave, "sgdb-key") == ("ação", winreg.REG_SZ)
    assert conf.get_string("sgdb-key") == "ação"


def test_reset_apaga_e_volta_ao_padrao(conf, subchave):
    conf.set_int("process-tracking-grace", 9)
    conf.reset("process-tracking-grace")
    assert conf.get_int("process-tracking-grace") == 5
    with pytest.raises(FileNotFoundError):
        _ler(subchave, "process-tracking-grace")
    conf.reset("process-tracking-grace")  # já apagada: não levanta


def test_changed_so_quando_muda(conf):
    vistos = []
    id_chave = conf.connect("changed::auto-import", lambda c, k: vistos.append(("chave", c, k)))
    conf.connect("changed", lambda c, k: vistos.append(("todas", k)))
    conf.set_boolean("auto-import", False)  # igual ao padrão: nada muda
    assert vistos == []
    conf.set_boolean("auto-import", True)
    conf.set_boolean("auto-import", True)
    conf.set_string("sgdb-key", "a")  # outra chave: só o "changed" geral
    assert vistos == [
        ("chave", conf, "auto-import"),
        ("todas", "auto-import"),
        ("todas", "sgdb-key"),
    ]
    conf.disconnect(id_chave)
    conf.reset("auto-import")
    assert vistos[-1] == ("todas", "auto-import")
    assert len(vistos) == 4


def test_chave_desconhecida_levanta(conf):
    with pytest.raises(KeyError):
        conf.get_boolean("nao-existe")
    with pytest.raises(KeyError):
        conf.set_string("nao-existe", "x")
    with pytest.raises(KeyError):
        conf.reset("nao-existe")


def test_tipo_errado_levanta(conf):
    with pytest.raises(TypeError):
        conf.get_string("auto-import")


def test_get_value_e_list_keys(conf, estado):
    assert conf.get_value("playtime-tracking") is True
    assert conf.get_value("sgdb-key") == ""
    assert "auto-import" in conf.list_keys()
    assert "width" not in conf.list_keys()
    assert "width" in estado.list_keys()


def test_tipo_inesperado_no_registro_vale_o_padrao(conf, subchave, caplog):
    _gravar(subchave, "auto-import", "sim", winreg.REG_SZ)
    assert conf.get_boolean("auto-import") is False
    assert "auto-import" in caplog.text


def test_le_o_registro_gravado_pela_versao_gtk(conf, estado, subchave):
    _gravar(subchave, "playtime-tracking", 0, winreg.REG_DWORD)
    _gravar(subchave, "process-tracking-grace", 12, winreg.REG_DWORD)
    _gravar(subchave, "library-rows", 3, winreg.REG_DWORD)
    _gravar(subchave, "sgdb-key", "abc", winreg.REG_SZ)
    _gravar(subchave + r"\State", "x", 0xFFFFFFFF - 99, winreg.REG_DWORD)
    _gravar(subchave + r"\State", "news-last-seen-ts", 1_700_000_000, winreg.REG_QWORD)
    assert conf.get_boolean("playtime-tracking") is False
    assert conf.get_int("process-tracking-grace") == 12
    assert conf.get_uint("library-rows") == 3
    assert conf.get_string("sgdb-key") == "abc"
    assert estado.get_int("x") == -100
    assert estado.get_int64("news-last-seen-ts") == 1_700_000_000


def test_padrao_de_int_negativo_do_esquema(estado):
    assert estado.get_int("x") == -2147483648


def test_changed_de_outra_thread_chega_na_principal(conf, app_qt):
    vistos = []
    conf.connect("changed", lambda c, k: vistos.append(eh_thread_principal()))
    thread = threading.Thread(target=conf.set_boolean, args=("auto-import", True))
    thread.start()
    thread.join()
    fim = time.monotonic() + 5
    while not vistos and time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
    assert vistos == [True]


def test_aceita_confere_o_tipo(conf):
    assert conf.aceita("gamepad", True) is True
    assert conf.aceita("gamepad", 1) is False
    assert conf.aceita("gamepad", "sim") is False
    assert conf.aceita("process-tracking-grace", 7) is True
    assert conf.aceita("process-tracking-grace", True) is False  # bool não é número aqui
    assert conf.aceita("shortcuts-location", "D:/Atalhos") is True
    assert conf.aceita("shortcuts-location", 3) is False


def test_aceita_confere_a_faixa(conf):
    assert conf.aceita("conquistas-aviso-som-volume", 10) is True
    assert conf.aceita("conquistas-aviso-som-volume", 100) is True
    assert conf.aceita("conquistas-aviso-som-volume", 5) is False
    assert conf.aceita("conquistas-aviso-som-volume", 101) is False


def test_aceita_confere_as_escolhas(estado):
    assert estado.aceita("sort-mode", "a-z") is True
    assert estado.aceita("sort-mode", "x") is False


def test_aceita_chave_desconhecida_e_falso(conf):
    assert conf.aceita("nao-existe", True) is False
