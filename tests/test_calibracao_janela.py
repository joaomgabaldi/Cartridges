# test_calibracao_janela.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O assistente de calibração: o que ele mostra nas fitas, o que grava e
quando."""

import subprocess
import sys
from pathlib import Path

import pytest

from cartridges import shared
from cartridges.utils import calibracao, session_fita
from cartridges.calibracao_janela import PAGINAS_DA_CALIBRACAO, SATURACAO_DA_REFERENCIA
from cartridges.utils.calibracao import NEUTRA


@pytest.fixture
def assistente(app_qt, tmp_path, monkeypatch, schema):  # noqa: ARG001
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
    yield janela
    # O assistente que sobra deixa o temporizador do teste vivo: ele
    # dispararia nos testes seguintes, já sem a prévia espionada, e a prévia
    # de verdade ficaria "em andamento" no estado global do session_fita.
    # Encerrar aqui, com a espionagem ainda no lugar, para o temporizador e
    # manda a última prévia para o espião.
    janela._encerrar()


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


def test_navegacao_vai_do_inicio_ao_teste(assistente):
    """Depois do Branco vem o teste, direto: não há mais "Aplicar esta
    calibração também a" — para fitas iguais, há "Todos os dispositivos"."""
    assistente.escolher("eb0")
    assistente.anterior()
    assert assistente.pagina() == "inicio"
    assistente.escolher("eb0")
    for _ in range(7):
        assistente.proxima()
    assert assistente.pagina() == "teste"
    assert "fim" not in PAGINAS_DA_CALIBRACAO


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


def test_testar_passa_pelas_cores_em_todas_e_para_ao_fechar(assistente, flush_idle):
    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    assistente.testar()
    tipo, cor, calibracoes = assistente.previas[-1]
    assert tipo == "todas" and (cor.matiz, cor.saturacao) == (0, SATURACAO_DA_REFERENCIA)
    assert calibracoes["eb0"].cores[0] == (-8, 1.0)
    assistente.avancar_teste()
    assert assistente.previas[-1][1].matiz == 60
    assert assistente._temporizador is not None
    assistente.cancelar()
    assert assistente._temporizador is None
    # O intervalo do teste é de 3 s: depois de 4 s, nenhuma prévia nova.
    quantas = len(assistente.previas)
    flush_idle(4)
    assert len(assistente.previas) == quantas


def test_fita_calibrada_aparece_como_calibrada(app_qt, tmp_path, monkeypatch, schema):  # noqa: ARG001
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
    assert assistente._temporizador is None
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


def test_todos_juntos_acende_todas_e_ajusta_cada_uma(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assistente.escolher(TODOS)
    assert assistente.pagina() == "etapa_todos"
    assert assistente.previas[-1][0] == "todas"
    assistente.mudar_tom(-8, "eb0")
    assistente.mudar_intensidade(1.2, "eb1")
    assert assistente.calibracoes["eb0"].cores[0] == (-8, 1.0)
    assert assistente.calibracoes["eb1"].cores[0] == (0, 1.2)
    tipo, _cor, calibracoes = assistente.previas[-1]
    assert tipo == "todas" and calibracoes["eb0"].cores[0] == (-8, 1.0)


def test_todos_juntos_tem_controles_de_cada_dispositivo(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assistente.escolher(TODOS)
    assert [c["id"] for c in assistente.controles] == ["eb0", "eb1"]
    assistente.mudarTom(12, "eb1")  # como se a pessoa arrastasse
    assert assistente.controles[1]["tom"] == 12
    assert assistente.calibracoes["eb1"].cores[0] == (12, 1.0)
    assert assistente.calibracoes["eb0"].cores[0] == (0, 1.0)


def test_todos_juntos_cada_um_parte_da_sua_calibracao(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    puxada = calibracao.Calibracao(((-8, 1.0),) + ((0, 1.0),) * 5, (0, 0))
    assistente.calibracoes = {"eb0": puxada, "eb1": NEUTRA}
    assistente.escolher(TODOS)
    assert assistente.calibracoes == {"eb0": puxada, "eb1": NEUTRA}
    assert assistente.controles[0]["tom"] == -8


def test_todos_juntos_restaurar_volta_a_etapa_de_todas(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assistente.escolher(TODOS)
    assistente.mudar_tom(-8, "eb0")
    assistente.mudar_tom(5, "eb1")
    assistente.restaurar()
    assert assistente.calibracoes == {"eb0": NEUTRA, "eb1": NEUTRA}


def test_todos_juntos_vai_do_branco_direto_ao_teste(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assistente.escolher(TODOS)
    for _ in range(6):
        assistente.proxima()
    assistente.mudar_temperatura(-1, "eb1")
    assert assistente.calibracoes["eb1"].branco == calibracao.branco_da_temperatura(-1)
    assert assistente.calibracoes["eb0"].branco == NEUTRA.branco
    assistente.proxima()
    assert assistente.pagina() == "teste"


def test_lista_comeca_com_todos_os_dispositivos(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assert [linha["id"] for linha in assistente.linhas] == [TODOS, "eb0", "eb1"]
    assert assistente.linhas[0]["nome"] == "Todos os dispositivos"
    assert assistente.linhas[0]["subtitulo"] == "Ajusta todos ao mesmo tempo, cada um com os seus controles"


def test_temperatura_de_volta_ao_centro_nao_conta_como_calibrada(assistente):
    assistente.escolher("eb0")
    for _ in range(6):
        assistente.proxima()  # Branco
    assistente.mudar_temperatura(-0.2)
    assistente.mudar_temperatura(0)
    assert assistente.calibracoes["eb0"] == NEUTRA
    assert assistente.subtitulo_de("eb0") == ""


def test_um_dispositivo_sozinho_e_depois_todos_grava_tudo(assistente):
    from cartridges.calibracao_janela import TODOS  # noqa: PLC0415

    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    for _ in range(7):
        assistente.proxima()
    assistente.voltar_aos_ajustes()
    assistente.escolher(TODOS)
    assistente.mudar_tom(5, "eb1")
    for _ in range(7):
        assistente.proxima()
    assistente.concluir()
    gravadas = {fita.id: calibracao.de_json(fita.calibracao) for fita in session_fita.fitas()}
    assert gravadas["eb0"].cores[0] == (-8, 1.0)
    assert gravadas["eb1"].cores[0] == (5, 1.0)


def test_com_um_dispositivo_so_nao_ha_todos(app_qt, tmp_path, monkeypatch, schema):  # noqa: ARG001
    from cartridges.calibracao_janela import TODOS, AssistenteDeCalibracao  # noqa: PLC0415

    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    session_fita.gravar_fitas([session_fita.Fita("A", "eb0", "1", "k")])
    janela = AssistenteDeCalibracao(session_fita.fitas())
    assert [linha["id"] for linha in janela.linhas] == ["eb0"]


def test_avancar_no_teste_reinicia_o_tempo(assistente):
    assistente.escolher("eb0")
    assistente.testar()
    antes = assistente._temporizador
    assistente.avancar_teste()
    assert assistente._temporizador is not None and assistente._temporizador is not antes


def test_da_lista_da_para_ir_direto_ao_teste(assistente):
    assistente.escolher("eb0")
    assistente.mudar_tom(-8)
    assistente.anterior()  # de volta à lista
    assert assistente.pagina() == "inicio"
    assistente.testar()
    assert assistente.pagina() == "teste"
    assert assistente.previas[-1][2]["eb0"].cores[0] == (-8, 1.0)


def test_voltar_a_lista_devolve_as_fitas_a_cor_do_app(assistente):
    assistente.escolher("eb0")
    assistente.testar()
    assistente.voltar_aos_ajustes()
    tipo, cor, _calibracoes = assistente.previas[-1]
    assert tipo == "todas" and cor == session_fita.cor_do_app()
    assistente.escolher("eb0")
    assistente.anterior()
    assert assistente.previas[-1][1] == session_fita.cor_do_app()


def test_controles_preenchidos_nao_contam_como_ajuste(assistente):
    """Carregar a etapa nos controles não é ajuste: só a prévia da etapa, nenhuma a mais."""
    assistente.escolher("eb0")
    assert len([p for p in assistente.previas if p[0] == "so"]) == 1
    assistente.proxima()
    assert len([p for p in assistente.previas if p[0] == "so"]) == 2
    # Enquanto a etapa preenche os controles, o que eles disserem é ignorado.
    antes = (len(assistente.previas), assistente.calibracoes["eb0"])
    assistente._carregando = True  # noqa: SLF001
    assistente.mudarTom(9, "eb0")
    assistente.mudarIntensidade(50, "eb0")
    assistente._carregando = False  # noqa: SLF001
    assert (len(assistente.previas), assistente.calibracoes["eb0"]) == antes


def test_cancelar_repetido_encerra_uma_vez(assistente):
    fechados = []
    assistente.fechado.connect(lambda: fechados.append(1))
    assistente.escolher("eb0")
    assistente.testar()
    assistente.cancelar()  # o Esc do QML chama o cancelar
    assistente.cancelar()
    assistente._encerrar()  # noqa: SLF001
    assert fechados == [1]
    voltas = [p for p in assistente.previas if p[0] == "todas" and p[1] == session_fita.cor_do_app()]
    assert len(voltas) == 1


def test_calibracao_na_tela_acompanha_a_etapa_e_o_teste(assistente):
    assistente.escolher("eb0")
    assert assistente.paginaAtual == "etapa"
    assert assistente.titulo == "Vermelho (1 de 7)"
    cor = assistente.corNaTela
    assert (cor.hsvHue(), cor.value()) == (0, 255)
    assert abs(cor.hsvSaturation() - SATURACAO_DA_REFERENCIA / 1000 * 255) <= 1
    assistente.testar()
    assert assistente.paginaAtual == "teste"
    assert assistente.titulo == "Vermelho"
    assert assistente.pausado is False
    assistente.pausar()
    assert assistente.pausado is True and assistente._temporizador is None  # noqa: SLF001
    assistente.pausar()
    assert assistente.pausado is False and assistente._temporizador is not None  # noqa: SLF001


def test_controles_do_branco_trazem_a_temperatura(assistente):
    assistente.escolher("eb0")
    assert assistente.controles[0]["branco"] is False
    for _ in range(6):
        assistente.proxima()
    assert assistente.controles[0]["branco"] is True
    assistente.mudar_temperatura(-1)
    assert assistente.controles[0]["temperatura"] == -100


def test_depois_de_encerrado_nada_religa_o_temporizador_nem_as_fitas(assistente):
    assistente.escolher("eb0")
    assistente.mudar_tom(-8)  # um ajuste que o Concluir gravaria
    assistente.cancelar()
    quantas = len(assistente.previas)
    assistente.testar()
    assistente.pausar()
    assistente.avancar_teste()
    assistente.proxima()
    assistente.restaurar()
    assistente.mudarTom(5, "eb0")
    assistente.escolher("eb1")
    assistente.voltar_aos_ajustes()
    assistente.concluir()  # depois do Cancelar não grava
    assert all(fita.calibracao is None for fita in session_fita.fitas())
    assert assistente._temporizador is None  # noqa: SLF001
    assert len(assistente.previas) == quantas
    assert assistente.paginaAtual == "etapa"


def test_faixas_dos_controles_vem_das_constantes(assistente):
    assert assistente.tomMaximo == calibracao.TOM_MAXIMO
    assert assistente.intensidadeMinima == round(calibracao.FATOR_MINIMO * 100)
    assert assistente.intensidadeMaxima == round(calibracao.FATOR_MAXIMO * 100)


# region Sem GTK


def test_calibracao_janela_sem_gi():
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; "
        "builtins.ngettext = lambda s, p, n: s if n == 1 else p; "
        "import cartridges.calibracao_janela; "
        "assert 'gi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", codigo], check=True, cwd=Path(__file__).resolve().parent.parent, timeout=60)


# endregion
