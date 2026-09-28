"""As consultas online reaproveitam a conexão da thread e não carregam cookie."""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

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
