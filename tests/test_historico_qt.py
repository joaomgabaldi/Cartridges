# test_historico_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `HistoricoDeSessoes` e a geometria do gráfico: tudo o que a tela do histórico mostra, sem tela."""

from datetime import date, datetime, timedelta
from time import time

import pytest
from PIL import Image

from cartridges.jogo import Jogo
from cartridges.modelos import historico as modulo
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.session_history import dia_mais_perto, format_session_date, geometria_do_grafico, sem_lacunas_longas
from cartridges.utils import session_log


class _Loja:
    """O que o `HistoricoDeSessoes` pede à `Store`: achar o jogo."""

    def __init__(self, *jogos):
        self.por_id = {jogo.game_id: jogo for jogo in jogos}

    def get(self, game_id):
        return self.por_id.get(game_id)


def _jogo(playtime=5400):
    jogo = Jogo({"source": "imported", "game_id": "imported_1", "name": "Probe", "executable": "x.exe", "added": 0, "playtime": playtime})
    jogo.gravacoes = 0
    jogo.salvar.connect(lambda: setattr(jogo, "gravacoes", jogo.gravacoes + 1))
    return jogo


def _aberto(jogo=None):
    jogo = jogo or _jogo()
    historico = HistoricoDeSessoes(_Loja(jogo))
    historico.abrir(jogo.game_id)
    return historico, jogo


def _ts(*args):
    return int(datetime(*args).timestamp())


def _dias(inicio, jogados, total=None):
    """Dias seguidos a partir de `inicio`; os índices em `jogados` têm 60 s."""
    total = total or max(jogados) + 1
    return [(inicio + timedelta(days=i), 60 if i in jogados else 0) for i in range(total)]


def _logo_em_disco(jogo, monkeypatch, tmp_path, largura, altura):
    caminho = tmp_path / "logo.png"
    Image.new("RGBA", (largura, altura), "red").save(caminho)
    monkeypatch.setattr(modulo.game_logo, "cached_logo_path", lambda _jogo: caminho)


def test_uma_linha_por_sessao():
    jogo = _jogo()
    session_log.record(jogo.game_id, 3600, end=1_700_000_000)
    session_log.record(jogo.game_id, 1800, end=1_700_100_000)

    historico, _ = _aberto(jogo)

    sessoes = historico.sessoes
    assert len(sessoes) == 2
    # Mais recente primeiro, como a lista que a alimenta.
    assert sessoes[0]["titulo"] == "15 de novembro de 2023"
    assert sessoes[0]["subtitulo"] == f"Terminou às {datetime.fromtimestamp(1_700_100_000):%H:%M} · 30 min"
    assert (sessoes[0]["fim"], sessoes[0]["segundos"]) == (1_700_100_000, 1800)
    assert historico.aberto is True
    assert historico.nome == "Probe"
    assert historico.vazio is False


def test_mostrar_mais_de_cem_em_cem():
    jogo = _jogo()
    for indice in range(250):
        session_log.record(jogo.game_id, 60, 1_700_000_000 + indice * 100)

    historico, _ = _aberto(jogo)
    assert len(historico.sessoes) == 100
    assert historico.haMais is True
    historico.mostrarMais()
    assert len(historico.sessoes) == 200
    assert historico.haMais is True
    historico.mostrarMais()
    assert len(historico.sessoes) == 250
    assert historico.haMais is False


def test_resumo_dos_ultimos_dias():
    jogo = _jogo()
    session_log.record(jogo.game_id, 3600)

    historico, _ = _aberto(jogo)

    assert historico.resumo == "Últimos 7 dias: 1 hora · últimos 30 dias: 1 hora"


def test_sem_sessao_diz_nenhuma_e_esconde_as_colunas():
    """A biblioteca inteira antecede o histórico: a tela vazia é o estado normal no começo."""
    historico, _ = _aberto()

    assert historico.sessoes == []
    assert historico.resumo == "Nenhuma sessão registrada."
    assert historico.vazio is True
    assert historico.haMais is False
    assert historico.grafico == {}


@pytest.mark.parametrize(
    ("origem", "largura"),
    [
        # 5,2:1, como o do Dawnwalker: manda o teto de altura (120).
        ((2858, 552), 621),
        # 10:1: a altura de 120 daria 1200 de largura; manda a largura útil da caixa (1040 menos as margens de 24).
        ((4000, 400), 992),
    ],
)
def test_logo_no_lugar_do_titulo(monkeypatch, tmp_path, origem, largura):
    jogo = _jogo()
    _logo_em_disco(jogo, monkeypatch, tmp_path, *origem)

    historico, _ = _aberto(jogo)

    assert historico.logo.startswith("file:")
    assert historico.larguraDoLogo == largura


def test_sem_logo_o_nome():
    historico, _ = _aberto()

    assert historico.logo == ""
    assert historico.larguraDoLogo == 0
    assert historico.nome == "Probe"


def test_excluir_desconta_do_total():
    """O motivo de a tela existir: uma sessão que contou errado só podia ser corrigida editando o total à mão."""
    jogo = _jogo()
    session_log.record(jogo.game_id, 3600, end=1_700_000_000)
    session_log.record(jogo.game_id, 1800, end=1_700_100_000)
    historico, _ = _aberto(jogo)
    atualizacoes = []
    jogo.atualizado.connect(lambda: atualizacoes.append(1))

    historico.excluir(1_700_000_000, 3600)

    assert jogo.playtime == 1800
    assert len(historico.sessoes) == 1
    assert jogo.gravacoes == 1  # a ficha foi gravada
    assert atualizacoes == [1]  # e a página de detalhes avisada


def test_reabrir_sem_excluir_nao_muda_nada():
    """Fechar e reabrir não toca no total nem na ficha (o cancelamento da confirmação está em test_qml_historico.py)."""
    jogo = _jogo()
    session_log.record(jogo.game_id, 3600, end=1_700_000_000)

    historico, _ = _aberto(jogo)
    historico.fechar()
    historico.abrir(jogo.game_id)

    assert jogo.playtime == 5400
    assert len(historico.sessoes) == 1
    assert jogo.gravacoes == 0


def test_sessao_que_ja_sumiu_nao_desconta():
    """A linha sumiu entre abrir a tela e confirmar: descontar deixaria o total menor que a soma do que sobrou."""
    jogo = _jogo()
    session_log.record(jogo.game_id, 3600, end=1_700_000_000)
    historico, _ = _aberto(jogo)

    session_log.delete(jogo.game_id, 1_700_000_000, 3600)
    historico.excluir(1_700_000_000, 3600)

    assert jogo.playtime == 5400
    assert jogo.gravacoes == 0
    assert historico.sessoes == []
    assert historico.vazio is True


def test_total_nunca_fica_negativo():
    """Um total menor que a sessão só acontece com um registro editado à mão: o certo é zerar."""
    jogo = _jogo(playtime=600)
    session_log.record(jogo.game_id, 3600, end=1_700_000_000)
    historico, _ = _aberto(jogo)

    historico.excluir(1_700_000_000, 3600)

    assert jogo.playtime == 0


def test_periodo_comeca_no_mes_e_segue_a_escolha():
    jogo = _jogo()
    session_log.record(jogo.game_id, 3600)
    # Uma sessão antiga também: sem ela, a única sessão (de hoje) seria a primeira já registrada, e o corte de dias
    # vazios reduziria a faixa a 1 dia; o que este teste verifica é a troca de período.
    session_log.record(jogo.game_id, 60, end=int(time()) - 100 * 86400)

    historico, _ = _aberto(jogo)

    assert historico.periodo == "month"
    assert len(historico.grafico["horas"]) == 30
    assert historico.totalDoPeriodo == "1 hora no período"
    historico.definirPeriodo("week")
    assert historico.periodo == "week"
    assert len(historico.grafico["horas"]) == 7
    historico.definirPeriodo("all")
    assert historico.periodo == "all"
    historico.definirPeriodo("ano")  # nome que não existe: ignorado
    assert historico.periodo == "all"
    # Reabrir recomeça no mês.
    historico.fechar()
    historico.abrir(jogo.game_id)
    assert historico.periodo == "month"


def test_quebras_so_em_todo_o_periodo():
    """O jogo zerado há duas semanas não ganha um dia vazio por dia que passa, e "Todo o período" corta a pausa de um ano."""
    jogo = _jogo()
    ultimo = date.today() - timedelta(days=14)
    for dia in (ultimo - timedelta(days=400), ultimo - timedelta(days=399), ultimo):
        fim = int(datetime.combine(dia, datetime.min.time()).timestamp()) + 20 * 3600
        session_log.record(jogo.game_id, 3600, end=fim)
    historico, _ = _aberto(jogo)

    historico.definirPeriodo("all")
    assert len(historico.grafico["quebras"]) == 1
    assert len(historico.grafico["horas"]) < 10
    assert historico.totalDoPeriodo == "3 horas no período"

    historico.definirPeriodo("month")
    assert historico.grafico["quebras"] == []
    assert len(historico.grafico["horas"]) == 30
    # O mês termina no último dia jogado: o gráfico mostra o dia 14 atrás com 1 hora.
    assert historico.grafico["horas"][-1] == 1.0


def test_dica_do_dia_mais_perto():
    jogo = _jogo()
    ontem = date.today() - timedelta(days=1)
    session_log.record(jogo.game_id, 3600, end=int(datetime.combine(ontem, datetime.min.time()).timestamp()) + 20 * 3600)
    session_log.record(jogo.game_id, 600, end=int(datetime.combine(date.today(), datetime.min.time()).timestamp()) + 3600)
    historico, _ = _aberto(jogo)
    historico.definirPeriodo("week")

    # Só dois dias na faixa: os dois extremos.
    assert historico.dica(0.0) == f"{format_session_date(_ts(ontem.year, ontem.month, ontem.day))}: 1 hora"
    assert historico.dica(1.0).endswith(": 10 min")
    # Fora do gráfico vale a ponta mais perto.
    assert historico.dica(-3.0) == historico.dica(0.0)
    assert historico.dica(7.0) == historico.dica(1.0)


def test_dica_sem_sessao_e_vazia():
    historico, _ = _aberto()

    assert historico.dica(0.5) == ""


def test_fechar_limpa_e_abrir_jogo_que_nao_existe_nao_abre():
    historico, _ = _aberto()
    historico.fechar()
    assert historico.aberto is False

    historico.abrir("nao_existe")
    assert historico.aberto is False


def test_nome_com_marcacao_chega_inteiro():
    jogo = _jogo()
    jogo.name = "A & B <i>itálico</i>"
    historico, _ = _aberto(jogo)

    assert historico.nome == "A & B <i>itálico</i>"


def test_geometria_vazia():
    assert geometria_do_grafico([], frozenset()) == {}


def test_geometria_da_grade_e_do_topo():
    # Um dia de 1,5 h: o passo é 0,5 (no máximo 4 linhas) e o topo, 1,5.
    dias = [(date(2026, 9, 1), 5400), (date(2026, 9, 2), 0)]

    geometria = geometria_do_grafico(dias, frozenset())

    assert geometria["horas"] == [1.5, 0.0]
    assert geometria["passo"] == 0.5
    assert geometria["topo"] == 1.5
    assert geometria["grade"] == [[0.0, "0 h"], [0.5, "0,5 h"], [1.0, "1 h"], [1.5, "1,5 h"]]
    assert geometria["posicoes"] == [0, 1]


def test_quebra_ocupa_mais_que_um_dia_e_o_mes_depois_dela_tem_rotulo():
    dias, quebras = sem_lacunas_longas(_dias(date(2025, 9, 15), {0, 1, 40, 41, 400}, 401))

    geometria = geometria_do_grafico(dias, quebras)

    posicoes = geometria["posicoes"]
    assert geometria["quebras"] == sorted(quebras)
    for i in quebras:
        assert posicoes[i + 1] - posicoes[i] == 2
    assert posicoes == sorted(posicoes)
    # Mais de dois meses: rótulo por mês, um por mês, inclusive o que só sobrou depois de uma quebra.
    textos = [texto for _i, texto, _a in geometria["rotulos"]]
    assert len(textos) == len(set(textos))
    assert "out 26" in textos


def test_meses_dos_dois_lados_da_quebra_nao_se_sobrepoem():
    """Parado de out/25 a set/26: o último dia vazio antes da volta é 30/09 e o primeiro jogado, 1º/10. Fica o do dia 1º."""
    inicio = date(2025, 10, 1)
    volta = (date(2026, 10, 1) - inicio).days
    jogados = set(range(0, 20, 2)) | set(range(volta, volta + 12))
    dias, quebras = sem_lacunas_longas(_dias(inicio, jogados, volta + 12))

    geometria = geometria_do_grafico(dias, quebras)

    assert [texto for _i, texto, _a in geometria["rotulos"]] == ["out 25", "out 26"]


def test_eixo_x_rotula_o_primeiro_e_o_ultimo_dia_sem_aglomerar():
    for total in (1, 2, 7, 30, 31, 61):
        dias = [(date(2026, 1, 1) + timedelta(days=i), 0) for i in range(total)]
        rotulos = geometria_do_grafico(dias, frozenset())["rotulos"]
        indices = [i for i, _t, _a in rotulos]
        assert indices[0] == 0 and indices[-1] == total - 1
        assert len(indices) <= 7
        assert indices == sorted(set(indices))
        # As pontas alinham para dentro (começo e fim do texto); o miolo, ao centro; um só dia, ao centro.
        alinhamentos = [a for _i, _t, a in rotulos]
        if total == 1:
            assert alinhamentos == [0.5]
        else:
            assert alinhamentos[0] == 0.0 and alinhamentos[-1] == 1.0
            assert set(alinhamentos[1:-1]) <= {0.5}

    # Por mês: só dias 1º, então nenhum mês aparece duas vezes.
    dias = [(date(2026, 1, 15) + timedelta(days=i), 0) for i in range(400)]
    rotulos = geometria_do_grafico(dias, frozenset())["rotulos"]
    assert all(dias[i][0].day == 1 for i, _t, _a in rotulos)
    textos = [t for _i, t, _a in rotulos]
    assert len(textos) == len(set(textos)) <= 7


def test_rotulo_por_dia_e_por_mes():
    curto = [(date(2026, 9, 12) + timedelta(days=i), 0) for i in range(3)]
    assert [t for _i, t, _a in geometria_do_grafico(curto, frozenset())["rotulos"]] == ["12/09", "13/09", "14/09"]
    longo = [(date(2026, 1, 1) + timedelta(days=i), 0) for i in range(100)]
    assert geometria_do_grafico(longo, frozenset())["rotulos"][0][1] == "jan 26"


def test_dia_mais_perto_e_o_inverso_do_eixo():
    posicoes = [0, 1, 2, 4, 5]  # uma quebra entre o 3º e o 4º dia

    assert dia_mais_perto(posicoes, 0.0) == 0
    assert dia_mais_perto(posicoes, 1.0) == 4
    assert dia_mais_perto(posicoes, 2 / 5) == 2
    assert dia_mais_perto(posicoes, 0.69) == 3  # 3,45 está mais perto do 4 que do 2
    assert dia_mais_perto(posicoes, 0.59) == 2
    assert dia_mais_perto(posicoes, -9.0) == 0
    assert dia_mais_perto(posicoes, 9.0) == 4
    assert dia_mais_perto([0], 0.5) == 0
    assert dia_mais_perto([], 0.5) == 0


def test_excluir_com_fim_depois_de_2038():
    """O carimbo passa de 2^31: o slot tem de aceitar um inteiro de 64 bits."""
    jogo = _jogo()
    fim = 2**31 + 5
    session_log.record(jogo.game_id, 3600, end=fim)
    historico, _ = _aberto(jogo)

    # O QML chama pelo slot: o carimbo tem de ser um qint64 (um `int` do Qt estoura em 2038).
    meta = historico.metaObject()
    assert meta.indexOfMethod("excluir(qlonglong,qlonglong)") >= 0
    historico.excluir(fim, 3600)

    assert jogo.playtime == 1800
    assert historico.sessoes == []


def test_dica_e_mostrar_mais_na_saida_nao_esvaziam_o_que_esta_a_vista():
    """Nos 120 ms de saída o cartão ainda aparece: a dica do gráfico continua e "Mostrar mais" não esvazia a tabela."""
    jogo = _jogo()
    for n in range(modulo.PAGINA + 5):
        session_log.record(jogo.game_id, 60, end=1_700_000_000 + n * 86400)
    historico, _ = _aberto(jogo)
    dica = historico.dica(0.5)
    assert dica != ""
    antes = len(historico.sessoes)

    historico.fechar()
    historico.mostrarMais()

    assert historico.dica(0.5) == dica
    assert len(historico.sessoes) >= antes


def _contar(historico):
    contagem = {"alterado": 0, "tabelaMudou": 0, "graficoMudou": 0}
    for nome in contagem:
        getattr(historico, nome).connect(lambda nome=nome: contagem.__setitem__(nome, contagem[nome] + 1))
    return contagem


def test_trocar_o_periodo_nao_renotifica_as_sessoes():
    jogo = _jogo()
    session_log.record(jogo.game_id, 3600, end=int(time()))
    historico, _ = _aberto(jogo)
    contagem = _contar(historico)

    historico.definirPeriodo("week")

    assert contagem == {"alterado": 0, "tabelaMudou": 0, "graficoMudou": 1}
    assert historico.periodo == "week"


def test_mostrar_mais_nao_renotifica_o_grafico():
    jogo = _jogo()
    for i in range(modulo.PAGINA + 5):
        session_log.record(jogo.game_id, 60, end=int(time()) - i * 60)
    historico, _ = _aberto(jogo)
    contagem = _contar(historico)

    historico.mostrarMais()

    assert contagem == {"alterado": 0, "tabelaMudou": 1, "graficoMudou": 0}
    assert len(historico.sessoes) == modulo.PAGINA + 5


def test_fechar_so_avisa_o_aberto_e_guarda_o_conteudo_para_a_animacao_de_saida():
    jogo = _jogo()
    session_log.record(jogo.game_id, 3600, end=int(time()))
    historico, _ = _aberto(jogo)
    contagem = _contar(historico)

    historico.fechar()

    # Só `aberto` muda: o cartão sai com o conteúdo intacto.
    assert contagem == {"alterado": 1, "tabelaMudou": 0, "graficoMudou": 0}
    assert historico.aberto is False and historico.nome == jogo.name and len(historico.sessoes) == 1
