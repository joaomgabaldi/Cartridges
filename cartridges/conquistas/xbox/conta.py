"""A conta Microsoft do usuário: guarda, renovação e desconexão.

O caminho é o documentado pela Microsoft ("Xbox services sign-in for title
websites", GDK): o login da conta Microsoft (MSA) vira um token de usuário do
Xbox e este, um token XSTS para ``http://xboxlive.com``. A API de conquistas
recebe o par ``(uhs, xsts)``.

Só a chave de renovação é guardada, cifrada pelo DPAPI (``utils/dpapi.py``), em
``contas/microsoft.json`` — fora do backup, porque o DPAPI só abre no PC e no
usuário do Windows que a cifrou. Os tokens de acesso ficam só na memória.

Nada de token, código, chave de renovação ou corpo de resposta da autenticação
vai para o log: só o tipo da exceção, o status HTTP e o ``XErr`` do Xbox.
"""

import base64
import datetime
import json
import logging
import math
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional

import requests
from gi.repository import Adw, GLib

from cartridges import shared
from cartridges.utils import dpapi

CLIENT_ID = "6a0af9cc-6dce-49d8-a53d-bcc9130275f0"
AUTORIZAR = "https://login.microsoftonline.com/consumers/oauth2/v2.0/authorize"
TOKEN = "https://login.microsoftonline.com/consumers/oauth2/v2.0/token"
ESCOPO = "XboxLive.signin XboxLive.offline_access"
PREFIXO_DO_TICKET = "d="
_USUARIO = "https://user.auth.xboxlive.com/user/authenticate"
_XSTS = "https://xsts.auth.xboxlive.com/xsts/authorize"
SEM_PERFIL_XBOX = 2148916233
CONTA_INFANTIL = 2148916238
# Renova o que vence em menos que isto.
_MARGEM = 5 * 60
_TEMPO = 15
_UMA_HORA = 3600
_ERROS_DE_RECUSA = frozenset({"invalid_grant", "interaction_required", "invalid_client", "unauthorized_client"})


class Recusada(Exception):
    """A Microsoft recusou a renovação: só um novo login resolve."""


class SemPerfilXbox(Exception):
    """A conta Microsoft não tem perfil Xbox."""


class ContaInfantil(Exception):
    """A conta é de menor e precisa de permissão de um responsável."""


@dataclass
class _Acesso:
    valor: str
    vence: float


@dataclass
class _Sessao:
    renovacao: str
    gamertag: str = ""
    xuid: str = ""
    msa: Optional[_Acesso] = None
    xsts: Optional[_Acesso] = None
    uhs: str = ""


# `_trava` guarda `_sessao` e o arquivo (só memória e disco, nunca rede);
# `_renovando` serializa as renovações, que vão à rede.
_trava = threading.Lock()
_renovando = threading.Lock()
_sessao: Optional[_Sessao] = None
# Um aviso de desconexão por execução (volta a valer depois de um login).
_avisou = False
_ouvintes: list[Callable[[], None]] = []


def _arquivo():
    return shared.contas_dir / "microsoft.json"


def _post(url: str, **kwargs: Any) -> requests.Response:
    return requests.post(url, timeout=_TEMPO, **kwargs)


def _corpo(resposta: Any) -> dict:
    try:
        corpo = resposta.json()
    except (ValueError, RecursionError):
        return {}
    return corpo if isinstance(corpo, dict) else {}


def _vence_em(segundos: Any) -> float:
    """Instante em que um token de `segundos` de vida vence; na dúvida, 1 h."""
    try:
        duracao = float(segundos)
    except (TypeError, ValueError):
        duracao = _UMA_HORA
    if not math.isfinite(duracao):
        duracao = _UMA_HORA
    return time.time() + duracao


def _vence(texto: Any) -> float:
    """`NotAfter` do Xbox (`2026-10-19T12:00:00.1234567Z`) em segundos; na dúvida, 1 h."""
    try:
        return datetime.datetime.strptime(str(texto)[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=datetime.timezone.utc
        ).timestamp()
    except (ValueError, OverflowError, OSError):
        return time.time() + _UMA_HORA


def _msa(dados: dict[str, str]) -> tuple[_Acesso, str]:
    resposta = _post(TOKEN, data={"client_id": CLIENT_ID, "scope": ESCOPO, **dados})
    if resposta.status_code in (400, 401) and _corpo(resposta).get("error") in _ERROS_DE_RECUSA:
        raise Recusada()
    resposta.raise_for_status()
    corpo = _corpo(resposta)
    acesso = _Acesso(str(corpo["access_token"]), _vence_em(corpo.get("expires_in", _UMA_HORA)))
    return acesso, str(corpo.get("refresh_token") or dados.get("refresh_token", ""))


def _xbox(acesso_msa: str) -> tuple[_Acesso, str, str, str]:
    """Token de usuário e XSTS: devolve ``(xsts, uhs, xuid, gamertag)``."""
    cabecalho = {"x-xbl-contract-version": "1"}
    resposta = _post(
        _USUARIO,
        json={
            "RelyingParty": "http://auth.xboxlive.com",
            "TokenType": "JWT",
            "Properties": {
                "AuthMethod": "RPS",
                "SiteName": "user.auth.xboxlive.com",
                "RpsTicket": PREFIXO_DO_TICKET + acesso_msa,
            },
        },
        headers=cabecalho,
    )
    if resposta.status_code == 401:
        raise Recusada()
    resposta.raise_for_status()
    usuario = str(_corpo(resposta)["Token"])
    resposta = _post(
        _XSTS,
        json={
            "RelyingParty": "http://xboxlive.com",
            "TokenType": "JWT",
            "Properties": {"SandboxId": "RETAIL", "UserTokens": [usuario]},
        },
        headers=cabecalho,
    )
    if resposta.status_code == 401:
        xerr = _corpo(resposta).get("XErr")
        logging.info("Conta Microsoft: XSTS recusado (XErr %s)", xerr)
        if xerr == SEM_PERFIL_XBOX:
            raise SemPerfilXbox()
        if xerr == CONTA_INFANTIL:
            raise ContaInfantil()
        raise Recusada()
    resposta.raise_for_status()
    corpo = _corpo(resposta)
    xui = corpo["DisplayClaims"]["xui"][0]
    return (
        _Acesso(str(corpo["Token"]), _vence(corpo.get("NotAfter"))),
        str(xui["uhs"]),
        str(xui.get("xid", "")),
        str(xui.get("gtg", "")),
    )


def _salvar(sessao: _Sessao) -> None:
    protegido = dpapi.proteger(sessao.renovacao.encode("utf-8"))
    if protegido is None:
        logging.warning("Conta Microsoft: não foi possível cifrar a chave de renovação")
        return
    destino = _arquivo()
    temporario = destino.with_name(f"{destino.name}.{uuid.uuid4().hex}.tmp")
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_text(
            json.dumps(
                {
                    "gamertag": sessao.gamertag,
                    "xuid": sessao.xuid,
                    "renovacao": base64.b64encode(protegido).decode("ascii"),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporario.replace(destino)
    except OSError as erro:
        logging.warning("Conta Microsoft não gravada: %s", type(erro).__name__)
    finally:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass


def carregar() -> None:
    """Lê a conta guardada, sem rede. Ilegível ou de outro PC = não conectada."""
    global _sessao  # pylint: disable=global-statement
    try:
        dados = json.loads(_arquivo().read_text(encoding="utf-8"))
        renovacao = dpapi.abrir(base64.b64decode(dados["renovacao"], validate=True))
        if renovacao is None:
            raise ValueError("não decifra")
        sessao = _Sessao(renovacao.decode("utf-8"), str(dados.get("gamertag", "")), str(dados.get("xuid", "")))
    except FileNotFoundError:
        return
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError) as erro:
        logging.info("Conta Microsoft guardada ilegível (%s)", type(erro).__name__)
        return
    with _trava:
        _sessao = sessao


def conectada() -> bool:
    return _sessao is not None


def gamertag() -> Optional[str]:
    sessao = _sessao
    return sessao.gamertag if sessao is not None else None


def xuid() -> Optional[str]:
    sessao = _sessao
    return sessao.xuid if sessao is not None else None


def ao_mudar(ouvinte: Callable[[], None]) -> Callable[[], None]:
    """Registra `ouvinte` (chamado na thread principal a cada conexão ou
    desconexão) e devolve a função que o remove."""
    _ouvintes.append(ouvinte)

    def remover() -> None:
        try:
            _ouvintes.remove(ouvinte)
        except ValueError:
            pass

    return remover


def _notificar(avisar: bool) -> bool:
    """Na thread principal: aviso (uma vez), ouvintes e o cartão do jogo aberto."""
    global _avisou  # pylint: disable=global-statement
    try:
        if avisar and not _avisou and shared.win is not None:
            _avisou = True
            toast = Adw.Toast.new(_("A conta Microsoft foi desconectada. Entre novamente nas Preferências."))
            toast.set_use_markup(False)
            shared.win.toast_queue.add(toast)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao avisar da desconexão da conta Microsoft", exc_info=True)
    for ouvinte in list(_ouvintes):
        try:
            ouvinte()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha num ouvinte da conta Microsoft", exc_info=True)
    try:
        game = getattr(shared.win, "active_game", None)
        atualizar = getattr(shared.win, "update_conquistas_block", None)
        if game is not None and atualizar is not None:
            atualizar(game)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao atualizar o cartão de conquistas", exc_info=True)
    return False


def _desconectar(avisar: bool) -> None:
    """Chamar com `_trava` tomada."""
    global _sessao  # pylint: disable=global-statement
    _sessao = None
    try:
        _arquivo().unlink(missing_ok=True)
    except OSError as erro:
        logging.warning("Conta Microsoft não apagada: %s", type(erro).__name__)
    GLib.idle_add(_notificar, avisar)


def conectar(codigo: str, verificador: str, retorno: str) -> None:
    """Troca o código do login pelas chaves, guarda e conecta.

    Levanta ``SemPerfilXbox``, ``ContaInfantil``, ``Recusada``,
    ``requests.RequestException``, ``ValueError`` ou ``KeyError``: quem chama é
    o login, que mostra o que aconteceu.
    """
    global _sessao, _avisou  # pylint: disable=global-statement
    msa, renovacao = _msa(
        {
            "grant_type": "authorization_code",
            "code": codigo,
            "redirect_uri": retorno,
            "code_verifier": verificador,
        }
    )
    xsts, uhs, xuid_, gamertag_ = _xbox(msa.valor)
    sessao = _Sessao(renovacao, gamertag_, xuid_, msa, xsts, uhs)
    _salvar(sessao)
    with _trava:
        _sessao = sessao
        _avisou = False
    GLib.idle_add(_notificar, False)


def autorizacao(forcar: bool = False) -> Optional[tuple[str, str]]:
    """O par ``(uhs, xsts)`` para a API do Xbox, renovando o que venceu.

    Roda em thread. ``None``: sem conta, falha (logada) ou renovação recusada
    (a conta já foi desconectada e o usuário avisado).
    """
    # A rede roda fora de `_trava`, que só guarda memória e arquivo: `sair()` e
    # `recusada()` vêm da thread principal e não podem esperar uma renovação
    # lenta. `_renovando` só serializa as renovações entre si. Cada passo que
    # publica confere que a sessão ainda é a mesma (sair, recusada ou um novo
    # login a trocam): se mudou, o resultado é descartado sem gravar nada.
    with _renovando:
        with _trava:
            sessao = _sessao
            if sessao is None:
                return None
            renovacao, msa, xsts, uhs = sessao.renovacao, sessao.msa, sessao.xsts, sessao.uhs
        agora = time.time()
        try:
            if forcar or xsts is None or xsts.vence - agora < _MARGEM:
                if forcar or msa is None or msa.vence - agora < _MARGEM:
                    msa, nova = _msa({"grant_type": "refresh_token", "refresh_token": renovacao})
                    with _trava:
                        if _sessao is not sessao:
                            return None
                        sessao.msa = msa
                        if nova and nova != sessao.renovacao:
                            sessao.renovacao = nova
                            _salvar(sessao)
                xsts, uhs, xuid_, gamertag_ = _xbox(msa.valor)
                with _trava:
                    if _sessao is not sessao:
                        return None
                    sessao.xsts, sessao.uhs = xsts, uhs
                    if (xuid_, gamertag_) != (sessao.xuid, sessao.gamertag):
                        sessao.xuid, sessao.gamertag = xuid_, gamertag_
                        _salvar(sessao)
        except (Recusada, SemPerfilXbox, ContaInfantil):
            with _trava:
                if _sessao is not sessao:
                    return None
                logging.info("Conta Microsoft: renovação recusada; desconectando")
                _desconectar(avisar=True)
            return None
        except Exception as erro:  # pylint: disable=broad-exception-caught
            # Rede fora, resposta fora do formato, o que for: a conta continua
            # conectada e a próxima tentativa renova de novo.
            logging.info("Conta Microsoft: renovação falhou (%s)", type(erro).__name__)
            return None
        return uhs, xsts.valor


def recusada() -> None:
    """A API do Xbox recusou o acesso duas vezes: desconecta e avisa."""
    with _trava:
        if _sessao is not None:
            _desconectar(avisar=True)


def sair() -> None:
    """Desconecta sem aviso (o usuário pediu)."""
    with _trava:
        _desconectar(avisar=False)
