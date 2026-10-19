"""A conta EA: cookies colados, guarda com DPAPI, `remid` de uso único, desconexão."""

import base64
import json
import threading
import time

import pytest
import requests

from cartridges import shared
from cartridges.conquistas.ea import conta
from cartridges.utils import dpapi
from tests.apoio_xbox import Resposta, rede_falsa

_AVISO = "A conta EA foi desconectada. Entre novamente nas Preferências."


@pytest.fixture(autouse=True)
def limpa(monkeypatch):
    monkeypatch.setattr(conta, "_sessao", None)
    monkeypatch.setattr(conta, "_avisou", False)
    monkeypatch.setattr(conta, "_ouvintes", [])
    monkeypatch.setattr(conta, "_pendente", None)
    monkeypatch.setattr(conta, "_sem_gravar", False)


class _Resp(Resposta):
    """Uma `Resposta` com os cookies que a EA devolve em `Set-Cookie`."""

    def __init__(self, status, corpo=None, cookies=None):
        super().__init__(status, corpo)
        self.cookies = cookies or {}


def _token(acesso="TOK1", remid="R2", expira="14399"):
    return _Resp(200, {"access_token": acesso, "token_type": "Bearer", "expires_in": expira},
                 {"remid": remid} if remid else {})


def _recusa():
    return _Resp(200, {"error": "login_required"})


def _identidade(pid=1, persona=2, nome="Fulano"):
    return {
        conta.IDENTIDADE + "/pids/me": [Resposta(200, {"pid": {"pidId": pid}})],
        f"{conta.IDENTIDADE}/pids/{pid}/personas": [
            Resposta(200, {"personas": {"persona": [{"personaId": persona, "displayName": nome}]}})
        ],
    }


def _login(monkeypatch, *tokens, **identidade):
    """Conecta com `tokens` na fila do TOKEN; devolve as chamadas feitas."""
    fila = {conta.TOKEN: list(tokens) or [_token()], **_identidade(**identidade)}
    chamadas = rede_falsa(monkeypatch, conta, fila, nome="_pedir")
    conta.conectar("remid=R1; _nx_mpcid=N1")
    return chamadas


def _guardado():
    dados = json.loads((shared.contas_dir / "ea.json").read_text(encoding="utf-8"))
    return dados, json.loads(dpapi.abrir(base64.b64decode(dados["cookies"])))


# ---- extrair ---------------------------------------------------------------


def test_extrair_curl_bash():
    texto = "curl 'https://x' -H 'user-agent: UA-NAV' -b 'remid=R1; sid=S; _nx_mpcid=N1'"
    assert conta.extrair(texto) == conta.Cookies("R1", "N1")


def test_extrair_curl_cmd():
    texto = 'curl ^"https://x^" ^\n  -b ^"remid=R^%3D1; sid=S; _nx_mpcid=N^%2B1^" ^\n  -H ^"a: b^"'
    assert conta.extrair(texto) == conta.Cookies("R%3D1", "N%2B1")


def test_extrair_cabecalho_cookie_solto():
    assert conta.extrair("Cookie: _nx_mpcid=N1; remid=R1") == conta.Cookies("R1", "N1")


def test_extrair_sem_um_dos_cookies():
    assert conta.extrair("Cookie: remid=R1; sid=S") is None
    assert conta.extrair("Cookie: _nx_mpcid=N1") is None


def test_extrair_primeiro_valor_e_valor_com_igual():
    texto = "-b 'remid=R1; _nx_mpcid=A=B%3D' -H 'Cookie: remid=R9; _nx_mpcid=Z'"
    assert conta.extrair(texto) == conta.Cookies("R1", "A=B%3D")


def test_extrair_ignora_nome_que_termina_em_remid():
    assert conta.extrair("Cookie: ak_remid=X; xremid=Y; remid=R1; _nx_mpcid=N1") == conta.Cookies("R1", "N1")
    assert conta.extrair("Cookie: ak_remid=X; x_nx_mpcid=Y; _nx_mpcid=N1") is None
    assert conta.extrair("Cookie: remid=R1; x_nx_mpcid=Y") is None


def test_extrair_texto_grande_ou_nao_texto():
    assert conta.extrair("remid=R1; _nx_mpcid=N1 " + "a" * (64 * 1024)) is None
    assert conta.extrair(None) is None
    assert conta.extrair(123) is None


# ---- conectar, guarda e carregar -------------------------------------------


def test_conectar_grava_e_publica(monkeypatch):
    chamadas = _login(monkeypatch)
    assert conta.conectada() and conta.nome() == "Fulano" and conta.persona() == "2"
    dados, cookies = _guardado()
    assert cookies == {"remid": "R2", "nx_mpcid": "N1"}
    assert dados["nome"] == "Fulano" and dados["persona"] == "2"
    # a renovação pede com o User-Agent do EA app e os dois cookies, sem seguir redirecionamento
    url, kwargs = chamadas[0]
    assert url == conta.TOKEN and kwargs["allow_redirects"] is False
    assert kwargs["headers"]["User-Agent"] == conta.UA
    assert kwargs["headers"]["Cookie"] == "remid=R1; _nx_mpcid=N1"
    # a identidade usa o token de acesso; só as personas pedem a expansão
    assert chamadas[1][1]["headers"]["Authorization"] == "Bearer TOK1"
    assert "X-Expand-Results" not in chamadas[1][1]["headers"]
    assert chamadas[2][1]["headers"]["X-Expand-Results"] == "true"


def test_conectar_que_nao_grava_levanta_oserror(monkeypatch):
    def falha(*_a):
        raise OSError("disco")

    monkeypatch.setattr(conta, "gravar_atomico", falha)
    with pytest.raises(OSError):
        _login(monkeypatch)
    assert not conta.conectada()


def test_conectar_que_falha_depois_da_renovacao_reaproveita_o_remid_novo(monkeypatch):
    # O R1 colado foi gasto na renovação; a falha em pids/me não pode perder o R2.
    rede_falsa(monkeypatch, conta, {
        conta.TOKEN: [_token(acesso="TOK1", remid="R2")],
        conta.IDENTIDADE + "/pids/me": [Resposta(500)],
    }, nome="_pedir")
    with pytest.raises(requests.RequestException):
        conta.conectar("remid=R1; _nx_mpcid=N1")
    assert not conta.conectada()
    # O usuário tenta de novo com o mesmo texto colado (o R1, já gasto).
    fila = {conta.TOKEN: [_token(acesso="TOK2", remid="R3")], **_identidade()}
    chamadas = rede_falsa(monkeypatch, conta, fila, nome="_pedir")
    conta.conectar("remid=R1; _nx_mpcid=N1")
    assert chamadas[0][1]["headers"]["Cookie"] == "remid=R2; _nx_mpcid=N1"
    assert conta.conectada() and _guardado()[1]["remid"] == "R3"


def test_conectar_que_nao_grava_reaproveita_o_remid_novo(monkeypatch):
    def falha(*_a):
        raise OSError("disco")

    with monkeypatch.context() as parcial:
        parcial.setattr(conta, "gravar_atomico", falha)
        with pytest.raises(OSError):
            _login(parcial, _token(acesso="TOK1", remid="R2"))
    fila = {conta.TOKEN: [_token(acesso="TOK2", remid="R3")], **_identidade()}
    chamadas = rede_falsa(monkeypatch, conta, fila, nome="_pedir")
    conta.conectar("remid=R1; _nx_mpcid=N1")
    assert chamadas[0][1]["headers"]["Cookie"] == "remid=R2; _nx_mpcid=N1"


def test_conectar_com_outro_remid_nao_usa_o_pendente(monkeypatch):
    rede_falsa(monkeypatch, conta, {
        conta.TOKEN: [_token(remid="R2")], conta.IDENTIDADE + "/pids/me": [Resposta(500)],
    }, nome="_pedir")
    with pytest.raises(requests.RequestException):
        conta.conectar("remid=R1; _nx_mpcid=N1")
    chamadas = rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(remid="R9")], **_identidade()}, nome="_pedir")
    conta.conectar("remid=NOVO; _nx_mpcid=N7")
    assert chamadas[0][1]["headers"]["Cookie"] == "remid=NOVO; _nx_mpcid=N7"


def test_conectar_texto_sem_cookies_levanta_value_error():
    with pytest.raises(ValueError):
        conta.conectar("nada de cookies")
    assert not conta.conectada()


def test_conectar_login_required_levanta(monkeypatch):
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_recusa()]}, nome="_pedir")
    with pytest.raises(conta.LoginRecusado):
        conta.conectar("remid=R1; _nx_mpcid=N1")
    assert not conta.conectada() and not (shared.contas_dir / "ea.json").exists()


@pytest.mark.parametrize("corpo", [{"pid": {}}, {"pid": {"pidId": "../x"}}, [], {"pid": 3}])
def test_conectar_identidade_fora_do_formato_levanta(monkeypatch, corpo):
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token()], conta.IDENTIDADE: [Resposta(200, corpo)]},
               nome="_pedir")
    with pytest.raises((ValueError, KeyError)):
        conta.conectar("remid=R1; _nx_mpcid=N1")
    assert not conta.conectada()


def test_carregar_abre_o_que_foi_guardado(monkeypatch):
    _login(monkeypatch)
    monkeypatch.setattr(conta, "_sessao", None)
    conta.carregar()
    assert conta.conectada() and conta.nome() == "Fulano" and conta.persona() == "2"


@pytest.mark.parametrize(
    "conteudo",
    ["não é json", "[]", '{"nome": "J", "persona": "2", "cookies": "@@@"}', '{"nome": "J", "cookies": "QUJD"}'],
)
def test_carregar_arquivo_ilegivel(conteudo, win, flush_idle):
    shared.contas_dir.mkdir(parents=True)
    (shared.contas_dir / "ea.json").write_text(conteudo, encoding="utf-8")
    conta.carregar()
    flush_idle()
    assert not conta.conectada() and not win.toast_queue.added


# ---- renovação -------------------------------------------------------------


def test_renovacao_grava_o_remid_novo_antes_do_token(monkeypatch):
    _login(monkeypatch, _token(acesso="TOK1", remid="R2"))
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(acesso="TOK2", remid="R3")]}, nome="_pedir")
    ordem = []
    salvar = conta._salvar

    def espiao(sessao):
        # quando grava, o token novo ainda não foi publicado
        ordem.append(("salvou", sessao.remid, conta._sessao.acesso.valor))
        salvar(sessao)

    monkeypatch.setattr(conta, "_salvar", espiao)
    assert conta.autorizacao(forcar=True) == "TOK2"
    ordem.append("devolveu")
    assert ordem == [("salvou", "R3", "TOK1"), "devolveu"]
    assert _guardado()[1]["remid"] == "R3"


def _disco_falha(monkeypatch):
    """Faz o `gravar_atomico` da conta falhar; `estado["falha"] = False` volta ao normal."""
    estado = {"falha": True}
    original = conta.gravar_atomico

    def gravar(destino, conteudo, **kw):
        if estado["falha"]:
            raise PermissionError("em uso")
        return original(destino, conteudo, **kw)

    monkeypatch.setattr(conta, "gravar_atomico", gravar)
    return estado


def test_renovacao_que_nao_grava_mantem_o_remid_novo_na_sessao(monkeypatch):
    _login(monkeypatch)
    estado = _disco_falha(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(acesso="TOK2", remid="R3")]}, nome="_pedir")
    assert conta.autorizacao(forcar=True) == "TOK2"
    assert conta.conectada() and conta._sessao.remid == "R3" and conta._sem_gravar
    assert _guardado()[1]["remid"] == "R2"


def test_renovacao_seguinte_grava_e_limpa_a_marca(monkeypatch):
    _login(monkeypatch)
    estado = _disco_falha(monkeypatch)
    rede_falsa(
        monkeypatch, conta,
        {conta.TOKEN: [_token(acesso="TOK2", remid="R3"), _token(acesso="TOK3", remid=None)]},
        nome="_pedir",
    )
    conta.autorizacao(forcar=True)
    estado["falha"] = False
    assert conta.autorizacao(forcar=True) == "TOK3"
    assert not conta._sem_gravar and _guardado()[1]["remid"] == "R3"


def test_gravar_pendente_grava_no_encerramento(monkeypatch):
    _login(monkeypatch)
    estado = _disco_falha(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(acesso="TOK2", remid="R3")]}, nome="_pedir")
    conta.autorizacao(forcar=True)
    assert conta.gravar_pendente() is False and conta._sem_gravar
    estado["falha"] = False
    assert conta.gravar_pendente() is True
    assert not conta._sem_gravar and _guardado()[1]["remid"] == "R3"


def test_gravacao_ok_nao_marca_nada(monkeypatch):
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(acesso="TOK2", remid="R3")]}, nome="_pedir")
    conta.autorizacao(forcar=True)
    assert not conta._sem_gravar and conta.gravar_pendente() is True
    assert _guardado()[1]["remid"] == "R3"


def test_renovacao_sem_remid_novo_mantem_o_atual(monkeypatch):
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(acesso="TOK2", remid=None)]}, nome="_pedir")
    assert conta.autorizacao(forcar=True) == "TOK2"
    assert _guardado()[1]["remid"] == "R2"


def test_expires_in_invalido_vira_uma_hora(monkeypatch):
    _login(monkeypatch, _token(expira="abc"))
    assert 3000 < conta._sessao.acesso.vence - time.time() <= 3600


def test_renova_com_menos_de_5_min(monkeypatch):
    chamadas = _login(monkeypatch, _token(expira="14399"))
    assert conta.autorizacao() == "TOK1"
    assert [u for u, _k in chamadas].count(conta.TOKEN) == 1
    # Perto do vencimento, a próxima leitura renova.
    conta._sessao.acesso.vence -= 14399 - 200
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(acesso="TOK2", remid="R3")]}, nome="_pedir")
    assert conta.autorizacao() == "TOK2"


def test_duas_renovacoes_simultaneas_usam_o_cookie_uma_vez(monkeypatch):
    _login(monkeypatch)
    usados = []
    portao = threading.Event()

    def pedir(_metodo, _url, **kwargs):
        usados.append(kwargs["headers"]["Cookie"].split(";")[0])
        portao.wait(2)
        return _token(acesso=f"T{len(usados)}", remid=f"R{len(usados) + 2}")

    monkeypatch.setattr(conta, "_pedir", pedir)
    linhas = [threading.Thread(target=conta.autorizacao, args=(True,)) for _ in range(2)]
    for linha in linhas:
        linha.start()
    portao.set()
    for linha in linhas:
        linha.join(5)
    assert usados == ["remid=R2", "remid=R3"]


def test_403_simultaneos_com_o_mesmo_token_renovam_uma_vez(monkeypatch):
    _login(monkeypatch)  # o token vigente é TOK1
    usados = []
    portao = threading.Event()

    def pedir(_metodo, _url, **kwargs):
        usados.append(kwargs["headers"]["Cookie"].split(";")[0])
        portao.wait(2)
        return _token(acesso="TOK2", remid="R3")

    monkeypatch.setattr(conta, "_pedir", pedir)
    resultados = []
    linhas = [
        threading.Thread(target=lambda: resultados.append(conta.autorizacao(True, recusado="TOK1")))
        for _ in range(2)
    ]
    linhas[0].start()
    for _ in range(300):
        if usados:
            break
        time.sleep(0.01)
    # a primeira já está na rede, com a trava de renovação
    linhas[1].start()
    time.sleep(0.1)  # a segunda espera a trava
    portao.set()
    for linha in linhas:
        linha.join(5)
    assert usados == ["remid=R2"]
    assert resultados == ["TOK2", "TOK2"]


def test_recusado_diferente_do_vigente_nao_renova(monkeypatch):
    chamadas = _login(monkeypatch)
    antes = len(chamadas)
    assert conta.autorizacao(True, recusado="TOK-ANTIGO") == "TOK1"
    assert len(chamadas) == antes


def test_recusado_igual_ao_vigente_renova(monkeypatch):
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(acesso="TOK2", remid="R3")]}, nome="_pedir")
    assert conta.autorizacao(True, recusado="TOK1") == "TOK2"


def test_login_required_na_renovacao_desconecta_e_avisa_uma_vez(monkeypatch, flush_idle, win):
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_recusa(), _recusa()]}, nome="_pedir")
    assert conta.autorizacao(forcar=True) is None
    flush_idle()
    assert not conta.conectada() and not (shared.contas_dir / "ea.json").exists()
    # uma segunda sessão recusada na mesma execução não repete o aviso
    monkeypatch.setattr(conta, "_sessao", conta._Sessao("R9", "N9", "Z", "9"))
    assert conta.autorizacao(forcar=True) is None
    flush_idle()
    assert [t.get_title() for t in win.toast_queue.added] == [_AVISO]


def test_dois_set_cookie_remid_usam_o_primeiro(monkeypatch):
    _login(monkeypatch)
    jarra = requests.cookies.RequestsCookieJar()
    jarra.set("remid", "RA", domain="a.ea.com")
    jarra.set("remid", "RB", domain="b.ea.com")
    resposta = _token(acesso="TOK2", remid=None)
    resposta.cookies = jarra
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [resposta]}, nome="_pedir")
    assert conta.autorizacao(forcar=True) == "TOK2"
    assert _guardado()[1]["remid"] == "RA"


def test_401_na_renovacao_desconecta(monkeypatch, flush_idle):
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_Resp(401)]}, nome="_pedir")
    assert conta.autorizacao(forcar=True) is None
    flush_idle()
    assert not conta.conectada()


@pytest.mark.parametrize("status", [403, 429])
def test_outro_4xx_na_renovacao_nao_desconecta(monkeypatch, status):
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_Resp(status)]}, nome="_pedir")
    assert conta.autorizacao(forcar=True) is None
    assert conta.conectada() and (shared.contas_dir / "ea.json").exists()


def test_rede_fora_so_loga(monkeypatch):
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [requests.ConnectionError("x")]}, nome="_pedir")
    assert conta.autorizacao(forcar=True) is None
    assert conta.conectada() and (shared.contas_dir / "ea.json").exists()


def test_servidor_fora_so_loga(monkeypatch):
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_Resp(503)]}, nome="_pedir")
    assert conta.autorizacao(forcar=True) is None
    assert conta.conectada()


def test_ouvintes_sao_avisados_ao_conectar_e_ao_sair(monkeypatch, flush_idle):
    vezes = []
    remover = conta.ao_mudar(lambda: vezes.append(1))
    _login(monkeypatch)
    flush_idle()
    conta.sair()
    flush_idle()
    remover()
    assert len(vezes) == 2


# ---- sair ------------------------------------------------------------------


def test_sair_apaga_conta_e_caches(monkeypatch, flush_idle, win):
    _login(monkeypatch)
    shared.conquistas_cache_dir.mkdir(parents=True, exist_ok=True)
    for arquivo in ("ea-biblioteca.json", "ea-jogos.json", "ea-ABC.json"):
        (shared.conquistas_cache_dir / arquivo).write_text("{}", encoding="utf-8")
    (shared.conquistas_cache_dir / "epic-ns1.json").write_text("{}", encoding="utf-8")
    conta.sair()
    flush_idle()
    assert not conta.conectada() and not (shared.contas_dir / "ea.json").exists()
    assert [p.name for p in shared.conquistas_cache_dir.iterdir()] == ["epic-ns1.json"]
    assert not win.toast_queue.added


def test_sair_sem_pasta_de_caches(monkeypatch):
    _login(monkeypatch)
    conta.sair()
    assert not conta.conectada()


# ---- log -------------------------------------------------------------------


def test_nada_sensivel_no_log(monkeypatch, caplog):
    caplog.set_level("DEBUG")
    _login(monkeypatch)
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [_token(acesso="TOK2", remid="R3"), _recusa(),
                                                  requests.ConnectionError("R9 N9")]}, nome="_pedir")
    conta.autorizacao(forcar=True)
    conta.autorizacao(forcar=True)
    monkeypatch.setattr(conta, "_sessao", conta._Sessao("R9", "N9", "Z", "9"))
    conta.autorizacao(forcar=True)
    for segredo in ("R1", "R2", "R3", "R9", "N1", "N9", "TOK1", "TOK2", "Fulano"):
        assert segredo not in caplog.text
