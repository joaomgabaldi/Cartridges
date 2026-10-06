"""A conta Epic: código colado, guarda com DPAPI, chave girada, desconexão."""

import json
import threading
import time

import pytest

from cartridges import shared
from cartridges.conquistas.epic import conta
from tests.apoio_xbox import Resposta, RespostaSemFim, rede_falsa

_COD = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def limpa(monkeypatch):
    monkeypatch.setattr(conta, "_sessao", None)
    monkeypatch.setattr(conta, "_avisou", False)
    monkeypatch.setattr(conta, "_ouvintes", [])
    monkeypatch.setattr(conta, "_em_segundo_plano", lambda funcao, *args: funcao(*args))


def _token(renovacao="R1", acesso="A1", nome="Jogador", conta_id="c" * 32):
    return Resposta(200, {
        "access_token": acesso, "expires_at": "2099-01-01T00:00:00.000Z", "expires_in": 7200,
        "refresh_token": renovacao, "refresh_expires": 2592000,
        "account_id": conta_id, "displayName": nome, "token_type": "bearer",
    })


def _recusa(codigo="errors.com.epicgames.account.oauth.authorization_code_not_found"):
    return Resposta(400, {"errorCode": codigo, "error": "invalid_grant", "errorMessage": "x"})


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        (_COD, _COD),
        (f'  "{_COD}"  ', _COD),
        (json.dumps({"redirectUrl": "x", "authorizationCode": _COD, "sid": "f" * 32}), _COD),
        (json.dumps({"authorizationCode": None, "sid": "f" * 32}), None),
        ('{"warning": "x", "authorizationCode": "' + _COD + '", "sid"', _COD),  # JSON cortado
        ("f" * 32 + " " + _COD, None),  # dois códigos soltos: nenhum
        ("lixo", None),
        ("", None),
        # `id` curto: o pytest usa o texto como nome do teste, e no Windows uma
        # variável de ambiente não passa de 32767 caracteres.
        pytest.param("a" * 100_000, None, id="texto-enorme"),
    ],
)
def test_extrair_codigo(texto, esperado):
    assert conta.extrair_codigo(texto) == esperado


def test_conectar_guarda_cifrado_e_conecta(monkeypatch):
    chamadas = rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(renovacao="RENOVACAO-SECRETA")]}, nome="_pedir")
    conta.conectar(_COD)
    assert conta.conectada() and conta.nome() == "Jogador" and conta.account_id() == "c" * 32
    texto = (shared.contas_dir / "epic.json").read_text(encoding="utf-8")
    # Um texto distintivo: "R1" aparece por acaso no base64 de vez em quando.
    assert "RENOVACAO-SECRETA" not in texto and json.loads(texto)["conta"] == "c" * 32
    _url, kwargs = chamadas[0]
    assert kwargs["data"]["grant_type"] == "authorization_code" and kwargs["data"]["token_type"] == "eg1"
    assert kwargs["auth"] == (conta.CLIENT_ID, conta.SEGREDO)


def test_validade_com_inteiro_enorme_vira_uma_hora(monkeypatch):
    """`float(10**400)` levanta OverflowError: cai no padrão de 1 h e a conta conecta."""
    corpo = {**_token().json(), "expires_in": 10**400}
    del corpo["expires_at"]
    assert 3000 < conta._vence(corpo) - time.time() <= 3600
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [Resposta(200, corpo)]}, nome="_pedir")
    conta.conectar(_COD)
    assert conta.conectada()


def test_conectar_apaga_a_biblioteca_da_conta_anterior(monkeypatch):
    """A biblioteca é de uma conta: outra conta não herda o "fora da biblioteca" da primeira."""
    shared.conquistas_cache_dir.mkdir(parents=True)
    biblioteca = shared.conquistas_cache_dir / "epic.biblioteca.json"
    catalogo = shared.conquistas_cache_dir / "epic-ns1.json"
    biblioteca.write_text('{"apps": {}, "em": 1}', encoding="utf-8")
    catalogo.write_text("{}", encoding="utf-8")
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token()]}, nome="_pedir")
    conta.conectar(_COD)
    assert conta.conectada()
    assert not biblioteca.exists() and catalogo.exists()


def test_conectar_sem_biblioteca_ou_com_erro_ao_apagar_conecta_assim_mesmo(monkeypatch):
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(), _token()]}, nome="_pedir")
    conta.conectar(_COD)  # sem arquivo: missing_ok
    assert conta.conectada()

    def nega(*_a, **_k):
        raise PermissionError("negado")

    monkeypatch.setattr("pathlib.Path.unlink", nega)
    conta.conectar(_COD)
    assert conta.conectada()


def test_codigo_recusado(monkeypatch):
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_recusa()]}, nome="_pedir")
    with pytest.raises(conta.CodigoRecusado):
        conta.conectar(_COD)
    assert not conta.conectada()


def test_carregar_abre_o_que_foi_guardado(monkeypatch):
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token()]}, nome="_pedir")
    conta.conectar(_COD)
    monkeypatch.setattr(conta, "_sessao", None)
    conta.carregar()
    assert conta.conectada() and conta.nome() == "Jogador"


@pytest.mark.parametrize(
    "conteudo",
    ["não é json", '{"nome": "J", "conta": "c", "renovacao": "@@@"}', '{"nome": "J", "renovacao": "QUJD"}', "[]"],
)
def test_arquivo_ruim_e_nao_conectada(conteudo):
    shared.contas_dir.mkdir(parents=True)
    (shared.contas_dir / "epic.json").write_text(conteudo, encoding="utf-8")
    conta.carregar()
    assert not conta.conectada()


def test_token_valido_nao_vai_a_rede(monkeypatch):
    chamadas = rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token()]}, nome="_pedir")
    conta.conectar(_COD)
    assert conta.autorizacao() == "A1"
    assert len(chamadas) == 1


def test_renovar_grava_a_chave_girada(monkeypatch):
    rede_falsa(
        monkeypatch, conta, {conta.TOKEN: [_token(), _token(renovacao="R2", acesso="A2")]}, nome="_pedir"
    )
    conta.conectar(_COD)
    assert conta.autorizacao(forcar=True) == "A2"
    monkeypatch.setattr(conta, "_sessao", None)
    conta.carregar()
    assert conta._sessao.renovacao == "R2"


def test_duas_renovacoes_simultaneas_usam_a_chave_uma_vez(monkeypatch):
    usadas = []
    portao = threading.Event()

    def pedir(_metodo, url, **kwargs):
        dados = kwargs["data"]
        if dados["grant_type"] == "authorization_code":
            return Resposta(200, {**_token(acesso="A0").json(), "expires_at": "2000-01-01T00:00:00.000Z"})
        usadas.append(dados["refresh_token"])
        portao.wait(2)
        return _token(renovacao=f"R{len(usadas) + 1}", acesso=f"A{len(usadas) + 1}")

    monkeypatch.setattr(conta, "_pedir", pedir)
    conta.conectar(_COD)
    resultados = []
    linhas = [threading.Thread(target=lambda: resultados.append(conta.autorizacao())) for _ in range(2)]
    for linha in linhas:
        linha.start()
    portao.set()
    for linha in linhas:
        linha.join(5)
    assert usadas == ["R1"]
    assert resultados == ["A2", "A2"]


def test_renovacao_recusada_desconecta_e_avisa_uma_vez(monkeypatch, flush_idle, win):
    rede_falsa(
        monkeypatch, conta,
        {conta.TOKEN: [_token(), _recusa("errors.com.epicgames.account.auth_token.invalid_refresh_token")]},
        nome="_pedir",
    )
    conta.conectar(_COD)
    assert conta.autorizacao(forcar=True) is None
    flush_idle()
    assert not conta.conectada() and not (shared.contas_dir / "epic.json").exists()
    conta.recusada()
    flush_idle()
    textos = [t.get_title() for t in win.toast_queue.added]
    assert textos.count("A conta Epic foi desconectada. Entre novamente nas Preferências.") == 1


def test_rede_fora_na_renovacao_fica_conectada(monkeypatch):
    import requests  # noqa: PLC0415

    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(), requests.ConnectionError("x")]}, nome="_pedir")
    conta.conectar(_COD)
    assert conta.autorizacao(forcar=True) is None
    assert conta.conectada()


def test_sair_esquece_e_tenta_encerrar_a_sessao(monkeypatch):
    chamadas = rede_falsa(
        monkeypatch, conta, {conta.TOKEN: [_token()], conta.ENCERRAR: [Resposta(204)]}, nome="_pedir"
    )
    conta.conectar(_COD)
    conta.sair()
    assert not conta.conectada() and not (shared.contas_dir / "epic.json").exists()
    assert chamadas[-1][0].startswith(conta.ENCERRAR)


def test_sair_com_rede_fora_nao_levanta(monkeypatch):
    import requests  # noqa: PLC0415

    rede_falsa(
        monkeypatch, conta, {conta.TOKEN: [_token()], conta.ENCERRAR: [requests.ConnectionError("x")]},
        nome="_pedir",
    )
    conta.conectar(_COD)
    conta.sair()
    assert not conta.conectada()


def test_error_code_enorme_vai_ao_log_com_teto(monkeypatch, caplog):
    """O `errorCode` é um valor da Epic, sem limite de tamanho."""
    caplog.set_level("DEBUG")
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_recusa("x" * 5000)]}, nome="_pedir")
    with pytest.raises(conta.CodigoRecusado):
        conta.conectar(_COD)
    assert "x" * 120 in caplog.text and "x" * 121 not in caplog.text


def test_nada_secreto_no_log(monkeypatch, caplog):
    caplog.set_level("DEBUG")
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(), _recusa()]}, nome="_pedir")
    conta.conectar(_COD)
    conta.autorizacao(forcar=True)
    for segredo in (_COD, "A1", "R1", "c" * 32):
        assert segredo not in caplog.text


def test_corpo_sem_fim_na_renovacao_e_rede_fora_e_continua_conectada(monkeypatch, caplog):
    import logging  # noqa: PLC0415
    import requests  # noqa: PLC0415

    caplog.set_level(logging.DEBUG)
    pedir = conta._pedir
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(renovacao="RENOVACAO-SECRETA")]}, nome="_pedir")
    conta.conectar(_COD)
    sem_fim = RespostaSemFim()
    monkeypatch.setattr(conta, "_pedir", pedir)
    monkeypatch.setattr(requests, "request", lambda *_a, **_k: sem_fim)
    assert conta.autorizacao(forcar=True) is None
    assert sem_fim.fechada and conta.conectada()
    assert "ResponseTooLargeError" in caplog.text and "RENOVACAO-SECRETA" not in caplog.text


def test_corpo_sem_fim_no_login_levanta_erro_de_rede(monkeypatch):
    import requests  # noqa: PLC0415

    sem_fim = RespostaSemFim()
    monkeypatch.setattr(requests, "request", lambda *_a, **_k: sem_fim)
    with pytest.raises(requests.RequestException):
        conta.conectar(_COD)
    assert sem_fim.fechada and not conta.conectada()
