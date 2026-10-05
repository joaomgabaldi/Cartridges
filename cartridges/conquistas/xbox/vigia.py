"""O vigia da sessão para os jogos do Xbox: o vigia da conta (`vigia_da_conta.py`)
com a loja do Xbox. Fica como módulo próprio porque a sessão escolhe o vigia por
loja (e os testes trocam `Vigia` aqui)."""

import time
from typing import Any, Callable

from cartridges.conquistas import vigia_da_conta
from cartridges.conquistas.vigia import Desbloqueada
from cartridges.conquistas.vigia_da_conta import INTERVALO, _em_thread  # noqa: F401
from cartridges.conquistas.xbox import loja


class Vigia(vigia_da_conta.Vigia):
    def __init__(
        self,
        game: Any,
        avisar: Callable[[list[Desbloqueada]], None],
        relogio: Callable[[], float] = time.time,
        em_thread: Callable[..., None] = _em_thread,
    ) -> None:
        super().__init__(game, avisar, relogio, em_thread, loja=loja)
