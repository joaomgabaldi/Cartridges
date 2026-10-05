"""A Epic como "loja com conta" (`conquistas/contas.py`): só adapta `api` e `conta`.

Cada função procura o nome no módulo na hora da chamada (os testes os trocam).
"""

from typing import Any, Optional

from cartridges.conquistas.contas import Leitura
from cartridges.conquistas.epic import api, conta
from cartridges.conquistas.formatos import Desbloqueio

TIPO = "epic"
FalhaDeRede = api.FalhaDeRede


def conectada() -> bool:
    return conta.conectada()


def id_da_conta() -> Optional[str]:
    return conta.account_id()


def resolver(game: Any, _fonte: Any) -> Optional[str]:
    """O namespace que faltava: o atalho só tinha o ``AppName``. Pela biblioteca da conta."""
    from cartridges.conquistas import fontes  # noqa: PLC0415  (fontes importa contas)

    achado = fontes.da_epic(game)
    if achado is None:
        return ""
    namespace, app = achado
    if namespace:
        return namespace
    return api.namespace_do_app(app) if app else ""


def ler(id_: str) -> Optional[Leitura]:
    return api.ler(id_)


def desbloqueadas(id_: str) -> Optional[list[Desbloqueio]]:
    return api.desbloqueadas(id_)


def chave_do_catalogo(id_: str) -> str:
    return api.chave_do_catalogo(id_)
