# test_preferencias_atualizacoes_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O grupo "Atualizações" da página Geral das Preferências. Nada de verdade: a release é falsa e o instalador, o guarda do conftest."""

import types

import pytest
from PySide6.QtCore import QMetaObject, Qt

from cartridges import shared
from cartridges.utils import app_updater
from cartridges.utils.app_updater import AppUpdater, Release
from tests.apoio_janela_atualizacao import Janela, esperar

FORA = "A busca de atualizações só funciona no aplicativo instalado."


@pytest.fixture
def janela(app_qt, monkeypatch, sem_instalador_de_verdade):  # noqa: ARG001
    j = Janela()
    monkeypatch.setattr(shared, "aplicativo", j.aplicativo, raising=False)
    monkeypatch.setattr(AppUpdater, "_ocupado", staticmethod(lambda: False))
    yield j
    j.atualizador.stop()
    j.fechar()


def _abrir_preferencias(janela):
    assert janela.preferencias.abrir("general")
    assert esperar(lambda: janela.achar("dialogoDePreferencias").property("visible") is True)


def _clicar_em_buscar(janela):
    QMetaObject.invokeMethod(janela.achar("linhaBuscarAtualizacoesBotao"), "click", Qt.ConnectionType.DirectConnection)


def _aviso(janela):
    return janela.aplicativo.avisos.property("texto")


def test_linha_mostra_a_versao_atual(janela):
    # `versao` é constante: o QML a lê uma vez, então o teste confere a que o app tem.
    _abrir_preferencias(janela)
    linha = janela.achar("linhaBuscarAtualizacoes")
    assert linha.property("titulo") == "Buscar atualizações"
    assert linha.property("subtitulo") == f"Versão atual: {shared.VERSION}"
    # A linha não aciona nada; o botão "Buscar" é que responde.
    assert janela.achar("linhaBuscarAtualizacoesBotao").property("text") == "Buscar"
    assert janela.achar("grupoAtualizacoes").property("titulo") == "Atualizações"


def test_clique_fora_da_instalacao_mostra_aviso(janela, monkeypatch):
    monkeypatch.setattr(app_updater, "installed_root", lambda: None)
    _abrir_preferencias(janela)

    _clicar_em_buscar(janela)

    assert esperar(lambda: _aviso(janela) == FORA)
    assert janela.achar("linhaBuscarAtualizacoesBotao").property("enabled") is True


def test_clique_com_o_dialogo_aberto_mostra_aviso_nele(janela, monkeypatch):
    """Com as Preferências abertas o aviso aparece por cima delas, na mesma fila do app."""
    monkeypatch.setattr(app_updater, "installed_root", lambda: None)
    _abrir_preferencias(janela)

    _clicar_em_buscar(janela)

    assert esperar(lambda: janela.achar("aviso").property("visible") is True)
    assert janela.achar("textoDoAviso").property("text") == FORA
    assert janela.achar("dialogoDePreferencias").property("visible") is True


def test_buscar_fica_apagado_enquanto_busca(janela, monkeypatch, tmp_path):
    monkeypatch.setattr(app_updater, "installed_root", lambda: tmp_path)
    monkeypatch.setattr(shared, "VERSION", "2026.09.10")
    monkeypatch.setattr(app_updater, "_buscar_release", lambda: Release("2026.09.10", "", "https://x", 1, "ab"))
    pendentes = []
    monkeypatch.setattr(
        app_updater.threading, "Thread", lambda target, **_kw: types.SimpleNamespace(start=lambda: pendentes.append(target))
    )
    _abrir_preferencias(janela)
    botao = janela.achar("linhaBuscarAtualizacoesBotao")
    linha = janela.achar("linhaBuscarAtualizacoes")

    _clicar_em_buscar(janela)

    assert janela.atualizador.buscando is True
    # Só o botão apaga, não a linha inteira.
    assert botao.property("enabled") is False
    assert linha.property("enabled") is True
    assert len(pendentes) == 1

    pendentes[0]()  # a resposta chega pela fila da thread principal
    assert esperar(lambda: janela.atualizador.buscando is False)
    assert linha.property("enabled") is True
    assert _aviso(janela) == "O Kyron já está na versão mais recente."
    assert botao.property("enabled") is True


def test_clique_sem_atualizador_no_contexto_avisa(app_qt, monkeypatch):  # noqa: ARG001
    j = Janela(com_atualizador=False)
    try:
        monkeypatch.setattr(shared, "aplicativo", j.aplicativo, raising=False)
        _abrir_preferencias(j)
        _clicar_em_buscar(j)
        assert esperar(lambda: _aviso(j) == "Não foi possível buscar atualizações")
        assert j.achar("linhaBuscarAtualizacoes").property("subtitulo") == "Versão atual: "
    finally:
        j.fechar()


def test_busca_com_versao_nova_abre_a_pergunta_sem_aviso(janela, monkeypatch, tmp_path):
    monkeypatch.setattr(app_updater, "installed_root", lambda: tmp_path)
    monkeypatch.setattr(shared, "VERSION", "2026.09.01")
    monkeypatch.setattr(app_updater, "_buscar_release", lambda: Release("2026.09.10", "- Algo", "https://x", 1, "ab"))
    monkeypatch.setattr(
        app_updater.threading, "Thread", lambda target, **_kw: types.SimpleNamespace(start=target)
    )
    _abrir_preferencias(janela)

    _clicar_em_buscar(janela)

    assert esperar(lambda: janela.achar("dialogoDaAtualizacao").property("visible") is True)
    assert janela.achar("tituloDaAtualizacao").property("text") == "Nova versão disponível: 2026.09.10"
    assert _aviso(janela) == ""


def _resultados_da_busca(janela):
    achados, pilha = [], [janela.achar("resultadosDaBuscaDasPreferencias")]
    while pilha:
        atual = pilha.pop()
        if atual.objectName().startswith("resultadoDaBusca-") and atual.objectName()[17:].isdigit():
            achados.append((atual.property("titulo"), atual.property("subtitulo")))
        pilha.extend(atual.childItems())
    return achados


def test_busca_acha_buscar_atualizacoes(janela):
    _abrir_preferencias(janela)
    janela.achar("dialogoDePreferencias").setProperty("filtro", "atualiza")
    assert esperar(lambda: janela.achar("campoDeBuscaDasPreferencias").property("text") == "atualiza")
    assert esperar(lambda: ("Buscar atualizações", "Geral → Atualizações") in _resultados_da_busca(janela))
    # Uma busca que não combina não deixa resultado: só a tela de nenhum resultado.
    janela.achar("dialogoDePreferencias").setProperty("filtro", "zzzz")
    assert esperar(lambda: janela.achar("estadoSemResultadoDasPreferencias").property("visible") is True)
    assert _resultados_da_busca(janela) == []
