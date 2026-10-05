"""O login da conta Microsoft pelo navegador padrão.

O app abre a página de login da Microsoft (OAuth, código de autorização com
PKCE S256) e recebe a volta numa porta livre em ``127.0.0.1`` (o Entra ignora a
porta nos redirecionamentos ``localhost``). O app nunca vê a senha, e o
servidor só aceita a volta que traz o ``state`` deste pedido.

A troca do código pelas chaves (``conta.conectar``) faz rede e roda na thread
do servidor, nunca na principal. ``ao_terminar`` é chamado uma única vez, na
thread principal, e o servidor sempre é fechado.

Nada de código, URL com ``code=`` nem corpo de resposta vai para o log.
"""

import base64
import enum
import hashlib
import html
import http.server
import logging
import os
import secrets
import threading
import time
import urllib.parse
from typing import Callable, Optional

from gi.repository import GLib

from cartridges.conquistas.xbox import conta

TEXTO_OK = "Login concluído. Pode fechar esta aba e voltar ao Cartridges."
TEXTO_FALHOU = "O login não foi concluído. Pode fechar esta aba."
# Quanto uma conexão pode ficar aberta sem terminar a requisição.
_TEMPO_DA_CONEXAO = 5


class Resultado(enum.Enum):
    OK = enum.auto()
    CANCELADO = enum.auto()
    SEM_PERFIL_XBOX = enum.auto()
    CONTA_INFANTIL = enum.auto()
    FALHOU = enum.auto()


def _abrir_navegador(url: str) -> None:
    os.startfile(url)  # type: ignore[attr-defined]  # pylint: disable=no-member


_pendente: Optional["Pedido"] = None


def _pagina(texto: str) -> bytes:
    return (
        '<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Cartridges</title>'
        f'<body style="font-family:sans-serif;margin:3em"><p>{html.escape(texto)}</p></body></html>'
    ).encode("utf-8")


class Pedido:
    """Um login em curso: o servidor de retorno e o que ele espera receber."""

    def __init__(self, ao_terminar: Callable[[Resultado], None], prazo: float) -> None:
        self._ao_terminar = ao_terminar
        self._prazo = time.monotonic() + prazo
        self._verificador = secrets.token_urlsafe(64)
        self._estado = secrets.token_urlsafe(24)
        self._terminou = threading.Event()
        self._fim = threading.Lock()
        pedido = self

        class _Volta(http.server.BaseHTTPRequestHandler):
            # Uma conexão aberta que não manda requisição (pré-conexão
            # especulativa do navegador, outro processo local) não pode
            # segurar a thread para sempre.
            timeout = _TEMPO_DA_CONEXAO

            def do_GET(self) -> None:  # noqa: N802
                pedido._receber(self)  # pylint: disable=protected-access

            def log_message(self, *_args) -> None:
                pass

        # Uma thread por conexão: a conexão ociosa não segura a volta real
        # nem o laço que confere o prazo. Threads daemon: fechar o servidor
        # não espera por elas.
        self._servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Volta)
        self._servidor.daemon_threads = True
        self._servidor.block_on_close = False
        self._servidor.timeout = 0.2
        self._trocando = False
        self.porta: int = self._servidor.server_port
        # Forma aprovada pela prova ao vivo: sem barra no fim.
        self.retorno = f"http://localhost:{self.porta}"

    def url(self) -> str:
        desafio = (
            base64.urlsafe_b64encode(hashlib.sha256(self._verificador.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        return (
            conta.AUTORIZAR
            + "?"
            + urllib.parse.urlencode(
                {
                    "client_id": conta.CLIENT_ID,
                    "response_type": "code",
                    "redirect_uri": self.retorno,
                    "scope": conta.ESCOPO,
                    "state": self._estado,
                    "code_challenge": desafio,
                    "code_challenge_method": "S256",
                    "prompt": "select_account",
                }
            )
        )

    def _servir(self) -> None:
        try:
            while not self._terminou.is_set() and time.monotonic() < self._prazo:
                self._servidor.handle_request()
        except Exception:  # pylint: disable=broad-exception-caught
            # Cancelar fecha o servidor por baixo da espera: não é falha.
            if not self._terminou.is_set():
                logging.warning("Falha no retorno do login da conta Microsoft", exc_info=True)
        finally:
            self._terminar(Resultado.CANCELADO)

    @staticmethod
    def _responder(pedido_http, status: int, texto: str) -> None:
        try:
            pedido_http.send_response(status)
            pedido_http.send_header("Content-Type", "text/html; charset=utf-8")
            pedido_http.end_headers()
            pedido_http.wfile.write(_pagina(texto))
        except OSError:
            pass  # a aba foi fechada antes da resposta

    def _receber(self, pedido_http) -> None:
        consulta = urllib.parse.parse_qs(urllib.parse.urlparse(pedido_http.path).query)
        valor = {chave: valores[0] for chave, valores in consulta.items() if valores}
        if self._terminou.is_set() or not secrets.compare_digest(
            valor.get("state", "").encode("utf-8"), self._estado.encode("utf-8")
        ):
            self._responder(pedido_http, 400, TEXTO_FALHOU)
            return
        with self._fim:
            # Com uma thread por conexão, só a primeira volta válida troca o código.
            repetida = self._trocando
            self._trocando = True
        if repetida:
            self._responder(pedido_http, 400, TEXTO_FALHOU)
            return
        resultado = Resultado.CANCELADO
        try:
            if "code" in valor:
                resultado = self._trocar(valor["code"])
        finally:
            self._responder(pedido_http, 200, TEXTO_OK if resultado is Resultado.OK else TEXTO_FALHOU)
            self._terminar(resultado)

    def _trocar(self, codigo: str) -> Resultado:
        try:
            conta.conectar(codigo, self._verificador, self.retorno)
        except conta.SemPerfilXbox:
            return Resultado.SEM_PERFIL_XBOX
        except conta.ContaInfantil:
            return Resultado.CONTA_INFANTIL
        except Exception as erro:  # pylint: disable=broad-exception-caught
            # Recusada, rede fora, resposta fora do formato, o que for: o login
            # falhou e só o tipo do erro vai para o log.
            logging.info("Login da conta Microsoft falhou (%s)", type(erro).__name__)
            return Resultado.FALHOU
        return Resultado.OK

    def _terminar(self, resultado: Resultado) -> None:
        global _pendente  # pylint: disable=global-statement
        with self._fim:
            if self._terminou.is_set():
                return
            self._terminou.set()
        if _pendente is self:
            _pendente = None
        GLib.idle_add(self._entregar, resultado)

    def _entregar(self, resultado: Resultado) -> bool:
        """Na thread principal: fecha o servidor e avisa quem pediu."""
        try:
            self._servidor.server_close()
        except OSError:
            pass
        try:
            self._ao_terminar(resultado)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao concluir o login da conta Microsoft", exc_info=True)
        return False

    def cancelar(self) -> None:
        self._terminar(Resultado.CANCELADO)


def entrar(
    ao_terminar: Callable[[Resultado], None],
    abrir: Callable[[str], None] = _abrir_navegador,
    prazo: float = 300,
) -> Pedido:
    """Abre o login no navegador. Thread principal; `ao_terminar` roda nela."""
    global _pendente  # pylint: disable=global-statement
    cancelar_pendente()
    pedido = Pedido(ao_terminar, prazo)
    _pendente = pedido
    threading.Thread(target=pedido._servir, daemon=True).start()  # pylint: disable=protected-access
    try:
        abrir(pedido.url())
    except Exception as erro:  # pylint: disable=broad-exception-caught
        logging.info("Navegador não abriu para o login (%s)", type(erro).__name__)
        pedido._terminar(Resultado.FALHOU)  # pylint: disable=protected-access
    return pedido


def cancelar_pendente() -> None:
    """Cancela o login em curso, se houver (fechamento do app ou das Preferências)."""
    pedido = _pendente
    if pedido is not None:
        pedido.cancelar()
