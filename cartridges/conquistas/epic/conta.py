"""A conta Epic do usuário: guarda, renovação e desconexão.

O login é o do Epic Games Launcher, como fazem o legendary e o Heroic (pesquisa
de 04/10, seção 2.2): a página de login da Epic mostra um código, que o usuário
cola na janela do app (`epic/janela.py`). O app nunca vê a senha.

Só a chave de renovação é guardada, cifrada pelo DPAPI (``utils/dpapi.py``), em
``contas/epic.json`` — fora do backup. O token de acesso fica só na memória.

A Epic troca a chave de renovação a cada uso. A antiga ainda foi aceita logo
depois (prova de 05/10), mas nada garante por quanto tempo: a nova é gravada
sempre, e as renovações vão uma de cada vez, para nunca depender da antiga.

Nada de token, código, chave, ``account_id`` ou corpo de resposta vai para o log:
só o tipo da exceção, o status HTTP e o ``errorCode`` da Epic.
"""

import base64
import datetime
import json
import logging
import math
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests
from gi.repository import GLib

from cartridges import shared
from cartridges.conquistas import aviso_da_conta
from cartridges.utils import download, dpapi
from cartridges.utils.gravar_atomico import gravar_atomico

# O client do Epic Games Launcher (segredo público; legendary `egs.py`).
CLIENT_ID = "34a02cf8f4414e29b15921876da36f9a"
SEGREDO = "daafbccc737745039dffe53d94fc76cf"
_REDIRECIONAR = f"https://www.epicgames.com/id/api/redirect?clientId={CLIENT_ID}&responseType=code"
PAGINA_DE_LOGIN = "https://www.epicgames.com/id/login?redirectUrl=" + urllib.parse.quote(
    _REDIRECIONAR, safe=""
)
_OAUTH = "https://account-public-service-prod03.ol.epicgames.com/account/api/oauth"
TOKEN = f"{_OAUTH}/token"
ENCERRAR = f"{_OAUTH}/sessions/kill/"
# Renova o que vence em menos que isto.
_MARGEM = 5 * 60
_TEMPO = 15
_UMA_HORA = 3600
_CODIGO = re.compile(r"[0-9A-Fa-f]{32}")
_CODIGO_NO_JSON = re.compile(r'"authorizationCode"\s*:\s*"([0-9A-Fa-f]{32})"')
_TAMANHO_MAXIMO_COLADO = 64 * 1024
# A biblioteca da conta em `conquistas_cache_dir` (quem a lê e grava é `epic/api.py`).
BIBLIOTECA = "epic.biblioteca.json"


class Recusada(Exception):
    """A Epic recusou a chave de renovação: só um novo login resolve."""


class CodigoRecusado(Exception):
    """O código colado não vale (vencido, já usado ou errado)."""


@dataclass
class _Acesso:
    valor: str
    vence: float


@dataclass
class _Sessao:
    renovacao: str
    nome: str = ""
    conta: str = ""
    acesso: Optional[_Acesso] = None


# `_trava` guarda `_sessao` e o arquivo (só memória e disco, nunca rede);
# `_renovando` serializa as renovações, que vão à rede.
_trava = threading.Lock()
_renovando = threading.Lock()
_sessao: Optional[_Sessao] = None
# Um aviso de desconexão por execução (volta a valer depois de um login).
_avisou = False
_ouvintes: list[Callable[[], None]] = []


def _arquivo():
    return shared.contas_dir / "epic.json"


def _pedir(metodo: str, url: str, **kwargs: Any) -> requests.Response:
    """O único ponto de rede da conta. O corpo é lido sob um teto antes de devolver."""
    return download.request_capped(metodo, url, timeout=_TEMPO, **kwargs)


def _em_segundo_plano(funcao: Callable[..., None], *args: Any) -> None:
    threading.Thread(target=funcao, args=args, daemon=True).start()


def extrair_codigo(texto: Any) -> Optional[str]:
    """O código de autorização no texto colado: o código sozinho (com ou sem
    aspas) ou a página inteira da Epic. Nunca o ``sid`` nem outro número solto."""
    if not isinstance(texto, str) or len(texto) > _TAMANHO_MAXIMO_COLADO:
        return None
    texto = texto.strip()
    if "authorizationCode" in texto:
        achado = _CODIGO_NO_JSON.search(texto)
        return achado.group(1) if achado else None
    texto = texto.strip("\"'")
    return texto if _CODIGO.fullmatch(texto) else None


def _corpo(resposta: Any) -> dict:
    try:
        corpo = resposta.json()
    except (ValueError, RecursionError):
        return {}
    return corpo if isinstance(corpo, dict) else {}


def _vence(corpo: dict) -> float:
    """Quando o token vence: ``expires_at`` (ISO), senão ``expires_in``; na dúvida, 1 h."""
    try:
        return datetime.datetime.strptime(str(corpo.get("expires_at"))[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc
        ).timestamp()
    except (ValueError, OverflowError, OSError):
        pass
    try:
        segundos = float(corpo.get("expires_in"))
    except (TypeError, ValueError, OverflowError):
        segundos = _UMA_HORA
    if not math.isfinite(segundos):
        segundos = _UMA_HORA
    return time.time() + segundos


def _token(dados: dict[str, str]) -> dict:
    """Pede um token. Levanta ``Recusada``, ``requests.RequestException`` ou ``ValueError``."""
    resposta = _pedir("POST", TOKEN, data={**dados, "token_type": "eg1"}, auth=(CLIENT_ID, SEGREDO))
    corpo = _corpo(resposta)
    if resposta.status_code in (400, 401) and corpo.get("error") == "invalid_grant":
        # O `errorCode` é da Epic e vem sem limite de tamanho.
        logging.info("Conta Epic: pedido recusado (%s)", str(corpo.get("errorCode"))[:120])
        raise Recusada()
    resposta.raise_for_status()
    if not isinstance(corpo.get("access_token"), str) or not isinstance(corpo.get("refresh_token"), str):
        raise ValueError("resposta do token fora do formato")
    return corpo


def _salvar(sessao: _Sessao) -> None:
    protegido = dpapi.proteger(sessao.renovacao.encode("utf-8"))
    if protegido is None:
        logging.warning("Conta Epic: não foi possível cifrar a chave de renovação")
        return
    conteudo = json.dumps(
        {
            "nome": sessao.nome,
            "conta": sessao.conta,
            "renovacao": base64.b64encode(protegido).decode("ascii"),
        },
        ensure_ascii=False,
    )
    try:
        gravar_atomico(_arquivo(), conteudo)
    except OSError as erro:
        logging.warning("Conta Epic não gravada: %s", type(erro).__name__)


def carregar() -> None:
    """Lê a conta guardada, sem rede. Ilegível ou de outro PC = não conectada."""
    global _sessao  # pylint: disable=global-statement
    try:
        dados = json.loads(_arquivo().read_text(encoding="utf-8"))
        renovacao = dpapi.abrir(base64.b64decode(dados["renovacao"], validate=True))
        conta_ = dados["conta"]
        if renovacao is None or not isinstance(conta_, str) or not conta_:
            raise ValueError("não decifra ou sem conta")
        sessao = _Sessao(renovacao.decode("utf-8"), str(dados.get("nome", "")), conta_)
    except FileNotFoundError:
        return
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as erro:
        logging.info("Conta Epic guardada ilegível (%s)", type(erro).__name__)
        return
    with _trava:
        _sessao = sessao


def conectada() -> bool:
    return _sessao is not None


def nome() -> Optional[str]:
    sessao = _sessao
    return sessao.nome if sessao is not None else None


def account_id() -> Optional[str]:
    sessao = _sessao
    return sessao.conta if sessao is not None else None


def ao_mudar(ouvinte: Callable[[], None]) -> Callable[[], None]:
    """Registra `ouvinte` (chamado na thread principal a cada conexão ou
    desconexão) e devolve a função que o remove."""
    return aviso_da_conta.inscrever(_ouvintes, ouvinte)


def _notificar(avisar: bool) -> bool:
    """Na thread principal: aviso (uma vez), ouvintes e o cartão do jogo aberto."""
    global _avisou  # pylint: disable=global-statement
    _avisou = aviso_da_conta.notificar(avisar, _avisou, _ouvintes, _("A conta Epic foi desconectada. Entre novamente nas Preferências."), "Epic")
    return False


def _desconectar(avisar: bool) -> None:
    """Chamar com `_trava` tomada."""
    global _sessao  # pylint: disable=global-statement
    _sessao = None
    try:
        _arquivo().unlink(missing_ok=True)
    except OSError as erro:
        logging.warning("Conta Epic não apagada: %s", type(erro).__name__)
    GLib.idle_add(_notificar, avisar)


def _esquecer_a_biblioteca() -> None:
    """A biblioteca guardada é de uma conta só: outra conta não herda o "fora da
    biblioteca" da primeira. Só log em caso de erro."""
    try:
        (shared.conquistas_cache_dir / BIBLIOTECA).unlink(missing_ok=True)
    except OSError as erro:
        logging.info("Conta Epic: biblioteca guardada não apagada (%s)", type(erro).__name__)


def conectar(codigo: str) -> None:
    """Troca o código colado pelas chaves, guarda e conecta.

    Levanta ``CodigoRecusado``, ``requests.RequestException``, ``ValueError`` ou
    ``KeyError``: quem chama é a janela de login, que mostra o que aconteceu.
    """
    global _sessao, _avisou  # pylint: disable=global-statement
    try:
        corpo = _token({"grant_type": "authorization_code", "code": codigo})
    except Recusada:
        raise CodigoRecusado() from None
    conta_ = corpo.get("account_id")
    if not isinstance(conta_, str) or not conta_:
        raise ValueError("resposta do token sem conta")
    sessao = _Sessao(
        corpo["refresh_token"],
        str(corpo.get("displayName") or ""),
        conta_,
        _Acesso(corpo["access_token"], _vence(corpo)),
    )
    _salvar(sessao)
    _esquecer_a_biblioteca()
    with _trava:
        _sessao = sessao
        _avisou = False
    GLib.idle_add(_notificar, False)


def autorizacao(forcar: bool = False) -> Optional[str]:
    """O token de acesso para a API da Epic, renovando se venceu.

    Roda em thread. ``None``: sem conta, falha (logada) ou renovação recusada
    (a conta já foi desconectada e o usuário avisado).
    """
    # Mesmas garantias do Xbox: rede fora de `_trava`; `_renovando` serializa
    # as renovações; a publicação confere que a sessão ainda é a mesma.
    with _renovando:
        with _trava:
            sessao = _sessao
            if sessao is None:
                return None
            acesso, renovacao = sessao.acesso, sessao.renovacao
        if not forcar and acesso is not None and acesso.vence - time.time() >= _MARGEM:
            return acesso.valor
        try:
            corpo = _token({"grant_type": "refresh_token", "refresh_token": renovacao})
            acesso = _Acesso(corpo["access_token"], _vence(corpo))
            with _trava:
                if _sessao is not sessao:
                    return None
                sessao.acesso = acesso
                # A chave usada já não vale: a nova é gravada sempre que muda.
                nova, nome_ = corpo["refresh_token"], str(corpo.get("displayName") or sessao.nome)
                if (nova, nome_) != (sessao.renovacao, sessao.nome):
                    sessao.renovacao, sessao.nome = nova, nome_
                    _salvar(sessao)
        except Recusada:
            with _trava:
                if _sessao is not sessao:
                    return None
                logging.info("Conta Epic: renovação recusada; desconectando")
                _desconectar(avisar=True)
            return None
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.info("Conta Epic: renovação falhou (%s)", type(erro).__name__)
            return None
        return acesso.valor


def recusada() -> None:
    """A API da Epic recusou o acesso duas vezes: desconecta e avisa."""
    with _trava:
        if _sessao is not None:
            _desconectar(avisar=True)


def _encerrar(acesso: str) -> None:
    try:
        resposta = _pedir("DELETE", ENCERRAR + acesso, headers={"Authorization": f"bearer {acesso}"})
        logging.info("Conta Epic: sessão encerrada na Epic (%s)", resposta.status_code)
    except Exception as erro:  # pylint: disable=broad-exception-caught
        logging.info("Conta Epic: sessão não encerrada na Epic (%s)", type(erro).__name__)


def sair() -> None:
    """Desconecta sem aviso (o usuário pediu) e tenta encerrar a sessão na Epic."""
    with _trava:
        sessao = _sessao
        _desconectar(avisar=False)
    if sessao is not None and sessao.acesso is not None:
        _em_segundo_plano(_encerrar, sessao.acesso.valor)
