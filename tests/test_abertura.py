"""A abertura do app com um backup agendado: a janela "Restaurando…" primeiro."""

import pytest

from cartridges import main as main_module
from cartridges import shared


class _JanelaFalsa:
    criadas: list["_JanelaFalsa"] = []

    def __init__(self, application=None):
        self.passos, self.apresentada = [], 0
        _JanelaFalsa.criadas.append(self)

    def present(self):
        self.apresentada += 1

    def avancar(self, fracao):
        self.passos.append(fracao)

    def terminar(self):
        self.passos.append("terminou")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(shared, "store", None, raising=False)  # o __init__ troca a store
    _JanelaFalsa.criadas = []
    monkeypatch.setattr(main_module, "JanelaRestaurando", _JanelaFalsa)
    monkeypatch.setattr(main_module, "setup_logging", lambda: None)
    monkeypatch.setattr(main_module, "log_system_info", lambda: None)
    monkeypatch.setattr(main_module.GLib, "idle_add", lambda funcao, *args: funcao(*args))
    tarefas = []
    monkeypatch.setattr(main_module, "_em_thread", tarefas.append)
    aplicacao = main_module.CartridgesApplication()
    monkeypatch.setattr(aplicacao, "apply_windows_theme", lambda: True)
    aberturas = []
    monkeypatch.setattr(
        aplicacao, "_abrir", lambda: aberturas.append(aplicacao.restauracao_falhou)
    )
    return aplicacao, tarefas, aberturas


def test_com_backup_agendado_a_abertura_espera_a_restauracao(app, monkeypatch):
    aplicacao, tarefas, aberturas = app
    monkeypatch.setattr(main_module.backup, "ha_pendente", lambda: True)
    monkeypatch.setattr(
        main_module.backup, "aplicar_pendente", lambda progresso=None: progresso(0.5) or True
    )
    aplicacao.do_activate()
    (janela,) = _JanelaFalsa.criadas
    assert janela.apresentada == 1 and aberturas == []
    tarefas.pop()()
    assert janela.passos == [0.5, "terminou"]
    assert aberturas == [False]


def test_segunda_ativacao_durante_a_restauracao_traz_a_janela(app, monkeypatch):
    aplicacao, tarefas, aberturas = app
    monkeypatch.setattr(main_module.backup, "ha_pendente", lambda: True)
    monkeypatch.setattr(main_module.backup, "aplicar_pendente", lambda progresso=None: True)
    aplicacao.do_activate()
    aplicacao.do_activate()
    assert _JanelaFalsa.criadas[0].apresentada == 2 and len(_JanelaFalsa.criadas) == 1
    assert len(tarefas) == 1 and aberturas == []


@pytest.mark.parametrize(
    "falha", [lambda progresso=None: False, lambda progresso=None: 1 / 0], ids=["falso", "excecao"]
)
def test_restauracao_que_falha_abre_com_o_aviso(app, monkeypatch, falha):
    aplicacao, tarefas, aberturas = app
    monkeypatch.setattr(main_module.backup, "ha_pendente", lambda: True)
    monkeypatch.setattr(main_module.backup, "aplicar_pendente", falha)
    aplicacao.do_activate()
    tarefas.pop()()
    assert aberturas == [True]


def test_sem_backup_agendado_abre_na_hora(app, monkeypatch):
    aplicacao, tarefas, aberturas = app
    monkeypatch.setattr(main_module.backup, "ha_pendente", lambda: False)
    monkeypatch.setattr(main_module.backup, "aplicar_pendente", lambda progresso=None: None)
    aplicacao.do_activate()
    assert _JanelaFalsa.criadas == [] and tarefas == [] and aberturas == [False]
