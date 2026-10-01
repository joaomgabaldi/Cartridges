"""O histórico de conquistas segue o jogo para onde ele for."""

import json
import zipfile

from cartridges import shared
from cartridges.conquistas import historico
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.store import store as store_module
from cartridges.store.managers.file_manager import FileManager
from cartridges.utils import backup
from tests.test_auditoria_0923_ligacao import ligar  # noqa: F401
from tests.test_zerados import jogo


def test_campo_novo_vem_ligado_e_e_gravado(store):
    game = jogo(store, 1)
    assert game.conquistas is True
    game.conquistas = False
    # `save()` só emite "save-ready"; quem escreve o arquivo é o FileManager.
    FileManager().main(game, {})
    gravado = json.loads(
        (shared.games_dir / f"{game.game_id}.json").read_text(encoding="utf-8")
    )
    assert gravado["conquistas"] is False


def test_excluir_apaga_o_historico(store, make_game):
    game = make_game(game_id="shortcuts_1")
    store.add_game(game, {}, run_pipeline=False)
    historico.registrar("shortcuts_1", [Desbloqueio("A", 1)])
    store.excluir(game)
    assert historico.ler("shortcuts_1") is None


def test_reinstalar_mantem_o_historico(store, make_game):
    """O ramo de reinstalação do `add_game` também passa por `cleanup_game`, e
    o histórico de conquistas só some com o Excluir."""
    tumba = make_game(
        game_id="shortcuts_1", removed=True, shortcut_path="C:\\A\\Jogo.lnk",
        shortcut_mtime=100,
    )
    store.add_game(tumba, {})
    store.new_game_ids = set()
    store.duplicate_game_ids = set()
    historico.registrar("shortcuts_1", [Desbloqueio("A", 1)])

    volta = make_game(
        game_id="shortcuts_1", shortcut_path="C:\\A\\Jogo.lnk", shortcut_mtime=999
    )
    assert store.add_game(volta, {}) is not None
    assert "shortcuts_1" in store.new_game_ids  # passou pelo ramo da reinstalação
    assert historico.ler("shortcuts_1") == {"A": 1}


def test_cleanup_game_sozinho_nao_apaga_o_historico(store, make_game):
    game = make_game(game_id="shortcuts_1")
    historico.registrar("shortcuts_1", [Desbloqueio("A", 1)])
    store.cleanup_game(game)
    assert historico.ler("shortcuts_1") == {"A": 1}


def test_troca_de_id_leva_o_historico():
    historico.registrar("velho", [Desbloqueio("A", 1)])
    store_module._migrate_game_files("velho", "novo")
    assert historico.ler("novo") == {"A": 1}
    assert historico.ler("velho") is None


def test_troca_de_id_passa_pela_trava_do_historico(monkeypatch):
    """O arquivo não anda por fora do `historico`: a varredura pode estar
    gravando nele, na thread principal, e a trava é dele."""
    chamadas = []
    monkeypatch.setattr(historico, "mover", lambda de, para: chamadas.append((de, para)))
    historico.registrar("velho", [Desbloqueio("A", 1)])
    store_module._migrate_game_files("velho", "novo")
    assert chamadas == [("velho", "novo")]
    assert historico.ler("velho") == {"A": 1}  # só o `historico` mexe no arquivo


def test_ligacao_de_zerado_soma_os_historicos(store, ligar):  # noqa: F811
    zerado = jogo(store, 1, removed=True, status="beaten", steam_appid="570")
    vivo = jogo(store, 2, steam_appid="570")
    historico.registrar(zerado.game_id, [Desbloqueio("A", 5), Desbloqueio("B", 9)])
    historico.registrar(vivo.game_id, [Desbloqueio("B", 7)])

    assert ligar(vivo) is True
    assert historico.ler(vivo.game_id) == {"A": 5, "B": 7}
    assert historico.ler(zerado.game_id) is None  # saiu com o zerado


def test_ligacao_sem_gravar_nao_perde_o_historico_do_zerado(store, ligar, monkeypatch):  # noqa: F811
    zerado = jogo(store, 1, removed=True, status="beaten", steam_appid="570")
    vivo = jogo(store, 2, steam_appid="570")
    historico.registrar(zerado.game_id, [Desbloqueio("A", 5)])

    def falha(_game_id, _desbloqueadas):
        raise OSError("disco cheio")

    monkeypatch.setattr(historico, "_gravar", falha)
    assert ligar(vivo) is True
    pendente = historico.caminho(zerado.game_id).with_name(f"{zerado.game_id}.json.pendente")
    assert pendente.is_file()


def test_backup_leva_o_historico(tmp_path):
    historico.registrar("shortcuts_1", [Desbloqueio("A", 1)])
    destino = tmp_path / "saida" / "backup.zip"
    destino.parent.mkdir()
    backup.exportar(destino, {"settings": {}, "state": {}})
    with zipfile.ZipFile(destino) as arquivo:
        assert "conquistas/shortcuts_1.json" in arquivo.namelist()
    assert shared.conquistas_dir.is_dir()
