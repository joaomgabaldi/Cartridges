"""As lojas em que as conquistas vêm de uma conta do usuário (Xbox, Epic).

O que é igual entre elas — o vigia por consulta (`vigia_da_conta.py`) e o ramo
da rede da varredura — fala só com a "loja": um módulo com os nomes de
`LojaComConta`. Login, guarda da conta e API ficam no pacote de cada loja, porque
são diferentes de verdade.

O registro é montado na primeira chamada: `xbox/api.py` importa `Leitura` daqui,
e os módulos de cada loja importam a `api` deles — no topo, fecharia um ciclo.
"""

from dataclasses import dataclass
from types import ModuleType
from typing import Any, Optional, Protocol

from cartridges.conquistas.catalogo import Catalogo
from cartridges.conquistas.formatos import Desbloqueio


@dataclass(frozen=True)
class Leitura:
    catalogo: Catalogo
    desbloqueios: list[Desbloqueio]


class LojaComConta(Protocol):  # pragma: no cover - só documenta os nomes
    TIPO: str
    FalhaDeRede: type[Exception]

    def conectada(self) -> bool: ...

    # XUID no Xbox, account_id na Epic.
    def id_da_conta(self) -> Optional[str]: ...

    # Em thread, com rede: completa a fonte pendente (id ""). "" = sabidamente
    # sem fonte; None = não se sabe (sem conta). Levanta `FalhaDeRede`.
    def resolver(self, game: Any, fonte: Any) -> Optional[str]: ...

    # Catálogo (vai ao cache) e progresso. Levanta `FalhaDeRede`.
    def ler(self, id_: str) -> Optional[Leitura]: ...

    # Só o progresso, para o vigia. Levanta `FalhaDeRede`.
    def desbloqueadas(self, id_: str) -> Optional[list[Desbloqueio]]: ...

    def chave_do_catalogo(self, id_: str) -> str: ...


_lojas: Optional[dict[str, ModuleType]] = None


def lojas() -> dict[str, ModuleType]:
    global _lojas  # pylint: disable=global-statement
    if _lojas is None:
        from cartridges.conquistas.xbox import loja as xbox  # noqa: PLC0415

        _lojas = {xbox.TIPO: xbox}
    return _lojas


def da_fonte(fonte: Any) -> Optional[ModuleType]:
    """A loja da fonte, ou None (Steam, emulador, nenhuma)."""
    return lojas().get(fonte.tipo) if fonte is not None else None
