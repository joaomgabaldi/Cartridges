"""Leitura de JSON do app que esbarra na troca (temporário + replace) de outra thread."""

import logging
from pathlib import Path

import pytest

from cartridges.utils import game_logo, ler_json


def _abrir_negando(monkeypatch, vezes: int) -> list[int]:
    """`Path.open` nega o acesso nas primeiras ``vezes`` chamadas, como o
    Windows no instante do `replace`."""
    chamadas = []
    original = Path.open

    def abrir(self, *args, **kwargs):
        chamadas.append(1)
        if len(chamadas) <= vezes:
            raise PermissionError(13, "Permission denied")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", abrir)
    monkeypatch.setattr(ler_json.time, "sleep", lambda _s: None)
    return chamadas


def test_acesso_negado_por_um_instante_le_na_tentativa_seguinte(tmp_path, monkeypatch):
    arquivo = tmp_path / "a.json"
    arquivo.write_text('{"x": 1}', encoding="utf-8")
    chamadas = _abrir_negando(monkeypatch, 2)

    assert ler_json.ler_json(arquivo) == {"x": 1}
    assert len(chamadas) == 3


def test_acesso_negado_de_vez_levanta(tmp_path, monkeypatch):
    arquivo = tmp_path / "a.json"
    arquivo.write_text("{}", encoding="utf-8")
    _abrir_negando(monkeypatch, 99)

    with pytest.raises(PermissionError):
        ler_json.ler_json(arquivo)


def test_logo_lido_durante_a_troca_nao_vira_aviso(app_dirs, monkeypatch, caplog):
    # Passeio de 28/09: "Unreadable logo sidecar … Permission denied" ao abrir
    # o histórico enquanto a busca do logo gravava o mesmo arquivo.
    game_logo.shared.logos_dir.mkdir(parents=True, exist_ok=True)
    (game_logo.shared.logos_dir / "jogo.json").write_text(
        '{"name": "Jogo", "file": null}', encoding="utf-8"
    )
    _abrir_negando(monkeypatch, 1)

    assert game_logo._read_sidecar("jogo") == {"name": "Jogo", "file": None}  # pylint: disable=protected-access
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
