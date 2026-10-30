# test_app_conquistas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A varredura de conquistas ligada à abertura e ao fechamento do app, com tudo falso (sem QML, sem rede)."""

from types import SimpleNamespace

import pytest

from cartridges import app, shared


class _Gravador:
    """Um objeto cujos métodos anotam a chamada numa lista comum; `falhar` levanta no método dado."""

    def __init__(self, passos, nome, falhar=()):
        self._passos, self._nome, self._falhar = passos, nome, falhar

    def __getattr__(self, metodo):
        def chamar(*_):
            self._passos.append(f"{self._nome}.{metodo}")
            if metodo in self._falhar:
                raise RuntimeError(metodo)

        return chamar


def test_abertura_carrega_as_contas_antes_da_varredura(monkeypatch):
    passos = []
    monkeypatch.setattr(app, "conta", _Gravador(passos, "xbox"))
    monkeypatch.setattr(app, "epic_conta", _Gravador(passos, "epic"))
    monkeypatch.setattr(app, "ea_conta", _Gravador(passos, "ea"))

    class _Varredura:
        def start(self):
            passos.append("varredura.start")

    monkeypatch.setattr(app, "VarreduraConquistas", _Varredura)
    aplicativo = SimpleNamespace(varredura_conquistas=None)

    app._carregar_contas()  # noqa: SLF001
    passos.append("---")
    varredura = app._ligar_conquistas(aplicativo)  # noqa: SLF001

    assert passos == ["xbox.carregar", "epic.carregar", "ea.carregar", "---", "varredura.start"]
    assert aplicativo.varredura_conquistas is varredura and isinstance(varredura, _Varredura)


def _fechar(monkeypatch, falhar=()):
    passos = []
    monkeypatch.setattr(app, "login", _Gravador(passos, "login", falhar))
    monkeypatch.setattr(app, "ea_conta", _Gravador(passos, "ea", falhar))
    monkeypatch.setattr(app, "icones", _Gravador(passos, "icones", falhar))
    monkeypatch.setattr(app, "async_manager", _Gravador(passos, "async", falhar))
    monkeypatch.setattr(app, "copias_animadas", _Gravador(passos, "copias", falhar))
    monkeypatch.setattr(
        shared, "aplicativo", SimpleNamespace(varredura_conquistas=_Gravador(passos, "varredura", falhar)), raising=False
    )
    app._fechar(  # noqa: SLF001
        _Gravador(passos, "bp", falhar), _Gravador(passos, "sessao", falhar), _Gravador(passos, "verificador", falhar),
        _Gravador(passos, "hltb", falhar), _Gravador(passos, "tamanho", falhar), _Gravador(passos, "edicao", falhar),
    )  # fmt: skip
    return passos


_ORDEM = [
    "bp.encerrar", "sessao.devolver", "login.cancelar_pendente", "ea.gravar_pendente", "verificador.stop",
    "hltb.stop", "tamanho.stop", "varredura.stop", "edicao.cancelar", "async.encerrar", "copias.encerrar",
    "icones.encerrar",
]  # fmt: skip


def test_encerrar_cancela_o_login_e_os_icones(monkeypatch):
    assert _fechar(monkeypatch) == _ORDEM


@pytest.mark.parametrize("falha", ["cancelar_pendente", "gravar_pendente", "stop", "encerrar", "cancelar"])
def test_uma_falha_nao_impede_os_passos_seguintes(monkeypatch, falha):
    assert _fechar(monkeypatch, falhar=(falha,)) == _ORDEM


def test_encerrar_sem_varredura_nao_levanta(monkeypatch):
    passos = _fechar(monkeypatch)
    passos.clear()
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    app._parar_varredura_de_conquistas()  # noqa: SLF001
    assert passos == []
