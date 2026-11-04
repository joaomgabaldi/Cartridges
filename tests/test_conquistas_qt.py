# test_conquistas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O cartão da página do jogo e a lista de conquistas, sem tela: as puras e o `ConquistasDoJogo` (D58, D62)."""

import gc
import logging
import time
import weakref
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QImage

from cartridges import shared
from cartridges.conquistas import catalogo, historico, icones, progresso
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.xbox import conta
from cartridges.jogo import Jogo
from cartridges.modelos import conquistas as modulo
from cartridges.modelos.conquistas import ConquistasDoJogo, cartao_da_pagina, data_por_extenso, fileira, icone
from tests.apoio_conquistas import com_fonte
from tests.apoio_conquistas_qt import _Detalhes, _jogo

CAT = Catalogo(
    (
        ConquistaInfo("A", "Primeira", "Faça algo.", "", "", False, 55.0),
        ConquistaInfo("B", "Rara", "Difícil.", "", "", False, 4.1),
        ConquistaInfo("C", "Segredo", "Spoiler.", "", "", True, 20.0),
    ),
    0,
    True,
)


@pytest.fixture(autouse=True)
def pedidos(monkeypatch):
    """No lugar do `icones.carregar` de verdade: anota (origem, entregar) e nunca baixa nada."""
    anotados = []
    monkeypatch.setattr(icones, "carregar", lambda origem, entregar: anotados.append((origem, entregar)))
    return anotados


@pytest.fixture
def tela():
    """O modelo ligado a um jogo com 2 de 3 conquistas (a oculta ainda bloqueada), com a página nele."""
    jogo = _jogo()
    catalogo.guardar("570", CAT)
    historico.registrar(jogo.game_id, [Desbloqueio("A", 100), Desbloqueio("B", 200)])
    com_fonte(jogo, "steam:570")
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    return SimpleNamespace(jogo=jogo, detalhes=detalhes, modelo=modelo)


def _titulos(linhas):
    return [linha["titulo"] for linha in linhas]


def _catalogo_de(*infos):
    return Catalogo(tuple(infos), 0, True)


# -- o cartão da página -----------------------------------------------------------------------


def test_cartao_mostra_o_progresso(tela):
    pagina = tela.modelo.pagina
    assert pagina["visivel"] is True
    assert pagina["contagem"] == "2 de 3"
    assert pagina["porcentagem"] == "66%"  # para baixo
    assert pagina["fracao"] == pytest.approx(2 / 3)
    assert pagina["resto"] == ""


def test_cartao_nao_arredonda_para_cima_ate_o_fim():
    """999 de 1000 é 99%: 100% só quando está tudo desbloqueado."""
    jogo = _jogo()
    catalogo.guardar("570", _catalogo_de(*(ConquistaInfo(f"N{n}", f"N{n}", "", "", "", False) for n in range(1000))))
    historico.registrar(jogo.game_id, [Desbloqueio(f"N{n}", 1) for n in range(999)])
    com_fonte(jogo, "steam:570")
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    assert modelo.pagina["contagem"] == "999 de 1000"
    assert modelo.pagina["porcentagem"] == "99%"

    historico.registrar(jogo.game_id, [Desbloqueio("N999", 1)])
    modelo.mudou(jogo.game_id)
    assert modelo.pagina["porcentagem"] == "100%"


def test_cartao_some_sem_catalogo_ou_desligado(tela):
    tela.jogo.conquistas = False
    tela.detalhes.alterado.emit()
    assert tela.modelo.pagina["visivel"] is False

    sem_catalogo = _jogo(2)
    tela.detalhes.loja.por_id[sem_catalogo.game_id] = sem_catalogo
    com_fonte(sem_catalogo, "steam:999")
    tela.detalhes.mostrar(sem_catalogo.game_id)
    assert tela.modelo.pagina["visivel"] is False


def test_historico_antigo_sem_fonte_fica_oculto_ate_a_varredura():
    jogo = _jogo()
    catalogo.guardar("570", CAT)
    historico.registrar(jogo.game_id, [Desbloqueio("A", 1)])
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    assert modelo.pagina["visivel"] is False
    com_fonte(jogo, "steam:570")
    modelo.mudou(jogo.game_id)
    assert modelo.pagina["visivel"] is True


def test_xbox_some_ao_sair_da_conta(monkeypatch):
    jogo = _jogo()
    catalogo.guardar("xbox-7", CAT)
    com_fonte(jogo, "xbox:7")
    monkeypatch.setattr(conta, "conectada", lambda: True)
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    assert modelo.pagina["visivel"] is True
    monkeypatch.setattr(conta, "conectada", lambda: False)
    modelo.mudou(None)
    assert modelo.pagina["visivel"] is False


def test_fonte_gravada_manda_mais_que_o_appid_atual():
    jogo = _jogo(steam_appid="999")
    catalogo.guardar("570", CAT)
    com_fonte(jogo, "steam:570")
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    assert modelo.pagina["visivel"] is True


def test_quatro_icones_e_o_resto(pedidos):
    jogo = _jogo()
    infos = [ConquistaInfo(f"N{n}", f"N{n}", "", f"https://x/{n}.png", "", False) for n in range(6)]
    catalogo.guardar("570", _catalogo_de(*infos))
    historico.registrar(jogo.game_id, [Desbloqueio(f"N{n}", n + 1) for n in range(6)])
    com_fonte(jogo, "steam:570")
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    assert len(modelo.pagina["icones"]) == 4
    assert modelo.pagina["resto"] == "+2"
    # Só os 4 ícones mais recentes, que são os que a página mostra, são pedidos (a ordem do pedido não importa).
    assert sorted(origem for origem, _entregar in pedidos) == [f"https://x/{n}.png" for n in (2, 3, 4, 5)]


def test_cartao_sem_conquistas_e_vazio():
    assert cartao_da_pagina(None, {}) == {
        "visivel": False, "contagem": "", "porcentagem": "", "fracao": 0.0, "icones": [], "resto": "",
    }  # fmt: skip


# -- a lista ----------------------------------------------------------------------------------


def test_lista_em_duas_secoes(tela):
    tela.modelo.abrir(tela.jogo.game_id)
    modelo = tela.modelo
    assert modelo.aberto is True
    assert modelo.nome == "Jogo 1"
    assert modelo.resumo == "2 de 3 conquistas desbloqueadas"
    assert modelo.fracao == pytest.approx(2 / 3)
    assert _titulos(modelo.desbloqueadas) == ["Rara", "Primeira"]  # recente primeiro
    assert _titulos(modelo.bloqueadas) == ["Conquista oculta"]
    assert modelo.bloqueadas[0]["subtitulo"] == "Os detalhes aparecem depois do desbloqueio."
    assert modelo.bloqueadas[0]["icone"]["oculta"] is True
    assert modelo.bloqueadas[0]["desbloqueada"] is False


def test_ocultas_reveladas_pela_preferencia(tela, schema):
    tela.modelo.abrir(tela.jogo.game_id)
    schema.set_boolean("conquistas-mostrar-ocultas", True)
    # D14: a lista aberta é o retrato de quando abriu; a preferência vale na abertura seguinte.
    assert _titulos(tela.modelo.bloqueadas) == ["Conquista oculta"]
    assert tela.modelo.bloqueadas[0]["icone"]["oculta"] is True
    tela.modelo.fechar()
    tela.modelo.abrir(tela.jogo.game_id)
    assert _titulos(tela.modelo.bloqueadas) == ["Segredo"]
    assert tela.modelo.bloqueadas[0]["icone"]["oculta"] is False


def test_oculta_desbloqueada_aparece_sempre(tela):
    historico.registrar(tela.jogo.game_id, [Desbloqueio("C", 300)])
    tela.modelo.abrir(tela.jogo.game_id)
    assert _titulos(tela.modelo.desbloqueadas) == ["Segredo", "Rara", "Primeira"]
    assert tela.modelo.bloqueadas == []


def test_bloqueada_sem_icone_cinza_usa_o_icone_apagado(pedidos, monkeypatch):
    jogo = _jogo()
    catalogo.guardar("xbox-7", Catalogo((ConquistaInfo("XBOX:1", "T", "D", "https://x/1.png", "", False),), 0, False))
    com_fonte(jogo, "xbox:7")
    monkeypatch.setattr(conta, "conectada", lambda: True)
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    modelo.abrir(jogo.game_id)
    assert [origem for origem, _e in pedidos] == ["https://x/1.png"]
    assert modelo.bloqueadas[0]["icone"]["cinza"] is True


def test_bloqueada_com_icone_cinza_nao_ganha_filtro(pedidos):
    jogo = _jogo()
    catalogo.guardar(
        "570", Catalogo((ConquistaInfo("A", "T", "D", "https://x/cor.png", "https://x/cinza.png", False),), 0, False)
    )
    com_fonte(jogo, "steam:570")
    modelo = ConquistasDoJogo(_Detalhes(jogo))
    modelo.abrir(jogo.game_id)
    assert [origem for origem, _e in pedidos] == ["https://x/cinza.png"]
    assert modelo.bloqueadas[0]["icone"]["cinza"] is False


def test_data_da_conquista_comeca_com_maiuscula(tela):
    assert data_por_extenso(int(time.time())) == "Hoje"
    assert data_por_extenso(int(time.time()) - 86400) == "Ontem"
    assert data_por_extenso(2**62) is None

    historico.registrar(tela.jogo.game_id, [Desbloqueio("C", int(time.time()))])
    tela.modelo.abrir(tela.jogo.game_id)
    datas = [linha["data"] for linha in tela.modelo.desbloqueadas]
    assert "Hoje" in datas
    assert "hoje" not in datas


@pytest.mark.parametrize("quando", [2**62, -(2**62), -1, 2**63 - 1, -(2**63)])
def test_data_absurda_nao_derruba_a_lista(tela, quando):
    historico.registrar(tela.jogo.game_id, [Desbloqueio("C", quando)])
    tela.modelo.abrir(tela.jogo.game_id)
    assert "Segredo" in _titulos(tela.modelo.desbloqueadas)


def test_rara_leva_a_estrela_e_a_virgula():
    rara = progresso.Linha(ConquistaInfo("B", "Rara", "", "", "", False, 4.1), 5)
    comum = progresso.Linha(ConquistaInfo("A", "Comum", "", "", "", False, 55.0), 5)
    sem = progresso.Linha(ConquistaInfo("S", "Sem", "", "", "", False, None), None)
    assert fileira(rara, False, {})["porcentagem"] == "★ 4,1%"
    assert fileira(rara, False, {})["rara"] is True
    assert fileira(comum, False, {})["porcentagem"] == "55,0%"
    assert fileira(comum, False, {})["rara"] is False
    assert fileira(sem, False, {})["porcentagem"] == ""


def test_dica_do_icone_troca_a_quebra_de_linha():
    linha = progresso.Linha(ConquistaInfo("A", "A & B", "Descrição.", "", "", False, 3.8), 1)
    dica = icone(linha, False, {})["dica"]
    assert "\n" not in dica
    assert dica == "<b>A &amp; B</b><br>Descrição.<br>3,8% dos jogadores"


def test_logo_ou_nome_no_dialogo(tela, monkeypatch, tmp_path):
    tela.modelo.abrir(tela.jogo.game_id)
    assert (tela.modelo.logo, tela.modelo.larguraDoLogo) == ("", 0)
    assert tela.modelo.nome == "Jogo 1"

    imagem = QImage(2858, 552, QImage.Format.Format_ARGB32)
    imagem.fill(QColor("red"))
    assert imagem.save(str(tmp_path / "logo.png"), "PNG")
    monkeypatch.setattr(modulo.game_logo, "cached_logo_path", lambda _jogo: tmp_path / "logo.png")
    tela.modelo.abrir(tela.jogo.game_id)
    assert tela.modelo.logo.startswith("file:///")
    assert tela.modelo.larguraDoLogo == 472
    assert tela.modelo.nome == "Jogo 1"  # o nome segue: o QML mostra só um dos dois

    tela.modelo.fechar()
    # Fecha sem esvaziar: o cartão não encolhe durante a animação de saída.
    assert (tela.modelo.aberto, tela.modelo.nome) == (False, "Jogo 1")
    assert tela.modelo.logo.startswith("file:///")


def test_abrir_jogo_desconhecido_ou_sem_cartao_nao_abre(tela):
    tela.modelo.abrir("imported_99")
    assert tela.modelo.aberto is False
    tela.jogo.conquistas = False
    tela.modelo.abrir(tela.jogo.game_id)
    assert tela.modelo.aberto is False


# -- os ícones --------------------------------------------------------------------------------


def _com_icones(numero, prefixo, quantos=1, **extra):
    jogo = _jogo(numero, **extra)
    infos = [ConquistaInfo(f"N{n}", f"N{n}", "", f"https://x/{prefixo}{n}.png", "", False) for n in range(quantos)]
    catalogo.guardar(f"90{numero}", _catalogo_de(*infos))
    historico.registrar(jogo.game_id, [Desbloqueio(f"N{n}", n + 1) for n in range(quantos)])
    com_fonte(jogo, f"steam:90{numero}")
    return jogo


def _arquivo_de_icone(tmp_path, nome="a.png"):
    imagem = QImage(8, 8, QImage.Format.Format_ARGB32)
    imagem.fill(QColor("red"))
    assert imagem.save(str(tmp_path / nome), "PNG")
    return tmp_path / nome


def test_icone_chega_e_a_pagina_atualiza(pedidos, tmp_path, flush_idle):
    jogo = _com_icones(1, "a")
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    avisos = []
    modelo.alterado.connect(lambda: avisos.append(1))
    detalhes.mostrar(jogo.game_id)
    assert modelo.pagina["icones"][0]["url"] == ""
    avisos.clear()

    (origem, entregar), = pedidos
    entregar(_arquivo_de_icone(tmp_path))
    flush_idle(0.3)

    assert modelo.pagina["icones"][0]["url"].startswith("file:///")
    assert modelo.pagina["icones"][0]["url"].endswith("a.png")
    assert avisos
    assert origem == "https://x/a0.png"


def test_icone_de_outro_jogo_nao_troca_a_pagina(pedidos, tmp_path, flush_idle):
    um, dois = _com_icones(1, "a"), _com_icones(2, "b")
    detalhes = _Detalhes(um, dois)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(um.game_id)
    detalhes.mostrar(dois.game_id)
    entregas = dict(pedidos)
    avisos = []
    modelo.alterado.connect(lambda: avisos.append(1))

    entregas["https://x/a0.png"](_arquivo_de_icone(tmp_path))
    flush_idle(0.3)

    # A página já é do outro jogo: a URL fica guardada e a vista não muda (nem avisa).
    assert avisos == []
    assert modelo.pagina["icones"][0]["url"] == ""
    assert modelo._urls["https://x/a0.png"].endswith("a.png")  # noqa: SLF001
    # E voltando ao primeiro, o ícone já está lá sem novo pedido.
    pedidos.clear()
    detalhes.mostrar(um.game_id)
    assert modelo.pagina["icones"][0]["url"].endswith("a.png")
    assert pedidos == []


def test_mesma_origem_pedida_uma_vez(pedidos):
    jogo = _jogo()
    infos = [ConquistaInfo(f"N{n}", f"N{n}", "", "https://x/igual.png", "", False) for n in range(3)]
    catalogo.guardar("570", _catalogo_de(*infos))
    historico.registrar(jogo.game_id, [Desbloqueio(f"N{n}", n + 1) for n in range(3)])
    com_fonte(jogo, "steam:570")
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)  # a página usa as três
    modelo.abrir(jogo.game_id)  # e o diálogo, as mesmas
    modelo.mudou(None)
    assert [origem for origem, _e in pedidos] == ["https://x/igual.png"]


def test_varios_icones_refazem_a_vista_uma_vez(pedidos, tmp_path, flush_idle):
    jogo = _com_icones(1, "a", quantos=3)
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    avisos = []
    modelo.alterado.connect(lambda: avisos.append(1))

    for origem, entregar in pedidos:
        entregar(_arquivo_de_icone(tmp_path, origem.rsplit("/", 1)[1]))
    flush_idle(0.3)

    # Os mais recentes primeiro: N2, N1, N0.
    assert [i["url"].rsplit("/", 1)[1] for i in modelo.pagina["icones"]] == ["a2.png", "a1.png", "a0.png"]
    assert len(avisos) == 1


def test_icone_que_chega_depois_do_fechamento_nao_levanta(pedidos, tmp_path):
    jogo = _com_icones(1, "a")
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    (_origem, entregar), = pedidos
    ref = weakref.ref(modelo)
    del modelo, detalhes
    gc.collect()
    assert ref() is None  # o modelo morreu de verdade
    entregar(_arquivo_de_icone(tmp_path))  # a referência fraca não chega a nada


def test_icone_que_nao_chegou_e_pedido_de_novo_depois_da_espera(pedidos, monkeypatch):
    relogio = [1000.0]
    monkeypatch.setattr(modulo, "_agora", lambda: relogio[0])
    jogo = _com_icones(1, "a")
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    detalhes.mostrar(jogo.game_id)
    assert len(pedidos) == 1

    relogio[0] += modulo.ESPERA_DO_ICONE - 1  # ainda a caminho: nada de pedido repetido
    modelo.mudou(None)
    assert len(pedidos) == 1

    relogio[0] += 2  # passou da espera: o download falhou, pede de novo (uma vez)
    modelo.mudou(None)
    modelo.mudou(None)
    assert [origem for origem, _e in pedidos] == ["https://x/a0.png"] * 2


# -- quem avisa -------------------------------------------------------------------------------


def test_mudou_de_outro_jogo_nao_refaz(tela, monkeypatch):
    chamadas = []
    original = progresso.do_jogo
    monkeypatch.setattr(progresso, "do_jogo", lambda jogo: chamadas.append(jogo.game_id) or original(jogo))

    tela.modelo.mudou("imported_99")
    assert chamadas == []
    tela.modelo.mudou(tela.jogo.game_id)
    assert chamadas == [tela.jogo.game_id]
    tela.modelo.mudou(None)
    assert chamadas == [tela.jogo.game_id] * 2


def test_mudou_de_outra_thread_chega_na_principal(tela, flush_idle):
    import threading  # noqa: PLC0415

    historico.registrar(tela.jogo.game_id, [Desbloqueio("C", 300)])
    thread = threading.Thread(target=tela.modelo.mudou, args=(tela.jogo.game_id,))
    thread.start()
    thread.join()
    flush_idle()
    assert tela.modelo.pagina["contagem"] == "3 de 3"


def test_desconectar_avisa_uma_vez_e_some_o_cartao_aberto(avisos, flush_idle, monkeypatch):
    """Review Focus 2: a conta Microsoft recusada com a página, a lista e a tela da sessão do jogo abertas."""
    jogo = _jogo()
    catalogo.guardar("xbox-7", CAT)
    com_fonte(jogo, "xbox:7")
    monkeypatch.setattr(conta, "_sessao", conta._Sessao("R1", "Jogador", "1"))  # noqa: SLF001
    monkeypatch.setattr(conta, "_avisou", False)
    detalhes = _Detalhes(jogo)
    sessao = _Detalhes(jogo)  # a sessão também só expõe `jogoId` e `alterado`
    modelo = ConquistasDoJogo(detalhes, sessao)
    monkeypatch.setattr(shared, "conquistas", modelo, raising=False)
    detalhes.mostrar(jogo.game_id)
    sessao.mostrar(jogo.game_id)
    modelo.abrir(jogo.game_id)
    assert modelo.pagina["visivel"] is True
    assert modelo.aberto is True
    assert modelo.sessao["visivel"] is True

    conta.recusada()
    conta.recusada()  # a segunda não acha mais conta
    flush_idle()

    assert avisos.textos == ["A conta Microsoft foi desconectada. Entre novamente nas Preferências."]
    assert modelo.pagina["visivel"] is False
    assert modelo.aberto is True  # D13: a lista aberta segue como estava (o retrato de quando abriu)
    assert modelo.sessao["visivel"] is False


def test_falha_ao_abrir_o_dialogo_fecha_e_esquece_o_retrato(tela, monkeypatch, caplog):
    def quebrar(_jogo):
        raise RuntimeError("falha")

    monkeypatch.setattr(progresso, "do_jogo", quebrar)
    with caplog.at_level(logging.WARNING):
        tela.modelo.abrir(tela.jogo.game_id)

    assert tela.modelo.aberto is False
    assert tela.modelo._retrato is None  # pylint: disable=protected-access
    assert tela.modelo._dialogo == ""  # pylint: disable=protected-access
    assert caplog.text.count("Falha ao montar as conquistas (dialogo)") == 1


def test_falha_ao_montar_esconde_a_vista(tela, monkeypatch, caplog):
    tela.modelo.abrir(tela.jogo.game_id)
    assert tela.modelo.pagina["visivel"] is True
    assert tela.modelo.aberto is True

    def quebrar(_jogo):
        raise RuntimeError("falha")

    monkeypatch.setattr(progresso, "do_jogo", quebrar)
    with caplog.at_level(logging.WARNING):
        tela.modelo.mudou(None)

    assert tela.modelo.pagina["visivel"] is False
    assert tela.modelo.aberto is True  # D13: a lista aberta não é refeita, então não falha nem fecha
    assert caplog.text.count("Falha ao montar as conquistas") == 1
