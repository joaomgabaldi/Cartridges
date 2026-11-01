# test_carga.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A carga da biblioteca do disco (`carga`), copiada do `main.py` da versão GTK."""

import json

from cartridges import shared
from cartridges.carga import carregar_jogos_do_disco, sanitize_game_fields
from cartridges.jogo import Jogo


class _StoreDeMentira:
    """Só o `add_game` que a carga chama (a `Store` real ainda depende do gi)."""

    def __init__(self) -> None:
        self.recebidos: list[tuple[Jogo, dict]] = []

    def add_game(self, game, additional_data, run_pipeline=True):
        self.recebidos.append((game, additional_data))


def _gravar(app_dirs, nome: str, conteudo) -> None:
    texto = conteudo if isinstance(conteudo, str) else json.dumps(conteudo)
    (app_dirs.games / nome).write_text(texto, encoding="utf-8")


def _ficha(game_id: str, **campos) -> dict:
    return {
        "game_id": game_id,
        "source": "shortcuts",
        "name": game_id,
        "executable": "x.exe",
        **campos,
    }


def test_json_quebrado_e_pulado_e_os_outros_carregam(app_dirs):
    _gravar(app_dirs, "shortcuts_a.json", _ficha("shortcuts_a"))
    _gravar(app_dirs, "quebrado.json", "{ isto não é json")
    _gravar(app_dirs, "shortcuts_b.json", _ficha("shortcuts_b"))
    _gravar(app_dirs, "shortcuts_c.json.abc123.tmp", _ficha("shortcuts_c"))
    store = _StoreDeMentira()

    assert carregar_jogos_do_disco(store) == 2

    ids = sorted(jogo.game_id for jogo, _ in store.recebidos)
    assert ids == ["shortcuts_a", "shortcuts_b"]
    assert all(isinstance(jogo, Jogo) for jogo, _ in store.recebidos)
    assert all(dados == {"skip_save": True} for _, dados in store.recebidos)


def test_ficha_malformada_e_pulada(app_dirs):
    sem_id = _ficha("x")
    del sem_id["game_id"]
    _gravar(app_dirs, "sem_id.json", sem_id)
    _gravar(app_dirs, "fora.json", _ficha("..\\fora"))
    _gravar(app_dirs, "lista.json", [1, 2])
    _gravar(app_dirs, "sem_exe.json", _ficha("shortcuts_e", executable=""))
    _gravar(app_dirs, "tumba.json", _ficha("shortcuts_t", executable="", removed=True))
    store = _StoreDeMentira()

    assert carregar_jogos_do_disco(store) == 1
    assert [jogo.game_id for jogo, _ in store.recebidos] == ["shortcuts_t"]


def test_registro_com_game_id_de_caminho_nao_e_carregado(app_dirs):
    # O game_id vira nome de arquivo (capa, logo, exclusão): só o formato que o app gera é carregado.
    barra = chr(92)
    _gravar(app_dirs, "bom.json", _ficha("imported_1"))
    _gravar(app_dirs, "fuga.json", _ficha(f"..{barra}..{barra}Documents{barra}x"))
    _gravar(app_dirs, "absoluto.json", _ficha(f"C:{barra}x"))
    _gravar(app_dirs, "barra.json", _ficha("a/b"))
    store = _StoreDeMentira()

    assert carregar_jogos_do_disco(store) == 1
    assert [jogo.game_id for jogo, _ in store.recebidos] == ["imported_1"]


def test_campo_de_tipo_errado_e_saneado(app_dirs):
    _gravar(
        app_dirs,
        "shortcuts_s.json",
        _ficha("shortcuts_s", playtime="5h", removed="false", notes=5, rating=4),
    )
    store = _StoreDeMentira()

    carregar_jogos_do_disco(store)

    (jogo, _), = store.recebidos
    assert jogo.playtime == 0
    assert jogo.removed is False
    assert jogo.notes == ""
    assert jogo.rating == 4


def test_falha_no_add_game_custa_so_aquele_jogo(app_dirs):
    _gravar(app_dirs, "shortcuts_a.json", _ficha("shortcuts_a"))
    _gravar(app_dirs, "shortcuts_b.json", _ficha("shortcuts_b"))

    class Exigente(_StoreDeMentira):
        def add_game(self, game, additional_data, run_pipeline=True):
            if game.game_id == "shortcuts_a":
                raise RuntimeError("ruim")
            super().add_game(game, additional_data)

    store = Exigente()
    assert carregar_jogos_do_disco(store) == 1
    assert [jogo.game_id for jogo, _ in store.recebidos] == ["shortcuts_b"]


def test_sem_pasta_de_jogos_nao_carrega_nada(app_dirs, monkeypatch):
    monkeypatch.setattr(shared, "games_dir", app_dirs.root / "nao_existe")
    assert carregar_jogos_do_disco(_StoreDeMentira()) == 0


# -- Vindos de tests/test_ui_logic.py -----------------------------------------


def test_wrong_typed_numeric_fields_are_dropped_on_load():
    """B4: `"playtime": "5h"` num registro editado à mão passava e estourava
    TypeError na tela de detalhes e na ordenação. Cai o campo, não o jogo."""
    data = {
        "name": "Probe",
        "playtime": "5h",
        "metacritic": "bom",
        "install_size": 1024,
        "hltb_main": None,
    }
    cleaned = sanitize_game_fields(data, "probe.json")

    assert "playtime" not in cleaned
    assert "metacritic" not in cleaned
    assert cleaned["install_size"] == 1024
    assert cleaned["hltb_main"] is None
    assert cleaned["name"] == "Probe"


def test_campo_conquistas_de_tipo_errado_cai_no_saneador():
    """`"conquistas": "false"` (texto) mantinha o recurso ligado e `null`
    o desligava; o campo precisa passar pelo saneador como os outros booleanos."""
    for ruim in ("false", None, 0, "sim"):
        limpo = sanitize_game_fields({"name": "Probe", "conquistas": ruim}, "p.json")
        assert "conquistas" not in limpo, ruim

    assert sanitize_game_fields({"conquistas": False}, "p.json")["conquistas"] is False
    assert sanitize_game_fields({"conquistas": True}, "p.json")["conquistas"] is True


def test_campo_do_aviso_dos_saves_de_tipo_errado_cai_no_saneador():
    """Um texto qualquer em `saves_local_desconhecido_avisado` contaria como "já avisado"."""
    for ruim in ("false", None, 0, "sim"):
        limpo = sanitize_game_fields({"saves_local_desconhecido_avisado": ruim}, "p.json")
        assert "saves_local_desconhecido_avisado" not in limpo, ruim

    assert sanitize_game_fields({"saves_local_desconhecido_avisado": True}, "p.json") == {
        "saves_local_desconhecido_avisado": True
    }


def test_campo_do_backup_desligado_persiste_e_tipo_errado_cai_no_saneador(app_dirs):
    from cartridges.store.managers.file_manager import FileManager  # noqa: PLC0415

    dados = {"source": "shortcuts", "game_id": "shortcuts_d", "name": "D", "executable": "x", "added": 0}
    jogo = Jogo({**dados, "backup_dos_saves_desligado": True})
    FileManager().main(jogo, {})
    gravado = json.loads((shared.games_dir / "shortcuts_d.json").read_text(encoding="utf-8"))
    assert gravado["backup_dos_saves_desligado"] is True
    assert Jogo({**dados, **gravado}).backup_dos_saves_desligado is True
    assert Jogo(dados).backup_dos_saves_desligado is False

    for ruim in ("false", None, 0, "sim"):
        assert "backup_dos_saves_desligado" not in sanitize_game_fields(
            {"backup_dos_saves_desligado": ruim}, "p.json"
        ), ruim


def test_file_manager_grava_exatamente_as_chaves_da_ficha(app_dirs):
    from cartridges.jogo import PERSISTED_ATTRS  # noqa: PLC0415
    from cartridges.store.managers.file_manager import FileManager  # noqa: PLC0415

    jogo = Jogo(_ficha("shortcuts_f"))
    FileManager().main(jogo, {})
    texto = (shared.games_dir / "shortcuts_f.json").read_text(encoding="utf-8")

    assert set(json.loads(texto)) == set(PERSISTED_ATTRS)
    assert texto.startswith('{\n    "added": 0,')  # indent=4, sort_keys
