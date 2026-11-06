# test_auditoria_1023_seguranca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regressões da auditoria de segurança de 23/10/2026.

O ponto comum dos achados: o conteúdo de um backup (ou de uma resposta de API)
era tratado como confiável. Cada teste cobre um achado, com o nome dele.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kyron import shared
from kyron.importer import shortcuts_source as ss
from kyron.saves import conferencia
from kyron.saves.ludusavi import Previa
from kyron.utils import game_logo, session_wallpaper

# cmd_safe: `%` expande variáveis mesmo entre aspas

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
    """No cmd.exe de verdade, com as aspas do comando que o importador monta (`echo` no lugar de `start`)."""
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


# .lnk com alvo UNC: a varredura não olha o caminho de rede


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


# Restauração de saves não grava na pasta do app


def test_restauracao_de_saves_recusa_a_pasta_do_app(tmp_path):
    from kyron.conquistas.arquivos import Pastas  # noqa: PLC0415

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


# Sidecars: `file` só pode ser um nome solto


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


# game_id vira nome de arquivo: só o formato que o app gera é carregado


# Seletores: o id da API nunca vira nome de arquivo


# Backup restaurado: o primeiro lançamento mostra o comando


def test_restauracao_marca_os_comandos_a_conferir(app_dirs):
    from kyron.utils import backup  # noqa: PLC0415

    def gravar(nome, **dados):
        (shared.games_dir / f"{nome}.json").write_text(json.dumps(dados), encoding="utf-8")

    gravar("jogo", game_id="jogo", executable="calc")
    gravar("zerado", game_id="zerado", executable="", removed=True)
    (shared.games_dir / "quebrado.json").write_text("{", encoding="utf-8")

    backup._marcar_comandos_a_conferir()

    ler = lambda nome: json.loads((shared.games_dir / f"{nome}.json").read_text("utf-8"))  # noqa: E731
    assert ler("jogo")["comando_a_conferir"] is True
    assert "comando_a_conferir" not in ler("zerado")


# Caminho de rede: nem a varredura de tamanho, nem a pasta de atalhos do backup


def test_comando_com_caminho_unc_nao_e_vigiado(monkeypatch):
    from kyron.utils import process_monitor  # noqa: PLC0415

    listados = []
    monkeypatch.setattr(process_monitor.os, "scandir", lambda p: listados.append(p) or iter(()))
    comando = 'start "" "\\\\203.0.113.9\\jogos\\Jogo\\game.exe"'

    assert process_monitor.install_dir_from_command(comando) == ""
    assert listados == []


def test_backup_nao_traz_pasta_de_atalhos_de_rede(schema):  # noqa: ARG001
    from kyron.utils import backup  # noqa: PLC0415

    backup.aplicar_configuracoes({"settings": {"shortcuts-location": "\\\\203.0.113.9\\x"}})
    assert shared.schema.get_string("shortcuts-location") != "\\\\203.0.113.9\\x"

    backup.aplicar_configuracoes({"settings": {"shortcuts-location": "D:\\Atalhos"}})
    assert shared.schema.get_string("shortcuts-location") == "D:\\Atalhos"
