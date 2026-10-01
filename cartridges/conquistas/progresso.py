"""O catálogo cruzado com o histórico: o que a página do jogo e a lista mostram.

Só contam as conquistas que existem no catálogo (`resolveUnlockedAchievementCount`
do Hydra): um nome estranho no arquivo de um crack fica guardado, mas não infla o
"X de Y". Sem catálogo não há o que mostrar, e o cartão some.
"""

from dataclasses import dataclass
from typing import Any, Optional

from cartridges.conquistas import catalogo, historico
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo


@dataclass(frozen=True)
class Linha:
    info: ConquistaInfo
    # Segundos Unix; 0 é desbloqueada sem data; None é bloqueada.
    quando: Optional[int]

    @property
    def desbloqueada(self) -> bool:
        return self.quando is not None


@dataclass(frozen=True)
class Progresso:
    desbloqueadas: tuple[Linha, ...]
    bloqueadas: tuple[Linha, ...]

    @property
    def total(self) -> int:
        return len(self.desbloqueadas) + len(self.bloqueadas)

    @property
    def feitas(self) -> int:
        return len(self.desbloqueadas)

    @property
    def fracao(self) -> float:
        return self.feitas / self.total if self.total else 0.0

    @property
    def porcentagem(self) -> int:
        """Inteira, para baixo: 999 de 1000 é 99%, e só tudo desbloqueado é 100%.

        Em inteiros, não em `floor(fracao * 100)`: 29 de 100 dá
        0.29 * 100 = 28.999999999999996 em ponto flutuante.
        """
        return self.feitas * 100 // self.total if self.total else 0

    @property
    def completo(self) -> bool:
        return self.total > 0 and self.feitas == self.total


def montar(cat: Optional[Catalogo], hist: Optional[dict[str, int]]) -> Optional[Progresso]:
    if cat is None or not cat.conquistas:
        return None
    hist = hist or {}
    feitas: list[Linha] = []
    faltam: list[Linha] = []
    for info in cat.conquistas:
        quando = hist.get(info.nome.upper())
        (feitas if quando is not None else faltam).append(Linha(info, quando))
    # Mais recente primeiro. `sort` é estável, então as sem data (0) ficam no
    # fim, na ordem do catálogo.
    feitas.sort(key=lambda linha: linha.quando or 0, reverse=True)
    return Progresso(tuple(feitas), tuple(faltam))


def do_jogo(game: Any) -> Optional[Progresso]:
    appid = getattr(game, "steam_appid", None)
    if not appid or not getattr(game, "conquistas", True):
        return None
    return montar(catalogo.em_cache(str(appid)), historico.ler(game.game_id))
