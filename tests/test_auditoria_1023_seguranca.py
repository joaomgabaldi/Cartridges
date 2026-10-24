# test_auditoria_1023_seguranca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressões da auditoria de segurança de 23/10/2026.

O ponto comum dos achados: o conteúdo de um backup (ou de uma resposta de API)
era tratado como confiável. Cada teste cobre um achado, com o nome dele.
"""

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from cartridges import shared
from cartridges.importer import shortcuts_source as ss
from cartridges.saves import conferencia
from cartridges.saves.ludusavi import Previa
from cartridges.utils import game_logo, session_wallpaper

# ---------------------------------------------------------------------------
# cmd_safe: `%` expande variáveis mesmo entre aspas
# ---------------------------------------------------------------------------

_EPIC = (
    "com.epicgames.launcher://apps/fn%3A4fe75bbc5a674f4f9b356b5c90567da5"
    "%3AFortnite?action=launch&silent=true"
)


@pytest.mark.parametrize(
    "url",
    [
        _EPIC,
        "steam://rungameid/440",
        "uplay://launch/635/0",
        "D:\\SteamLibrary\\steamapps\\common\\Overcooked! 2\\Overcooked2.exe",
    ],
)
def test_cmd_safe_aceita_urls_de_loja(url):
    assert ss.cmd_safe(url)


@pytest.mark.parametrize(
    "url",
    [
        "steam://x%CMDCMDLINE:~-1%&calc&%CMDCMDLINE:~-1%",
        "x%PATH%",
        "x%CD%",
        "x%",
        "x%3",
    ],
)
def test_cmd_safe_recusa_expansao_de_variavel(url):
    assert not ss.cmd_safe(url)


@pytest.mark.skipif(sys.platform != "win32", reason="precisa do cmd.exe real")
def test_cmd_real_so_injeta_o_que_cmd_safe_recusa(tmp_path):
    """No cmd.exe de verdade, com as aspas do comando que o importador monta
    (`echo` no lugar de `start`, para não abrir nada)."""
    marca = str(tmp_path / "marca.txt")
    eco = f'echo x> "{marca}"'

    def injeta(url):
        if os.path.exists(marca):
            os.remove(marca)
        subprocess.run(f'echo "{url}"', shell=True, capture_output=True, timeout=30)
        return os.path.exists(marca)

    recusada = f"nada://x%CMDCMDLINE:~-1%&{eco}&%CMDCMDLINE:~-1%".replace(f'"{marca}"', marca)
    aceita = f"nada://x%3A%3A&{eco}".replace(f'"{marca}"', marca)
    assert not ss.cmd_safe(recusada) and injeta(recusada), "o arnês não viu a injeção"
    assert ss.cmd_safe(aceita) and not injeta(aceita)


# ---------------------------------------------------------------------------
# .lnk com alvo UNC: a varredura não olha o caminho de rede
# ---------------------------------------------------------------------------


def test_alvo_unc_nao_e_consultado_na_varredura(tmp_path, schema, monkeypatch):
    alvo = "\\\\203.0.113.9\\jogos\\game.exe"
    (tmp_path / "Jogo.lnk").write_text("x", encoding="utf-8")
    schema["shortcuts-location"] = str(tmp_path)
    schema["shortcuts-recursive"] = False
    monkeypatch.setattr(
        ss,
        "resolve_lnk_targets",
        lambda paths: {str(tmp_path / "Jogo.lnk"): {"File": str(tmp_path / "Jogo.lnk"), "Target": alvo}},
    )
    monkeypatch.setattr(ss, "resolve_start_apps", lambda: [])
    consultados = []
    for nome in ("is_file", "exists"):
        original = getattr(Path, nome)

        def espiao(self, *a, _original=original, **k):
            consultados.append(str(self))
            return _original(self, *a, **k)

        monkeypatch.setattr(Path, nome, espiao)

    (jogo, _), = [r for r in iter(ss.ShortcutsSource()) if r is not None]

    assert not [c for c in consultados if "203.0.113.9" in c]
    assert jogo.executable == f'start "" "{alvo}"'


# ---------------------------------------------------------------------------
# Restauração de saves não grava na pasta do app
# ---------------------------------------------------------------------------


def test_restauracao_de_saves_recusa_a_pasta_do_app(tmp_path):
    from cartridges.conquistas.arquivos import Pastas  # noqa: PLC0415

    local = Path(shared.app_dir).parent
    pastas = Pastas(
        appdata=tmp_path / "Roaming",
        localappdata=local,
        documentos=tmp_path / "Documents",
        documentos_publicos=tmp_path / "Public" / "Documents",
        programdata=tmp_path / "ProgramData",
    )
    limites = conferencia.raizes(pastas, tmp_path / "casa", [])
    plantado = str(shared.app_dir / "games" / "x.json")

    assert conferencia.recusado(Previa((plantado,), ()), limites) == plantado
    assert conferencia.recusado(Previa((str(local / "Jogo" / "x.sav"),), ()), limites) is None


# ---------------------------------------------------------------------------
# Sidecars: `file` só pode ser um nome solto
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "arquivo",
    ["\\\\127.0.0.1\\x\\l.png", "//127.0.0.1/x/l.png", "C:\\Windows\\win.ini", "C:x.png", "..\\x.png", "../x.png"],
)
def test_sidecar_recusa_caminho_fora_da_pasta(app_dirs, arquivo):
    assert game_logo._cached_file({"file": arquivo}) is None
    assert session_wallpaper._arquivo_do_sidecar({"file": arquivo}) is None


def test_sidecar_com_nome_solto_continua_valendo(app_dirs):
    (shared.logos_dir / "g.png").write_bytes(b"x")
    (shared.wallpapers_dir / "g.jpg").write_bytes(b"x")
    assert game_logo._cached_file({"file": "g.png"}) == shared.logos_dir / "g.png"
    assert session_wallpaper._arquivo_do_sidecar({"file": "g.jpg"}) == shared.wallpapers_dir / "g.jpg"


# ---------------------------------------------------------------------------
# game_id vira nome de arquivo: só o formato que o app gera é carregado
# ---------------------------------------------------------------------------


def test_registro_com_game_id_de_caminho_nao_e_carregado(app_dirs, monkeypatch):
    from cartridges import main  # noqa: PLC0415

    def gravar(nome, game_id):
        (shared.games_dir / f"{nome}.json").write_text(
            json.dumps({"source": "imported", "game_id": game_id, "name": nome, "executable": "x"}),
            encoding="utf-8",
        )

    gravar("bom", "imported_1")
    gravar("fuga", "..\\..\\Documents\\x")
    gravar("absoluto", "C:\\x")
    carregados = []
    monkeypatch.setattr(
        shared, "store", type("S", (), {"add_game": lambda _s, g, _d: carregados.append(g)})()
    )
    monkeypatch.setattr(main.GameCover, "pre_decodificadas", lambda _c: contextlib.nullcontext())
    monkeypatch.setattr(main, "Game", type("G", (dict,), {"get_cover_path": lambda _s: None}))

    main.CartridgesApplication.load_games_from_disk(None)

    assert [g["game_id"] for g in carregados] == ["imported_1"]


# ---------------------------------------------------------------------------
# Seletores: o id da API nunca vira nome de arquivo
# ---------------------------------------------------------------------------


def test_previa_do_sgdb_fica_na_pasta_temporaria(monkeypatch):
    from cartridges import sgdb_picker as modulo  # noqa: PLC0415
    from cartridges.sgdb_picker import SgdbPicker  # noqa: PLC0415

    picker = SgdbPicker("Jogo", lambda *_: None)
    entregas = []
    monkeypatch.setattr(picker.sgdb, "search_games", lambda _q: [{"id": 1}])
    monkeypatch.setattr(
        picker.sgdb,
        "get_grids",
        lambda *_a, **_k: [{"id": "..\\..\\fuga", "url": "https://x/a.png", "thumb": "https://x/t/x.bat"}],
    )
    monkeypatch.setattr(modulo, "download_bytes", lambda *_a, **_k: b"img")
    monkeypatch.setattr(modulo, "entregar_na_tela", lambda func, *args: entregas.append(args))

    picker._search_thread("Jogo", False, picker._generation)

    previas = [args[0] for args in entregas if args and isinstance(args[0], Path)]
    assert len(previas) == 1
    assert previas[0].parent == picker._temp_dir and previas[0].suffix == ".png"


# ---------------------------------------------------------------------------
# Backup restaurado: o primeiro lançamento mostra o comando
# ---------------------------------------------------------------------------


def test_restauracao_marca_os_comandos_a_conferir(app_dirs):
    from cartridges.utils import backup  # noqa: PLC0415

    def gravar(nome, **dados):
        (shared.games_dir / f"{nome}.json").write_text(json.dumps(dados), encoding="utf-8")

    gravar("jogo", game_id="jogo", executable="calc")
    gravar("zerado", game_id="zerado", executable="", removed=True)
    (shared.games_dir / "quebrado.json").write_text("{", encoding="utf-8")

    backup._marcar_comandos_a_conferir()

    ler = lambda nome: json.loads((shared.games_dir / f"{nome}.json").read_text("utf-8"))  # noqa: E731
    assert ler("jogo")["comando_a_conferir"] is True
    assert "comando_a_conferir" not in ler("zerado")


def test_primeiro_lancamento_pede_confirmacao(real_window, monkeypatch):
    from cartridges import game as modulo  # noqa: PLC0415
    from cartridges.game import Game  # noqa: PLC0415

    executados, dialogos = [], []
    monkeypatch.setattr(modulo, "run_executable", lambda *a: executados.append(a))

    class Dialogo:
        def connect(self, _sinal, funcao):
            dialogos[-1]["resposta"] = funcao

    def criar(janela, titulo, corpo, *_a, **_k):
        dialogos.append({"titulo": titulo, "corpo": corpo})
        return Dialogo()

    monkeypatch.setattr(modulo, "create_dialog", criar)
    real_window.get_application = lambda: type("App", (), {"get_active_window": lambda _s: None})()
    jogo = Game(
        {"source": "imported", "game_id": "imported_1", "name": "Jogo", "added": 0,
         "executable": "cmd /c echo x‮& calc", "run_as_admin": True,
         "comando_a_conferir": True}
    )
    monkeypatch.setattr(jogo, "save", lambda: None)
    relancado = []

    assert jogo.launch(lambda: relancado.append(1)) is False
    assert executados == []
    assert "cmd /c echo x<U+202E>& calc" in dialogos[0]["corpo"]
    assert "administrador" in dialogos[0]["corpo"]

    dialogos[0]["resposta"](None, "dismiss")
    assert jogo.comando_a_conferir is True and relancado == []
    dialogos[0]["resposta"](None, "launch")
    assert jogo.comando_a_conferir is False and relancado == [1]


# ---------------------------------------------------------------------------
# Caminho de rede: nem a varredura de tamanho, nem a pasta de atalhos do backup
# ---------------------------------------------------------------------------


def test_comando_com_caminho_unc_nao_e_vigiado(monkeypatch):
    from cartridges.utils import process_monitor  # noqa: PLC0415

    listados = []
    monkeypatch.setattr(process_monitor.os, "scandir", lambda p: listados.append(p) or iter(()))
    comando = 'start "" "\\\\203.0.113.9\\jogos\\Jogo\\game.exe"'

    assert process_monitor.install_dir_from_command(comando) == ""
    assert listados == []


def test_backup_nao_traz_pasta_de_atalhos_de_rede(settings):
    from cartridges.utils import backup  # noqa: PLC0415

    backup.aplicar_configuracoes({"settings": {"shortcuts-location": "\\\\203.0.113.9\\x"}})
    assert shared.schema.get_string("shortcuts-location") != "\\\\203.0.113.9\\x"

    backup.aplicar_configuracoes({"settings": {"shortcuts-location": "D:\\Atalhos"}})
    assert shared.schema.get_string("shortcuts-location") == "D:\\Atalhos"
