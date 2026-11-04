"""As lojas em que as conquistas vêm de uma conta do usuário (Xbox, Epic, EA).

O que é igual entre elas (o vigia por consulta, `vigia_da_conta.py`, e o ramo da rede da varredura) fala só com a "loja": um módulo com os nomes de `LojaComConta`. Login, guarda da conta e API ficam no pacote de cada loja. O registro é montado na primeira chamada: `xbox/api.py` importa `Leitura` daqui, e importar as `api` no topo fecharia um ciclo.
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

    def id_da_conta(self) -> Optional[str]: ...

    # Em thread, com rede: completa a fonte pendente (id ""). "" = sabidamente
    # sem fonte; None = não se sabe (sem conta). Levanta `FalhaDeRede`.
    def resolver(self, game: Any, fonte: Any) -> Optional[str]: ...

    def ler(self, id_: str) -> Optional[Leitura]: ...

    def desbloqueadas(self, id_: str) -> Optional[list[Desbloqueio]]: ...

    def chave_do_catalogo(self, id_: str) -> str: ...


_lojas: Optional[dict[str, ModuleType]] = None


def lojas() -> dict[str, ModuleType]:
    global _lojas  # pylint: disable=global-statement
    if _lojas is None:
        from cartridges.conquistas.ea import loja as ea  # noqa: PLC0415
        from cartridges.conquistas.epic import loja as epic  # noqa: PLC0415
        from cartridges.conquistas.xbox import loja as xbox  # noqa: PLC0415

        _lojas = {xbox.TIPO: xbox, epic.TIPO: epic, ea.TIPO: ea}
    return _lojas


def da_fonte(fonte: Any) -> Optional[ModuleType]:
    return lojas().get(fonte.tipo) if fonte is not None else None
