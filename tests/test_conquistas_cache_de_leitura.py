"""O cache de leituras de disco e quem o usa: manifests da Epic e `loginusers.vdf`."""

import json
import os

import pytest

from cartridges.conquistas import arquivos, fontes
from cartridges.conquistas.cache_de_leitura import CacheDeLeitura, assinatura
from tests.apoio_conquistas import criar, pastas  # noqa: F401


def test_assinatura_so_de_arquivo_comum(tmp_path):
    arquivo = criar(tmp_path / "a.txt", "abc")
    marca = assinatura(arquivo)
    assert marca is not None and marca[0] == str(arquivo) and marca[2] == 3
    assert assinatura(tmp_path) is None
    assert assinatura(tmp_path / "nao_existe") is None


def test_mesma_chave_le_uma_vez():
    cache = CacheDeLeitura()
    leituras = []
    for _vez in range(3):
        assert cache.obter("a", lambda: leituras.append(1) or "valor") == "valor"
    assert leituras == [1]


def test_leitura_que_levanta_nao_fica_guardada():
    cache = CacheDeLeitura()
    with pytest.raises(ValueError):
        cache.obter("a", lambda: (_ for _ in ()).throw(ValueError("ruim")))
    assert len(cache) == 0
    assert cache.obter("a", lambda: 1) == 1


def test_capacidade_tira_o_usado_ha_mais_tempo():
    cache = CacheDeLeitura(2)
    cache.obter("a", lambda: 1)
    cache.obter("b", lambda: 2)
    cache.obter("a", lambda: 99)  # "a" volta a ser o mais recente
    cache.obter("c", lambda: 3)
    assert len(cache) == 2
    assert cache.obter("a", lambda: 99) == 1
    assert cache.obter("b", lambda: 22) == 22


# -- manifests da Epic: lidos uma vez por mudança, não uma vez por jogo -----------------


def _manifest(pastas, nome, dados):  # noqa: F811
    pasta = pastas.programdata / "Epic" / "EpicGamesLauncher" / "Data" / "Manifests"
    return criar(pasta / f"{nome}.item", json.dumps(dados))


@pytest.fixture
def leituras_de_manifest(monkeypatch):
    fontes._cache_dos_manifests.clear()
    lidos = []
    original = fontes._ler_manifests

    def contando(itens):
        lidos.append(len(itens))
        return original(itens)

    monkeypatch.setattr(fontes, "_ler_manifests", contando)
    yield lidos
    fontes._cache_dos_manifests.clear()


def test_varios_jogos_leem_os_manifests_uma_vez(tmp_path, pastas, leituras_de_manifest):  # noqa: F811
    _manifest(pastas, "a", {"AppName": "A", "CatalogNamespace": "nsA", "InstallLocation": str(tmp_path / "A")})
    for numero in range(5):
        assert fontes._da_pasta([tmp_path / f"Outro{numero}"]) is None
    assert fontes._da_pasta([tmp_path / "A" / "bin"]) == ("nsA", "A")
    assert leituras_de_manifest == [1]


def test_manifest_regravado_e_lido_de_novo(tmp_path, pastas, leituras_de_manifest):  # noqa: F811
    item = _manifest(pastas, "a", {"AppName": "A", "CatalogNamespace": "nsA", "InstallLocation": str(tmp_path / "A")})
    assert fontes._da_pasta([tmp_path / "A"]) == ("nsA", "A")
    item.write_text(json.dumps({"AppName": "A", "CatalogNamespace": "nsB", "InstallLocation": str(tmp_path / "A")}))
    mtime = item.stat().st_mtime_ns + 10**9  # o NTFS guarda 100 ns: passo de 1 s
    os.utime(item, ns=(mtime, mtime))
    assert fontes._da_pasta([tmp_path / "A"]) == ("nsB", "A")
    assert leituras_de_manifest == [1, 1]


def test_manifest_novo_entra_sem_esperar(tmp_path, pastas, leituras_de_manifest):  # noqa: F811
    _manifest(pastas, "a", {"AppName": "A", "CatalogNamespace": "nsA", "InstallLocation": str(tmp_path / "A")})
    assert fontes._da_pasta([tmp_path / "B"]) is None
    _manifest(pastas, "b", {"AppName": "B", "CatalogNamespace": "nsB", "InstallLocation": str(tmp_path / "B")})
    assert fontes._da_pasta([tmp_path / "B"]) == ("nsB", "B")


# -- loginusers.vdf --------------------------------------------------------------------


def test_loginusers_lido_uma_vez_por_mudanca(tmp_path, monkeypatch):
    arquivos._cache_do_loginusers.clear()
    vdf = criar(
        tmp_path / "config" / "loginusers.vdf",
        '"users" { "76561197960265851" { "MostRecent" "1" "Timestamp" "10" } }',
    )
    lidos = []
    original = arquivos.keyvalues.ler_texto
    monkeypatch.setattr(arquivos.keyvalues, "ler_texto", lambda c: lidos.append(c) or original(c))
    for _jogo in range(4):
        assert arquivos._conta_mais_recente(tmp_path) == "123"
    assert len(lidos) == 1
    vdf.write_text('"users" { "76561197960266184" { "MostRecent" "1" "Timestamp" "20" } }')
    mtime = vdf.stat().st_mtime_ns + 10**9
    os.utime(vdf, ns=(mtime, mtime))
    assert arquivos._conta_mais_recente(tmp_path) == "456"
    assert len(lidos) == 2
    arquivos._cache_do_loginusers.clear()


def test_sem_loginusers_nao_ha_conta(tmp_path):
    assert arquivos._conta_mais_recente(tmp_path) is None
