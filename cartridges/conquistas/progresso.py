"""O catálogo cruzado com o histórico: o que a página do jogo e a lista mostram.

Só contam as conquistas que existem no catálogo (`resolveUnlockedAchievementCount`
do Hydra): um nome estranho no arquivo de um crack fica guardado, mas não infla o
"X de Y". Sem catálogo não há o que mostrar, e o cartão some. Também some sem
fonte gravada no histórico (a varredura grava de onde vêm as conquistas do jogo):
sem de onde ler o progresso, "0 de N" ficaria parado para sempre.
"""

from dataclasses import dataclass
from typing import Any, NamedTuple, Optional
from xml.sax.saxutils import escape as _escapar

from cartridges.conquistas import catalogo, fontes, historico
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

    @property
    def em_ordem_da_sessao(self) -> tuple[Linha, ...]:
        """A fila da tela de sessão: as desbloqueadas (mais recente primeiro),
        depois as bloqueadas que se pode ver e, por último, as ocultas."""
        visiveis = tuple(linha for linha in self.bloqueadas if not linha.info.oculta)
        ocultas = tuple(linha for linha in self.bloqueadas if linha.info.oculta)
        return self.desbloqueadas + visiveis + ocultas


def montar(cat: Optional[Catalogo], hist: Optional[dict[str, int]]) -> Optional[Progresso]:
    if cat is None or not cat.conquistas:
        return None
    hist = hist or {}
    feitas: list[Linha] = []
    faltam: list[Linha] = []
    for info in cat.conquistas:
        quando = hist.get(info.nome.upper())
        linha = Linha(info, quando)
        (feitas if quando is not None else faltam).append(linha)
    # Mais recente primeiro. `sort` é estável, então as sem data (0) ficam no
    # fim, na ordem do catálogo.
    feitas.sort(key=lambda linha: linha.quando or 0, reverse=True)
    return Progresso(tuple(feitas), tuple(faltam))


def do_jogo(game: Any) -> Optional[Progresso]:
    """O progresso do cartão, ou None (cartão oculto): interruptor desligado,
    sem fonte gravada, conta Xbox desconectada ou sem catálogo."""
    if not getattr(game, "conquistas", True):
        return None
    fonte = fontes.gravada(game)
    if not fontes.ativa(fonte):
        return None
    return montar(catalogo.em_cache(fontes.chave_do_catalogo(fonte)), historico.ler(game.game_id))


def porcentagem_em_texto(valor: float) -> str:
    """Porcentagem global no jeito brasileiro: 4.1 vira "4,1%"."""
    return f"{valor:.1f}%".replace(".", ",")


class Aparencia(NamedTuple):
    """O que um ícone de conquista mostra: de onde vem a imagem, se leva o
    filtro cinza e se é a interrogação de uma oculta."""

    origem: str
    cinza: bool
    oculta: bool


def _escondida(linha: Linha, mostrar_ocultas: bool) -> bool:
    return linha.info.oculta and not linha.desbloqueada and not mostrar_ocultas


def aparencia(linha: Linha, mostrar_ocultas: bool) -> Aparencia:
    """A regra da lista e da tela de sessão: colorida se desbloqueada; a
    bloqueada usa o ícone cinza da loja ou, sem ele, o mesmo em cinza."""
    if _escondida(linha, mostrar_ocultas):
        return Aparencia("", False, True)
    info = linha.info
    if linha.desbloqueada:
        return Aparencia(info.icone, False, False)
    return Aparencia(info.icone_cinza or info.icone, not info.icone_cinza, False)


def dica(linha: Linha, mostrar_ocultas: bool) -> str:
    """O texto ao passar o mouse no ícone: nome, descrição e porcentagem (markup Pango)."""
    if _escondida(linha, mostrar_ocultas):
        return "<b>{}</b>\n{}".format(
            _escapar(_("Conquista oculta")), _escapar(_("Os detalhes aparecem depois do desbloqueio."))
        )
    info = linha.info
    partes = [f"<b>{_escapar(info.titulo)}</b>"]
    if info.descricao:
        partes.append(_escapar(info.descricao))
    if info.porcentagem is not None:
        # A variável é a porcentagem já formatada, como "3,8%"
        partes.append(_escapar(_("{} dos jogadores").format(porcentagem_em_texto(info.porcentagem))))
    return "\n".join(partes)
