"""O histórico de conquistas segue o jogo para onde ele for."""

import zipfile

from cartridges import shared
from cartridges.conquistas import historico
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.store import store as store_module
from cartridges.utils import backup
from tests.test_auditoria_0923_ligacao import ligar  # noqa: F401
from tests.test_zerados import jogo


def test_campo_novo_vem_ligado_e_e_gravado(store):
    game = jogo(store, 1)
    assert game.conquistas is True
    game.conquistas = False
    game.save()
    from cartridges.game import PERSISTED_ATTRS  # noqa: PLC0415

    assert "conquistas" in PERSISTED_ATTRS


def test_excluir_apaga_o_historico(store, make_game):
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {}, run_pipeline=False)
    historico.registrar("shortcuts_1", [Desbloqueio("A", 1)])
    store.excluir(game)
    assert historico.ler("shortcuts_1") is None


def test_troca_de_id_leva_o_historico():
    historico.registrar("velho", [Desbloqueio("A", 1)])
    store_module._migrate_game_files("velho", "novo")
    assert historico.ler("novo") == {"A": 1}
    assert historico.ler("velho") is None


def test_ligacao_de_zerado_soma_os_historicos(store, ligar):  # noqa: F811
    zerado = jogo(store, 1, removed=True, status="beaten", steam_appid="570")
    vivo = jogo(store, 2, steam_appid="570")
    historico.registrar(zerado.game_id, [Desbloqueio("A", 5), Desbloqueio("B", 9)])
    historico.registrar(vivo.game_id, [Desbloqueio("B", 7)])

    assert ligar(vivo) is True
    assert historico.ler(vivo.game_id) == {"A": 5, "B": 7}
    assert historico.ler(zerado.game_id) is None  # saiu com o zerado


def test_backup_leva_o_historico(tmp_path):
    historico.registrar("shortcuts_1", [Desbloqueio("A", 1)])
    destino = tmp_path / "saida" / "backup.zip"
    destino.parent.mkdir()
    backup.exportar(destino, {"settings": {}, "state": {}})
    with zipfile.ZipFile(destino) as arquivo:
        assert "conquistas/shortcuts_1.json" in arquivo.namelist()
    assert shared.conquistas_dir.is_dir()
