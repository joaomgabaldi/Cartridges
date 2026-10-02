"""O que os testes de conquistas compartilham: pastas do sistema falsas."""

import struct
from pathlib import Path

import pytest

from cartridges.conquistas import arquivos


def kv_bytes(itens: dict) -> bytes:
    """KeyValues binário, do jeito que a Steam grava em `appcache\\stats` (só para teste).

    dict vira seção, str vira texto, int vira int32 e float vira float32.
    """
    saida = bytearray()
    for chave, valor in itens.items():
        nome = chave.encode("utf-8") + b"\0"
        if isinstance(valor, dict):
            saida += b"\x00" + nome + kv_bytes(valor)
        elif isinstance(valor, str):
            saida += b"\x01" + nome + valor.encode("utf-8") + b"\0"
        elif isinstance(valor, int):
            saida += b"\x02" + nome + struct.pack("<i", valor)
        elif isinstance(valor, float):
            saida += b"\x03" + nome + struct.pack("<f", valor)
        else:
            raise TypeError(f"tipo sem escrita de teste: {type(valor)}")
    return bytes(saida + b"\x08")


def schema_de_teste(appid: str, blocos: dict[str, dict[str, dict]]) -> bytes:
    """Um `UserGameStatsSchema_<appid>.bin` pequeno: cada bloco é de conquistas."""
    return kv_bytes(
        {
            appid: {
                "gamename": "Jogo",
                "version": 1,
                "stats": {
                    bloco: {"type": "ACHIEVEMENTS", "bits": bits} for bloco, bits in blocos.items()
                },
            }
        }
    )


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
