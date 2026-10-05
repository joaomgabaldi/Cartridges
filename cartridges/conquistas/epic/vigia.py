"""O vigia da sessão para os jogos da Epic: o vigia da conta (`vigia_da_conta.py`)
com a loja da Epic. Só pulso: o overlay da Epic já mostra o aviso dele. Fica como
módulo próprio porque a sessão escolhe o vigia por loja (e os testes trocam `Vigia` aqui)."""

import time
from typing import Any, Callable

from cartridges.conquistas import vigia_da_conta
from cartridges.conquistas.epic import loja
from cartridges.conquistas.vigia import Desbloqueada
from cartridges.conquistas.vigia_da_conta import _em_thread


class Vigia(vigia_da_conta.Vigia):
    def __init__(
        self,
        game: Any,
        avisar: Callable[[list[Desbloqueada]], None],
        relogio: Callable[[], float] = time.time,
        em_thread: Callable[..., None] = _em_thread,
    ) -> None:
        super().__init__(game, avisar, relogio, em_thread, loja=loja)
