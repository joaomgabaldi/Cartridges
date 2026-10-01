"""O cartão de conquistas na página do jogo e a lista completa."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from requests.exceptions import ConnectionError as ErroDeConexao

from cartridges.conquistas import catalogo, historico, icones
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from tests.test_zerados import jogo

# A fixture abaixo troca `icones.carregar` por um no-op; os testes do próprio
# módulo de ícones precisam da função de verdade.
carregar_de_verdade = icones.carregar

CAT = Catalogo(
    (
        ConquistaInfo("A", "Primeira", "Faça algo.", "", "", False, 55.0),
        ConquistaInfo("B", "Rara", "Difícil.", "", "", False, 4.1),
        ConquistaInfo("C", "Segredo", "Spoiler.", "", "", True, 20.0),
    ),
    0,
    True,
)

URL = "https://cdn.exemplo.com/a.jpg?key=SEGREDO"


@pytest.fixture(autouse=True)
def sem_icones(monkeypatch):
    monkeypatch.setattr(icones, "carregar", lambda _origem, _entregar: None)


@pytest.fixture
def executor_proprio(monkeypatch):
    """Um executor novo por teste: ``encerrar`` não pode vazar para os outros."""
    executor = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(icones, "_trabalhadores", executor)
    yield executor
    executor.shutdown(wait=False, cancel_futures=True)


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
    primeiro = icones.arquivo_local(URL)
    assert primeiro is not None and primeiro.read_bytes() == b"dados"
    assert icones.arquivo_local(URL) == primeiro
    assert len(chamadas) == 1
    assert not list(primeiro.parent.glob("*.tmp"))


def test_downloads_simultaneos_do_mesmo_icone_nao_se_atropelam(monkeypatch):
    ambas_baixando = threading.Barrier(2, timeout=5)

    def baixar(url, timeout, max_bytes):
        ambas_baixando.wait()  # as duas já passaram pela checagem do cache
        return b"dados"

    monkeypatch.setattr(icones, "download_bytes", baixar)
    resultados = []
    threads = [
        threading.Thread(target=lambda: resultados.append(icones.arquivo_local(URL)))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert len(resultados) == 2 and all(r is not None for r in resultados)
    assert resultados[0] == resultados[1]
    assert resultados[0].read_bytes() == b"dados"
    assert not list(resultados[0].parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "erro", [OSError("disco"), RuntimeError("rede"), RecursionError()]
)
def test_icone_nunca_levanta(monkeypatch, erro):
    def baixar(url, timeout, max_bytes):
        raise erro

    monkeypatch.setattr(icones, "download_bytes", baixar)
    assert icones.arquivo_local(URL) is None


def test_erro_de_rede_com_a_url_no_texto_nao_vaza_a_chave(monkeypatch, caplog):
    def baixar(url, timeout, max_bytes):
        raise ErroDeConexao(f"Falha ao conectar em {url}")

    monkeypatch.setattr(icones, "download_bytes", baixar)
    with caplog.at_level("DEBUG"):
        assert icones.arquivo_local(URL) is None
    assert "SEGREDO" not in caplog.text
    assert "cdn.exemplo.com/a.jpg" in caplog.text


def test_erro_inesperado_leva_traceback_sem_a_chave_na_mensagem(monkeypatch, caplog):
    def baixar(url, timeout, max_bytes):
        raise ValueError("defeito nosso")

    monkeypatch.setattr(icones, "download_bytes", baixar)
    with caplog.at_level("DEBUG"):
        assert icones.arquivo_local(URL) is None
    registro = next(r for r in caplog.records if r.levelname == "WARNING")
    assert registro.exc_info is not None
    assert "SEGREDO" not in registro.getMessage()


def test_icone_local_inexistente_ou_vazio(tmp_path):
    assert icones.arquivo_local("") is None
    assert icones.arquivo_local(str(tmp_path / "nao_existe.png")) is None


def test_arquivo_ilegivel_no_cache_e_apagado(monkeypatch):
    monkeypatch.setattr(
        icones, "download_bytes", lambda *_a, **_k: b"<html>portal</html>"
    )
    arquivo = icones.arquivo_local(URL)
    assert arquivo is not None and arquivo.is_file()

    assert icones._textura(URL) is None
    assert not arquivo.exists()


def test_arquivo_local_ilegivel_nao_e_apagado(tmp_path):
    arquivo = tmp_path / "icone.png"
    arquivo.write_bytes(b"nao e imagem")
    assert icones._textura(str(arquivo)) is None
    assert arquivo.exists()


def test_carregar_depois_de_encerrar_nao_faz_nada(executor_proprio, monkeypatch):
    baixou = []
    monkeypatch.setattr(
        icones, "download_bytes", lambda *_a, **_k: baixou.append(1) or b""
    )
    entregues = []

    icones.encerrar()
    carregar_de_verdade(URL, entregues.append)

    assert not baixou
    assert not entregues


def test_encerrar_nunca_levanta(executor_proprio, monkeypatch):
    def quebrar(*_a, **_k):
        raise RuntimeError("falha")

    with monkeypatch.context() as parcial:
        parcial.setattr(executor_proprio, "shutdown", quebrar)
        icones.encerrar()
