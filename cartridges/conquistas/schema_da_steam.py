"""O schema de conquistas que a Steam guarda por jogo (`UserGameStatsSchema_<appid>.bin`).

As conquistas moram em blocos de estatística do tipo "ACHIEVEMENTS" (ou 4, nos
schemas antigos), um bit por conquista. O estado do usuário
(`UserGameStats_<conta>_<appid>.bin`) só diz bloco e bit; o nome, a descrição e
os ícones vêm daqui. Nunca levanta: o que não tem a forma esperada é ignorado.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ConquistaDoSchema:
    bloco: str
    bit: int
    # O "API name", o mesmo que os emuladores usam.
    nome: str
    display: dict = field(default_factory=dict)


def _de_conquistas(bloco: dict) -> bool:
    return str(bloco.get("type", "")).strip().upper() in ("ACHIEVEMENTS", "4")


def conquistas(schema: Any, appid: str) -> list[ConquistaDoSchema]:
    """As conquistas do schema, na ordem em que ele as traz."""
    raiz = schema.get(appid) if isinstance(schema, dict) else None
    blocos = raiz.get("stats") if isinstance(raiz, dict) else None
    if not isinstance(blocos, dict):
        return []
    achadas = []
    for chave_do_bloco, bloco in blocos.items():
        if not (isinstance(bloco, dict) and _de_conquistas(bloco)):
            continue
        bits = bloco.get("bits")
        if not isinstance(bits, dict):
            continue
        for chave_do_bit, item in bits.items():
            # Os bits vão de 0 a 31: chave com mais de dois caracteres nunca serve
            # (e evita o limite de dígitos do `int`, que levantaria).
            if not (
                isinstance(item, dict)
                and len(chave_do_bit) <= 2
                and chave_do_bit.isascii()
                and chave_do_bit.isdigit()
            ):
                continue
            bit = int(chave_do_bit)
            nome = item.get("name")
            nome = nome.strip() if isinstance(nome, str) else ""
            if bit > 31 or not nome:
                continue
            display = item.get("display")
            achadas.append(
                ConquistaDoSchema(
                    str(chave_do_bloco), bit, nome, display if isinstance(display, dict) else {}
                )
            )
    return achadas
