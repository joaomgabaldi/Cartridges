"""Os ícones das conquistas: baixados uma vez, guardados no cache, entregues como arquivo na thread principal."""

import socket
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests
from PySide6.QtGui import QColor, QImage, QImageReader
from requests.exceptions import ConnectionError as ErroDeConexao

from kyron import shared
from kyron.conquistas import arquivos, aviso_da_conta, icones
from kyron.utils.thread_principal import eh_thread_principal

URL = "https://cdn.exemplo.com/a.jpg?key=SEGREDO"


@pytest.fixture
def executor_proprio(monkeypatch):
    """Um executor novo por teste: ``encerrar`` não pode vazar para os outros."""
    executor = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(icones, "_trabalhadores", executor)
    yield executor
    executor.shutdown(wait=False, cancel_futures=True)


@pytest.fixture
def carregar_e_esperar(monkeypatch, flush_idle):
    """Carrega ``origem`` de verdade e devolve o que foi entregue (espera a thread e a fila da principal)."""

    def carregar(origem):
        executor = ThreadPoolExecutor(max_workers=1)
        monkeypatch.setattr(icones, "_trabalhadores", executor)
        entregues = []
        icones.carregar(origem, entregues.append)
        executor.shutdown(wait=True)
        flush_idle()
        return entregues

    return carregar


def _png(caminho, largura, altura):
    imagem = QImage(largura, altura, QImage.Format.Format_ARGB32)
    imagem.fill(QColor("red"))
    assert imagem.save(str(caminho), "PNG")
    return caminho


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
    threads = [threading.Thread(target=lambda: resultados.append(icones.arquivo_local(URL))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert len(resultados) == 2 and all(r is not None for r in resultados)
    assert resultados[0] == resultados[1]
    assert resultados[0].read_bytes() == b"dados"
    assert not list(resultados[0].parent.glob("*.tmp"))


@pytest.mark.parametrize("erro", [OSError("disco"), RuntimeError("rede"), RecursionError()])
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


@pytest.mark.parametrize("origem", [r"\\servidor\pasta\x.png", "//servidor/pasta/x.png", r"\\?\UNC\srv\x.png"])
def test_icone_em_caminho_de_rede_nao_toca_no_disco(monkeypatch, carregar_e_esperar, origem):
    tocou = []

    def is_file(self, *_a, **_k):
        # `_resolver` engole qualquer exceção: o registro é o que prova o acesso.
        tocou.append(str(self))
        return False

    monkeypatch.setattr(Path, "is_file", is_file)
    assert icones.arquivo_local(origem) is None
    assert carregar_e_esperar(origem) == []
    assert tocou == []


def test_arquivo_ilegivel_no_cache_e_apagado(monkeypatch, carregar_e_esperar, caplog):
    monkeypatch.setattr(icones, "download_bytes", lambda *_a, **_k: b"<html>portal</html>")
    arquivo = icones.arquivo_local(URL)
    assert arquivo is not None and arquivo.is_file()

    with caplog.at_level("DEBUG"):
        assert carregar_e_esperar(URL) == []
    assert not arquivo.exists()
    # Ilegível é falha esperada (um portal de rede serve HTML no lugar do ícone): info, sem traceback.
    assert not [r for r in caplog.records if r.levelno >= 30]
    assert "SEGREDO" not in caplog.text


def test_icone_com_corpo_ruim_sai_do_cache(tmp_path, monkeypatch, carregar_e_esperar):
    """Só a assinatura do PNG: o `canRead` aceita, a decodificação não."""
    bom = _png(tmp_path / "bom.png", 8, 8).read_bytes()
    ruim = bom[:8] + b"\x00" * 16
    monkeypatch.setattr(icones, "download_bytes", lambda *_a, **_k: ruim)
    arquivo = icones.arquivo_local(URL)
    assert arquivo is not None and arquivo.is_file()
    assert QImageReader(str(arquivo)).canRead()
    assert not icones._legivel(arquivo)  # noqa: SLF001
    assert carregar_e_esperar(URL) == []
    assert not arquivo.exists()


def test_arquivo_local_ilegivel_nao_e_apagado(tmp_path, carregar_e_esperar):
    arquivo = tmp_path / "icone.png"
    arquivo.write_bytes(b"nao e imagem")
    assert carregar_e_esperar(str(arquivo)) == []
    assert arquivo.exists()


@pytest.mark.parametrize("largura, altura", [(208, 117), (208, 208), (117, 208)])
def test_icone_nao_quadrado_e_entregue_inteiro(tmp_path, carregar_e_esperar, largura, altura):
    # O corte no quadrado central é do QML: o domínio entrega o arquivo como veio.
    arquivo = _png(tmp_path / "i.png", largura, altura)
    assert carregar_e_esperar(str(arquivo)) == [arquivo]
    assert QImage(str(arquivo)).width() == largura


def test_entrega_chega_na_thread_principal(tmp_path, monkeypatch, flush_idle):
    arquivo = _png(tmp_path / "i.png", 8, 8)
    executor = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(icones, "_trabalhadores", executor)
    ondes = []
    icones.carregar(str(arquivo), lambda _caminho: ondes.append(eh_thread_principal()))
    executor.shutdown(wait=True)
    assert ondes == []  # só sai pela fila da thread principal
    flush_idle()
    assert ondes == [True]


def test_carregar_depois_de_encerrar_nao_faz_nada(executor_proprio, monkeypatch):
    baixou = []
    monkeypatch.setattr(icones, "download_bytes", lambda *_a, **_k: baixou.append(1) or b"")
    entregues = []

    icones.encerrar()
    icones.carregar(URL, entregues.append)

    assert not baixou
    assert not entregues


def test_encerrar_nunca_levanta(executor_proprio, monkeypatch):
    def quebrar(*_a, **_k):
        raise RuntimeError("falha")

    with monkeypatch.context() as parcial:
        parcial.setattr(executor_proprio, "shutdown", quebrar)
        icones.encerrar()


def test_desconexao_avisa_pela_fila_e_atualiza_as_telas(avisos, monkeypatch):
    mudou = []
    monkeypatch.setattr(shared, "conquistas", SimpleNamespace(mudou=mudou.append))
    ja = aviso_da_conta.notificar(True, False, [], "A conta caiu.", "Teste")
    assert ja is True
    assert avisos.textos == ["A conta caiu."]
    assert mudou == [None]


def test_sem_aplicativo_nao_levanta(monkeypatch):
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    assert aviso_da_conta.notificar(True, False, [], "A conta caiu.", "Teste") is False


def test_conftest_bloqueia_a_rede(monkeypatch):
    def sem_dns(*_a, **_k):
        raise AssertionError("a resolução de nomes não devia ser alcançada")

    monkeypatch.setattr(socket, "getaddrinfo", sem_dns)
    with pytest.raises(requests.ConnectionError, match="rede bloqueada nos testes"):
        requests.get("https://example.invalid", timeout=1)


def test_laco_local_passa_pelo_guarda_sem_proxy(monkeypatch):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: PLC0415

    class Resposta(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *_args):
            pass

    servico = ThreadingHTTPServer(("127.0.0.1", 0), Resposta)
    threading.Thread(target=servico.serve_forever, daemon=True).start()
    try:
        # Um proxy de ambiente (morto) não pode receber o tráfego do laço local.
        monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
        monkeypatch.delenv("NO_PROXY", raising=False)
        monkeypatch.delenv("no_proxy", raising=False)
        assert requests.get(f"http://127.0.0.1:{servico.server_port}/", timeout=5).content == b"ok"
    finally:
        servico.shutdown()
        servico.server_close()


def test_documentos_do_sistema_sem_gi():
    documentos = arquivos.pastas_do_sistema().documentos
    assert isinstance(documentos, Path) and documentos.is_absolute()


def test_modulos_sem_gi():
    modulos = [
        "kyron.conquistas.arquivos",
        "kyron.conquistas.aviso_da_conta",
        "kyron.conquistas.icones",
        "kyron.conquistas.ea.conta",
        "kyron.conquistas.epic.conta",
        "kyron.conquistas.xbox.conta",
        "kyron.conquistas.xbox.login",
        "kyron.conquistas.vigia",
        "kyron.conquistas.vigia_da_conta",
        "kyron.conquistas.ubisoft.vigia",
        "kyron.conquistas.varredura",
        "kyron.conquistas.sessao",
        "kyron.conquista_aviso",
    ]
    codigo = "import builtins, sys\nbuiltins._ = lambda m: m\n"
    codigo += "".join(f"import {m}\n" for m in modulos) + "assert 'gi' not in sys.modules\n"
    # O ambiente do subprocesso herda `KYRON_DADOS`/`KYRON_REGISTRO` temporários do conftest.
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], capture_output=True, text=True, timeout=120, cwd=Path(__file__).parent.parent
    )
    assert resultado.returncode == 0, resultado.stderr
