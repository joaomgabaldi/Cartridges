"""O que os testes de conquistas compartilham: pastas do sistema falsas."""

import struct
import zipfile
from pathlib import Path

import pytest

from cartridges.conquistas import arquivos, historico


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


def com_fonte(game, texto: str) -> None:
    """Grava no histórico de ``game`` a fonte das conquistas (``"steam:570"``).

    Sem fonte gravada o cartão fica oculto; é o que a varredura faz de verdade.
    """
    historico.registrar(game.game_id, [], fonte=texto)


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


# -- Ubisoft Connect --------------------------------------------------------------

# O `.spool` real do AC Black Flag Resynced (productId 65043), lido em 05/10/2026:
# conquistas 23 (1785102639) e 12 (1791243494). Só varints: nenhum dado pessoal.
SPOOL_DO_HOST = bytes.fromhex(
    "0a0a0a020817" "10af829ad306" "0a0a0a02080c" "10e6e990d606"
)
# Basta a assinatura: nenhum teste decodifica a imagem.
PNG_MINIMO = bytes.fromhex("89504e470d0a1a0a")


def varint(valor: int) -> bytes:
    saida = bytearray()
    while True:
        byte = valor & 0x7F
        valor >>= 7
        if valor:
            saida.append(byte | 0x80)
        else:
            saida.append(byte)
            return bytes(saida)


def spool_bytes(conquistas: list[tuple[int, int]]) -> bytes:
    """Um `.spool` no formato real: `1:{1:{1:id}, 2:hora}` por conquista."""
    saida = bytearray()
    for id_, hora in conquistas:
        dentro = b"\x08" + varint(id_)
        registro = b"\x0a" + varint(len(dentro)) + dentro + b"\x10" + varint(hora)
        saida += b"\x0a" + varint(len(registro)) + registro
    return bytes(saida)


def gravar_spool(pastas, produto: str, conquistas, conta: str = "conta-1") -> Path:
    caminho = pastas.localappdata / "Ubisoft Game Launcher" / "spool" / conta / f"{produto}.spool"
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(spool_bytes(conquistas))
    return caminho


def gravar_pacote(
    pastas,
    produto: str,
    idiomas: dict,
    pngs=None,
    extras=None,
    hash_: str = "c261752455c1fa666d515971dd6645a6",
) -> Path:
    """O ZIP do catálogo como o Ubisoft Connect grava (sem extensão), com cópias `file_*` ao lado.

    ``idiomas``: ``{"pt-BR": {id: (título, descrição)}}``; ``pngs``: ids com ícone (padrão:
    todos os ids); ``extras``: entradas a mais, ``{nome: bytes}``.
    """
    pasta = pastas.programdata / "Ubisoft" / "Ubisoft Game Launcher" / "cache" / "achievements"
    pasta.mkdir(parents=True, exist_ok=True)
    if pngs is None:
        pngs = sorted({id_ for conquistas in idiomas.values() for id_ in conquistas})
    caminho = pasta / f"{produto}_{hash_}"
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as arquivo:
        arquivo.writestr("achievements.dat", b"\x0a\x08\x08\x01\x10\x01\x18\x01\x20\x01")
        for idioma, conquistas in idiomas.items():
            linhas = "".join(f"{id_}\t{titulo}\t{descricao}\n" for id_, (titulo, descricao) in conquistas.items())
            # BOM e primeira linha vazia, como no arquivo real.
            arquivo.writestr(f"{idioma}_loc.txt", ("﻿\n" + linhas).encode("utf-8"))
        for id_ in pngs:
            arquivo.writestr(f"{id_}.png", PNG_MINIMO)
        for nome, dados in (extras or {}).items():
            arquivo.writestr(nome, dados)
    # As cópias que o Ubisoft Connect extrai ao lado do ZIP.
    (pasta / f"file_{hash_}").write_bytes(b"\xef\xbb\xbf\n1\tcopia\tcopia")
    (pasta / f"file_{hash_}1.png").write_bytes(PNG_MINIMO)
    return caminho
