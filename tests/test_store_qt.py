# test_store_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A `Store` sem gi: os sinais do `Jogo` ligados aos managers, os sinais da store e a
memória dos jogos e pipelines que saem de cena."""

import gc
import json
import threading
import weakref

from PySide6.QtCore import Qt

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.store.managers.file_manager import FileManager
from cartridges.store.managers.manager import Manager

# O que a versão anterior (GTK) grava para um jogo novo com estes campos. Escrito à mão de propósito: se um padrão
# ou uma chave mudar, o arquivo do jogo deixa de ser o mesmo para a versão anterior.
_FICHA_GTK = {
    "appid_manual": False,
    "idioma_proprio": "",
    "idiomas_steam": None,
    "inis": None,
    "nome_proprio": "",
    "added": 1_700_000_000,
    "backup_dos_saves_desligado": False,
    "blacklisted": False,
    "comando_a_conferir": False,
    "conquistas": True,
    "controller_support": None,
    "description": None,
    "developer": None,
    "executable": 'start "" "C:\\g\\game.exe"',
    "game_id": "shortcuts_abc",
    "gamepad_recommended": False,
    "genre": None,
    "hltb_chapters": None,
    "hltb_completionist": None,
    "hltb_id": None,
    "hltb_main": None,
    "hltb_main_extra": None,
    "install_size": 0,
    "install_size_ts": 0,
    "last_played": 0,
    "ludusavi_nome": "",
    "metacritic": None,
    "name": "Jogo de Teste",
    "notes": "",
    "playtime": 3600,
    "process_executable": "",
    "publisher": None,
    "rating": 0,
    "release_date": None,
    "removed": False,
    "run_as_admin": False,
    "saves_local_desconhecido_avisado": False,
    "shortcut_mtime": 0,
    "shortcut_path": "",
    "source": "shortcuts",
    "status": "",
    "steam_appid": None,
    "steam_checked": 0,
    "steam_review": None,
    "track_process": False,
    "track_updates": False,
    "update_available_ts": 0,
    "update_dismissed_ts": 0,
    "update_url": "",
    "version": 1.6,
}


def _jogo(game_id="shortcuts_abc", **campos) -> Jogo:
    dados = {
        "game_id": game_id,
        "source": "shortcuts",
        "name": "Jogo de Teste",
        "executable": 'start "" "C:\\g\\game.exe"',
        "added": shared.import_time,
    }
    dados.update(campos)
    return Jogo(dados)


def _ficha(game_id: str) -> dict:
    return json.loads((shared.games_dir / f"{game_id}.json").read_text(encoding="utf-8"))


def _na_thread(funcao) -> None:
    thread = threading.Thread(target=funcao, name="importador")
    thread.start()
    thread.join()


def _ouvir(sinal) -> list:
    recebidos = []
    sinal.connect(lambda *args: recebidos.append(args), Qt.ConnectionType.DirectConnection)
    return recebidos


def test_salvar_numa_thread_grava_a_ficha_da_versao_gtk(store):
    store.add_manager(FileManager(), in_pipeline=False)

    def importador():
        jogo = _jogo()
        store.add_game(jogo, {}, run_pipeline=False)
        jogo.playtime = 3600
        jogo.save()

    _na_thread(importador)

    assert _ficha("shortcuts_abc") == _FICHA_GTK


def test_remover_grava_a_tumba(store):
    store.add_manager(FileManager(), in_pipeline=False)
    jogo = _jogo()
    store.add_game(jogo, {}, run_pipeline=False)

    _na_thread(jogo.remove_game)

    assert _ficha("shortcuts_abc")["removed"] is True
    assert store["shortcuts_abc"] is jogo  # a tumba continua na store


def test_tumba_carregada_tambem_grava(store):
    store.add_manager(FileManager(), in_pipeline=False)
    tumba = _jogo(removed=True, status="beaten", executable="")
    store.add_game(tumba, {"skip_save": True})

    tumba.notes = "fim"
    tumba.save()

    assert _ficha("shortcuts_abc")["notes"] == "fim"


def test_excluir_emite_jogo_excluido_e_solta_o_jogo(store):
    store.add_manager(FileManager(), in_pipeline=False)
    excluidos = _ouvir(store.jogo_excluido)
    jogo = _jogo()
    store.add_game(jogo, {}, run_pipeline=False)
    jogo.save()
    ref = weakref.ref(jogo)

    _na_thread(lambda: store.excluir(jogo))
    del jogo
    gc.collect()

    assert excluidos == [("shortcuts_abc",)]
    assert not (shared.games_dir / "shortcuts_abc.json").exists()
    assert ref() is None, "a ligação com os managers não pode prender o jogo"


def test_adocao_emite_capa_trocou_de_id(store, tmp_path):
    atalho = str(tmp_path / "jogo.lnk")
    trocas = _ouvir(store.capa_trocou_de_id)
    antigo = _jogo("shortcuts_velho", shortcut_path=atalho)
    store.add_game(antigo, {}, run_pipeline=False)

    novo = _jogo("shortcuts_novo", shortcut_path=atalho)
    _na_thread(lambda: store.add_game(novo, {"identity_anchor": True}, run_pipeline=False))

    assert trocas == [("shortcuts_velho", "shortcuts_novo")]
    assert store["shortcuts_novo"] is antigo


def test_pipeline_terminado_e_o_jogo_sao_coletados(store):
    class Bloqueante(Manager):
        def main(self, game, additional_data):
            pass

    store.add_manager(Bloqueante())
    resultado = {}

    def importador():
        jogo = _jogo()
        pipeline = store.add_game(jogo, {})
        resultado["pronto"] = pipeline.is_done
        resultado["pipeline"] = weakref.ref(pipeline)
        resultado["jogo"] = weakref.ref(jogo)

    _na_thread(importador)
    store.clear()
    gc.collect()

    assert resultado["pronto"]
    assert resultado["pipeline"]() is None
    assert resultado["jogo"]() is None
