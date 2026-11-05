# test_seletores_steam_ludusavi.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A busca na Steam, o HowLongToBeat e o jogo do Ludusavi no editor (`cartridges.modelos`).

Nenhum teste fala com a rede: a Steam e o HowLongToBeat são falsos. O Ludusavi é só a leitura de um
`manifest.yaml` numa pasta temporária; o `ludusavi.exe` desta máquina nunca roda. A interface
(`SeletorDaSteam.qml`, `SeletorDoLudusavi.qml`) tem os seus testes em `test_qml_edicao.py`.
"""

import threading
from types import SimpleNamespace

import pytest

from cartridges import shared
from cartridges.modelos import edicao as modulo_edicao
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.utils.steam import SteamGameNotFoundError, SteamNotAGameError
from tests.apoio_edicao import jogo
from tests.apoio_seletores import DADOS, HltbFalso, SteamFalsa, esperar as _esperar

MANIFESTO = 'Zelda:\n  files: {}\n"Alien: Isolation":\n  files: {}\nPortal:\n  files: {}\n'


@pytest.fixture
def steam():
    return SteamFalsa()


@pytest.fixture
def hltb(monkeypatch):
    falso = HltbFalso()
    monkeypatch.setattr(modulo_edicao, "shared_hltb_helper", lambda: object())
    monkeypatch.setattr(modulo_edicao, "fetch_times", falso)
    return falso


@pytest.fixture
def dialogos():
    return []


@pytest.fixture
def edicao(app_qt, store, steam, hltb, dialogos, ludusavi_de_verdade):
    aplicativo = SimpleNamespace(pedir_dialogo=lambda *a: dialogos.append(a))
    modelo = ModeloDaEdicao(aplicativo)
    modelo.seletorDaSteam.helper = steam
    modelo.seletorDaSteam.atraso_da_busca_ms = 40
    yield modelo
    modelo.cancelar()


def _manifesto(texto=MANIFESTO):
    pasta = shared.app_dir / "ludusavi"
    pasta.mkdir(parents=True, exist_ok=True)
    if texto is not None:
        (pasta / "manifest.yaml").write_text(texto, encoding="utf-8")


def _nomes(seletor):
    return [seletor.data(seletor.index(i, 0), seletor.Papel.Nome) for i in range(seletor.rowCount())]


# -- a Steam ----------------------------------------------------------------------------------


def test_escolher_na_steam_preenche_o_appid(edicao, steam):
    edicao.adicionar()
    seletor = edicao.seletorDaSteam
    seletor.abrir("Portal")
    assert _esperar(lambda: seletor.rowCount() == 2 and not seletor.buscando)
    assert seletor.data(seletor.index(0, 0), seletor.Papel.Appid) == "400"
    assert _nomes(seletor) == ["Portal", "Portal 2"]
    seletor.escolher(0)
    assert _esperar(lambda: edicao.appid == "400")
    assert steam.appids == ["400"] and seletor.aberto is False
    # Escolhido pela linha do AppID, só o campo muda: nada mais é preenchido.
    assert edicao.desenvolvedora == "" and edicao._form.buscado == {}  # noqa: SLF001


def test_steam_sem_resultado_e_item_que_nao_e_jogo(edicao, steam):
    edicao.adicionar()
    seletor = edicao.seletorDaSteam
    steam.candidatos = []
    seletor.abrir("Portal")
    assert _esperar(lambda: seletor.vazio)
    steam.candidatos = [({"id": 9, "name": "Trilha"}, None)]
    steam.erro_do_get = SteamNotAGameError()
    seletor.busca = "Trilha"
    seletor.buscarAgora()
    assert _esperar(lambda: seletor.rowCount() == 1)
    seletor.escolher(0)
    assert _esperar(lambda: seletor.vazio)
    assert seletor.tituloDoEstado == "Este item não é um jogo" and seletor.erro is True
    assert edicao.appid == ""


def test_falha_de_busca_troca_o_titulo(edicao, steam):
    """A busca que cai mostra o erro, não 'nenhum encontrado'."""
    edicao.adicionar()
    seletor = edicao.seletorDaSteam

    def cair(_nome):
        raise RuntimeError("sem rede")

    steam.find_candidates = cair
    seletor.abrir("Portal")
    assert _esperar(lambda: seletor.vazio)
    assert seletor.tituloDoEstado == "Não foi possível concluir a busca" and seletor.erro is True
    assert seletor.descricaoDoEstado == "Verifique a conexão e tente novamente."


def test_fechar_o_seletor_descarta_o_que_chega_depois(edicao, steam):
    edicao.adicionar()
    seletor = edicao.seletorDaSteam
    seletor.abrir("Portal")
    assert _esperar(lambda: seletor.rowCount() == 2)
    seletor.fechar()
    assert seletor.rowCount() == 0 and seletor.aberto is False
    seletor.escolher(0)  # fechado: nada
    assert steam.appids == []


def test_buscar_metadados_um_candidato_preenche(edicao, steam, hltb):
    edicao.adicionar()
    edicao.nome = "portal [GOG]"
    edicao.buscarMetadados()
    assert edicao.ocupado is True and edicao.buscandoMetadados is True
    assert _esperar(lambda: not edicao.ocupado)
    assert edicao.buscandoMetadados is False
    assert steam.consultas == ["portal"] and edicao.seletorDaSteam.aberto is False
    assert (edicao.nome, edicao.desenvolvedora, edicao.publicadora) == ("Portal", "Valve", "Valve Corp")
    assert (edicao.lancamento, edicao.genero, edicao.appid) == ("10/out./2007", "Puzzle", "400")
    assert edicao.controleIndice == 1  # "full"
    buscado = edicao._form.buscado  # noqa: SLF001
    assert buscado["steam_appid"] == "400" and buscado["metacritic"] == 90
    assert buscado["description"] == "Um jogo de portais." and buscado["gamepad_recommended"] is True
    assert buscado["steam_review"] == "Muito positivas"


def test_hltb_buscado_vai_para_o_formulario(edicao, hltb):
    edicao.adicionar()
    edicao.nome = "Portal"
    edicao.buscarMetadados()
    assert _esperar(lambda: not edicao.ocupado)
    # A busca no HowLongToBeat usa o título que a Steam confirmou.
    assert hltb.pedidos == [("Portal", None)]
    assert edicao._form.buscado["hltb"] == hltb.resposta  # noqa: SLF001


def test_hltb_com_erro_e_silencioso(edicao, hltb, dialogos):
    edicao.adicionar()
    edicao.nome = "Portal"
    hltb.erro = ValueError("ficha editada à mão")
    edicao.buscarMetadados()
    assert _esperar(lambda: not edicao.ocupado)
    assert "hltb" not in edicao._form.buscado and dialogos == []  # noqa: SLF001
    assert edicao.desenvolvedora == "Valve"


def test_hltb_de_titulo_que_mudou_no_voo_e_descartado(edicao, hltb):
    edicao.adicionar()
    edicao.nome = "Portal"
    hltb.soltar.clear()
    edicao.buscarMetadados()
    assert _esperar(lambda: edicao.desenvolvedora == "Valve" and hltb.pedidos)
    edicao.nome = "Outro título"  # a pessoa diz que é outro jogo
    hltb.soltar.set()
    assert _esperar(lambda: not edicao.ocupado)
    assert "hltb" not in edicao._form.buscado  # noqa: SLF001


def test_buscar_metadados_usa_o_appid_digitado_e_o_salvo(edicao, store, steam):
    game = jogo(store, 1, name="Alfa", steam_appid="111")
    edicao.abrir(game.game_id)
    edicao.buscarMetadados()  # título intacto: vale o AppID gravado, sem busca por nome
    assert _esperar(lambda: not edicao.ocupado)
    assert steam.appids == ["111"] and steam.consultas == []
    edicao.nome = "Alfa 2"
    edicao.appid = "222"
    edicao.buscarMetadados()
    assert _esperar(lambda: not edicao.ocupado)
    assert steam.appids == ["111", "222"]


def test_buscar_metadados_varios_abre_o_seletor(edicao, steam, hltb):
    edicao.adicionar()
    edicao.nome = "Portal"
    steam.erro_do_resolve = SteamGameNotFoundError()
    edicao.buscarMetadados()
    seletor = edicao.seletorDaSteam
    assert _esperar(lambda: seletor.aberto and seletor.rowCount() == 2)
    # A busca terminou como na versão anterior: o botão volta ao normal e o Aplicar fica livre, sob o seletor modal.
    assert edicao.ocupado is False and edicao.buscandoMetadados is False
    assert seletor.busca == "Portal"
    seletor.escolher(1)
    assert _esperar(lambda: edicao.desenvolvedora == "Valve" and not edicao.ocupado)
    assert edicao.appid == "620" and seletor.aberto is False
    assert edicao._form.buscado["steam_appid"] == "620"  # noqa: SLF001
    assert hltb.pedidos == [("Portal", None)]


def test_b29_escolha_da_steam_volta_o_spinner(edicao, steam, hltb):
    edicao.adicionar()
    edicao.nome = "Portal"
    steam.erro_do_resolve = SteamGameNotFoundError()
    edicao.buscarMetadados()
    seletor = edicao.seletorDaSteam
    assert _esperar(lambda: seletor.aberto and seletor.rowCount() == 2)
    assert edicao.ocupado is False and edicao.buscandoMetadados is False
    hltb.soltar.clear()  # a perna do HowLongToBeat fica esperando

    seletor.escolher(1)

    # Escolhido o jogo, a busca volta a andar: o botão gira e o Aplicar fica bloqueado até terminar.
    assert _esperar(lambda: hltb.pedidos)
    assert edicao.buscandoMetadados is True and edicao.ocupado is True
    hltb.soltar.set()
    assert _esperar(lambda: not edicao.ocupado and edicao.buscandoMetadados is False)
    assert edicao.appid == "620"


def test_buscar_metadados_sem_resultado_mostra_erro(edicao, steam, dialogos):
    edicao.adicionar()
    edicao.nome = "Portal"
    steam.erro_do_resolve = RuntimeError("fora do ar")
    edicao.buscarMetadados()
    assert _esperar(lambda: dialogos)
    titulo, corpo, itens, _ao_fechar = dialogos[0]
    assert (titulo, corpo, itens) == ("Jogo não encontrado na Steam", "Confira o título e tente novamente.", [])
    assert edicao.ocupado is False and edicao.buscandoMetadados is False
    assert edicao.desenvolvedora == "" and edicao._form.buscado == {}  # noqa: SLF001


def test_buscar_metadados_sem_titulo_nao_faz_nada(edicao, steam):
    edicao.adicionar()
    edicao.buscarMetadados()
    assert edicao.ocupado is False and steam.consultas == []


def test_resultado_com_dialogo_fechado_e_descartado(edicao, steam, hltb, dialogos):
    edicao.adicionar()
    edicao.nome = "Portal"
    steam.soltar.clear()
    edicao.buscarMetadados()
    edicao.cancelar()
    steam.soltar.set()
    # Outro jogo aberto em seguida não recebe nada do pedido velho.
    edicao.adicionar()
    assert _esperar(lambda: False, 0.4) is False
    assert edicao.nome == "" and edicao.desenvolvedora == "" and edicao.appid == ""
    assert edicao.ocupado is False and edicao.buscandoMetadados is False
    assert hltb.pedidos == [] and dialogos == []


def test_resultado_negativo_com_dialogo_fechado_nao_pergunta_nada(edicao, steam, dialogos):
    edicao.adicionar()
    edicao.nome = "Portal"
    steam.erro_do_resolve = SteamGameNotFoundError()
    steam.soltar.clear()
    edicao.buscarMetadados()
    edicao.cancelar()
    steam.soltar.set()
    assert _esperar(lambda: False, 0.4) is False
    assert edicao.seletorDaSteam.aberto is False and dialogos == []


def test_titulo_novo_devolve_o_appid_de_antes_da_busca(edicao, store):
    game = jogo(store, 1, name="Alfa", steam_appid="111")
    edicao.abrir(game.game_id)
    edicao.nome = "Portal"  # outro título: o AppID gravado não vale
    edicao.buscarMetadados()
    assert _esperar(lambda: not edicao.ocupado)
    assert edicao.appid == "400" and edicao._form.buscado["steam_appid"] == "400"  # noqa: SLF001
    edicao.nome = "Portal 2"
    assert edicao.appid == "111", "o AppID volta ao de antes da busca"
    assert edicao._form.buscado == {}  # noqa: SLF001


def test_titulo_novo_mantem_o_appid_que_a_pessoa_digitou_depois_da_busca(edicao):
    edicao.adicionar()
    edicao.nome = "Portal"
    edicao.buscarMetadados()
    assert _esperar(lambda: not edicao.ocupado)
    edicao.appid = "999"
    edicao.nome = "Portal 2"
    assert edicao.appid == "999" and edicao._form.buscado == {}  # noqa: SLF001


def test_aplicar_depois_da_busca_grava_o_que_chegou(edicao, store):
    game = jogo(store, 1, name="Alfa", steam_appid="111", executable='"C:\\a.exe"')
    edicao.abrir(game.game_id)
    edicao.nome = "Portal"
    edicao.buscarMetadados()
    assert _esperar(lambda: not edicao.ocupado)
    edicao.aplicar()
    assert (game.developer, game.steam_appid, game.metacritic) == ("Valve", "400", 90)
    assert game.hltb_id == 7


# -- o Ludusavi -------------------------------------------------------------------------------


def test_ludusavi_lista_os_nomes_e_filtra(edicao):
    _manifesto()
    edicao.adicionar()
    seletor = edicao.seletorDoLudusavi
    seletor.abrir("")
    assert _esperar(lambda: not seletor.carregando)
    assert _nomes(seletor) == ["Alien: Isolation", "Portal", "Zelda"]
    seletor.busca = "ALIEN"
    assert _nomes(seletor) == ["Alien: Isolation"]
    seletor.busca = "zzz"
    assert _nomes(seletor) == [] and seletor.vazio is True
    seletor.fechar()


def test_ludusavi_escolher_um_nome(edicao):
    _manifesto()
    edicao.adicionar()
    seletor = edicao.seletorDoLudusavi
    seletor.abrir("")
    assert _esperar(lambda: not seletor.carregando)
    seletor.escolher(1)
    assert edicao.ludusaviSubtitulo == "Portal" and seletor.aberto is False


def test_ludusavi_destaca_o_jogo_atual(edicao):
    _manifesto()
    edicao.adicionar()
    seletor = edicao.seletorDoLudusavi
    seletor.abrir("Portal")
    assert _esperar(lambda: not seletor.carregando)
    assert seletor.indiceAtual == 1
    seletor.fechar()


def test_ludusavi_nenhum_desliga_o_backup(edicao, store):
    _manifesto()
    game = jogo(store, 1, name="Alfa", executable='"C:\\a.exe"', ludusavi_nome="Portal")
    edicao.abrir(game.game_id)
    assert edicao.ludusaviSubtitulo == "Portal"
    edicao.escolherJogoNoLudusavi()
    seletor = edicao.seletorDoLudusavi
    assert _esperar(lambda: not seletor.carregando)
    seletor.escolherNenhum()
    assert edicao.ludusaviSubtitulo == "Backup desligado" and seletor.aberto is False
    edicao.aplicar()
    assert game.backup_dos_saves_desligado is True and game.ludusavi_nome == ""


def test_ludusavi_subtitulos_da_linha(edicao):
    _manifesto()
    edicao.adicionar()
    assert edicao.ludusaviSubtitulo == "Nenhum"
    edicao.appid = "400"
    assert edicao.ludusaviSubtitulo == "Automático pelo AppID"


def test_ludusavi_lista_ausente_avisa(edicao):
    edicao.adicionar()  # sem manifesto
    assert edicao.ludusaviDisponivel is False
    assert edicao.ludusaviSubtitulo == "A lista de jogos do Ludusavi ainda não foi baixada."
    edicao.escolherJogoNoLudusavi()
    assert edicao.seletorDoLudusavi.aberto is False
    edicao.cancelar()
    _manifesto()
    edicao.adicionar()
    assert edicao.ludusaviDisponivel is True and edicao.ludusaviSubtitulo == "Nenhum"


@pytest.mark.parametrize("texto", ["", "# nada\n"])
def test_ludusavi_manifesto_ilegivel_mostra_o_erro(edicao, texto):
    # "" é um manifesto vazio (sem chave de topo); a pasta existe, o arquivo existe, a lista não vale.
    _manifesto(texto)
    seletor = edicao.seletorDoLudusavi
    edicao.adicionar()
    seletor.abrir("")
    assert _esperar(lambda: seletor.erro)
    assert seletor.tituloDoEstado == "Não foi possível ler a lista de jogos do Ludusavi."
    assert seletor.rowCount() == 0 and seletor.carregando is False
    seletor.fechar()


def test_ludusavi_arquivo_que_sumiu_mostra_o_erro(edicao):
    seletor = edicao.seletorDoLudusavi
    edicao.adicionar()
    seletor.abrir("")  # sem manifesto: o `OSError` da leitura
    assert _esperar(lambda: seletor.erro)
    seletor.fechar()


def test_ludusavi_leitura_que_chega_depois_de_fechar_e_descartada(edicao, monkeypatch):
    _manifesto()
    soltar = threading.Event()
    from cartridges.saves import ludusavi  # noqa: PLC0415

    original = ludusavi.nomes_do_manifesto

    def lenta(pasta):
        assert soltar.wait(5)
        return original(pasta)

    monkeypatch.setattr(ludusavi, "nomes_do_manifesto", lenta)
    seletor = edicao.seletorDoLudusavi
    edicao.adicionar()
    seletor.abrir("")
    seletor.fechar()
    soltar.set()
    assert _esperar(lambda: False, 0.4) is False
    assert seletor.rowCount() == 0 and seletor.aberto is False


def test_cancelar_a_edicao_fecha_os_seletores_novos(edicao):
    _manifesto()
    edicao.adicionar()
    edicao.seletorDaSteam.abrir("Portal")
    edicao.seletorDoLudusavi.abrir("")
    edicao.cancelar()
    assert edicao.seletorDaSteam.aberto is False and edicao.seletorDoLudusavi.aberto is False


def test_buscar_outro_jogo_descarta_o_que_a_busca_anterior_trouxe(edicao, steam, hltb):
    edicao.adicionar()
    edicao.nome = "Portal"
    edicao.buscarMetadados()
    assert _esperar(lambda: not edicao.ocupado)
    assert edicao._form.buscado["hltb"] and edicao._form.buscado["metacritic"] == 90  # noqa: SLF001
    # O AppID de outro jogo, sem mexer no título; a Steam traz outro nome, sem nota nem descrição.
    edicao.appid = "620"
    steam.dados = {"name": "Portal 2", "developer": "Valve"}
    hltb.erro = ValueError("fora do ar")
    edicao.buscarMetadados()
    assert _esperar(lambda: not edicao.ocupado)
    assert edicao.nome == "Portal 2"
    assert edicao._form.buscado == {"steam_appid": "620"}  # noqa: SLF001
