"""O leitor do formato binário KeyValues da Steam (os `.bin` de `appcache\\stats`)."""

import struct

import pytest

from cartridges.conquistas import keyvalues
from tests.apoio_conquistas import kv_bytes


def _item(tipo: int, chave: str, valor: bytes = b"") -> bytes:
    return bytes([tipo]) + chave.encode() + b"\0" + valor


def _aninhado(niveis: int) -> bytes:
    itens: dict = {}
    for _nivel in range(niveis):
        itens = {"s": itens}
    return kv_bytes(itens)


def test_tipos():
    dados = (
        _item(1, "texto", "olá".encode() + b"\0")
        + _item(2, "int32", struct.pack("<i", -5))
        + _item(3, "float", struct.pack("<f", 1.5))
        + _item(4, "ponteiro", struct.pack("<I", 7))
        + _item(6, "cor", struct.pack("<I", 0xFF00FF))
        + _item(7, "uint64", struct.pack("<Q", 2**63))
        + _item(10, "int64", struct.pack("<q", -(2**40)))
        + b"\x08"
    )
    assert keyvalues.ler_bytes(dados) == {
        "texto": "olá",
        "int32": -5,
        "float": 1.5,
        "ponteiro": 7,
        "cor": 0xFF00FF,
        "uint64": 2**63,
        "int64": -(2**40),
    }


def test_secoes_aninhadas_e_fim_alternativo():
    interna = _item(0, "b", _item(2, "c", struct.pack("<i", 1)) + b"\x0b")
    dados = _item(0, "a", interna + b"\x08") + b"\x08"
    assert keyvalues.ler_bytes(dados) == {"a": {"b": {"c": 1}}}


def test_escritor_de_teste_ida_e_volta():
    original = {
        "cache": {"crc": 0, "1": {"data": 16384, "AchievementTimes": {"14": 1790952235}}},
        "nome": "x",
    }
    assert keyvalues.ler_bytes(kv_bytes(original)) == original


@pytest.mark.parametrize("corte", [0, 1, 3, 10, 14, 20, 24, 26, -1])
def test_arquivo_cortado_e_falha(corte):
    # 14 corta dentro do int32, 24 dentro do texto, 26 deixa a seção sem fim.
    dados = kv_bytes({"cache": {"crc": 0, "nome": "abc"}})
    assert keyvalues.ler_bytes(dados[:corte]) is None


def test_valor_de_8_bytes_cortado_e_falha():
    # O valor tem 3 dos 8 bytes: o fim (8) vem depois, mas já dentro do valor.
    assert keyvalues.ler_bytes(_item(7, "u", b"\0\0\0") + b"\x08") is None


@pytest.mark.parametrize("tipo", [5, 9, 12, 255])
def test_tipo_desconhecido_e_falha(tipo):
    assert keyvalues.ler_bytes(_item(tipo, "x", b"\0\0\0\0") + b"\x08") is None


def test_profundidade():
    assert keyvalues.ler_bytes(_aninhado(32)) is not None
    assert keyvalues.ler_bytes(_aninhado(33)) is None


def test_tamanho_acima_do_limite(monkeypatch):
    monkeypatch.setattr(keyvalues, "LIMITE_DE_BYTES", 10)
    assert keyvalues.ler_bytes(kv_bytes({"a": "0123456789"})) is None


def test_utf8_invalido_vira_substituicao():
    assert keyvalues.ler_bytes(_item(1, "t", b"\xff\xfe\0") + b"\x08") == {"t": "\ufffd\ufffd"}


def test_chave_repetida_vale_a_ultima():
    dados = _item(2, "a", struct.pack("<i", 1)) + _item(2, "a", struct.pack("<i", 2)) + b"\x08"
    assert keyvalues.ler_bytes(dados) == {"a": 2}


def test_bytes_depois_do_fim_sao_ignorados():
    assert keyvalues.ler_bytes(kv_bytes({"a": 1}) + b"lixo") == {"a": 1}


def test_ler_arquivo(tmp_path):
    caminho = tmp_path / "x.bin"
    caminho.write_bytes(kv_bytes({"a": 1}))
    assert keyvalues.ler(caminho) == {"a": 1}
    assert keyvalues.ler(tmp_path / "nao_existe.bin") is None
    assert keyvalues.ler(tmp_path) is None  # pasta, não arquivo


def test_ler_caminho_com_nul(tmp_path):
    assert keyvalues.ler(tmp_path / "x\0.bin") is None


def test_ler_arquivo_grande_demais(tmp_path, monkeypatch):
    monkeypatch.setattr(keyvalues, "LIMITE_DE_BYTES", 4)
    caminho = tmp_path / "x.bin"
    caminho.write_bytes(kv_bytes({"a": 1}))
    assert keyvalues.ler(caminho) is None


# --- o KeyValues em texto (`config\loginusers.vdf`) ---


def test_texto_aninhado_e_aspas_escapadas():
    dados = (
        b'"users"\n{\n\t"7656"\n\t{\n\t\t"PersonaName"\t\t"Ana \\"A\\" {x}"\n'
        b'\t\t"MostRecent"\t\t"1"\n\t}\n}\n'
    )
    assert keyvalues.ler_texto_bytes(dados) == {
        "users": {"7656": {"PersonaName": 'Ana \\"A\\" {x}', "MostRecent": "1"}}
    }


@pytest.mark.parametrize(
    "dados",
    [b'"a" {', b'"a" }', b'{ "a" "b" }', b'"a" { "b" }', b'"a"', b'"a" "b" "c"'],
)
def test_texto_mal_formado_e_none(dados):
    assert keyvalues.ler_texto_bytes(dados) is None


def test_texto_fundo_demais_e_grande_demais_sao_none():
    fundo = b'"a" {' * (keyvalues.LIMITE_DE_NIVEIS + 2) + b"}" * (keyvalues.LIMITE_DE_NIVEIS + 2)
    assert keyvalues.ler_texto_bytes(fundo) is None
    assert keyvalues.ler_texto_bytes(b" " * (keyvalues.LIMITE_DO_TEXTO + 1)) is None


def test_ler_texto_arquivo_ausente_ou_com_bytes_ruins(tmp_path):
    assert keyvalues.ler_texto(tmp_path / "nao_existe.vdf") is None
    ruim = tmp_path / "x.vdf"
    ruim.write_bytes(b'"a" "\xff\xfe"')
    assert keyvalues.ler_texto(ruim) == {"a": "\ufffd\ufffd"}
