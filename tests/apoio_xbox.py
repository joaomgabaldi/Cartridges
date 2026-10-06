"""Rede falsa para os testes do Xbox: nenhuma chamada sai do PC."""

import json
from typing import Any

import requests


class Resposta:
    def __init__(self, status: int, corpo: Any = None) -> None:
        self.status_code = status
        self._corpo = corpo
        self.content = json.dumps(corpo).encode() if corpo is not None else b""
        self.headers: dict[str, str] = {}

    def json(self) -> Any:
        if self._corpo is None:
            raise ValueError("sem corpo")
        return self._corpo

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class RespostaSemFim:
    """Corpo que não acaba: só o teto de `download.request_capped` o interrompe."""

    status_code = 200

    def __init__(self) -> None:
        self.fechada = False

    def iter_content(self, chunk_size: int = 1):
        while True:
            yield b"x" * chunk_size

    def close(self) -> None:
        self.fechada = True


def rede_falsa(monkeypatch, modulo, respostas, nome="_post"):
    """Cada URL (por prefixo) devolve a próxima resposta da sua fila.

    Uma resposta que é uma exceção é levantada. URL sem fila = ConnectionError.
    """
    chamadas: list[tuple[str, dict]] = []

    def falso(*args, **kwargs):
        url = args[-1]
        chamadas.append((url, kwargs))
        for prefixo, fila in respostas.items():
            if url.startswith(prefixo) and fila:
                resposta = fila.pop(0)
                if isinstance(resposta, BaseException):
                    raise resposta
                return resposta
        raise requests.ConnectionError("sem rede no teste")

    monkeypatch.setattr(modulo, nome, falso)
    return chamadas


def respostas_de_login(gamertag="Jogador", xuid="2535400000000000", renovacao="R1"):
    """O que a Microsoft responde a um login (ou a uma renovação) bem-sucedido."""
    from cartridges.conquistas.xbox import conta  # noqa: PLC0415

    return {
        conta.TOKEN: [Resposta(200, {"access_token": "A1", "refresh_token": renovacao, "expires_in": 3600})],
        "https://user.auth.xboxlive.com": [Resposta(200, {"Token": "U1"})],
        "https://xsts.auth.xboxlive.com": [
            Resposta(200, {
                "Token": "X1",
                "NotAfter": "2099-01-01T00:00:00.0000000Z",
                "DisplayClaims": {"xui": [{"uhs": "UHS", "xid": xuid, "gtg": gamertag}]},
            })
        ],
    }
