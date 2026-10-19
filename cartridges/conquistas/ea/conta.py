"""A conta EA do usuário: guarda, renovação e desconexão.

Não há OAuth para apps de terceiros na EA. O usuário entra em ea.com no navegador
e cola o pedido copiado ("Copiar como cURL", ``ea/janela.py``); dele o app tira só
dois cookies, ``remid`` e ``_nx_mpcid``. Com eles, ``accounts.ea.com`` emite o
token de acesso, como faz o EA app. O app nunca vê a senha.

Os dois cookies são guardados cifrados pelo DPAPI (``utils/dpapi.py``), em
``contas/ea.json`` — fora do backup. O token de acesso fica só na memória.

O ``remid`` é de uso único: cada renovação devolve um novo em ``Set-Cookie`` e o
antigo pode ser recusado logo depois. O novo é gravado antes de o token ser
publicado, e as renovações vão uma de cada vez.

Nada de token, cookie, texto colado, pid, persona, nome da conta ou corpo de
resposta vai para o log: só o tipo da exceção, o status HTTP e o ``error`` da EA.
"""

import base64
import json
import logging
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple, Optional

import requests
from gi.repository import GLib

from cartridges import shared
from cartridges.conquistas import aviso_da_conta
from cartridges.utils import download, dpapi
from cartridges.utils.gravar_atomico import gravar_atomico

# O User-Agent do EA app: a Juno e o token o exigem (prova de 15/10).
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Origin/10.6.0.00000 EAApp/13.805.11.6320 Chrome/109.0.5414.120 Safari/537.36"
)
TOKEN = "https://accounts.ea.com/connect/auth?client_id=ORIGIN_JS_SDK&response_type=token&redirect_uri=nucleus:rest&prompt=none"
PAGINA_DE_LOGIN = "https://www.ea.com/login"
IDENTIDADE = "https://gateway.ea.com/proxy/identity"
# Renova o que vence em menos que isto.
_MARGEM = 5 * 60
_TEMPO = 15
_UMA_HORA = 3600
# Sem letra, número, `_` ou `-` antes: `ak_remid=` e `xremid=` não são o cookie.
_REMID = re.compile(r"(?<![\w-])remid=([^;'\"\s^]+)", re.IGNORECASE)
_NX_MPCID = re.compile(r"(?<![\w-])_nx_mpcid=([^;'\"\s^]+)", re.IGNORECASE)
# O "Copiar como cURL (cmd)" escapa com `^`: `^"`, `^%`, `^^`.
_ESCAPE_DO_CMD = re.compile(r'\^(["%^])')
_NUMERO = re.compile(r"[0-9]{1,30}")
_TAMANHO_MAXIMO_COLADO = 64 * 1024


class Cookies(NamedTuple):
    remid: str
    nx_mpcid: str


class LoginRecusado(Exception):
    """A EA não reconheceu os cookies (``login_required``): só um novo login resolve."""


@dataclass
class _Acesso:
    valor: str
    vence: float


@dataclass
class _Sessao:
    remid: str
    nx_mpcid: str
    nome: str = ""
    persona: str = ""
    acesso: Optional[_Acesso] = None


# `_trava` guarda `_sessao` e o arquivo (só memória e disco, nunca rede);
# `_renovando` serializa as renovações, que vão à rede.
_trava = threading.Lock()
_renovando = threading.Lock()
_sessao: Optional[_Sessao] = None
# Um aviso de desconexão por execução (volta a valer depois de um login).
_avisou = False
# (`remid` colado e já gasto, cookies que a renovação devolveu): se o `conectar` falha
# depois de renovar, a nova tentativa com o mesmo texto parte dos cookies novos.
_pendente: Optional[tuple[str, Cookies]] = None
_ouvintes: list[Callable[[], None]] = []


def _arquivo():
    return shared.contas_dir / "ea.json"


def _pedir(metodo: str, url: str, **kwargs: Any) -> requests.Response:
    """O único ponto de rede da conta. O corpo é lido sob um teto antes de devolver."""
    return download.request_capped(metodo, url, timeout=_TEMPO, **kwargs)


def extrair(texto: Any) -> Optional[Cookies]:
    """Os cookies ``remid`` e ``_nx_mpcid`` no texto colado (cURL de bash ou de
    cmd, ou só o cabeçalho ``Cookie``); o primeiro valor de cada um vence.
    ``None`` se faltar algum. Nunca loga o texto."""
    if not isinstance(texto, str) or len(texto) > _TAMANHO_MAXIMO_COLADO:
        return None
    texto = _ESCAPE_DO_CMD.sub(r"\1", texto)
    remid, nx_mpcid = _REMID.search(texto), _NX_MPCID.search(texto)
    if remid is None or nx_mpcid is None:
        return None
    return Cookies(remid.group(1), nx_mpcid.group(1))


def _corpo(resposta: Any) -> dict:
    try:
        corpo = resposta.json()
    except (ValueError, RecursionError):
        return {}
    return corpo if isinstance(corpo, dict) else {}


def _vence(corpo: dict) -> float:
    """Quando o token vence: ``expires_in`` (a EA o manda como texto); inválido = 1 h."""
    try:
        segundos = float(corpo.get("expires_in"))
    except (TypeError, ValueError, OverflowError):
        segundos = _UMA_HORA
    if not math.isfinite(segundos):
        segundos = _UMA_HORA
    return time.time() + segundos


def _remid_da_resposta(resposta: Any) -> Optional[str]:
    """O ``remid`` do ``Set-Cookie``; com dois cookies de mesmo nome, o primeiro."""
    try:
        return resposta.cookies.get("remid")
    except requests.cookies.CookieConflictError:
        return next((c.value for c in resposta.cookies if c.name == "remid"), None)


def _renovar(remid: str, nx_mpcid: str) -> tuple[_Acesso, str]:
    """Troca os cookies por um token. Devolve o token e o ``remid`` seguinte (o
    mesmo, se a EA não mandou outro). Levanta ``LoginRecusado``,
    ``requests.RequestException`` ou ``ValueError``."""
    resposta = _pedir(
        "GET",
        TOKEN,
        headers={"User-Agent": UA, "Cookie": f"remid={remid}; _nx_mpcid={nx_mpcid}"},
        allow_redirects=False,
    )
    corpo = _corpo(resposta)
    token = corpo.get("access_token")
    if isinstance(token, str) and token:
        return _Acesso(token, _vence(corpo)), _remid_da_resposta(resposta) or remid
    # Só `login_required` e 401 são recusa do `remid`; 403 e 429 (limite de uso) não desconectam.
    if corpo.get("error") == "login_required" or resposta.status_code == 401:
        # O `error` é da EA e vem sem limite de tamanho.
        logging.info("Conta EA: pedido recusado (%s, %s)", resposta.status_code, str(corpo.get("error"))[:120])
        raise LoginRecusado()
    resposta.raise_for_status()
    raise ValueError("resposta do token fora do formato")


def _identidade(acesso: str) -> tuple[str, str]:
    """O nome e a persona da conta. Levanta ``requests.RequestException`` ou ``ValueError``."""
    autorizado = {"Authorization": f"Bearer {acesso}", "User-Agent": UA}
    resposta = _pedir("GET", f"{IDENTIDADE}/pids/me", headers=autorizado)
    resposta.raise_for_status()
    try:
        pid = str(_corpo(resposta)["pid"]["pidId"])
    except (KeyError, TypeError) as erro:
        raise ValueError("resposta de pids/me fora do formato") from erro
    if not _NUMERO.fullmatch(pid):
        raise ValueError("pid fora do formato")
    resposta = _pedir(
        "GET", f"{IDENTIDADE}/pids/{pid}/personas", headers={**autorizado, "X-Expand-Results": "true"}
    )
    resposta.raise_for_status()
    try:
        persona = _corpo(resposta)["personas"]["persona"][0]
        persona_id, nome_ = str(persona["personaId"]), str(persona["displayName"])
    except (KeyError, IndexError, TypeError) as erro:
        raise ValueError("resposta de personas fora do formato") from erro
    if not _NUMERO.fullmatch(persona_id):
        raise ValueError("persona fora do formato")
    return nome_, persona_id


def _salvar(sessao: _Sessao) -> bool:
    """Grava a conta; ``False`` (logado) se não deu para cifrar ou gravar."""
    protegido = dpapi.proteger(
        json.dumps({"remid": sessao.remid, "nx_mpcid": sessao.nx_mpcid}).encode("utf-8")
    )
    if protegido is None:
        logging.warning("Conta EA: não foi possível cifrar os cookies")
        return False
    conteudo = json.dumps(
        {
            "nome": sessao.nome,
            "persona": sessao.persona,
            "cookies": base64.b64encode(protegido).decode("ascii"),
        },
        ensure_ascii=False,
    )
    try:
        gravar_atomico(_arquivo(), conteudo)
    except OSError as erro:
        logging.warning("Conta EA não gravada: %s", type(erro).__name__)
        return False
    return True


def carregar() -> None:
    """Lê a conta guardada, sem rede. Ilegível ou de outro PC = não conectada."""
    global _sessao  # pylint: disable=global-statement
    try:
        dados = json.loads(_arquivo().read_text(encoding="utf-8"))
        aberto = dpapi.abrir(base64.b64decode(dados["cookies"], validate=True))
        persona_ = dados["persona"]
        if aberto is None or not isinstance(persona_, str) or not persona_:
            raise ValueError("não decifra ou sem persona")
        cookies = json.loads(aberto.decode("utf-8"))
        remid, nx_mpcid = cookies["remid"], cookies["nx_mpcid"]
        if not (isinstance(remid, str) and remid and isinstance(nx_mpcid, str) and nx_mpcid):
            raise ValueError("cookies fora do formato")
        sessao = _Sessao(remid, nx_mpcid, str(dados.get("nome", "")), persona_)
    except FileNotFoundError:
        return
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as erro:
        logging.info("Conta EA guardada ilegível (%s)", type(erro).__name__)
        return
    with _trava:
        _sessao = sessao


def conectada() -> bool:
    return _sessao is not None


def nome() -> Optional[str]:
    sessao = _sessao
    return sessao.nome if sessao is not None else None


def persona() -> Optional[str]:
    sessao = _sessao
    return sessao.persona if sessao is not None else None


def ao_mudar(ouvinte: Callable[[], None]) -> Callable[[], None]:
    """Registra `ouvinte` (chamado na thread principal a cada conexão ou
    desconexão) e devolve a função que o remove."""
    return aviso_da_conta.inscrever(_ouvintes, ouvinte)


def _notificar(avisar: bool) -> bool:
    """Na thread principal: aviso (uma vez), ouvintes e o cartão do jogo aberto."""
    global _avisou  # pylint: disable=global-statement
    _avisou = aviso_da_conta.notificar(avisar, _avisou, _ouvintes, _("A conta EA foi desconectada. Entre novamente nas Preferências."), "EA")
    return False


def _desconectar(avisar: bool) -> None:
    """Chamar com `_trava` tomada."""
    global _sessao  # pylint: disable=global-statement
    _sessao = None
    try:
        _arquivo().unlink(missing_ok=True)
    except OSError as erro:
        logging.warning("Conta EA não apagada: %s", type(erro).__name__)
    GLib.idle_add(_notificar, avisar)


def conectar(texto: str) -> None:
    """Tira os cookies do texto colado, confere com a EA, guarda e conecta.

    Levanta ``LoginRecusado``, ``requests.RequestException``, ``ValueError``,
    ``KeyError`` ou ``OSError`` (não gravou: sem isso a conta sumiria na próxima
    abertura): quem chama é a janela de login, que mostra o que aconteceu.
    """
    global _sessao, _avisou  # pylint: disable=global-statement
    cookies = extrair(texto)
    if cookies is None:
        raise ValueError("faltam os cookies no texto colado")
    global _pendente  # pylint: disable=global-statement
    colado = cookies.remid
    with _trava:
        if _pendente is not None and _pendente[0] == colado:
            cookies = _pendente[1]
    acesso, remid = _renovar(*cookies)
    if remid != cookies.remid:
        # O `remid` usado já não vale: se o resto falhar, o novo é o que o usuário ainda tem.
        with _trava:
            _pendente = (colado, Cookies(remid, cookies.nx_mpcid))
    nome_, persona_ = _identidade(acesso.valor)
    sessao = _Sessao(remid, cookies.nx_mpcid, nome_, persona_, acesso)
    if not _salvar(sessao):
        raise OSError("conta EA não gravada")
    with _trava:
        _sessao = sessao
        _avisou = False
        _pendente = None
    GLib.idle_add(_notificar, False)


def autorizacao(forcar: bool = False, recusado: Optional[str] = None) -> Optional[str]:
    """O token de acesso para a API da EA, renovando se venceu.

    ``forcar`` renova mesmo sem vencer; ``recusado`` é o token que a EA recusou: se outra
    thread já o trocou enquanto esta esperava a vez, vale o token novo (sem gastar outro ``remid``).

    Roda em thread. ``None``: sem conta, falha (logada) ou renovação recusada
    (a conta já foi desconectada e o usuário avisado).
    """
    # Rede fora de `_trava`; `_renovando` serializa as renovações; a publicação
    # confere que a sessão ainda é a mesma.
    with _renovando:
        with _trava:
            sessao = _sessao
            if sessao is None:
                return None
            acesso, remid, nx_mpcid = sessao.acesso, sessao.remid, sessao.nx_mpcid
        if acesso is not None and (
            (not forcar and acesso.vence - time.time() >= _MARGEM)
            or (recusado is not None and acesso.valor != recusado)
        ):
            return acesso.valor
        try:
            acesso, novo = _renovar(remid, nx_mpcid)
            with _trava:
                if _sessao is not sessao:
                    return None
                # O `remid` usado já não vale: o novo é gravado antes de o token ser publicado.
                if novo != sessao.remid:
                    sessao.remid = novo
                    _salvar(sessao)
                sessao.acesso = acesso
        except LoginRecusado:
            with _trava:
                if _sessao is not sessao:
                    return None
                logging.info("Conta EA: renovação recusada; desconectando")
                _desconectar(avisar=True)
            return None
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.info("Conta EA: renovação falhou (%s)", type(erro).__name__)
            return None
        return acesso.valor


def sair() -> None:
    """Desconecta sem aviso (o usuário pediu) e apaga os catálogos e caches da conta."""
    with _trava:
        _desconectar(avisar=False)
    try:
        for arquivo in shared.conquistas_cache_dir.glob("ea-*.json"):
            arquivo.unlink(missing_ok=True)
    except OSError as erro:
        logging.info("Conta EA: caches não apagados (%s)", type(erro).__name__)
