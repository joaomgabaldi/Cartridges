"""A gravação por temporário + replace compartilhada pelos caches e contas."""

from pathlib import Path

import pytest

from cartridges.utils import gravar_atomico as modulo
from cartridges.utils.gravar_atomico import gravar_atomico


@pytest.fixture(autouse=True)
def pausas(monkeypatch):
    """Sem esperar de verdade; devolve as pausas pedidas."""
    pedidas = []
    monkeypatch.setattr(modulo.time, "sleep", pedidas.append)
    return pedidas


@pytest.fixture
def pasta(tmp_path):
    """Uma pasta só deste teste: o conftest cria as do app dentro de ``tmp_path``."""
    nova = tmp_path / "gravacao"
    nova.mkdir()
    return nova


def test_grava_texto_e_bytes_e_cria_a_pasta(tmp_path):
    texto = tmp_path / "a" / "b" / "texto.json"
    gravar_atomico(texto, '{"á": 1}')
    assert texto.read_text(encoding="utf-8") == '{"á": 1}'
    binario = tmp_path / "c" / "icone.png"
    gravar_atomico(binario, b"\x89PNG")
    assert binario.read_bytes() == b"\x89PNG"


def test_troca_que_falha_levanta_e_nao_deixa_temporario(pasta, monkeypatch):
    destino = pasta / "x.json"
    destino.write_text("antigo")

    def travado(self, alvo):
        raise PermissionError("em uso")

    monkeypatch.setattr(Path, "replace", travado)
    with pytest.raises(OSError):
        gravar_atomico(destino, "novo")
    assert destino.read_text() == "antigo"
    assert [p.name for p in pasta.iterdir()] == ["x.json"]


def test_outro_igual_basta_quando_o_destino_ja_existe(pasta, monkeypatch):
    destino = pasta / "icone.png"
    destino.write_bytes(b"do outro")

    def travado(self, alvo):
        raise PermissionError("o outro ganhou")

    monkeypatch.setattr(Path, "replace", travado)
    gravar_atomico(destino, b"meu", outro_igual_basta=True)
    assert destino.read_bytes() == b"do outro"
    assert [p.name for p in pasta.iterdir()] == ["icone.png"]


def test_outro_igual_basta_ainda_levanta_sem_destino(pasta, monkeypatch):
    def travado(self, alvo):
        raise PermissionError("disco")

    monkeypatch.setattr(Path, "replace", travado)
    with pytest.raises(OSError):
        gravar_atomico(pasta / "icone.png", b"meu", outro_igual_basta=True)
    assert list(pasta.iterdir()) == []


def test_temporarios_tem_nomes_unicos(pasta, monkeypatch):
    nomes = []
    original = Path.write_text

    def espiar(self, *args, **kwargs):
        nomes.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", espiar)
    gravar_atomico(pasta / "x.json", "1")
    gravar_atomico(pasta / "x.json", "2")
    assert len(set(nomes)) == 2 and all(n.endswith(".tmp") for n in nomes)


def _replace_que_falha(monkeypatch, erro, vezes):
    chamadas = []
    original = Path.replace

    def trocar(self, alvo):
        chamadas.append(1)
        if len(chamadas) <= vezes:
            raise erro
        return original(self, alvo)

    monkeypatch.setattr(Path, "replace", trocar)
    return chamadas


def test_permission_error_passageiro_e_repetido(pasta, monkeypatch, pausas):
    chamadas = _replace_que_falha(monkeypatch, PermissionError("em uso"), 2)
    gravar_atomico(pasta / "x.json", "novo")
    assert (pasta / "x.json").read_text() == "novo" and len(chamadas) == 3 and len(pausas) == 2
    assert [p.name for p in pasta.iterdir()] == ["x.json"]


def test_permission_error_sempre_levanta_depois_das_tentativas(pasta, monkeypatch, pausas):
    chamadas = _replace_que_falha(monkeypatch, PermissionError("em uso"), 99)
    with pytest.raises(PermissionError):
        gravar_atomico(pasta / "x.json", "novo")
    assert len(chamadas) == modulo._TENTATIVAS
    assert sum(pausas) < 0.5
    assert list(pasta.iterdir()) == []


def test_outro_oserror_nao_repete(pasta, monkeypatch, pausas):
    chamadas = _replace_que_falha(monkeypatch, OSError(28, "disco cheio"), 99)
    with pytest.raises(OSError):
        gravar_atomico(pasta / "x.json", "novo")
    assert len(chamadas) == 1 and pausas == []
