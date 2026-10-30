# test_sessao_fita_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As fitas de LED na sessão, pelo `ModeloDaSessao`: o que veste, o que despe e o que se avisa no fim.

Eram os testes de `real_window` em `test_session_fita.py`. Nenhuma fita de verdade: o `comecar`, o `voltar` e
os avisos do módulo são espionados, e o `_dispositivo` levanta (conftest).
"""

from types import SimpleNamespace

import pytest

from cartridges import shared
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.session_window import SessionWindow
from cartridges.utils import session_fita, session_log, session_wallpaper, window_geometry

AVISO_DA_TELA = "A iluminação não acompanhou a tela de Hollow Knight. Use o modo janela sem bordas."


@pytest.fixture
def avisos():
    """Cada aviso que a sessão pediu, em ordem (no lugar da fila de avisos)."""
    return []


@pytest.fixture
def modelo(avisos, monkeypatch, schema):
    instancia = ModeloDaSessao(SimpleNamespace(adicionar=lambda texto, *_a, **_k: avisos.append(texto)))
    instancia.chamadas = []
    monkeypatch.setattr(shared, "sessao", instancia, raising=False)
    # A parede e o monitor têm os testes deles (test_monitor_da_sessao.py).
    monkeypatch.setattr(session_wallpaper, "comecar", lambda _jogo: None)
    monkeypatch.setattr(session_wallpaper, "restaurar", lambda: instancia.chamadas.append("parede"))
    monkeypatch.setattr(window_geometry, "restore_from_monitor", lambda _janela: None)
    schema.set_boolean("session-wallpaper", False)
    monkeypatch.setattr(session_fita, "comecar", lambda jogo: instancia.chamadas.append(("comecar", jogo)))
    monkeypatch.setattr(session_fita, "voltar", lambda: instancia.chamadas.append("voltar"))
    monkeypatch.setattr(session_fita, "captura_bloqueada", lambda: False)
    monkeypatch.setattr(session_fita, "fitas_fora_do_ar", lambda: [])
    monkeypatch.setattr(session_fita, "fechar", lambda: instancia.chamadas.append("fechar"))
    return instancia


def _sessao(modelo, make_game):
    jogo = make_game(name="Hollow Knight")
    modelo.show_session_blocker(jogo)
    modelo.hide_session_blocker()
    return jogo


def test_a_sessao_veste_e_despe_as_fitas(modelo, make_game):
    """O bloqueador da sessão é quem manda vestir a cor do jogo, e quem despe.

    O jogo que chega ao `comecar` é o da sessão que acabou de abrir.
    """
    jogo = make_game(name="Hollow Knight")

    modelo.show_session_blocker(jogo)
    assert modelo.chamadas == [("comecar", jogo)]

    modelo.hide_session_blocker()
    assert modelo.chamadas == [("comecar", jogo), "parede", "voltar"]


def test_a_sessao_manual_tambem_veste_e_despe(modelo, make_game):
    """Pelo rastreador de verdade (a janela "Jogando"), e não só pela chamada direta ao modelo."""
    jogo = make_game(name="Hollow Knight", game_id="shortcuts_9")
    manual = SessionWindow(jogo)

    manual.present()
    assert modelo.chamadas == [("comecar", jogo)]

    manual.close()
    assert modelo.chamadas == [("comecar", jogo), "parede", "voltar"]


def test_a_queda_para_a_manual_nao_veste_de_novo(modelo, make_game):
    """A mesma sessão trocando de rastreador: as fitas já estão vestidas do jogo."""
    jogo = make_game(name="Hollow Knight")
    modelo.show_session_blocker(jogo)
    modelo.show_session_blocker(jogo)

    assert modelo.chamadas == [("comecar", jogo)]


def test_fim_bloqueado_avisa(modelo, make_game, avisos, monkeypatch):
    monkeypatch.setattr(session_fita, "captura_bloqueada", lambda: True)
    _sessao(modelo, make_game)

    assert avisos == [AVISO_DA_TELA]


def test_fim_normal_nao_avisa(modelo, make_game, avisos):
    _sessao(modelo, make_game)

    assert avisos == []


def test_fora_do_ar_um_e_varios(modelo, make_game, avisos, monkeypatch):
    monkeypatch.setattr(session_fita, "fitas_fora_do_ar", lambda: ["Fita Monitor Direito"])
    _sessao(modelo, make_game)
    assert avisos == ["O dispositivo Fita Monitor Direito não respondeu durante parte da sessão."]

    avisos.clear()
    monkeypatch.setattr(session_fita, "fitas_fora_do_ar", lambda: ["A", "B"])
    _sessao(modelo, make_game)
    assert avisos == ["Alguns dispositivos não responderam durante parte da sessão."]


def test_os_avisos_vem_depois_de_as_fitas_voltarem(modelo, make_game, avisos, monkeypatch):
    """Primeiro a cor do app, depois a conta do que faltou: a conta é da sessão que acabou."""
    ordem = []
    monkeypatch.setattr(session_fita, "voltar", lambda: ordem.append("voltar"))
    monkeypatch.setattr(session_fita, "captura_bloqueada", lambda: ordem.append("bloqueada") or True)
    monkeypatch.setattr(session_fita, "fitas_fora_do_ar", lambda: ordem.append("fora") or [])
    _sessao(modelo, make_game)

    assert ordem == ["voltar", "bloqueada", "fora"]


def test_falha_nas_fitas_nao_impede_o_fim_da_sessao(modelo, make_game, monkeypatch, caplog):
    """Quem chama (o rastreador) ainda traz a janela de volta depois do `hide_session_blocker`."""

    def quebra():
        raise OSError("fita fora da tomada")

    monkeypatch.setattr(session_fita, "voltar", quebra)
    with caplog.at_level("ERROR"):
        _sessao(modelo, make_game)

    assert modelo.emAndamento is False
    assert "devolver as fitas" in caplog.text


def test_encerrar_devolve_parede_e_fitas(modelo):
    """Review Focus 1: o app fechando devolve a parede e as fitas, nessa ordem, sem tocar na janela."""

    class JanelaQueNaoSeToca:
        def __getattr__(self, nome):
            raise AssertionError(f"a janela foi tocada: {nome}")

    modelo.definir_janela(JanelaQueNaoSeToca())

    modelo.encerrar()  # o `saindo`: as janelas ainda na tela, nada que espere (R1)
    assert modelo.chamadas == []
    modelo.devolver()  # o `aboutToQuit`, com as janelas já fechadas

    assert modelo.chamadas == ["parede", "fechar"]


def test_encerrar_no_meio_da_sessao_devolve_as_fitas_depois_de_gravar(modelo, make_game, monkeypatch):
    """O tempo vai ao jogo e ao histórico antes de qualquer conversa com as fitas (que pode demorar)."""
    jogo = make_game(game_id="shortcuts_7", name="Hollow Knight")
    manual = SessionWindow(jogo)
    manual.present()
    visto = {}
    monkeypatch.setattr(
        session_fita, "fechar", lambda: visto.update(gravado=SessionWindow.active is None, fitas="fechar")
    )

    modelo.devolver()  # sem o `saindo` antes (o desligar do Windows): grava primeiro assim mesmo

    assert visto == {"gravado": True, "fitas": "fechar"}


def test_devolver_com_falha_ao_gravar_devolve_parede_e_fitas(modelo, make_game, monkeypatch, caplog):
    """Uma falha ao gravar (no `encerrar` de dentro do `devolver`) não deixa a parede trocada nem as fitas acesas."""
    jogo = make_game(game_id="shortcuts_7", name="Hollow Knight")
    SessionWindow(jogo).present()
    modelo.chamadas.clear()

    def quebra(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(session_log, "record", quebra)
    with caplog.at_level("ERROR"):
        modelo.devolver()

    assert modelo.chamadas == ["parede", "fechar"]
    assert "disco cheio" in caplog.text
