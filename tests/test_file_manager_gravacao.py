import json
from pathlib import Path

from kyron import shared
from kyron.jogo import Jogo
from kyron.store.managers import async_manager
from kyron.store.managers.file_manager import FileManager


def test_gravacao_do_jogo_tenta_de_novo_no_arquivo_preso(app_dirs, monkeypatch):
    jogo = Jogo({"source": "shortcuts", "game_id": "shortcuts_p", "name": "P", "executable": "x", "added": 0})
    original = Path.replace
    chamadas = []

    def preso(self, alvo):
        chamadas.append(self)
        if len(chamadas) == 1:
            raise PermissionError(13, "preso pelo antivírus")
        return original(self, alvo)

    monkeypatch.setattr(Path, "replace", preso)
    monkeypatch.setattr("kyron.utils.gravar_atomico._PAUSA", 0)

    FileManager().main(jogo, {})

    assert len(chamadas) == 2
    assert json.loads((shared.games_dir / "shortcuts_p.json").read_text(encoding="utf-8"))["name"] == "P"
    assert [p.name for p in shared.games_dir.iterdir()] == ["shortcuts_p.json"]


def test_gravacoes_do_mesmo_jogo_saem_em_ordem():
    assert async_manager._gravacao._max_workers == 1
