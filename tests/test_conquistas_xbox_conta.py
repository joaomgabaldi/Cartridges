"""A conta Microsoft: guarda cifrada, renovação e desconexão."""

import json
import logging
import threading
import time

import pytest
import requests

from cartridges import shared
from cartridges.conquistas.xbox import conta
from tests.apoio_xbox import Resposta, rede_falsa, respostas_de_login


@pytest.fixture(autouse=True)
def conta_limpa(monkeypatch):
    monkeypatch.setattr(conta, "_sessao", None)
    monkeypatch.setattr(conta, "_avisou", False)
    monkeypatch.setattr(conta, "_ouvintes", [])
    yield


def _conectar(monkeypatch, **kw):
    rede_falsa(monkeypatch, conta, respostas_de_login(**kw))
    conta.conectar("codigo", "verificador", "http://localhost:1")


def _vencer_os_tokens():
    """Faz a próxima `autorizacao()` ir à rede, como depois de uma hora parado."""
    conta._sessao.msa = None
    conta._sessao.xsts = None


def test_conectar_guarda_cifrado_e_conecta(monkeypatch):
    _conectar(monkeypatch, renovacao="RENOVACAO-SECRETA")
    assert conta.conectada() and conta.gamertag() == "Jogador" and conta.xuid() == "2535400000000000"
    texto = (shared.contas_dir / "microsoft.json").read_text(encoding="utf-8")
    # Um texto distintivo: "R1" ou "A1" podem aparecer por acaso no base64.
    assert "RENOVACAO-SECRETA" not in texto
    assert set(json.loads(texto)) == {"gamertag", "xuid", "renovacao"}  # nenhum token de acesso
    assert json.loads(texto)["gamertag"] == "Jogador"


def test_carregar_le_o_que_foi_guardado(monkeypatch):
    _conectar(monkeypatch)
    monkeypatch.setattr(conta, "_sessao", None)
    conta.carregar()
    assert conta.conectada() and conta.gamertag() == "Jogador"


@pytest.mark.parametrize("conteudo", ["", "{", '{"gamertag": "x"}', '{"renovacao": "bm9wZQ=="}'])
def test_arquivo_ruim_e_nao_conectada(conteudo):
    shared.contas_dir.mkdir(parents=True)
    (shared.contas_dir / "microsoft.json").write_text(conteudo, encoding="utf-8")
    conta.carregar()
    assert not conta.conectada()


def test_sem_arquivo_e_nao_conectada():
    conta.carregar()
    assert not conta.conectada()


def test_autorizacao_renova_e_entrega(monkeypatch):
    _conectar(monkeypatch)
    _vencer_os_tokens()
    rede_falsa(monkeypatch, conta, respostas_de_login(renovacao="R2"))
    assert conta.autorizacao() == ("UHS", "X1")
    monkeypatch.setattr(conta, "_sessao", None)
    conta.carregar()
    assert conta._sessao.renovacao == "R2"  # a renovação nova foi guardada


def test_autorizacao_valida_nao_vai_a_rede(monkeypatch):
    _conectar(monkeypatch)
    chamadas = rede_falsa(monkeypatch, conta, {})
    assert conta.autorizacao() == ("UHS", "X1")
    assert chamadas == []


def test_autorizacao_sem_conta_e_none():
    assert conta.autorizacao() is None


def _reconectar_sem_login():
    """Uma conta conectada de novo sem passar por `conectar` (que zera o aviso):
    é o que a abertura seguinte do app faria com o arquivo guardado."""
    sessao = conta._Sessao("R1", "Jogador", "2535400000000000")
    conta._salvar(sessao)
    conta._sessao = sessao


def _renovacao_recusada(monkeypatch, flush_idle):
    _vencer_os_tokens()
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [Resposta(400, {"error": "invalid_grant"})]})
    assert conta.autorizacao() is None
    flush_idle()
    assert not conta.conectada()


def test_renovacao_recusada_desconecta_e_avisa_uma_vez(monkeypatch, win, flush_idle):
    _conectar(monkeypatch)
    _renovacao_recusada(monkeypatch, flush_idle)
    assert not (shared.contas_dir / "microsoft.json").exists()

    # Segunda desconexão no mesmo processo, sem login no meio: não avisa de novo.
    _reconectar_sem_login()
    _renovacao_recusada(monkeypatch, flush_idle)

    assert not conta.conectada()
    assert not (shared.contas_dir / "microsoft.json").exists()
    avisos = [t.get_title() for t in win.toast_queue.added]
    assert avisos == ["A conta Microsoft foi desconectada. Entre novamente nas Preferências."]


def test_novo_login_volta_a_permitir_o_aviso(monkeypatch, win, flush_idle):
    _conectar(monkeypatch)
    _renovacao_recusada(monkeypatch, flush_idle)
    _conectar(monkeypatch)
    _renovacao_recusada(monkeypatch, flush_idle)
    assert len(win.toast_queue.added) == 2


def test_rede_fora_so_loga_e_continua_conectada(monkeypatch, caplog, flush_idle, win):
    caplog.set_level(logging.DEBUG)
    _conectar(monkeypatch)
    _vencer_os_tokens()
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [requests.ConnectionError("https://x?code=SEGREDO")]})
    assert conta.autorizacao() is None
    flush_idle()
    assert conta.conectada()
    assert "SEGREDO" not in caplog.text and "R1" not in caplog.text
    assert win.toast_queue.added == []


def test_recusa_nao_loga_o_corpo_da_resposta(monkeypatch, caplog, flush_idle):
    caplog.set_level(logging.DEBUG)
    _conectar(monkeypatch)
    _vencer_os_tokens()
    corpo = {"error": "invalid_grant", "error_description": "SEGREDO do refresh R1"}
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [Resposta(400, corpo)]})
    assert conta.autorizacao() is None
    flush_idle()
    assert "SEGREDO" not in caplog.text and "R1" not in caplog.text


@pytest.mark.parametrize(
    "resposta",
    [
        Resposta(200, {"refresh_token": "R9"}),  # sem access_token
        Resposta(200, ["nao", "e", "dicionario"]),
        Resposta(200),  # sem corpo
        Resposta(500, {"error": "server_error"}),
        RuntimeError("inesperado"),
    ],
)
def test_resposta_fora_do_formato_nao_levanta_e_nao_desconecta(monkeypatch, resposta):
    _conectar(monkeypatch)
    _vencer_os_tokens()
    rede_falsa(monkeypatch, conta, {conta.TOKEN: [resposta]})
    assert conta.autorizacao() is None
    assert conta.conectada()


def test_validade_nao_finita_vira_uma_hora():
    for estranho in (float("inf"), float("nan"), "x", None):
        assert 3000 < conta._vence_em(estranho) - time.time() <= 3600


@pytest.mark.parametrize("xerr, erro", [(2148916233, conta.SemPerfilXbox), (2148916238, conta.ContaInfantil)])
def test_xerr_no_login(monkeypatch, xerr, erro):
    respostas = respostas_de_login()
    respostas["https://xsts.auth.xboxlive.com"] = [Resposta(401, {"XErr": xerr})]
    rede_falsa(monkeypatch, conta, respostas)
    with pytest.raises(erro):
        conta.conectar("c", "v", "http://localhost:1")
    assert not conta.conectada()


def test_sair_apaga_sem_aviso_e_chama_os_ouvintes(monkeypatch, win, flush_idle):
    _conectar(monkeypatch)
    flush_idle()  # o aviso da conexão sai antes de haver ouvinte
    chamados = []
    remover = conta.ao_mudar(lambda: chamados.append(1))
    conta.sair()
    flush_idle()
    assert not conta.conectada() and chamados == [1]
    assert not (shared.contas_dir / "microsoft.json").exists()
    assert win.toast_queue.added == []
    remover()
    _conectar(monkeypatch)
    flush_idle()
    assert chamados == [1]


def test_sair_durante_renovacao_lenta_volta_logo_e_a_renovacao_nao_ressuscita(monkeypatch, flush_idle):
    """`sair()` roda na thread principal: não pode esperar a rede de uma renovação."""
    _conectar(monkeypatch)
    _vencer_os_tokens()
    rede_falsa(monkeypatch, conta, respostas_de_login(renovacao="R2"))
    post_falso = conta._post
    na_rede = threading.Event()
    liberar = threading.Event()

    def post_lento(*args, **kwargs):
        na_rede.set()
        liberar.wait(10)
        return post_falso(*args, **kwargs)

    monkeypatch.setattr(conta, "_post", post_lento)
    resultado = []
    renovacao = threading.Thread(target=lambda: resultado.append(conta.autorizacao()))
    renovacao.start()
    try:
        assert na_rede.wait(5)
        saida = threading.Thread(target=conta.sair)
        saida.start()
        saida.join(2)
        assert not saida.is_alive(), "sair() ficou esperando a rede"
    finally:
        liberar.set()
        renovacao.join(10)
    assert not renovacao.is_alive()
    flush_idle()
    assert resultado == [None]
    assert not conta.conectada()
    assert not (shared.contas_dir / "microsoft.json").exists()


def test_login_durante_renovacao_lenta_descarta_a_renovacao_velha(monkeypatch, flush_idle):
    _conectar(monkeypatch, gamertag="Antigo", renovacao="R1")
    _vencer_os_tokens()
    rede_falsa(monkeypatch, conta, respostas_de_login(gamertag="Velho", renovacao="R2"))
    post_falso = conta._post
    na_rede = threading.Event()
    liberar = threading.Event()

    def post_lento(*args, **kwargs):
        na_rede.set()
        liberar.wait(10)
        return post_falso(*args, **kwargs)

    monkeypatch.setattr(conta, "_post", post_lento)
    resultado = []
    renovacao = threading.Thread(target=lambda: resultado.append(conta.autorizacao()))
    renovacao.start()
    try:
        assert na_rede.wait(5)
        # Um novo login (outra conta) entra enquanto a renovação espera a rede.
        sessao_nova = conta._Sessao("R9", "Novo", "1")
        conta._salvar(sessao_nova)
        conta._sessao = sessao_nova
    finally:
        liberar.set()
        renovacao.join(10)
    assert resultado == [None]
    assert conta._sessao is sessao_nova and conta.gamertag() == "Novo"
    monkeypatch.setattr(conta, "_sessao", None)
    conta.carregar()
    assert conta._sessao.renovacao == "R9"


def test_recusada_desconecta(monkeypatch, flush_idle):
    _conectar(monkeypatch)
    conta.recusada()
    flush_idle()
    assert not conta.conectada()


def test_ouvinte_que_levanta_nao_cala_os_outros(monkeypatch, flush_idle):
    chamados = []
    conta.ao_mudar(lambda: 1 / 0)
    conta.ao_mudar(lambda: chamados.append(1))
    _conectar(monkeypatch)
    flush_idle()
    assert chamados == [1]
