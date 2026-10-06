"""Onde o Ubisoft Connect deixa as conquistas: `.spool`, ZIP do catálogo e instalações."""

import os
from pathlib import Path

from cartridges.conquistas.ubisoft import locais
from tests.apoio_conquistas import gravar_pacote, gravar_spool, pastas  # noqa: F401

# O de verdade: o conftest troca `_do_registro` em todo teste.
_DO_REGISTRO_REAL = locais._do_registro


def test_spool_da_unica_conta(pastas):  # noqa: F811
    caminho = gravar_spool(pastas, "65043", [(23, 1785102639)], conta="aaa")
    assert locais.spool("65043") == (caminho, "aaa")
    assert locais.spools("65043") == [(caminho, "aaa")]


def test_sem_pasta_do_launcher_e_nada(pastas):  # noqa: F811
    assert locais.spool("65043") is None
    assert locais.spools("65043") == []
    assert locais.pacote("65043") is None


def test_varias_contas_vale_o_spool_mais_recente(pastas):  # noqa: F811
    velho = gravar_spool(pastas, "65043", [(1, 1785102639)], conta="aaa")
    novo = gravar_spool(pastas, "65043", [(2, 1785102639)], conta="bbb")
    os.utime(velho, (2_000_000_000, 2_000_000_000))
    os.utime(novo, (1_900_000_000, 1_900_000_000))
    assert locais.spool("65043") == (velho, "aaa")
    assert [conta for _arquivo, conta in locais.spools("65043")] == ["aaa", "bbb"]


def test_spool_de_outro_produto_nao_conta(pastas):  # noqa: F811
    gravar_spool(pastas, "274", [(1, 1785102639)])
    assert locais.spool("65043") is None


def test_pacote_ignora_as_copias_extraidas(pastas):  # noqa: F811
    caminho = gravar_pacote(pastas, "65043", {"pt-BR": {1: ("A", "a")}})
    assert caminho.name == "65043_c261752455c1fa666d515971dd6645a6"
    assert locais.pacote("65043") == caminho
    assert locais.pacote("6504") is None  # prefixo de outro produto não casa


def test_dois_pacotes_vale_o_mais_novo(pastas):  # noqa: F811
    velho = gravar_pacote(pastas, "65043", {"pt-BR": {1: ("A", "a")}}, hash_="aaaa")
    novo = gravar_pacote(pastas, "65043", {"pt-BR": {1: ("B", "b")}}, hash_="bbbb")
    os.utime(velho, (1_900_000_000, 1_900_000_000))
    os.utime(novo, (2_000_000_000, 2_000_000_000))
    assert locais.pacote("65043") == novo


def test_instalacoes_so_pastas_validas(monkeypatch, tmp_path):
    jogo = tmp_path / "AC"
    monkeypatch.setattr(
        locais,
        "_do_registro",
        lambda: {
            "65043": str(jogo),
            "1": "C:\\",
            "2": "relativa\\x",
            "3": "\\\\servidor\\jogos\\x",
            "4": "//servidor/x",
        },
    )
    assert locais.instalacoes() == {"65043": Path(os.path.normcase(os.path.abspath(jogo)))}


class _Chave:
    def __init__(self, filhos=None, valores=None):
        self.filhos, self.valores = filhos or {}, valores or {}

    def __enter__(self):
        return self

    def __exit__(self, *_erro):
        return False


class _Winreg:
    HKEY_LOCAL_MACHINE = object()

    def __init__(self, raizes):
        self.raizes = raizes

    def OpenKey(self, pai, caminho):  # noqa: N802 - nome do winreg
        filhos = self.raizes if pai is self.HKEY_LOCAL_MACHINE else pai.filhos
        if caminho not in filhos:
            raise OSError(caminho)
        return filhos[caminho]

    def EnumKey(self, chave, indice):  # noqa: N802
        nomes = list(chave.filhos)
        if indice >= len(nomes):
            raise OSError("fim")
        return nomes[indice]

    def QueryValueEx(self, chave, nome):  # noqa: N802
        if nome not in chave.valores:
            raise OSError(nome)
        return chave.valores[nome], 1


def test_registro_32_e_64_bits(monkeypatch):
    falso = _Winreg(
        {
            r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs": _Chave(
                {
                    "65043": _Chave(valores={"InstallDir": "D:/Jogos/AC/"}),
                    "lixo": _Chave(valores={"InstallDir": "D:/x"}),
                    "5": _Chave(),
                }
            ),
            r"SOFTWARE\Ubisoft\Launcher\Installs": _Chave(
                {
                    "65043": _Chave(valores={"InstallDir": "E:/outra"}),
                    "274": _Chave(valores={"InstallDir": 7}),
                    "720": _Chave(valores={"InstallDir": "  "}),
                }
            ),
        }
    )
    monkeypatch.setattr(locais, "winreg", falso)
    assert _DO_REGISTRO_REAL() == {"65043": "D:/Jogos/AC/"}


def test_registro_sem_a_chave_do_launcher(monkeypatch):
    monkeypatch.setattr(locais, "winreg", _Winreg({}))
    assert _DO_REGISTRO_REAL() == {}
