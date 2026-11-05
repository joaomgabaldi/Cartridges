# test_preferencias_conquistas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A página Conquistas das Preferências, as contas dentro delas e o fechamento completo. Nenhuma conta, rede, fita ou janela de verdade: a prévia, o `aplicar` e o navegador são falsos."""

import json
import os
import subprocess
import sys
import uuid
import winreg
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest

from cartridges import app as modulo_app
from cartridges import conquista_aviso, shared
from cartridges.conquistas.ea import conta as ea_conta
from cartridges.conquistas.epic import conta as epic_conta
from cartridges.modelos import contas as modulo_das_contas
from cartridges.modelos import preferencias as preferencias_mod
from cartridges.modelos.preferencias import Preferencias
from cartridges.utils import open_uri, session_fita
from tests.apoio_fita import falsas, pastas, sem_fade, sem_vigia  # noqa: F401
from tests.apoio_registro import _apagar_chave
from tests.apoio_app_conquistas import _Gravador
from tests.apoio_preferencias_fitas_qt import _com_fitas, previas
from tests.apoio_qml_biblioteca import _achar, _esperar
from tests.apoio_qml_preferencias import _abrir, _clique, _enabled, _linha, _textos, app, fitas_espiadas

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def p(app_qt):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir()
    yield modelo
    modelo.fechar()


@pytest.fixture(autouse=True)
def conta_da_tuya(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "tuya_conta_arquivo", tmp_path / "tuya_conta.json")


def _cor(matiz, saturacao):
    return QColor.fromRgbF(*session_fita.cor_para_rgb(session_fita.Cor(matiz, saturacao, session_fita.BRILHO_CHEIO)))


# region A chave da Steam Web API


def test_chave_digitada_vai_para_o_schema(p):
    p.definirTexto("conquistas-chave-steam", "  ABC  ")
    assert shared.schema.get_string("conquistas-chave-steam") == "ABC"


def test_descricao_do_grupo_da_chave(app, monkeypatch):
    urls = []
    monkeypatch.setattr(open_uri, "abrir_url", lambda url: urls.append(url) or True)
    _abrir(app, "conquistas")
    grupo = app.achar("grupoDaChaveDaSteam")
    assert grupo.property("titulo") == "Steam Web API"
    assert grupo.property("descricao") == (
        'Informe a chave da Steam Web API. <a href="https://steamcommunity.com/dev/apikey">Obtenha aqui</a>.'
    )
    assert grupo.property("descricaoRica") is True
    assert app.achar("campoDaChaveDaSteam").property("titulo") == "Chave da API"
    QMetaObject.invokeMethod(
        app.achar("grupoDaChaveDaSteamDescricao"), "linkActivated", Qt.ConnectionType.DirectConnection,
        Q_ARG("QString", "https://steamcommunity.com/dev/apikey"),
    )  # fmt: skip
    assert urls == ["https://steamcommunity.com/dev/apikey"]


def test_chave_guardada_aparece_na_linha(app):
    shared.schema.set_string("conquistas-chave-steam", "xyz")
    _abrir(app, "conquistas")
    assert app.achar("campoDaChaveDaSteam").property("text") == "xyz"
    campo = app.achar("campoDaChaveDaSteam")
    campo.setProperty("text", "  abc  ")
    QMetaObject.invokeMethod(campo, "editado", Qt.ConnectionType.DirectConnection)
    assert shared.schema.get_string("conquistas-chave-steam") == "abc"


# endregion
# region O aviso durante o jogo


def test_posicao_escolhida_vai_para_o_schema(p):
    p.escolherPosicaoDoAviso(0)
    assert shared.schema.get_string("conquistas-aviso-posicao") == "superior-esquerdo"
    p.escolherPosicaoDoAviso(3)
    assert shared.schema.get_string("conquistas-aviso-posicao") == "inferior-direito"


def test_posicao_guardada_aparece_na_linha(app):
    shared.schema.set_string("conquistas-aviso-posicao", "superior-direito")
    _abrir(app, "conquistas")
    assert app.preferencias.estado["posicaoDoAviso"] == 1
    assert app.achar("linhaDaPosicaoDoAviso").property("currentIndex") == 1
    assert app.achar("linhaDaPosicaoDoAviso").property("model") == [
        "Canto superior esquerdo", "Canto superior direito", "Canto inferior esquerdo", "Canto inferior direito",
    ]  # fmt: skip


def test_posicao_estranha_no_schema_cai_no_padrao(p):
    shared.schema.set_string("conquistas-aviso-posicao", "meio")
    assert _esperar(lambda: p.estado["posicaoDoAviso"] == 3)
    assert shared.schema.get_string("conquistas-aviso-posicao") == "meio"  # ler não regrava


def test_posicao_sem_selecao_nao_levanta_nem_grava(p):
    shared.schema.set_string("conquistas-aviso-posicao", "superior-direito")
    p.escolherPosicaoDoAviso(-1)
    p.escolherPosicaoDoAviso(9)
    assert shared.schema.get_string("conquistas-aviso-posicao") == "superior-direito"


def test_os_quatro_cantos_aparecem_inteiros(app):
    _abrir(app, "conquistas")
    caixa = app.achar("linhaDaPosicaoDoAvisoCaixa")
    texto = caixa.property("contentItem")
    for indice in range(4):
        caixa.setProperty("currentIndex", indice)
        assert _esperar(lambda: texto.property("text") == caixa.property("displayText"))
        assert _esperar(lambda: texto.property("truncated") is False), texto.property("text")
    # As demais linhas de escolha seguem com a largura de antes.
    assert app.achar("linhaDoEstiloDoAlerta").property("larguraDaCaixa") == 180


def test_botao_de_exemplo_mostra_um_aviso(p, monkeypatch):
    mostrados = []
    monkeypatch.setattr(conquista_aviso, "mostrar", mostrados.append)
    p.mostrarAvisoDeExemplo()
    assert len(mostrados) == 1 and mostrados[0] == conquista_aviso.Aviso.exemplo()


def test_botao_de_exemplo_fecha_o_anterior_antes_de_mostrar(p, monkeypatch):
    chamadas = []
    monkeypatch.setattr(conquista_aviso, "fechar", lambda: chamadas.append("fechar"))
    monkeypatch.setattr(conquista_aviso, "mostrar", lambda _a: chamadas.append("mostrar"))
    p.mostrarAvisoDeExemplo()
    assert chamadas == ["fechar", "mostrar"]


def test_cliques_repetidos_no_exemplo_nao_enfileiram(p, monkeypatch):
    # Sem janela de verdade: só a fila importa.
    proximos = []
    monkeypatch.setattr(conquista_aviso, "_proximo", lambda com_som=True: proximos.append(com_som) or False)
    try:
        for _clique_ in range(3):
            p.mostrarAvisoDeExemplo()
        assert len(conquista_aviso._fila) == 1  # noqa: SLF001
        assert len(proximos) == 3  # cada clique chegou a pedir o cartão, sem levantar
    finally:
        conquista_aviso.fechar()


def test_botao_de_exemplo_na_tela_chama_o_modelo(app, monkeypatch):
    chamadas = []
    monkeypatch.setattr(conquista_aviso, "fechar", lambda: chamadas.append("fechar"))
    monkeypatch.setattr(conquista_aviso, "mostrar", lambda _a: chamadas.append("mostrar"))
    _abrir(app, "conquistas")
    assert app.achar("linhaDoExemplo").property("titulo") == "Mostrar um aviso de exemplo"
    _clique(app, "linhaDoExemploBotao")
    assert chamadas == ["fechar", "mostrar"]


def test_posicao_so_responde_com_o_aviso_ligado(app):
    shared.schema.set_boolean("conquistas-aviso", True)
    _abrir(app, "conquistas")
    assert _enabled(app, "linhaDaPosicaoDoAviso")
    app.preferencias.definir("conquistas-aviso", False)
    assert _esperar(lambda: not _enabled(app, "linhaDaPosicaoDoAviso"))


def test_som_so_responde_com_o_aviso_ligado(app):
    shared.schema.set_boolean("conquistas-aviso", True)
    _abrir(app, "conquistas")
    assert _enabled(app, "interruptor-conquistas-aviso-som")
    app.preferencias.definir("conquistas-aviso", False)
    assert _esperar(lambda: not _enabled(app, "interruptor-conquistas-aviso-som"))


def test_volume_so_responde_com_aviso_e_som_ligados(app):
    shared.schema.set_boolean("conquistas-aviso", True)
    shared.schema.set_boolean("conquistas-aviso-som", True)
    _abrir(app, "conquistas")
    assert _enabled(app, "linhaDoVolumeDoAviso")
    app.preferencias.definir("conquistas-aviso-som", False)
    assert _esperar(lambda: not _enabled(app, "linhaDoVolumeDoAviso"))
    app.preferencias.definir("conquistas-aviso-som", True)
    assert _esperar(lambda: _enabled(app, "linhaDoVolumeDoAviso"))
    app.preferencias.definir("conquistas-aviso", False)
    assert _esperar(lambda: not _enabled(app, "linhaDoVolumeDoAviso"))


def test_volume_vai_para_o_schema(app):
    _abrir(app, "conquistas")
    assert app.achar("linhaDoVolumeDoAvisoCaixa").property("value") == 100
    caixa = app.achar("linhaDoVolumeDoAvisoCaixa")
    assert (caixa.property("from"), caixa.property("to"), caixa.property("stepSize")) == (10, 100, 5)
    assert app.achar("linhaDoVolumeDoAviso").property("pagina") == 10
    app.preferencias.definir("conquistas-aviso-som-volume", 35)
    assert shared.schema.get_int("conquistas-aviso-som-volume") == 35
    assert _esperar(lambda: caixa.property("value") == 35)


def test_textos_do_grupo_durante_o_jogo(app):
    _abrir(app, "conquistas")
    assert app.achar("grupoDuranteOJogo").property("titulo") == "Durante o jogo"
    assert not app.achar("grupoDuranteOJogo").property("descricao")
    assert _linha(app, "interruptor-conquistas-aviso") == (
        "Mostrar aviso durante o jogo",
        "Exibe um aviso por cima do jogo ao desbloquear uma conquista. "
        "Nos jogos da Steam, aparece o aviso da própria Steam.",
    )
    assert _linha(app, "interruptor-conquistas-aviso-som") == (
        "Tocar som com o aviso", "Reproduz um som quando o aviso aparece"
    )
    assert _linha(app, "linhaDoVolumeDoAviso") == ("Volume do som (%)", "")
    assert app.achar("linhaDaPosicaoDoAviso").property("titulo") == "Posição do aviso"
    assert _linha(app, "interruptor-conquistas-iluminacao") == (
        "Piscar a iluminação inteligente", "Os dispositivos piscam ao desbloquear uma conquista"
    )
    assert _linha(app, "linhaDaCorDoAlerta") == (
        "Cor do alerta", "A cor da iluminação inteligente ao desbloquear uma conquista"
    )
    assert app.achar("linhaDaCorDoAlertaAmostra").property("dica") == "Escolher a cor do alerta"
    assert app.achar("linhaDoEstiloDoAlerta").property("titulo") == "Estilo do alerta"
    assert app.achar("linhaDoEstiloDoAlerta").property("model") == [
        "Piscar", "Respirar", "Piscar rápido", "Brilho longo"
    ]
    assert app.achar("linhaDoTesteDoAlerta").property("titulo") == "Testar o alerta"


def test_textos_de_exibicao(app):
    _abrir(app, "conquistas")
    assert app.achar("grupoExibicao").property("titulo") == "Exibição"
    assert _linha(app, "interruptor-conquistas-mostrar-ocultas") == (
        "Mostrar descrição das conquistas ocultas",
        "Exibe o nome e a descrição das conquistas ocultas ainda não desbloqueadas",
    )


def test_aba_conquistas_e_a_ultima(app):
    _abrir(app, "conquistas")
    dialogo = app.achar("dialogoDePreferencias")
    assert dialogo.property("rotulosDasAbas").toVariant()[-1] == "Conquistas"
    assert app.achar("paginaDasConquistas").property("visible") is True
    assert app.achar("paginaGeral").property("visible") is False


# endregion
# region O pulso (a cor, o estilo e o teste do alerta)


def _linhas_do_pulso(app):
    return [_enabled(app, nome) for nome in ("linhaDaCorDoAlerta", "linhaDoEstiloDoAlerta", "linhaDoTesteDoAlerta")]


def test_linhas_do_pulso_desativadas_sem_iluminacao(app, fitas_espiadas):  # noqa: ARG001
    shared.schema.set_boolean("conquistas-iluminacao", True)
    shared.schema.set_boolean("session-fita", False)
    _abrir(app, "conquistas")
    assert _linhas_do_pulso(app) == [False] * 3
    app.preferencias.definir("session-fita", True)
    assert _esperar(lambda: _linhas_do_pulso(app) == [True] * 3)
    app.preferencias.definir("session-fita", False)
    assert _esperar(lambda: _linhas_do_pulso(app) == [False] * 3)


def test_linhas_do_pulso_desativadas_sem_piscar(app, fitas_espiadas):  # noqa: ARG001
    shared.schema.set_boolean("conquistas-iluminacao", False)
    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "conquistas")
    assert _linhas_do_pulso(app) == [False] * 3
    app.preferencias.definir("conquistas-iluminacao", True)
    assert _esperar(lambda: _linhas_do_pulso(app) == [True] * 3)


def test_estilo_do_pulso_gravado_pela_lista(p):
    assert p.fitas.estiloDoPulso == 1  # Respirar, o padrão
    p.fitas.escolherEstiloDoPulso(2)
    assert shared.schema.get_string("conquistas-pulso-estilo") == "rapido"
    p.fitas.escolherEstiloDoPulso(-1)
    p.fitas.escolherEstiloDoPulso(9)
    assert shared.schema.get_string("conquistas-pulso-estilo") == "rapido"


def test_estilo_e_cor_gravados_sao_lidos_ao_abrir(app_qt, previas):  # noqa: ARG001
    shared.schema.set_string("conquistas-pulso-estilo", "longo")
    session_fita.salvar_tom_do_pulso(200, 800)
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()
    assert modelo.fitas.estiloDoPulso == 3
    assert modelo.fitas.corDoPulsoPadrao is False
    # Ler o que está gravado não regrava nada nem acende as fitas.
    assert shared.schema.get_string("conquistas-pulso-estilo") == "longo"
    assert session_fita.tom_do_pulso() == (200, 800)
    assert previas == []
    modelo.fechar()


def test_cor_do_pulso_gravada_e_voltar_ao_padrao(p):
    assert p.fitas.corDoPulsoPadrao is True
    p.fitas.escolherCorDoPulso(_cor(200, 800))
    assert session_fita.tom_do_pulso() != session_fita.TOM_DO_OURO
    assert p.fitas.corDoPulsoPadrao is False
    assert abs(p.fitas.corDoPulso.hsvHueF() * 360 - 200) <= 1
    p.fitas.voltarCorDoPulso()
    assert session_fita.tom_do_pulso() == session_fita.TOM_DO_OURO
    assert p.fitas.corDoPulsoPadrao is True
    p.fitas.escolherCorDoPulso(QColor())  # cor inválida não grava
    assert session_fita.tom_do_pulso() == session_fita.TOM_DO_OURO


def test_fechar_o_balao_volta_a_cor_do_app(p, previas):
    p.fitas.abrirCorDoPulso()
    p.fitas.escolherCorDoPulso(_cor(200, 800))
    assert previas[-1] == (session_fita.cor_do_pulso(), None)
    p.fitas.fecharCorDoPulso()
    assert previas[-1] == (session_fita.cor_do_app(), None)
    quantas = len(previas)
    p.fitas.fecharCorDoPulso()  # o balão já estava fechado: nada a devolver
    assert len(previas) == quantas


def test_abrir_o_balao_mostra_a_cor_do_pulso_nas_fitas(app_qt, previas):  # noqa: ARG001
    session_fita.salvar_tom_do_pulso(200, 800)
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()
    assert previas == []  # abrir as Preferências não acende fita nenhuma
    modelo.fitas.abrirCorDoPulso()
    assert previas == [(session_fita.cor_do_pulso(), None)]
    modelo.fechar()


def test_voltar_ao_padrao_com_o_balao_fechado_nao_deixa_previa(app_qt, previas):  # noqa: ARG001
    """O botão fica fora do balão: sem balão aberto, não há prévia a mostrar."""
    session_fita.salvar_tom_do_pulso(200, 800)
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()
    modelo.fitas.voltarCorDoPulso()
    assert session_fita.tom_do_pulso() == session_fita.TOM_DO_OURO
    assert previas == []
    modelo.fitas.escolherCorDoPulso(_cor(10, 500))
    assert previas == []
    modelo.fechar()
    assert previas == []  # sem prévia nesta abertura, fechar não pinta a cor do app


def test_testar_o_pulso_chama_o_teste(p, monkeypatch):
    chamadas = []
    monkeypatch.setattr(session_fita, "testar_pulso", lambda: chamadas.append("teste"))
    p.fitas.testarAlerta()
    assert chamadas == ["teste"]


def test_a_lista_de_estilos_da_tela_cobre_todos_os_estilos():
    assert set(preferencias_mod.ESTILOS_NA_TELA) == set(session_fita.ESTILOS_DO_PULSO)


def test_o_balao_da_tela_mostra_e_devolve_a_cor(app, fitas_espiadas):
    shared.schema.set_boolean("session-fita", True)
    shared.schema.set_boolean("conquistas-iluminacao", True)
    _abrir(app, "conquistas")
    _clique(app, "linhaDaCorDoAlertaAmostra")
    assert _esperar(lambda: app.achar("linhaDaCorDoAlertaBalao").property("opened") is True)
    assert fitas_espiadas[-1] == session_fita.cor_do_pulso()
    QMetaObject.invokeMethod(
        app.achar("linhaDaCorDoAlertaSeletor"), "mover", Qt.ConnectionType.DirectConnection,
        Q_ARG("QVariant", 120), Q_ARG("QVariant", 900),
    )  # fmt: skip
    assert abs(session_fita.tom_do_pulso()[0] - 120) <= 1
    assert fitas_espiadas[-1] == session_fita.cor_do_pulso()
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)  # o Esc fecha só o balão
    assert _esperar(lambda: app.achar("linhaDaCorDoAlertaBalao").property("opened") is False)
    assert fitas_espiadas[-1] == session_fita.cor_do_app()
    assert app.preferencias.aberto is True
    assert _esperar(lambda: app.achar("linhaDaCorDoAlertaVoltar").property("visible") is True)
    _clique(app, "linhaDaCorDoAlertaVoltar")
    assert session_fita.tom_do_pulso() == session_fita.TOM_DO_OURO


def test_o_estilo_e_o_teste_na_tela(app, fitas_espiadas, monkeypatch):  # noqa: ARG001
    chamadas = []
    monkeypatch.setattr(session_fita, "testar_pulso", lambda: chamadas.append("teste"))
    shared.schema.set_boolean("session-fita", True)
    shared.schema.set_boolean("conquistas-iluminacao", True)
    _abrir(app, "conquistas")
    _clique(app, "linhaDoTesteDoAlertaBotao")
    assert chamadas == ["teste"]
    QMetaObject.invokeMethod(
        app.achar("linhaDoEstiloDoAlerta"), "escolhido", Qt.ConnectionType.DirectConnection, Q_ARG("int", 3)
    )
    assert shared.schema.get_string("conquistas-pulso-estilo") == "longo"


# endregion
# region As contas e o fechamento


def test_fechar_as_preferencias_fecha_o_grupo_das_contas(app_qt, monkeypatch):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    assert modelo.contas is None
    modelo.abrir()
    assert modelo.contas is not None
    fechados = []
    monkeypatch.setattr(modelo.contas, "fechar", lambda: fechados.append(1))
    modelo.fechar()
    assert fechados == [1]
    assert modelo.contas is None


def test_o_grupo_das_contas_aparece_na_pagina(app, monkeypatch):
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    _abrir(app, "conquistas")
    assert app.achar("grupoDasContas").property("visible") is True
    assert _esperar(lambda: app.achar("tituloDoGrupoDasContas").property("text") == "Contas")
    app.preferencias.fechar()
    assert _esperar(lambda: app.achar("dialogoDePreferencias").property("visible") is False)


def _tudo_aberto(p):
    _com_fitas("Centro", "Direita")
    p.fitas.reler()
    p.fitas.abrirCorDoPulso()
    p.abrirBrilhoPorDispositivo()
    p.abrirConfiguracaoDasFitas()
    p.abrirCalibracao()
    assert None not in (p.brilhoPorDispositivo, p.configuracaoDasFitas, p.calibracao, p.contas)


def test_fechar_com_tudo_aberto_devolve_as_fitas_e_solta_tudo(p, previas, monkeypatch):
    _tudo_aberto(p)
    ligacao = p._ligacao  # noqa: SLF001
    assert ligacao is not None
    soltos = []
    desconectar = shared.schema.disconnect
    monkeypatch.setattr(shared.schema, "disconnect", lambda i: soltos.append(i) or desconectar(i))
    p.fechar()
    assert (p.brilhoPorDispositivo, p.configuracaoDasFitas, p.calibracao, p.contas) == (None,) * 4
    assert p.aberto is False
    assert previas[-1] == (session_fita.cor_do_app(), None)  # as fitas voltaram à cor do app
    assert ligacao in soltos and p._ligacao is None  # noqa: SLF001
    assert p.biblioteca._seguindo is False  # noqa: SLF001
    # Solto o ouvinte, o schema não mexe mais nos valores.
    antes = p.valores["cover-autoplay"]
    shared.schema.set_boolean("cover-autoplay", not antes)
    assert p.valores["cover-autoplay"] == antes
    # O balão fechado com a tela não devolve nada de novo quando o QML o soltar.
    quantas = len(previas)
    p.fitas.fecharCorDoPulso()
    assert len(previas) == quantas


def test_um_passo_que_falha_no_fechar_nao_pula_os_outros(p, monkeypatch, caplog):
    _tudo_aberto(p)

    def quebra(*_a):
        raise RuntimeError("falhou")

    monkeypatch.setattr(p.contas, "fechar", quebra)
    monkeypatch.setattr(p.calibracao, "cancelar", quebra)
    monkeypatch.setattr(p.brilhoPorDispositivo, "cancelar", quebra)
    ligacao = p._ligacao  # noqa: SLF001
    soltos = []
    desconectar = shared.schema.disconnect
    monkeypatch.setattr(shared.schema, "disconnect", lambda i: soltos.append(i) or desconectar(i))
    with caplog.at_level("ERROR"):
        p.fechar()
    assert p.configuracaoDasFitas is None  # o assistente das fitas fechou mesmo assim
    assert ligacao in soltos
    assert p.contas is None
    assert "falhou" in caplog.text


def test_fechar_depois_do_assistente_das_fitas_nao_mexe_nas_fitas(p, previas):
    """Fechar as Preferências não devolve a cor do app; só o balão do pulso e os diálogos internos devolvem."""
    _com_fitas("Centro")
    p.fitas.definirBrilho(30)
    p.abrirConfiguracaoDasFitas()
    p.configuracaoDasFitas.fechar()
    assert p.configuracaoDasFitas is None
    previas.clear()
    p.fechar()
    assert previas == []


def test_fechar_duas_vezes_nao_levanta(p):
    _tudo_aberto(p)
    p.fechar()
    p.fechar()
    assert p.aberto is False


def _fechar_o_app(preferencias, monkeypatch):
    """O `_fechar` do app com tudo falso; `preferencias=None` põe um gravador no lugar. Devolve os passos anotados."""
    passos = []
    if preferencias is None:
        preferencias = _Gravador(passos, "preferencias")
    monkeypatch.setattr(modulo_app, "login", _Gravador(passos, "login"))
    monkeypatch.setattr(modulo_app, "ea_conta", _Gravador(passos, "ea"))
    monkeypatch.setattr(modulo_app, "icones", _Gravador(passos, "icones"))
    monkeypatch.setattr(modulo_app, "async_manager", _Gravador(passos, "async"))
    monkeypatch.setattr(modulo_app, "copias_animadas", _Gravador(passos, "copias"))
    monkeypatch.setattr(
        shared, "aplicativo", SimpleNamespace(varredura_conquistas=_Gravador(passos, "varredura")), raising=False
    )
    modulo_app._fechar(modulo_app._Abertura(  # noqa: SLF001
        big_picture=_Gravador(passos, "bp"), sessao=_Gravador(passos, "sessao"),
        verificador=_Gravador(passos, "verificador"), varredura_hltb=_Gravador(passos, "hltb"),
        varredura_tamanho=_Gravador(passos, "tamanho"), edicao=_Gravador(passos, "edicao"), preferencias=preferencias,
    ))  # fmt: skip
    return passos


def test_encerrar_o_app_fecha_as_preferencias_antes_do_login(monkeypatch):
    anotados = _fechar_o_app(None, monkeypatch)
    assert "preferencias.fechar" in anotados
    assert anotados.index("preferencias.fechar") < anotados.index("login.cancelar_pendente")
    # A prévia das fitas sai antes de a sessão devolvê-las: depois, ela as acenderia de novo.
    assert anotados.index("preferencias.fechar") < anotados.index("sessao.devolver")


def test_encerrar_o_app_fecha_o_modal_aberto(p, previas, monkeypatch):
    _com_fitas("Centro", "Direita")
    p.abrirCalibracao()
    p.abrirBrilhoPorDispositivo()
    previas.clear()
    _fechar_o_app(p, monkeypatch)
    assert (p.calibracao, p.brilhoPorDispositivo, p.contas) == (None, None, None)
    assert p.aberto is False
    assert previas[-1] == (session_fita.cor_do_app(), None)


def test_o_modelo_nao_traz_o_gtk():
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; builtins.ngettext = lambda s, p, n: s if n == 1 else p; "
        "import cartridges.modelos.preferencias; import cartridges.conquista_aviso; "
        "assert 'gi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", codigo], check=True, cwd=RAIZ, timeout=60)


# endregion
# region A janela de login por cima das Preferências


def test_janela_de_login_por_cima_das_preferencias(app, monkeypatch, flush_idle):
    monkeypatch.setattr(modulo_das_contas, "_abrir_navegador", lambda _url: None)  # `abrir` falso
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(ea_conta, "conectada", lambda: False)
    _abrir(app, "conquistas")
    botao = app.achar("botaoDaConta_epic")
    botao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    janela = app.achar("janelaDeLoginEpic")
    assert _esperar(lambda: janela.property("visible") is True)
    assert _achar(janela, "tituloDoLogin").property("text") == app.preferencias.contas.loginEpic.titulo != ""
    # A página e o cartão ficam apagados; a janela de login tem o foco.
    assert app.achar("cartaoDasPreferencias").property("enabled") is False
    assert _esperar(lambda: _achar(janela, "campoDeUmaLinha").property("activeFocus") is True)
    focados = []
    for _ in range(8):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        flush_idle(0.03)
        item = atual = app.janela.activeFocusItem()
        focados.append(atual)
        dentro = False
        while item is not None:
            dentro = dentro or item is janela
            item = item.parentItem()
        assert dentro  # o Tab circula dentro da janela de login
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: janela.property("visible") is False)
    assert app.preferencias.aberto is True  # o Esc fechou só o login
    assert app.achar("dialogoDePreferencias").property("visible") is True
    assert _esperar(lambda: app.achar("cartaoDasPreferencias").property("enabled") is True)
    assert _esperar(lambda: botao.property("activeFocus") is True)


def test_a_janela_da_ea_tambem_cobre_as_preferencias(app, monkeypatch):
    monkeypatch.setattr(modulo_das_contas, "_abrir_navegador", lambda _url: None)  # `abrir` falso
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(ea_conta, "conectada", lambda: False)
    _abrir(app, "conquistas")
    QMetaObject.invokeMethod(app.achar("botaoDaConta_ea"), "click", Qt.ConnectionType.DirectConnection)
    janela = app.achar("janelaDeLoginEa")
    assert _esperar(lambda: janela.property("visible") is True)
    assert app.achar("cartaoDasPreferencias").property("enabled") is False
    app.preferencias.fechar()  # fechar as Preferências fecha o login junto
    assert _esperar(lambda: janela.property("visible") is False)
    assert app.preferencias.contas is None


def test_textos_das_conquistas_sem_jargao(app):
    _abrir(app, "conquistas")
    todos = "\n".join(_textos(app.achar("paginaDasConquistas")))
    for proibido in ("ficha", "tumba", "sidecar", "registro"):
        assert proibido not in todos.lower()


# endregion
# region O fechamento da principal com o exemplo na tela (subprocesso, main() de verdade)


_PRINCIPAL_COM_EXEMPLO = r"""
import json, sys, time
from types import SimpleNamespace
import requests.sessions


def sem_rede(*_a, **_k):
    raise ConnectionError("sem rede no teste")


requests.sessions.Session.send = sem_rede
from cartridges import app as m, conquista_aviso, shared
from cartridges.utils import janela_por_cima, session_fita, session_wallpaper
from PySide6.QtCore import QTimer

m.session_fita = SimpleNamespace(abrir=lambda: None, fechar=lambda: None)
m.session_wallpaper = SimpleNamespace(restaurar_orfaos=lambda: None)
m.restauracao = SimpleNamespace(existe=lambda: True)  # sem a importação automática da abertura
# A pasta de dados vazia mostraria o assistente da primeira abertura (D86) no lugar da principal.
m.assistente.precisa_mostrar = lambda: False


class Quieto:
    def __init__(self, *_a, **_k):
        pass

    def __getattr__(self, _nome):
        return lambda *_a, **_k: None


for nome in ("UpdatesChecker", "HLTBBackfill", "InstallSizeSweep", "VarreduraConquistas"):
    setattr(m, nome, Quieto)
# Sem user32 de verdade: a janela do aviso aparece, mas nada fala com o Win32 e o som não toca.
janela_por_cima.preparar = lambda _j: True
janela_por_cima.mostrar_sem_tomar_o_foco = lambda j: j.show()
janela_por_cima.por_no_canto = lambda *_a, **_k: True
conquista_aviso._tocar_som = lambda: None
medidas = {}


class AppDeTeste(m.AplicacaoQt):
    def __init__(self, *argumentos):
        super().__init__(*argumentos)
        QTimer.singleShot(1500, self.mostrar_o_exemplo)

    def mostrar_o_exemplo(self):
        conquista_aviso.mostrar(conquista_aviso.Aviso.exemplo())
        medidas["na_tela"] = conquista_aviso.na_tela()
        QTimer.singleShot(500, self.fechar_a_principal)

    def fechar_a_principal(self):
        medidas["fechou_em"] = time.monotonic()
        principal = [j for j in self.topLevelWindows() if j.objectName() != "janelaDoAviso" and j.isVisible()]
        medidas["janelas"] = len(self.topLevelWindows())
        principal[0].close() if principal else self.quit()
        # Rede de segurança do próprio teste: nunca deixa o processo preso.
        QTimer.singleShot(15000, lambda: sys.exit(3))


m.AplicacaoQt = AppDeTeste
codigo = m.main(sys.argv[:1])
medidas["saiu_em"] = time.monotonic()
print(json.dumps({"codigo": codigo, "na_tela": medidas.get("na_tela"),
                  "demorou": medidas["saiu_em"] - medidas["fechou_em"]}), flush=True)
sys.exit(codigo)
"""


def test_fechar_a_principal_com_o_exemplo_na_tela_sai(tmp_path):
    registro = rf"Software\CartridgesTestes\app-{uuid.uuid4()}"
    ambiente = {
        **os.environ,
        "CARTRIDGES_DADOS": str(tmp_path),
        "CARTRIDGES_REGISTRO": registro,
        "QT_QPA_PLATFORM": "offscreen",
    }
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", _PRINCIPAL_COM_EXEMPLO], cwd=RAIZ, env=ambiente, capture_output=True, text=True,
            timeout=60, check=False,
        )  # fmt: skip
    finally:
        _apagar_chave(winreg.HKEY_CURRENT_USER, registro)  # a subchave que o subprocesso criou
    assert resultado.returncode == 0, resultado.stderr
    saida = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert saida["na_tela"] == "Conquista de exemplo"
    assert saida["codigo"] == 0 and saida["demorou"] < 10


# endregion
