"""O `.spool` da Ubisoft Connect: o progresso de um jogo."""

import pytest

from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.ubisoft import spool
from tests.apoio_conquistas import SPOOL_DO_HOST, spool_bytes, varint

DO_HOST = [Desbloqueio("UBI:23", 1785102639), Desbloqueio("UBI:12", 1791243494)]


def _ler(tmp_path, dados: bytes):
    caminho = tmp_path / "65043.spool"
    caminho.write_bytes(dados)
    return spool.ler_ou_none(caminho)


def test_formato_real_do_host(tmp_path):
    assert _ler(tmp_path, SPOOL_DO_HOST) == DO_HOST


def test_ajudante_de_teste_gera_o_formato_do_host():
    assert spool_bytes([(23, 1785102639), (12, 1791243494)]) == SPOOL_DO_HOST


def test_formato_do_pserban93_tambem_vale(tmp_path):
    registro = b"\x08" + varint(7) + b"\x10" + varint(1785102639)
    assert _ler(tmp_path, b"\x0a" + varint(len(registro)) + registro) == [Desbloqueio("UBI:7", 1785102639)]


def test_hora_em_milissegundos_vira_segundos(tmp_path):
    assert _ler(tmp_path, spool_bytes([(1, 1785102639123)])) == [Desbloqueio("UBI:1", 1785102639)]


@pytest.mark.parametrize("hora", [0, 5, 946_684_799, 4_102_444_800])
def test_hora_fora_da_faixa_fica_sem_data(tmp_path, hora):
    assert _ler(tmp_path, spool_bytes([(1, hora)])) == [Desbloqueio("UBI:1", 0)]


@pytest.mark.parametrize("id_", [0, 2**31 + 1, 2**40])
def test_id_zero_ou_enorme_e_pulado(tmp_path, id_):
    dados = spool_bytes([(id_, 1785102639), (3, 1785102639)])
    assert _ler(tmp_path, dados) == [Desbloqueio("UBI:3", 1785102639)]


def test_registro_sem_hora_entra_sem_data(tmp_path):
    dentro = b"\x08" + varint(9)
    registro = b"\x0a" + varint(len(dentro)) + dentro
    assert _ler(tmp_path, b"\x0a" + varint(len(registro)) + registro) == [Desbloqueio("UBI:9", 0)]


def test_campos_desconhecidos_sao_pulados(tmp_path):
    extra = b"\x18" + varint(5) + b"\x25" + b"\0" * 4 + b"\x29" + b"\0" * 8 + b"\x32\x02ab"
    assert _ler(tmp_path, extra + SPOOL_DO_HOST) == DO_HOST


def test_registro_estragado_por_dentro_cai_sozinho(tmp_path):
    ruim = b"\x0a\x02\x08\x80"  # registro de 2 bytes com o varint de dentro truncado
    assert _ler(tmp_path, ruim + SPOOL_DO_HOST) == DO_HOST


def test_vazio_e_lista_vazia(tmp_path):
    assert _ler(tmp_path, b"") == []


@pytest.mark.parametrize(
    "dados",
    [
        SPOOL_DO_HOST[:-1],  # gravação no meio: o último registro passa do fim
        b"\x0a\x30" + SPOOL_DO_HOST[2:],  # tamanho maior que o resto
        b"\x0b",  # tipo de campo 3: desconhecido
        b"\x8a",  # varint da tag truncado
        b"\x00\x01",  # campo zero
        b"\x08" + b"\xff" * 11,  # varint longo demais
    ],
)
def test_formato_estranho_e_none(tmp_path, dados):
    assert _ler(tmp_path, dados) is None


def test_grande_demais_e_none(tmp_path):
    assert _ler(tmp_path, b"\x18\x01" * (spool._TAMANHO_MAXIMO // 2 + 1)) is None


def test_arquivo_sumido_e_none(tmp_path):
    assert spool.ler_ou_none(tmp_path / "nao.spool") is None


def test_ler_troca_none_por_lista_vazia(tmp_path):
    assert spool.ler(tmp_path / "nao.spool") == []
    assert spool.ler(tmp_path / "x") == []
