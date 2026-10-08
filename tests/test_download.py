"""As consultas online reaproveitam a conexão da thread e não carregam cookie."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from cartridges.utils import download


@pytest.fixture
def servidor():
    """Servidor HTTP/1.1 local que conta conexões e anota o Cookie recebido."""
    conexoes: list[int] = []
    cookies: list = []

    class Resposta(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"  # mantém a conexão aberta entre pedidos

        def setup(self):
            conexoes.append(1)
            super().setup()

        def do_GET(self):
            cookies.append(self.headers.get("Cookie"))
            corpo = b"ok"
            self.send_response(200)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Set-Cookie", "pais=BR; Path=/")
            self.end_headers()
            self.wfile.write(corpo)

        def log_message(self, *_args):
            pass

    servico = ThreadingHTTPServer(("127.0.0.1", 0), Resposta)
    threading.Thread(target=servico.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servico.server_port}/", conexoes, cookies
    servico.shutdown()
    servico.server_close()


def test_chamadas_da_mesma_thread_usam_uma_conexao(servidor):
    url, conexoes, _cookies = servidor
    assert download.get_capped(url, timeout=5).content == b"ok"
    assert download.download_bytes(url, timeout=5) == b"ok"
    assert download.download_bytes(url, timeout=5) == b"ok"
    assert len(conexoes) == 1


def test_cookie_recebido_nao_volta_na_chamada_seguinte(servidor):
    url, _conexoes, cookies = servidor
    download.download_bytes(url, timeout=5)
    download.download_bytes(url, timeout=5)
    assert cookies == [None, None]


class _Chega:
    """Resposta em pedaços, como o `requests` a entrega com `stream=True`."""

    def __init__(self, pedacos):
        self._pedacos = pedacos
        self.fechada = False

    def iter_content(self, chunk_size=1):
        yield from self._pedacos

    def close(self):
        self.fechada = True


def test_request_capped_guarda_o_corpo_para_json_e_text(monkeypatch):
    resposta = requests.Response()
    resposta.status_code = 200
    resposta.iter_content = lambda chunk_size=1: iter([b'{"a":', b" 1}"])
    chamadas = []

    def falso(metodo, url, **kwargs):
        chamadas.append((metodo, url, kwargs))
        return resposta

    monkeypatch.setattr(requests, "request", falso)
    lida = download.request_capped("POST", "http://x/", timeout=5, data={"k": "v"})
    assert lida is resposta and lida.json() == {"a": 1} and lida.text == '{"a": 1}'
    assert chamadas == [("POST", "http://x/", {"stream": True, "timeout": 5, "data": {"k": "v"}})]


def test_request_capped_acima_do_teto_levanta_e_fecha(monkeypatch):
    resposta = _Chega([b"x" * 6, b"x" * 6])
    monkeypatch.setattr(requests, "request", lambda *_a, **_k: resposta)
    with pytest.raises(download.ResponseTooLargeError):
        download.request_capped("GET", "http://x/", max_bytes=10)
    assert resposta.fechada


def test_request_capped_no_teto_exato_passa(monkeypatch):
    resposta = requests.Response()
    resposta.iter_content = lambda chunk_size=1: iter([b"x" * 10])
    monkeypatch.setattr(requests, "request", lambda *_a, **_k: resposta)
    assert download.request_capped("GET", "http://x/", max_bytes=10).content == b"x" * 10


def test_request_capped_fecha_se_a_leitura_falha(monkeypatch):
    class Cai(_Chega):
        def iter_content(self, chunk_size=1):
            yield b"x"
            raise requests.ConnectionError("cortou")

    resposta = Cai([])
    monkeypatch.setattr(requests, "request", lambda *_a, **_k: resposta)
    with pytest.raises(requests.ConnectionError):
        download.request_capped("GET", "http://x/")
    assert resposta.fechada


def test_get_capped_acima_do_teto_levanta_e_fecha(monkeypatch):
    resposta = _Chega([b"x" * 6, b"x" * 6])
    monkeypatch.setattr(download, "_get", lambda *_a, **_k: resposta)
    with pytest.raises(download.ResponseTooLargeError):
        download.get_capped("http://x/", max_bytes=10)
    assert resposta.fechada


# region Progresso e cancelamento


class _Baixando(_Chega):
    """A resposta do `download_bytes`: `with`, cabeçalhos e `raise_for_status`."""

    def __init__(self, pedacos, headers=None):
        super().__init__(pedacos)
        self.headers = headers or {}

    def raise_for_status(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()


def _relogio(monkeypatch, tempos):
    tempos = iter(tempos)
    monkeypatch.setattr(download.time, "monotonic", lambda: next(tempos))


def test_progresso_traz_recebido_e_total(monkeypatch):
    resposta = _Baixando([b"ab", b"cd"], {"Content-Length": "4"})
    monkeypatch.setattr(download, "_get", lambda *_a, **_k: resposta)
    _relogio(monkeypatch, [0.0, 0.5])
    chamadas = []
    conteudo = download.download_bytes(
        "http://x/", ao_progredir=lambda r, t: chamadas.append((r, t))
    )
    assert conteudo == b"abcd"
    assert chamadas == [(2, 4), (4, 4)]


def test_progresso_limitado_a_dez_por_segundo_e_termina_no_total(monkeypatch):
    resposta = _Baixando([b"a"] * 4, {"Content-Length": "4"})
    monkeypatch.setattr(download, "_get", lambda *_a, **_k: resposta)
    _relogio(monkeypatch, [0.0, 0.05, 0.12, 0.13])
    chamadas = []
    download.download_bytes("http://x/", ao_progredir=lambda r, _t: chamadas.append(r))
    assert chamadas == [1, 3, 4]


@pytest.mark.parametrize(
    "cabecalho", [{}, {"Content-Length": "abc"}, {"Content-Length": "0"}]
)
def test_progresso_sem_tamanho_informa_none(monkeypatch, cabecalho):
    monkeypatch.setattr(download, "_get", lambda *_a, **_k: _Baixando([b"ab"], cabecalho))
    _relogio(monkeypatch, [0.0])
    chamadas = []
    download.download_bytes("http://x/", ao_progredir=lambda r, t: chamadas.append((r, t)))
    assert chamadas == [(2, None)]


def test_callback_cancela_e_fecha_a_resposta(monkeypatch):
    resposta = _Baixando([b"a", b"b"], {"Content-Length": "2"})
    monkeypatch.setattr(download, "_get", lambda *_a, **_k: resposta)
    _relogio(monkeypatch, [0.0, 1.0])

    def cancela(_r, _t):
        raise download.DownloadCancelado

    with pytest.raises(download.DownloadCancelado):
        download.download_bytes("http://x/", ao_progredir=cancela)
    assert resposta.fechada
    assert not issubclass(download.DownloadCancelado, requests.RequestException)


def test_sem_callback_nao_le_o_relogio(monkeypatch):
    monkeypatch.setattr(download, "_get", lambda *_a, **_k: _Baixando([b"ab"]))
    monkeypatch.setattr(download.time, "monotonic", lambda: pytest.fail("leu o relógio"))
    assert download.download_bytes("http://x/") == b"ab"


# endregion
