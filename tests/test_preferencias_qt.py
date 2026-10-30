"""O modelo das Preferências (D66): travas, regras dos textos, abrir/fechar e a busca."""

import types

import pytest

from cartridges import shared
from cartridges.modelos.preferencias import Preferencias


@pytest.fixture
def p(app_qt):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir()
    yield modelo
    modelo.fechar()


def test_contar_horas_trava_minimizar_ligado(p):
    shared.schema.set_boolean("minimize-after-launch", False)
    p.definir("playtime-tracking", True)
    assert shared.schema.get_boolean("minimize-after-launch")
    assert p.valores["minimize-after-launch"] is True
    assert p.estado["minimizarTravado"]


def test_desligar_contar_horas_destrava_sem_mudar_minimizar(p):
    p.definir("playtime-tracking", True)
    p.definir("playtime-tracking", False)
    assert not p.estado["minimizarTravado"]
    assert shared.schema.get_boolean("minimize-after-launch")


def test_chave_do_sgdb_vazia_desliga_o_sgdb(p):
    p.definirTexto("sgdb-key", "abc")
    p.definir("sgdb", True)
    assert p.estado["sgdbAtivo"]
    p.definirTexto("sgdb-key", "")
    assert not shared.schema.get_boolean("sgdb")
    assert not p.estado["sgdbAtivo"]


def test_chave_do_sgdb_gravada_como_digitada(p):
    p.definirTexto("sgdb-key", "  abc ")
    assert shared.schema.get_string("sgdb-key") == "  abc "


def test_chave_do_wallhaven_sem_espacos_nas_pontas(p):
    p.definirTexto("wallhaven-key", "  xyz \n")
    assert shared.schema.get_string("wallhaven-key") == "xyz"
    p.definirTexto("conquistas-chave-steam", " k ")
    assert shared.schema.get_string("conquistas-chave-steam") == "k"


def test_tempo_de_espera_limitado_e_inteiro(p):
    p.definir("process-tracking-grace", 200.7)
    assert shared.schema.get_int("process-tracking-grace") == 120
    p.definir("process-tracking-grace", -5)
    assert shared.schema.get_int("process-tracking-grace") == 0
    p.definir("process-tracking-grace", 30.9)
    assert shared.schema.get_int("process-tracking-grace") == 30


def test_chave_fora_da_lista_nao_e_gravada(p, caplog):
    antes = {c: shared.schema.get_value(c) for c in shared.schema.list_keys()}
    with caplog.at_level("WARNING"):
        p.definir("assistente-concluido", True)
        p.definir("fita-estado-anterior", "x")
        p.definir("show-news-button", True)
    assert {c: shared.schema.get_value(c) for c in shared.schema.list_keys()} == antes
    avisos = [r for r in caplog.records if r.name == "cartridges.modelos.preferencias"]
    assert [r.levelname for r in avisos] == ["WARNING"] * 3


def test_valores_seguem_o_schema(p):
    avisos = []
    p.alterado.connect(lambda: avisos.append(1))
    shared.schema.set_boolean("auto-import", True)
    assert avisos
    assert p.valores["auto-import"] is True


def test_abrir_duas_vezes_nao_reabre(p):
    assert not p.abrir("sgdb")
    assert p.pagina == "general"


def test_abrir_durante_a_importacao_nao_abre(app_qt, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(shared, "aplicativo", types.SimpleNamespace(importando=True), raising=False)
    modelo = Preferencias(None, lambda: True)
    assert not modelo.abrir()
    assert not modelo.aberto


def test_pagina_desconhecida_abre_o_geral(app_qt):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir("nao-existe")
    assert modelo.pagina == "general"
    modelo.fechar()
    assert modelo.abrir("sgdb")
    assert modelo.pagina == "sgdb"
    modelo.fechar()


def test_fechar_duas_vezes_nao_levanta(p):
    p.fechar()
    p.fechar()
    assert not p.aberto


def test_fechado_nao_segue_o_schema(p):
    p.fechar()
    avisos = []
    p.alterado.connect(lambda: avisos.append(1))
    shared.schema.set_boolean("auto-import", True)
    assert not avisos


def test_busca_ignora_maiusculas_e_acentos(p):
    assert p.corresponde("Iluminação inteligente", "ILUMINACAO")
    assert not p.corresponde("Iluminação inteligente", "controle")


def test_busca_vazia_mostra_tudo(p):
    assert p.corresponde("qualquer", "")


def test_valor_de_tipo_errado_e_recusado_sem_excecao(p, caplog):
    antes = {c: shared.schema.get_value(c) for c in shared.schema.list_keys()}
    with caplog.at_level("WARNING"):
        for chave, valor in (
            ("process-tracking-grace", float("nan")),
            ("process-tracking-grace", float("inf")),
            ("process-tracking-grace", "x"),
            ("process-tracking-grace", True),
            ("conquistas-aviso-som-volume", None),
            ("auto-import", "sim"),
            ("auto-import", 1),
        ):
            p.definir(chave, valor)
    assert {c: shared.schema.get_value(c) for c in shared.schema.list_keys()} == antes
    avisos = [r for r in caplog.records if r.name == "cartridges.modelos.preferencias"]
    assert len(avisos) == 7


def test_volume_limitado_de_10_a_100(p):
    p.definir("conquistas-aviso-som-volume", 3)
    assert shared.schema.get_int("conquistas-aviso-som-volume") == 10
    p.definir("conquistas-aviso-som-volume", 250.2)
    assert shared.schema.get_int("conquistas-aviso-som-volume") == 100


def test_rumble_segue_o_controle(p):
    p.definir("gamepad", False)
    assert not p.estado["rumbleAtivo"]
    p.definir("gamepad", True)
    assert p.estado["rumbleAtivo"]


def test_definir_texto_so_aceita_as_chaves_de_texto(p, caplog):
    with caplog.at_level("WARNING"):
        p.definirTexto("sgdb", "x")
        p.definirTexto("shortcuts-location", "C:/x")
    assert not shared.schema.get_boolean("sgdb")
    assert shared.schema.get_string("shortcuts-location") != "C:/x"
    avisos = [r for r in caplog.records if r.name == "cartridges.modelos.preferencias"]
    assert len(avisos) == 2
