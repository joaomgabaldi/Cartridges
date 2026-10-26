# test_store_ligacao_manual.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ligação: um jogo adicionado à mão e, depois, o atalho dele na pasta de
atalhos viram um jogo só, com tudo o que o manual já tinha."""

import json

import pytest

from cartridges import shared
from cartridges.importer.importer import Importer
from cartridges.store.store import alvo_do_comando
from cartridges.utils import session_log


@pytest.mark.parametrize(
    "comando, alvo",
    [
        ('"C:\\Jogos\\X\\x.exe"', "C:\\Jogos\\X\\x.exe"),
        ('"C:\\Jogos\\X\\x.exe" -windowed', "C:\\Jogos\\X\\x.exe"),
        ('start "" /D "C:\\Jogos\\X" "C:\\Jogos\\X\\x.exe" -a', "C:\\Jogos\\X\\x.exe"),
        ('start "" "C:\\Jogos\\X\\x.exe"', "C:\\Jogos\\X\\x.exe"),
        ("C:\\Jogos\\X\\x.exe", "C:\\Jogos\\X\\x.exe"),
        ("  C:\\Jogos\\X\\x.exe  ", "C:\\Jogos\\X\\x.exe"),
        ("steam://rungameid/10", "steam://rungameid/10"),
        ('start "" "steam://rungameid/10"', "steam://rungameid/10"),
    ],
)
def test_alvo_do_comando(comando, alvo):
    assert alvo_do_comando(comando) == alvo


@pytest.mark.parametrize("comando", ["", "   ", '""', '"C:\\sem\\fim', 'start ""'])
def test_alvo_do_comando_sem_alvo(comando):
    assert alvo_do_comando(comando) is None


# ---------------------------------------------------------------------------
# A ligação na store
# ---------------------------------------------------------------------------

MANUAL = "imported_1"
NOVO = "shortcuts_2222222222222222"
LNK = "D:\\Atalhos\\Halo.lnk"
EXE = "C:\\Jogos\\Halo\\halo.exe"
COMANDO_DO_ATALHO = f'start "" "{EXE}"'


@pytest.fixture
def seed(store):
    """Um jogo como uma execução anterior o deixou, com a contabilidade limpa."""

    def seeder(game):
        store.add_game(game, {})
        store.new_game_ids = set()
        store.duplicate_game_ids = set()
        return game

    return seeder


def manual(make_game, **kw):
    kw.setdefault("game_id", MANUAL)
    kw.setdefault("executable", f'"{EXE}"')
    return make_game(source="imported", shortcut_path="", **kw)


def escaneado(make_game, **kw):
    kw.setdefault("game_id", NOVO)
    kw.setdefault("shortcut_path", LNK)
    kw.setdefault("executable", COMANDO_DO_ATALHO)
    return make_game(source="shortcuts", shortcut_mtime=50, **kw)


def dados(alvo=EXE, ancora=LNK):
    return {"identity_anchor": ancora, "alvo": alvo}


def test_liga_jogo_manual_unico(store, make_game, seed):
    jogo = seed(manual(make_game, playtime=77))

    assert store.add_game(escaneado(make_game), dados()) is None

    assert store.get(NOVO) is jogo
    assert store.get(MANUAL) is None
    assert jogo.game_id == NOVO
    assert jogo.source == "shortcuts"
    assert jogo.base_source == "shortcuts"
    assert jogo.shortcut_path == LNK
    assert jogo.shortcut_mtime == 50
    assert jogo.executable == COMANDO_DO_ATALHO
    assert jogo.playtime == 77
    assert len(store) == 1
    assert NOVO in store.source_games["shortcuts"]
    assert MANUAL not in store.source_games.get("imported", {})
    assert NOVO in store.duplicate_game_ids
    assert NOVO not in store.new_game_ids


def test_liga_ignorando_caixa_e_barras(store, make_game, seed):
    jogo = seed(manual(make_game, executable='"c:/jogos/halo/HALO.EXE"'))

    store.add_game(escaneado(make_game), dados())

    assert store.get(NOVO) is jogo


def test_liga_manual_com_argumentos_a_atalho_sem_argumentos(store, make_game, seed):
    jogo = seed(manual(make_game, executable=f'"{EXE}" -windowed'))

    store.add_game(escaneado(make_game), dados())

    assert store.get(NOVO) is jogo
    assert jogo.executable == COMANDO_DO_ATALHO


def test_liga_com_os_mesmos_argumentos(store, make_game, seed):
    jogo = seed(manual(make_game, executable=f'"{EXE}"  -dx11'))

    store.add_game(
        escaneado(make_game, executable=f'start "" /D "C:\\Jogos\\Halo" "{EXE}" -dx11'),
        dados(),
    )

    assert store.get(NOVO) is jogo


def test_nao_liga_launcher_a_atalho_de_conteudo(store, make_game, seed):
    """Um RetroArch adicionado à mão não vira o atalho de um jogo que ele abre."""
    jogo = seed(manual(make_game))

    store.add_game(
        escaneado(make_game, executable=f'start "" "{EXE}" -L snes.dll smw.sfc'), dados()
    )

    assert store.get(MANUAL) is jogo
    assert jogo.source == "imported"
    assert len(store) == 2


def test_nao_liga_com_argumentos_diferentes(store, make_game, seed):
    jogo = seed(manual(make_game, executable=f'"{EXE}" -windowed'))

    store.add_game(escaneado(make_game, executable=f'start "" "{EXE}" -dx11'), dados())

    assert store.get(MANUAL) is jogo
    assert len(store) == 2


def test_migra_arquivos_e_sessoes(store, make_game, seed):
    seed(manual(make_game))
    registro = shared.games_dir / f"{MANUAL}.json"
    registro.parent.mkdir(parents=True, exist_ok=True)
    registro.write_text(json.dumps({"game_id": MANUAL}), encoding="utf-8")
    session_log.record(MANUAL, 60, end=1_700_000_000)

    store.add_game(escaneado(make_game), dados())

    assert not registro.exists()
    novo = shared.games_dir / f"{NOVO}.json"
    assert json.loads(novo.read_text(encoding="utf-8"))["game_id"] == NOVO
    assert [s["seconds"] for s in session_log.load(NOVO)] == [60]
    assert session_log.load(MANUAL) == []


def test_nao_liga_com_dois_candidatos(store, make_game, seed):
    um = seed(manual(make_game))
    outro = seed(manual(make_game, game_id="imported_2"))

    assert store.add_game(escaneado(make_game), dados()) is not None

    assert len(store) == 3
    assert store.get(MANUAL) is um and um.source == "imported"
    assert store.get("imported_2") is outro and outro.source == "imported"


@pytest.mark.parametrize("campo", ["removed", "blacklisted"])
def test_nao_liga_jogo_fora_da_biblioteca(store, make_game, seed, campo):
    jogo = seed(manual(make_game, **{campo: True}))

    store.add_game(escaneado(make_game), dados())

    assert store.get(MANUAL) is jogo
    assert jogo.source == "imported"


def test_nao_liga_sem_alvo(store, make_game, seed):
    jogo = seed(manual(make_game))

    store.add_game(escaneado(make_game), {"identity_anchor": LNK})

    assert store.get(MANUAL) is jogo
    assert len(store) == 2


def test_nao_liga_sem_ancora(store, make_game, seed):
    """Carregar a biblioteca do disco não passa âncora: nunca liga nada."""
    jogo = seed(manual(make_game))

    store.add_game(escaneado(make_game), {"alvo": EXE})

    assert store.get(MANUAL) is jogo
    assert len(store) == 2


def test_nao_liga_alvo_diferente(store, make_game, seed):
    jogo = seed(manual(make_game))

    store.add_game(escaneado(make_game), dados(alvo="C:\\Outro\\x.exe"))

    assert store.get(MANUAL) is jogo
    assert len(store) == 2


def test_nao_procura_manual_quando_o_id_ja_existe(store, make_game, seed):
    seed(escaneado(make_game))
    jogo = seed(manual(make_game))

    store.add_game(escaneado(make_game), dados())

    assert store.get(MANUAL) is jogo
    assert jogo.source == "imported"


def test_segundo_atalho_do_mesmo_jogo_vira_duplicata(store, make_game, seed):
    jogo = seed(manual(make_game))
    store.add_game(escaneado(make_game), dados())

    outro_lnk = "D:\\Atalhos\\Halo (2).lnk"
    store.add_game(escaneado(make_game, shortcut_path=outro_lnk), dados(ancora=outro_lnk))

    assert len(store) == 1
    assert store.get(NOVO) is jogo


def test_jogo_ligado_e_removido_quando_o_atalho_some(store, make_game, seed):
    jogo = seed(manual(make_game))
    store.add_game(escaneado(make_game), dados())

    importer = Importer()  # zera a contabilidade de ids, como no início de uma importação
    importer.scanned_source_ids.add("shortcuts")
    importer.remove_games()

    assert jogo.removed is True
    assert NOVO in importer.removed_game_ids


def test_jogo_manual_continua_fora_da_remocao(store, make_game, seed):
    """O controle do teste acima: sem atalho, o manual nunca é removido."""
    jogo = seed(manual(make_game))

    importer = Importer()
    importer.scanned_source_ids.add("shortcuts")
    importer.remove_games()

    assert jogo.removed is False
