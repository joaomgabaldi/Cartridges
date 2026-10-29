"""O interruptor de conquistas e a correção de appID na edição do jogo.

A varredura de conquistas depois do Aplicar volta no plano 6 (D42); até lá estes
testes conferem só o que a edição grava e o histórico que ela apaga ou mantém.
"""

from cartridges.conquistas import historico
from cartridges.conquistas.formatos import Desbloqueio
from tests.apoio_edicao import jogo, stub_sgdb


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


def test_desligar_mantem_o_historico(store):
    game = jogo(store, 25, executable="x.exe", steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("A", 1)])
    _aplicar(store, game, conquistas=False)
    assert game.conquistas is False
    assert historico.ler(game.game_id) == {"A": 1}


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
