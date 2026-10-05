"""O login pelo navegador: servidor em 127.0.0.1, PKCE, state e prazo."""

import base64
import hashlib
import socket
import urllib.parse
import urllib.request

import pytest

from cartridges.conquistas.xbox import conta, login


@pytest.fixture
def navegador():
    """Guarda a URL que o app mandou abrir, em vez de abrir o navegador."""
    abertas: list[str] = []
    return abertas


def _esperar(pedido, resultados, flush_idle, tempo=5.0):
    pedido._terminou.wait(tempo)
    flush_idle()
    return resultados


def _voltar(pedido, consulta: dict) -> str:
    url = f"http://127.0.0.1:{pedido.porta}/?" + urllib.parse.urlencode(consulta)
    try:
        with urllib.request.urlopen(url, timeout=5) as resposta:
            return resposta.read().decode("utf-8")
    except urllib.error.HTTPError as erro:
        return f"HTTP {erro.code}"


def _parametros(url: str) -> dict:
    return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}


def test_url_tem_pkce_state_e_retorno_local(navegador, flush_idle):
    pedido = login.entrar(lambda _r: None, abrir=navegador.append)
    try:
        p = _parametros(navegador[0])
        assert navegador[0].startswith(conta.AUTORIZAR)
        assert p["client_id"] == conta.CLIENT_ID and p["scope"] == conta.ESCOPO
        assert p["response_type"] == "code" and p["code_challenge_method"] == "S256"
        assert p["redirect_uri"].startswith(f"http://localhost:{pedido.porta}")
        assert len(p["state"]) >= 16
    finally:
        pedido.cancelar()


def test_codigo_certo_conecta(monkeypatch, navegador, flush_idle):
    recebido = {}
    monkeypatch.setattr(conta, "conectar", lambda c, v, r: recebido.update(c=c, v=v, r=r))
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append)
    p = _parametros(navegador[0])
    assert _voltar(pedido, {"code": "COD", "state": p["state"]}).find(login.TEXTO_OK) >= 0
    assert _esperar(pedido, resultados, flush_idle) == [login.Resultado.OK]
    desafio = base64.urlsafe_b64encode(hashlib.sha256(recebido["v"].encode()).digest()).rstrip(b"=").decode()
    assert recebido["c"] == "COD" and desafio == p["code_challenge"]
    assert recebido["r"] == p["redirect_uri"]


def test_state_errado_e_ignorado(monkeypatch, navegador, flush_idle):
    monkeypatch.setattr(conta, "conectar", lambda *_a: pytest.fail("trocou código alheio"))
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append)
    assert _voltar(pedido, {"code": "X", "state": "outro"}) == "HTTP 400"
    flush_idle()
    assert resultados == []
    pedido.cancelar()
    assert _esperar(pedido, resultados, flush_idle) == [login.Resultado.CANCELADO]


def test_erro_na_volta_cancela(navegador, flush_idle):
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append)
    estado = _parametros(navegador[0])["state"]
    assert login.TEXTO_FALHOU in _voltar(pedido, {"error": "access_denied", "state": estado})
    assert _esperar(pedido, resultados, flush_idle) == [login.Resultado.CANCELADO]


@pytest.mark.parametrize(
    "erro, esperado",
    [
        (conta.SemPerfilXbox(), login.Resultado.SEM_PERFIL_XBOX),
        (conta.ContaInfantil(), login.Resultado.CONTA_INFANTIL),
        (conta.Recusada(), login.Resultado.FALHOU),
        (ValueError("x"), login.Resultado.FALHOU),
    ],
)
def test_falha_na_troca(monkeypatch, navegador, flush_idle, erro, esperado):
    def falha(*_a):
        raise erro

    monkeypatch.setattr(conta, "conectar", falha)
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append)
    estado = _parametros(navegador[0])["state"]
    assert login.TEXTO_FALHOU in _voltar(pedido, {"code": "C", "state": estado})
    assert _esperar(pedido, resultados, flush_idle) == [esperado]


def test_prazo_esgotado_cancela_e_fecha(navegador, flush_idle):
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append, prazo=0.3)
    assert _esperar(pedido, resultados, flush_idle) == [login.Resultado.CANCELADO]
    with pytest.raises(OSError):
        urllib.request.urlopen(f"http://127.0.0.1:{pedido.porta}/", timeout=1)


def test_conexao_ociosa_nao_impede_o_prazo(navegador, flush_idle):
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append, prazo=0.5)
    with socket.create_connection(("127.0.0.1", pedido.porta), timeout=5):
        assert _esperar(pedido, resultados, flush_idle, tempo=3.0) == [login.Resultado.CANCELADO]
        with pytest.raises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{pedido.porta}/", timeout=1)


def test_conexao_ociosa_nao_segura_a_volta_real(monkeypatch, navegador, flush_idle):
    chamadas = []
    monkeypatch.setattr(conta, "conectar", lambda c, v, r: chamadas.append(c))
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append)
    estado = _parametros(navegador[0])["state"]
    with socket.create_connection(("127.0.0.1", pedido.porta), timeout=5):
        assert login.TEXTO_OK in _voltar(pedido, {"code": "COD", "state": estado})
        assert _esperar(pedido, resultados, flush_idle) == [login.Resultado.OK]
    assert chamadas == ["COD"]


def test_volta_repetida_troca_o_codigo_uma_vez(monkeypatch, navegador, flush_idle):
    chamadas = []
    monkeypatch.setattr(conta, "conectar", lambda c, v, r: chamadas.append(c))
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append)
    estado = _parametros(navegador[0])["state"]
    pedido._trocando = True  # outra volta já está trocando o código
    assert _voltar(pedido, {"code": "COD", "state": estado}) == "HTTP 400"
    assert chamadas == []
    pedido.cancelar()
    assert _esperar(pedido, resultados, flush_idle) == [login.Resultado.CANCELADO]


def test_cancelar_duas_vezes_termina_uma(navegador, flush_idle):
    resultados = []
    pedido = login.entrar(resultados.append, abrir=navegador.append)
    pedido.cancelar()
    pedido.cancelar()
    login.cancelar_pendente()
    assert _esperar(pedido, resultados, flush_idle) == [login.Resultado.CANCELADO]


def test_navegador_que_nao_abre_falha(flush_idle):
    def quebra(_url):
        raise OSError("sem navegador")

    resultados = []
    pedido = login.entrar(resultados.append, abrir=quebra)
    assert _esperar(pedido, resultados, flush_idle) == [login.Resultado.FALHOU]
