"""O que os testes de conquistas compartilham: pastas do sistema falsas."""

from pathlib import Path

import pytest

from cartridges.conquistas import arquivos


def criar(caminho: Path, texto: str = "x") -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(texto, encoding="utf-8")
    return caminho


@pytest.fixture
def pastas(tmp_path, monkeypatch):
    """AppData, Documentos e afins dentro de ``tmp_path``, e nenhuma Steam."""
    falsas = arquivos.Pastas(
        appdata=tmp_path / "Roaming",
        localappdata=tmp_path / "Local",
        documentos=tmp_path / "Docs",
        documentos_publicos=tmp_path / "Public" / "Documents",
        programdata=tmp_path / "ProgramData",
    )
    monkeypatch.setattr(arquivos, "pastas_do_sistema", lambda: falsas)
    monkeypatch.setattr(arquivos, "pasta_da_steam", lambda: None)
    return falsas
