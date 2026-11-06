# test_opcoes_avancadas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O grupo "Opções avançadas" do Editar: appID da Steam e jogo no Ludusavi (só a regra, `kyron.edicao`)."""

import pytest

from tests.apoio_edicao import jogo, stub_sgdb


@pytest.fixture
def editar(store):
    from kyron import edicao  # noqa: PLC0415

    stub_sgdb(store)

    def criar(numero=30, **campos):
        game = jogo(store, numero, executable="x.exe", conquistas=False, **campos)
        return game, edicao.Formulario.do_jogo(game)

    return criar


def _aplicar(game, form):
    from kyron import edicao  # noqa: PLC0415

    assert edicao.validar(form, game) is None
    edicao.aplicar(form, game, str(game.steam_appid or ""))


def _buscar(form, appid):
    form.appid = appid
    form.buscado = {"name": "Portal", "steam_appid": appid}


def test_appid_atual_aparece_no_campo(editar):
    _, form = editar(steam_appid="620")
    assert form.appid == "620"


def test_appid_digitado_com_espacos_grava_cortado_e_zera_o_nome(editar):
    game, form = editar(steam_appid="620", ludusavi_nome="Portal", saves_local_desconhecido_avisado=True)
    form.appid = " 400 "
    _aplicar(game, form)
    assert game.steam_appid == "400"
    assert game.ludusavi_nome == ""
    assert game.saves_local_desconhecido_avisado is False


def test_campo_vazio_tira_o_appid(editar):
    game, form = editar(steam_appid="620")
    form.appid = ""
    _aplicar(game, form)
    assert game.steam_appid is None


def test_appid_nao_numerico_bloqueia_aplicar(editar):
    from kyron import edicao  # noqa: PLC0415

    game, form = editar(steam_appid="620")
    form.appid = "abc"
    assert edicao.validar(form, game) == "O AppID da Steam deve conter apenas números."
    with pytest.raises(ValueError):
        edicao.aplicar(form, game, "620")
    assert game.steam_appid == "620"
    form.appid = "621"
    assert edicao.validar(form, game) is None


def test_escolher_nome_e_aplicar_religa_o_backup(editar):
    game, form = editar(backup_dos_saves_desligado=True)
    form.ludusavi_escolhido = "Portal 2"
    _aplicar(game, form)
    assert game.ludusavi_nome == "Portal 2"
    assert game.backup_dos_saves_desligado is False


def test_mudar_o_appid_nao_mexe_no_backup_desligado(editar):
    game, form = editar(steam_appid="10", backup_dos_saves_desligado=True)
    form.appid = "620"
    _aplicar(game, form)
    assert game.steam_appid == "620"
    assert game.backup_dos_saves_desligado is True


def test_nenhum_desliga_o_jogo_no_ludusavi(editar):
    game, form = editar(ludusavi_nome="Portal")
    form.ludusavi_escolhido = ""
    _aplicar(game, form)
    assert game.ludusavi_nome == ""
    assert game.backup_dos_saves_desligado is True


def test_appid_novo_e_jogo_escolhido_na_mesma_edicao_vale_o_jogo(editar):
    game, form = editar(steam_appid="10", ludusavi_nome="Antigo")
    form.appid = "620"
    form.ludusavi_escolhido = "Portal 2"
    _aplicar(game, form)
    assert game.steam_appid == "620"
    assert game.ludusavi_nome == "Portal 2"


def test_sem_escolha_o_nome_no_ludusavi_fica(editar):
    """O formulário não aplicado (o "Cancelar") não grava nada; aplicado sem escolha, o nome fica."""
    game, form = editar(ludusavi_nome="Portal")
    assert form.ludusavi_escolhido is None
    _aplicar(game, form)
    assert game.ludusavi_nome == "Portal"


def test_voltar_ao_appid_antigo_depois_da_busca_vale_o_digitado(editar):
    game, form = editar(steam_appid="10")
    _buscar(form, "620")
    form.appid = "10"
    _aplicar(game, form)
    assert game.steam_appid == "10"


def test_apagar_o_appid_depois_da_busca_vale_o_campo_vazio(editar):
    game, form = editar()
    _buscar(form, "620")
    form.appid = ""
    _aplicar(game, form)
    assert game.steam_appid is None


def test_busca_sem_mexer_no_campo_grava_o_da_busca_e_carimba(editar):
    from kyron.utils.steam import STEAM_METADATA_VERSION  # noqa: PLC0415

    game, form = editar(steam_appid="10")
    _buscar(form, "620")
    _aplicar(game, form)
    assert game.steam_appid == "620"
    assert game.steam_checked == STEAM_METADATA_VERSION
