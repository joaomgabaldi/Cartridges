"""O vigia da Ubisoft Connect: o `.spool` do jogo, durante a partida.

É o vigia de arquivos (`conquistas/vigia.py`) com as peças da Ubisoft: o arquivo é o
`.spool` do produto (de cada conta deste PC), lido por `ubisoft.spool`. Um `.spool` que
aparece no meio da partida entra em silêncio, porque o Ubisoft Connect o cria ao abrir o
jogo pela primeira vez neste PC já com o que a conta tinha. A hora vale sempre: conquista
anterior ao início da sessão veio da conta, não desta partida. O catálogo é só o do cache:
montar o do ZIP fica com a varredura, fora da thread principal.
"""

import time
from typing import Any, Callable, Optional

from cartridges.conquistas import fontes, vigia
from cartridges.conquistas.arquivos import ArquivoDeConquista
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.ubisoft import locais, spool

FORMATO = "ubisoft"


class Vigia(vigia.Vigia):
    def __init__(
        self,
        game: Any,
        avisar: Callable[[list[vigia.Desbloqueada]], None],
        relogio: Callable[[], float] = time.time,
    ) -> None:
        super().__init__(game, avisar, relogio)
        fonte = fontes.gravada(game)
        self._produto: Optional[str] = (
            fonte.id if fonte is not None and fonte.tipo == fontes.UBISOFT else None
        )

    def _acompanha(self) -> bool:
        return self._produto is not None and bool(getattr(self.game, "conquistas", True))

    def _achar(self) -> list[ArquivoDeConquista]:
        if self._produto is None:
            return []
        return [
            ArquivoDeConquista(caminho, FORMATO) for caminho, _conta in locais.spools(self._produto)
        ]

    def _esperados(self) -> list[ArquivoDeConquista]:
        return []

    def _ler(self, achado: ArquivoDeConquista) -> Optional[list[Desbloqueio]]:
        return spool.ler_ou_none(achado.caminho)

    def _fonte_ao_registrar(self) -> str:
        return f"{fontes.UBISOFT}:{self._produto}"

    def _novo_em_silencio(self) -> bool:
        return True

    def _limite(self) -> Optional[float]:
        return None if self._inicio is None else self._inicio - vigia.MARGEM_DA_STEAM
