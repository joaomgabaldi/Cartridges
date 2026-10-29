# apoio_seletores.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os falsos dos testes dos seletores do SteamGridDB: a API e o download, sem rede.

Módulo à parte, e não um teste: importar um `test_*.py` de outro arquivo roda a coleta de novo.
"""

import io
import threading
import time
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer

from cartridges.modelos import seletores
from cartridges.utils.download import DownloadCancelado


def png_bytes():
    saida = io.BytesIO()
    Image.new("RGB", (40, 60), "red").save(saida, "PNG")
    return saida.getvalue()


def lista_de_grades(n, base="https://x/g"):
    return [{"id": i, "url": f"{base}{i}.png", "thumb": f"{base}{i}-t.png"} for i in range(n)]


class SgdbFalso:
    """No lugar do `SgdbHelper`: anota os pedidos e responde sem rede."""

    def __init__(self, grids=None, logos=None, erro=None):
        self.consultas: list[str] = []
        self.grids_pedidas: list[tuple] = []
        self.grids = grids if grids is not None else lista_de_grades(3)
        self.logos = logos if logos is not None else lista_de_logos(3)
        self.erro = erro
        # `lento`: a busca por este texto espera o evento e devolve a grade `grids_lentas`.
        self.lento = threading.Event()
        self.grids_lentas = lista_de_grades(2, "https://x/velha")

    def search_games(self, consulta):
        self.consultas.append(consulta)
        if self.erro is not None:
            raise self.erro
        if consulta == "lento":
            assert self.lento.wait(5)
        return [{"id": 99 if consulta == "lento" else 1}]

    def get_grids(self, game_id, animated=False, dimensions=None):
        self.grids_pedidas.append((game_id, animated, dimensions))
        return list(self.grids_lentas if game_id == 99 else self.grids)

    def get_logos(self, game_id):
        return list(self.logos if game_id != 99 else lista_de_logos(2, "https://x/velho"))


def lista_de_logos(n, base="https://x/l"):
    return [
        {"id": i, "url": f"{base}{i}.png", "thumb": f"{base}{i}-t.png", "style": "white", "width": 600, "height": 200,
         "score": 10 - i, "mime": "image/png"}
        for i in range(n)
    ]  # fmt: skip


class DownloadFalso:
    """No lugar do `download_bytes`: devolve um PNG, ou espera ser solto avisando o progresso."""

    def __init__(self):
        self.urls: list[str] = []
        self.limites: list[int] = []
        self.soltar = threading.Event()
        self.soltar.set()
        self.comecou = threading.Event()
        self.cancelado = threading.Event()
        self.falhar: Exception | None = None

    def __call__(self, url, timeout=10, max_bytes=0, ao_progredir=None):
        self.urls.append(url)
        self.limites.append(max_bytes)
        self.comecou.set()
        if self.falhar is not None:
            raise self.falhar
        fim = time.monotonic() + 5
        while not self.soltar.wait(0.01):
            assert time.monotonic() < fim
            if ao_progredir is not None:
                try:
                    ao_progredir(1, 10)
                except DownloadCancelado:
                    self.cancelado.set()
                    raise
        if ao_progredir is not None:
            ao_progredir(10, 10)
        return png_bytes()


def esperar(ate, limite=5.0):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(20, laco.quit)
        laco.exec()
        if ate():
            return True
    return False


class Destino:
    """No lugar do `ModeloDaEdicao`: guarda o que o seletor entrega."""

    def __init__(self):
        self.capas: list[Path] = []
        self.logos: list[Path] = []
        self.titulos = 0

    def entregar_capa_baixada(self, arquivo):
        self.capas.append(arquivo)

    def entregar_logo_baixado(self, arquivo):
        self.logos.append(arquivo)

    def usar_titulo_no_logo(self):
        self.titulos += 1


@pytest.fixture
def temp(tmp_path, monkeypatch):
    """%TEMP% de mentira: o que sobrar nele depois do teste é vazamento."""
    pasta = tmp_path / "temp"
    pasta.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(pasta))
    return pasta


@pytest.fixture
def baixar(monkeypatch):
    falso = DownloadFalso()
    monkeypatch.setattr(seletores, "download_bytes", falso)
    return falso


@pytest.fixture(autouse=True)
def chave(schema):
    schema.set_string("sgdb-key", "chave-de-teste")


def criar(classe, sgdb=None):
    destino = Destino()
    seletor = classe(destino)
    seletor.sgdb = sgdb or SgdbFalso()
    seletor.atraso_da_busca_ms = 40
    return seletor, destino


def prontos(seletor, n=None):
    """A busca terminou e todas as miniaturas chegaram (ou falharam)."""
    return (
        not seletor.buscando
        and seletor.rowCount() > 0
        and not any(seletor.data(seletor.index(i, 0), seletor.Papel.Carregando) for i in range(seletor.rowCount()))
        and (n is None or seletor.rowCount() == n)
    )


def urls(seletor):
    return [seletor.data(seletor.index(i, 0), seletor.Papel.Miniatura) for i in range(seletor.rowCount())]


def vazio_de(pasta):
    return sorted(p.name for p in pasta.iterdir())


DADOS = {
    "name": "Portal",
    "developer": "Valve",
    "publisher": "Valve Corp",
    "release_date": "10/out./2007",
    "metacritic": 90,
    "steam_review": "Muito positivas",
    "genre": "Puzzle",
    "controller_support": "full",
    "gamepad_recommended": True,
    "description": "Um jogo de portais.",
}


class SteamFalsa:
    """No lugar do `SteamAPIHelper`: anota os pedidos e responde sem rede."""

    def __init__(self):
        self.candidatos = [({"id": 400, "name": "Portal"}, None), ({"id": 620, "name": "Portal 2"}, None)]
        self.resolvido = ("400", dict(DADOS))
        self.erro_do_resolve = None
        self.erro_do_get = None
        self.dados = None
        self.consultas: list[str] = []
        self.appids: list[str] = []
        self.soltar = threading.Event()
        self.soltar.set()

    def find_candidates(self, nome):
        self.consultas.append(nome)
        return list(self.candidatos)

    def get_api_data(self, appid):
        self.appids.append(appid)
        if self.erro_do_get is not None:
            raise self.erro_do_get
        return dict(self.dados or DADOS)

    def resolve(self, nome):
        self.consultas.append(nome)
        assert self.soltar.wait(5)
        if self.erro_do_resolve is not None:
            raise self.erro_do_resolve
        return self.resolvido


class HltbFalso:
    def __init__(self):
        self.pedidos: list[tuple] = []
        self.resposta = {"hltb_id": 7, "hltb_main": 18000}
        self.erro = None
        self.soltar = threading.Event()
        self.soltar.set()

    def __call__(self, _helper, nome, hltb_id=None):
        self.pedidos.append((nome, hltb_id))
        assert self.soltar.wait(5)
        if self.erro is not None:
            raise self.erro
        return dict(self.resposta)
