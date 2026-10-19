# test_opcoes_avancadas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O grupo "Opções avançadas" do Editar: appID da Steam e jogo no Ludusavi."""

import pytest

from cartridges import shared
from tests.test_auditoria_0923_ligacao import _stub_sgdb
from tests.test_zerados import jogo

LEGENDA = "A lista de jogos do Ludusavi ainda não foi baixada."


class _Janela:
    """Dublê de janela de escolha: guarda como foi aberta e deixa o teste escolher."""

    abertas: list = []

    def __init__(self, *args):
        self.args = args
        type(self).abertas.append(self)

    def present(self, _pai):
        pass


@pytest.fixture
def manifesto(app_dirs):
    pasta = shared.app_dir / "ludusavi"
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "manifest.yaml").write_text("Portal:\n  files: {}\n", encoding="utf-8")


@pytest.fixture
def janelas(monkeypatch):
    from cartridges import details_dialog  # noqa: PLC0415

    class SteamFalso(_Janela):
        abertas: list = []

    class SeletorFalso(_Janela):
        abertas: list = []

    monkeypatch.setattr(details_dialog, "SteamPicker", SteamFalso)
    monkeypatch.setattr(details_dialog, "SeletorDoLudusavi", SeletorFalso)
    monkeypatch.setattr(details_dialog.DetailsDialog, "_steam_helper", lambda _self: "helper")
    return SteamFalso, SeletorFalso


@pytest.fixture
def editar(store, real_window, manifesto):
    _stub_sgdb(store)

    def criar(numero=30, **campos):
        from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

        game = jogo(store, numero, executable="x.exe", conquistas=False, **campos)
        return game, DetailsDialog(game)

    return criar


def test_grupo_vem_recolhido_e_pode_abrir_expandido(editar):
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    _, dialogo = editar()
    assert dialogo.avancadas_row.get_title() == "Opções avançadas"
    assert not dialogo.avancadas_row.get_expanded()
    assert DetailsDialog(None, avancadas_abertas=True).avancadas_row.get_expanded()


def test_appid_atual_aparece_no_campo(editar):
    _, dialogo = editar(steam_appid="620")
    assert dialogo.appid_row.get_title() == "AppID da Steam"
    assert dialogo.appid_row.get_text() == "620"


def test_appid_digitado_com_espacos_grava_cortado_e_zera_o_nome(editar):
    game, dialogo = editar(
        steam_appid="620", ludusavi_nome="Portal", saves_local_desconhecido_avisado=True
    )
    dialogo.appid_row.set_text(" 400 ")
    dialogo.apply_preferences()
    assert game.steam_appid == "400"
    assert game.ludusavi_nome == ""
    assert game.saves_local_desconhecido_avisado is False


def test_campo_vazio_tira_o_appid(editar):
    game, dialogo = editar(steam_appid="620")
    dialogo.appid_row.set_text("")
    dialogo.apply_preferences()
    assert game.steam_appid is None


def test_appid_nao_numerico_marca_erro_e_bloqueia_aplicar(editar):
    game, dialogo = editar(steam_appid="620")
    dialogo.appid_row.set_text("abc")
    assert dialogo.appid_row.has_css_class("error")
    assert not dialogo.apply_button.get_sensitive()
    dialogo.apply_preferences()
    assert game.steam_appid == "620"
    dialogo.appid_row.set_text("621")
    assert not dialogo.appid_row.has_css_class("error")
    assert dialogo.apply_button.get_sensitive()


def test_botao_de_busca_poe_o_appid_no_campo_sem_gravar(editar, janelas):
    steam, _ = janelas
    game, dialogo = editar(steam_appid="10")
    dialogo.appid_buscar_button.emit("clicked")
    assert steam.abertas[-1].args[0] == game.name
    steam.abertas[-1].args[2]("620", {})
    assert dialogo.appid_row.get_text() == "620"
    assert game.steam_appid == "10"
    dialogo.apply_preferences()
    assert game.steam_appid == "620"


def test_jogo_no_ludusavi_mostra_o_atual_ou_nenhum(editar):
    _, sem = editar(31)
    _, com = editar(32, ludusavi_nome="Portal")
    assert sem.ludusavi_row.get_title() == "Jogo no Ludusavi"
    assert sem.ludusavi_row.get_subtitle() == "Nenhum"
    assert com.ludusavi_row.get_subtitle() == "Portal"


def test_subtitulo_do_jogo_no_ludusavi_automatico_e_desligado(editar):
    _, automatico = editar(31, steam_appid="620")
    _, desligado = editar(32, steam_appid="620", backup_dos_saves_desligado=True)
    _, desligado_com_nome = editar(33, ludusavi_nome="Portal", backup_dos_saves_desligado=True)
    assert automatico.ludusavi_row.get_subtitle() == "Automático pelo AppID"
    assert desligado.ludusavi_row.get_subtitle() == "Backup desligado"
    assert desligado_com_nome.ludusavi_row.get_subtitle() == "Portal"


def test_escolher_nome_e_aplicar_religa_o_backup(editar, janelas):
    _, seletor = janelas
    game, dialogo = editar(backup_dos_saves_desligado=True)
    dialogo.ludusavi_row.emit("activated")
    seletor.abertas[-1].args[1]("Portal 2")
    dialogo.apply_preferences()
    assert game.ludusavi_nome == "Portal 2"
    assert game.backup_dos_saves_desligado is False


def test_mudar_o_appid_nao_mexe_no_backup_desligado(editar):
    game, dialogo = editar(steam_appid="10", backup_dos_saves_desligado=True)
    dialogo.appid_row.set_text("620")
    dialogo.apply_preferences()
    assert game.steam_appid == "620"
    assert game.backup_dos_saves_desligado is True


def test_escolher_o_jogo_no_ludusavi_e_aplicar_grava(editar, janelas):
    _, seletor = janelas
    game, dialogo = editar()
    dialogo.ludusavi_row.emit("activated")
    assert seletor.abertas[-1].args[0] == ""
    seletor.abertas[-1].args[1]("Portal 2")
    assert dialogo.ludusavi_row.get_subtitle() == "Portal 2"
    dialogo.apply_preferences()
    assert game.ludusavi_nome == "Portal 2"


def test_nenhum_desliga_o_jogo_no_ludusavi(editar, janelas):
    _, seletor = janelas
    game, dialogo = editar(ludusavi_nome="Portal")
    dialogo.ludusavi_row.emit("activated")
    seletor.abertas[-1].args[1]("")
    assert dialogo.ludusavi_row.get_subtitle() == "Backup desligado"
    dialogo.apply_preferences()
    assert game.ludusavi_nome == ""
    assert game.backup_dos_saves_desligado is True


def test_appid_novo_e_jogo_escolhido_na_mesma_edicao_vale_o_jogo(editar, janelas):
    _, seletor = janelas
    game, dialogo = editar(steam_appid="10", ludusavi_nome="Antigo")
    dialogo.appid_row.set_text("620")
    dialogo.ludusavi_row.emit("activated")
    seletor.abertas[-1].args[1]("Portal 2")
    dialogo.apply_preferences()
    assert game.steam_appid == "620"
    assert game.ludusavi_nome == "Portal 2"


def test_sem_manifesto_a_linha_fica_desabilitada_com_a_legenda(store, real_window, app_dirs):
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    _stub_sgdb(store)
    dialogo = DetailsDialog(jogo(store, 40, executable="x.exe"))
    assert not dialogo.ludusavi_row.get_sensitive()
    assert dialogo.ludusavi_row.get_subtitle() == LEGENDA


def test_cancelar_depois_de_escolher_nao_grava(editar, janelas):
    _, seletor = janelas
    game, dialogo = editar(ludusavi_nome="Portal")
    dialogo.ludusavi_row.emit("activated")
    seletor.abertas[-1].args[1]("Outro")
    dialogo.close()
    assert game.ludusavi_nome == "Portal"


def test_titulo_novo_solta_o_appid_trazido_pela_busca(editar):
    game, dialogo = editar(steam_appid="10")
    dialogo._fetch_metadata_done({"name": "Portal"}, None, "620")
    assert dialogo.appid_row.get_text() == "620"
    dialogo.name.set_text("Outro título")
    assert dialogo.appid_row.get_text() == "10"


def test_voltar_ao_appid_antigo_depois_da_busca_vale_o_digitado(editar):
    game, dialogo = editar(steam_appid="10")
    dialogo._fetch_metadata_done({"name": "Portal"}, None, "620")
    dialogo.appid_row.set_text("10")
    dialogo.apply_preferences()
    assert game.steam_appid == "10"


def test_apagar_o_appid_depois_da_busca_vale_o_campo_vazio(editar):
    game, dialogo = editar()
    dialogo._fetch_metadata_done({"name": "Portal"}, None, "620")
    dialogo.appid_row.set_text("")
    dialogo.apply_preferences()
    assert game.steam_appid is None


def test_busca_sem_mexer_no_campo_grava_o_da_busca_e_carimba(editar):
    game, dialogo = editar(steam_appid="10")
    dialogo._fetch_metadata_done({"name": "Portal"}, None, "620")
    dialogo.apply_preferences()
    assert game.steam_appid == "620"
    from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: PLC0415

    assert game.steam_checked == STEAM_METADATA_VERSION


def test_busca_de_metadados_usa_o_appid_digitado(editar, monkeypatch):
    from cartridges import details_dialog  # noqa: PLC0415

    pedidos = []

    class Helper:
        def get_api_data(self, appid):
            pedidos.append(appid)
            return {"name": "Portal"}

    monkeypatch.setattr(details_dialog.DetailsDialog, "_steam_helper", lambda _self: Helper())
    monkeypatch.setattr(details_dialog, "entregar_na_tela", lambda *_a: None)
    _, dialogo = editar(steam_appid="10")
    dialogo._fetch_metadata_thread("Jogo 30", "620")
    assert pedidos == ["620"]


def test_subtitulo_do_jogo_no_ludusavi_nao_e_markup(editar):
    _, dialogo = editar(ludusavi_nome="Command & Conquer: Red Alert")
    assert dialogo.ludusavi_row.get_use_markup() is False
    assert dialogo.ludusavi_row.get_subtitle() == "Command & Conquer: Red Alert"


def test_busca_do_appid_fica_desabilitada_com_o_titulo_vazio(store, real_window, manifesto):
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

    dialogo = DetailsDialog(None)
    assert not dialogo.appid_buscar_button.get_sensitive()
    dialogo.name.set_text("Portal")
    assert dialogo.appid_buscar_button.get_sensitive()
