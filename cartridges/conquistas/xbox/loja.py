"""O Xbox como "loja com conta" (`conquistas/contas.py`): só adapta `api` e `conta`.

Cada função procura o nome no módulo na hora da chamada: os testes trocam
`conta.conectada`, `api.ler` etc.
"""

from typing import Any, Optional

from cartridges.conquistas.contas import Leitura
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.xbox import api, conta

TIPO = "xbox"
FalhaDeRede = api.FalhaDeRede


def conectada() -> bool:
    return conta.conectada()


def id_da_conta() -> Optional[str]:
    return conta.xuid()


def resolver(game: Any, _fonte: Any) -> Optional[str]:
    from cartridges.conquistas import fontes  # noqa: PLC0415  (fontes importa contas)

    return api.titulo(fontes.pfn(game), fontes.bases(game))


def ler(id_: str) -> Optional[Leitura]:
    return api.ler(id_)


def desbloqueadas(id_: str) -> Optional[list[Desbloqueio]]:
    return api.desbloqueadas(id_)


def chave_do_catalogo(id_: str) -> str:
    return api.chave_do_catalogo(id_)
