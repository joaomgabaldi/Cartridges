"""O cartão de conquistas na página do jogo e a lista completa."""

import pytest

from cartridges.conquistas import catalogo, historico, icones
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from tests.test_zerados import jogo

CAT = Catalogo(
    (
        ConquistaInfo("A", "Primeira", "Faça algo.", "", "", False, 55.0),
        ConquistaInfo("B", "Rara", "Difícil.", "", "", False, 4.1),
        ConquistaInfo("C", "Segredo", "Spoiler.", "", "", True, 20.0),
    ),
    0,
    True,
)


@pytest.fixture(autouse=True)
def sem_icones(monkeypatch):
    monkeypatch.setattr(icones, "carregar", lambda _origem, _entregar: None)


@pytest.fixture
def com_conquistas(store):
    catalogo._gravar_cache("570", CAT)
    game = jogo(store, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("A", 100), Desbloqueio("B", 200)])
    return game


def test_cartao_mostra_o_progresso(real_window, com_conquistas):
    real_window.update_conquistas_block(com_conquistas)
    assert real_window.details_view_conquistas_box.get_visible()
    assert real_window.details_view_conquistas_count.get_label() == "2 de 3"
    assert real_window.details_view_conquistas_percent.get_label() == "67%"
    assert real_window.details_view_conquistas_bar.get_fraction() == pytest.approx(2 / 3)


def test_cartao_some_sem_catalogo_ou_desligado(real_window, store, com_conquistas):
    com_conquistas.conquistas = False
    real_window.update_conquistas_block(com_conquistas)
    assert not real_window.details_view_conquistas_box.get_visible()

    sem_catalogo = jogo(store, 2, steam_appid="999")
    real_window.update_conquistas_block(sem_catalogo)
    assert not real_window.details_view_conquistas_box.get_visible()


def test_icone_baixado_vai_para_o_cache(monkeypatch):
    chamadas = []

    def baixar(url, timeout, max_bytes):
        chamadas.append(url)
        return b"dados"

    monkeypatch.setattr(icones, "download_bytes", baixar)
    url = "https://cdn.exemplo.com/a.jpg?chave=segredo"
    primeiro = icones.arquivo_local(url)
    assert primeiro is not None and primeiro.read_bytes() == b"dados"
    assert icones.arquivo_local(url) == primeiro
    assert len(chamadas) == 1


@pytest.mark.parametrize(
    "erro", [OSError("disco"), RuntimeError("rede"), RecursionError()]
)
def test_icone_nunca_levanta_nem_loga_a_chave(monkeypatch, caplog, erro):
    def baixar(url, timeout, max_bytes):
        raise erro

    monkeypatch.setattr(icones, "download_bytes", baixar)
    with caplog.at_level("INFO"):
        assert icones.arquivo_local("https://cdn.exemplo.com/a.jpg?chave=segredo") is None
    assert "segredo" not in caplog.text


def test_icone_local_inexistente_ou_vazio():
    assert icones.arquivo_local("") is None
    assert icones.arquivo_local("Z:/nao/existe.png") is None
