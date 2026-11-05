"""O interruptor de conquistas, a correção de appID e a varredura depois do Aplicar na edição do jogo."""

import types

import pytest

from cartridges import shared
from cartridges.conquistas import historico
from cartridges.conquistas.formatos import Desbloqueio
from tests.apoio_edicao import jogo, stub_sgdb


class _Varredura:
    def __init__(self):
        self.pedidos = []

    def varrer_jogo(self, game):
        self.pedidos.append(game.game_id)


@pytest.fixture
def varridos(monkeypatch):
    """Os jogos que a varredura (falsa, em `shared.aplicativo`) recebeu."""
    falsa = _Varredura()
    monkeypatch.setattr(shared, "aplicativo", types.SimpleNamespace(varredura_conquistas=falsa), raising=False)
    return falsa.pedidos


def _aplicar(store, game, **mudancas):
    from cartridges import edicao  # noqa: PLC0415

    stub_sgdb(store)
    form = edicao.Formulario.do_jogo(game)
    appid_inicial = form.appid
    for nome, valor in mudancas.items():
        if nome == "appid_buscado":
            # Como a busca de verdade: ela também preenche o campo do appID.
            form.appid = valor
            form.buscado = {"steam_appid": valor}
        else:
            setattr(form, nome, valor)
    edicao.aplicar(form, game, appid_inicial)


def test_interruptor_vem_ligado_e_e_gravado(store):
    from cartridges import edicao  # noqa: PLC0415

    game = jogo(store, 20, executable="x.exe")
    assert edicao.Formulario.do_jogo(game).conquistas is True
    _aplicar(store, game, conquistas=False)
    assert game.conquistas is False


def test_corrigir_o_appid_descarta_o_historico(store):
    game = jogo(store, 22, executable="x.exe", steam_appid="10")
    historico.registrar(game.game_id, [Desbloqueio("ERRADA", 1)])
    _aplicar(store, game, appid_buscado="20")
    assert historico.ler(game.game_id) is None


def test_primeiro_appid_nao_descarta_nada(store):
    game = jogo(store, 23, executable="x.exe")
    historico.registrar(game.game_id, [Desbloqueio("A", 1)])
    _aplicar(store, game, appid_buscado="20")
    assert historico.ler(game.game_id) == {"A": 1}


def test_desligar_mantem_o_historico(store, varridos):
    game = jogo(store, 25, executable="x.exe", steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("A", 1)])
    _aplicar(store, game, conquistas=False)
    assert game.conquistas is False
    assert historico.ler(game.game_id) == {"A": 1}
    assert not varridos


def _cartao_e_varredura(monkeypatch):
    """O cartão da página (`shared.conquistas.mudou`) e a varredura, na ordem em que foram chamados."""
    eventos = []
    monkeypatch.setattr(
        shared, "conquistas",
        types.SimpleNamespace(mudou=lambda game_id: eventos.append(("mudou", game_id, historico.ler(game_id)))),
    )
    varredura = types.SimpleNamespace(varrer_jogo=lambda game: eventos.append(("varrer", game.game_id)))
    avisos = types.SimpleNamespace(adicionar=lambda *_a, **_k: None)
    monkeypatch.setattr(
        shared, "aplicativo", types.SimpleNamespace(varredura_conquistas=varredura, avisos=avisos), raising=False
    )
    return eventos


def test_desligar_no_editor_refaz_o_cartao_da_pagina(store, monkeypatch):
    """O `update` não refaz o cartão da página aberta: quem refaz é o `aplicar`."""
    eventos = _cartao_e_varredura(monkeypatch)
    game = jogo(store, 28, executable="x.exe", steam_appid="570")
    _aplicar(store, game, conquistas=False)
    assert eventos == [("mudou", game.game_id, None)]


def test_religar_no_editor_refaz_o_cartao_e_depois_varre(store, monkeypatch):
    eventos = _cartao_e_varredura(monkeypatch)
    game = jogo(store, 29, executable="x.exe", steam_appid="570", conquistas=False)
    _aplicar(store, game, conquistas=True)
    assert eventos == [("mudou", game.game_id, None), ("varrer", game.game_id)]


def test_o_cartao_e_refeito_depois_da_correcao_e_da_ligacao_do_zerado(store, monkeypatch):
    """Se a refeita viesse antes, o cartão mostraria o histórico errado que a correção do appID apaga."""
    eventos = _cartao_e_varredura(monkeypatch)
    zerado = jogo(store, 30, removed=True, status="beaten", steam_appid="640")
    historico.registrar(zerado.game_id, [Desbloqueio("Z", 5)])
    vivo = jogo(store, 31, executable="x.exe", steam_appid="10")
    historico.registrar(vivo.game_id, [Desbloqueio("ERRADA", 1)])
    _aplicar(store, vivo, appid_buscado="640")
    assert eventos[0] == ("mudou", vivo.game_id, {"Z": 5})


def test_appid_que_liga_um_zerado_mantem_o_historico_dele(store):
    zerado = jogo(store, 26, removed=True, status="beaten", steam_appid="640")
    historico.registrar(zerado.game_id, [Desbloqueio("Z", 5)])
    vivo = jogo(store, 27, executable="x.exe", steam_appid="10")
    historico.registrar(vivo.game_id, [Desbloqueio("ERRADA", 1)])
    _aplicar(store, vivo, appid_buscado="640")
    # A conquista errada saiu antes da ligação, que então trouxe a do zerado.
    assert historico.ler(vivo.game_id) == {"Z": 5}


def test_corrigir_o_appid_de_jogo_do_xbox_nao_apaga_o_historico(store):
    """O appID não é a fonte de um jogo do Xbox: as conquistas dele não eram de outro jogo."""
    game = jogo(store, 28, executable="x.exe", steam_appid="10")
    historico.registrar(game.game_id, [Desbloqueio("XBOX:1", 1)], fonte="xbox:7", conta="111")
    _aplicar(store, game, appid_buscado="20")
    assert historico.ler(game.game_id) == {"XBOX:1": 1}
    assert historico.fonte(game.game_id) == "xbox:7"


def test_corrigir_o_appid_de_jogo_da_ubisoft_nao_apaga_o_historico(store):
    """Na Ubisoft o appID não é a fonte: as conquistas guardadas são dos arquivos do launcher."""
    game = jogo(store, 29, executable="x.exe", steam_appid="10")
    historico.registrar(game.game_id, [Desbloqueio("UBI:1", 1)], fonte="ubisoft:65043", conta="aaa")
    _aplicar(store, game, appid_buscado="20")
    assert historico.ler(game.game_id) == {"UBI:1": 1}


def test_corrigir_o_appid_de_jogo_da_steam_descarta_o_historico(store):
    game = jogo(store, 29, executable="x.exe", steam_appid="10")
    historico.registrar(game.game_id, [Desbloqueio("ERRADA", 1)], fonte="steam:10")
    _aplicar(store, game, appid_buscado="20")
    assert historico.ler(game.game_id) is None


def test_editar_o_executavel_e_gravado(store):
    game = jogo(store, 31, executable="x.exe")
    _aplicar(store, game, executavel="y.exe")
    assert game.executable == "y.exe"


def test_corrigir_o_appid_esquece_o_nome_no_ludusavi(store):
    """O nome no Ludusavi saiu do appID antigo: o próximo backup o procura de novo."""
    game = jogo(store, 30, executable="x.exe", steam_appid="10", ludusavi_nome="Jogo Errado")
    _aplicar(store, game, appid_buscado="20")
    assert game.ludusavi_nome == ""


def test_editar_sem_mudar_o_appid_mantem_o_nome_no_ludusavi(store):
    game = jogo(store, 31, executable="x.exe", steam_appid="10", ludusavi_nome="Jogo")
    _aplicar(store, game, appid_buscado="10", executavel="y.exe")
    assert game.ludusavi_nome == "Jogo"


def test_trocar_o_appid_zera_o_aviso(store):
    """Com o appID novo o jogo pode ser achado: se o local voltar a ser desconhecido,
    o aviso aparece de novo."""
    game = jogo(store, 32, executable="x.exe", steam_appid="10", saves_local_desconhecido_avisado=True)
    assert game.saves_local_desconhecido_avisado is True  # o campo é persistido e carrega
    _aplicar(store, game, appid_buscado="20")
    assert game.saves_local_desconhecido_avisado is False


def test_editar_sem_mudar_o_appid_mantem_o_aviso(store):
    game = jogo(store, 33, executable="x.exe", steam_appid="10", saves_local_desconhecido_avisado=True)
    _aplicar(store, game, appid_buscado="10", executavel="y.exe")
    assert game.saves_local_desconhecido_avisado is True


def test_religar_pede_varredura(store, varridos):
    game = jogo(store, 40, executable="x.exe", steam_appid="570", conquistas=False)
    _aplicar(store, game, conquistas=True)
    assert varridos == [game.game_id]


def test_sem_mudanca_nao_varre(store, varridos):
    game = jogo(store, 41, executable="x.exe", steam_appid="570")
    _aplicar(store, game)
    assert not varridos


def test_religar_pede_varredura_sem_appid(store, varridos):
    """Jogo do Xbox não tem appID: a varredura não pode depender dele."""
    game = jogo(store, 42, executable="x.exe", conquistas=False)
    _aplicar(store, game, conquistas=True)
    assert varridos == [game.game_id]


def test_jogo_sem_conquistas_nao_e_varrido_ao_editar_o_executavel(store, varridos):
    game = jogo(store, 43, executable="x.exe", conquistas=False)
    _aplicar(store, game, executavel="y.exe")
    assert not varridos


def test_editar_o_executavel_pede_varredura(store, varridos):
    game = jogo(store, 44, executable="x.exe", steam_appid="570")
    _aplicar(store, game, executavel="y.exe")
    assert varridos == [game.game_id]


def test_aplicar_corrige_o_appid_apaga_e_varre(store, varridos):
    game = jogo(store, 45, executable="x.exe", steam_appid="10")
    historico.registrar(game.game_id, [Desbloqueio("ERRADA", 1)])
    _aplicar(store, game, appid_buscado="20")
    assert historico.ler(game.game_id) is None
    assert varridos == [game.game_id]


def test_conta_com_fonte_invalida_apaga_como_a_main(store, varridos):
    """Fonte guardada ilegível (`xbox:`): apaga-se, como com a Steam; só a fonte de conta válida mantém."""
    game = jogo(store, 46, executable="x.exe", steam_appid="10")
    historico.registrar(game.game_id, [Desbloqueio("A", 1)], fonte="xbox:", conta="111")
    _aplicar(store, game, appid_buscado="20")
    assert historico.ler(game.game_id) is None
    assert varridos == [game.game_id]
