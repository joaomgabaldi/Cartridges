# test_calibracao_janela.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O assistente de calibração: o que ele mostra nas fitas, o que grava e
quando."""

import pytest

from cartridges import shared
from cartridges.utils import calibracao, session_fita
from cartridges.calibracao_janela import SATURACAO_DA_REFERENCIA
from cartridges.utils.calibracao import NEUTRA


@pytest.fixture
def assistente(tmp_path, monkeypatch, schema):
    """O assistente com duas fitas gravadas e a prévia nas fitas espionada."""
    from cartridges.calibracao_janela import AssistenteDeCalibracao  # noqa: PLC0415

    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    session_fita.gravar_fitas(
        [
            session_fita.Fita("Esquerda", "eb0", "1.2.3.4", "k", "3.3", 80),
            session_fita.Fita("Direita", "eb1", "1.2.3.5", "k"),
        ]
    )
    previas = []
    monkeypatch.setattr(
        session_fita,
        "previa_calibracao",
        lambda id_, cor, calibracoes: previas.append(("so", id_, cor, dict(calibracoes))),
    )
    monkeypatch.setattr(
        session_fita,
        "previa",
        lambda cor, tetos=None, calibracoes=None: previas.append(
            ("todas", cor, dict(calibracoes or {}))
        ),
    )
    janela = AssistenteDeCalibracao(session_fita.fitas())
    janela.previas = previas
    return janela


def test_escolher_acende_so_a_fita_na_primeira_referencia(assistente):
    assistente.escolher("eb0")
    tipo, id_, cor, _calibracoes = assistente.previas[-1]
    assert (tipo, id_) == ("so", "eb0")
    assert (cor.matiz, cor.saturacao) == (0, SATURACAO_DA_REFERENCIA)
    assert assistente.etapa == 0


def test_mexer_no_tom_mostra_a_calibracao_em_edicao(assistente):
    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    calibracoes = assistente.previas[-1][3]
    assert calibracoes["eb0"].cores[0] == (-8, 1.0)


def test_intensidade_e_temperatura_vao_para_a_calibracao(assistente):
    assistente.escolher("eb0")
    assistente.proxima()  # amarelo
    assistente.mudar_intensidade(1.2)
    for _ in range(5):
        assistente.proxima()  # até o branco
    assert assistente.etapa == 6
    assistente.mudar_temperatura(-1)
    assert assistente.calibracoes["eb0"].cores[1] == (0, 1.2)
    assert assistente.calibracoes["eb0"].branco == calibracao.branco_da_temperatura(-1)


def test_restaurar_volta_a_etapa_ao_neutro(assistente):
    assistente.escolher("eb0")
    assistente.mudar_tom(12)
    assistente.restaurar()
    assert assistente.calibracoes["eb0"] == NEUTRA


def test_navegacao_vai_do_inicio_ao_fim(assistente):
    assistente.escolher("eb0")
    assistente.anterior()
    assert assistente.pagina() == "inicio"
    assistente.escolher("eb0")
    for _ in range(7):
        assistente.proxima()
    assert assistente.pagina() == "fim"


def test_aplicar_tambem_copia_a_calibracao(assistente):
    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    assistente.aplicar_tambem({"eb1"})
    assert assistente.calibracoes["eb1"] == assistente.calibracoes["eb0"]


def test_concluir_grava_a_calibracao_de_cada_fita(assistente):
    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    assistente.concluir()
    gravadas = {fita.id: fita for fita in session_fita.fitas()}
    assert calibracao.de_json(gravadas["eb0"].calibracao).cores[0] == (-8, 1.0)
    assert gravadas["eb1"].calibracao is None  # neutra não é gravada
    assert gravadas["eb0"].brilho == 80  # o resto da fita não muda


def test_cancelar_nao_grava_e_volta_a_cor_do_app(assistente):
    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    assistente.cancelar()
    assert all(fita.calibracao is None for fita in session_fita.fitas())
    assert assistente.previas[-1][0] == "todas"
    assert assistente.previas[-1][1] == session_fita.cor_do_app()


def test_testar_passa_pelas_cores_em_todas_e_para_ao_fechar(assistente):
    from gi.repository import GLib  # noqa: PLC0415

    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    assistente.testar()
    tipo, cor, calibracoes = assistente.previas[-1]
    assert tipo == "todas" and (cor.matiz, cor.saturacao) == (0, SATURACAO_DA_REFERENCIA)
    assert calibracoes["eb0"].cores[0] == (-8, 1.0)
    assistente.avancar_teste()
    assert assistente.previas[-1][1].matiz == 60
    temporizador = assistente._temporizador
    assert temporizador
    assistente.cancelar()
    assert assistente._temporizador == 0
    assert GLib.MainContext.default().find_source_by_id(temporizador) is None


def test_fita_calibrada_aparece_como_calibrada(tmp_path, monkeypatch, schema):
    from cartridges.calibracao_janela import AssistenteDeCalibracao  # noqa: PLC0415

    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    puxada = calibracao.Calibracao(((-8, 1.0),) + ((0, 1.0),) * 5, (0, 0))
    session_fita.gravar_fitas(
        [
            session_fita.Fita("A", "eb0", "1", "k", calibracao=calibracao.para_json(puxada)),
            session_fita.Fita("B", "eb1", "2", "k"),
        ]
    )
    janela = AssistenteDeCalibracao(session_fita.fitas())
    assert janela.subtitulo_de("eb0") == "Calibrado"
    assert janela.subtitulo_de("eb1") == ""


def test_intensidade_acima_de_100_muda_a_referencia(assistente):
    """A referência não pode estar no máximo de saturação: aí aumentar a
    intensidade não muda nada na parede, e o valor é gravado sem ser visto."""
    from cartridges.calibracao_janela import _cor_da_etapa  # noqa: PLC0415

    referencia = _cor_da_etapa(0)
    assistente.escolher("eb0")
    assistente.mudar_intensidade(1.3)
    corrigida = calibracao.corrigir(referencia, assistente.calibracoes["eb0"])
    assert corrigida.saturacao > referencia.saturacao


def test_voltar_aos_ajustes_para_o_teste_e_guarda_os_ajustes(assistente):
    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    assistente.testar()
    assistente.voltar_aos_ajustes()
    assert assistente.pagina() == "inicio"
    assert assistente._temporizador == 0
    assert assistente.calibracoes["eb0"].cores[0] == (-8, 1.0)
    assert all(fita.calibracao is None for fita in session_fita.fitas())  # nada gravado


def test_escolher_depois_do_teste_comeca_do_inicio(assistente):
    assistente.escolher("eb0")
    assistente.testar()
    assistente.avancar_teste()
    assistente.avancar_teste()
    assistente.voltar_aos_ajustes()
    assistente.escolher("eb1")
    assert assistente.etapa == 0


def test_voltar_do_fim_leva_ao_branco(assistente):
    assistente.escolher("eb0")
    for _ in range(7):
        assistente.proxima()
    assert assistente.pagina() == "fim"
    assistente.voltar_do_fim()
    assert assistente.pagina() == "etapa"
    assert assistente.etapa == 6


def test_todos_juntos_acende_todas_e_ajusta_todas(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assistente.escolher(TODOS)
    assert assistente.previas[-1][0] == "todas"
    assistente.mudar_tom(-8)
    assert assistente.calibracoes["eb0"].cores[0] == (-8, 1.0)
    assert assistente.calibracoes["eb1"].cores[0] == (-8, 1.0)
    assert assistente.previas[-1][0] == "todas"


def test_todos_juntos_vai_do_branco_direto_ao_teste(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assistente.escolher(TODOS)
    for _ in range(7):
        assistente.proxima()
    assert assistente.pagina() == "teste"


def test_todos_juntos_parte_da_calibracao_comum_ou_do_neutro(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    puxada = calibracao.Calibracao(((-8, 1.0),) + ((0, 1.0),) * 5, (0, 0))
    assistente.calibracoes = {"eb0": puxada, "eb1": puxada}
    assistente.escolher(TODOS)
    assert assistente.calibracoes["eb1"] == puxada
    assistente.anterior()
    assistente.calibracoes = {"eb0": puxada, "eb1": NEUTRA}
    assistente.escolher(TODOS)
    assert assistente.calibracoes == {"eb0": NEUTRA, "eb1": NEUTRA}


def test_aplicar_tambem_nao_oferece_a_ja_calibrada_na_sessao(assistente):
    assistente.escolher("eb0")
    for _ in range(7):
        assistente.proxima()
    assert set(assistente._marcadas) == {"eb1"}
    assistente.calibrar_outro()
    assistente.escolher("eb1")
    for _ in range(7):
        assistente.proxima()
    assert assistente._marcadas == {}
    assert not assistente._grupo_do_fim.get_visible()


def test_lista_comeca_com_todos_os_dispositivos(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assert TODOS in assistente._linhas_do_inicio
