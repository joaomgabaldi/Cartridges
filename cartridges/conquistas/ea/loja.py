"""A EA como "loja com conta" (`conquistas/contas.py`): só adapta `api`, `conta` e `jogo`.

Cada função procura o nome no módulo na hora da chamada (os testes os trocam).
"""

from typing import Any, Optional

from cartridges.conquistas.contas import Leitura
from cartridges.conquistas.ea import api, conta, jogo
from cartridges.conquistas.formatos import Desbloqueio

TIPO = "ea"
FalhaDeRede = api.FalhaDeRede


def conectada() -> bool:
    return conta.conectada()


def id_da_conta() -> Optional[str]:
    return conta.persona()


def resolver(game: Any, _fonte: Any) -> Optional[str]:
    """O conjunto de conquistas do jogo: o título da instalação, achado na biblioteca da conta.

    ``""`` = sabidamente sem fonte (não é da biblioteca, ou a oferta não tem conquistas);
    ``None`` = não se sabe (sem conta). O resultado vai ao cache, para a próxima passada.
    """
    from cartridges.conquistas import fontes  # noqa: PLC0415  (fontes importa contas)

    candidato = fontes.candidato_da_ea(game)
    if candidato is None:
        return ""
    conjunto = ""
    desconhecida = False
    # Cada título que o jogo tem (pt_BR, en_US, DisplayName), em ordem, até um dar conjunto.
    for titulo in candidato.titulos or (candidato.titulo,):
        ofertas = api.ofertas(jogo.normalizar(titulo))
        if ofertas is None:
            return None
        for oferta in ofertas:
            achado = api.conjunto_da_oferta(oferta)
            if achado:
                conjunto = achado
                break
            desconhecida = desconhecida or achado is None
        if conjunto:
            break
    if not conjunto and desconhecida:
        return None  # uma oferta não respondeu: não se sabe, e "sem fonte" não pode ser guardado
    api.guardar_conjunto(candidato.pasta, conjunto)
    return conjunto


def ler(id_: str) -> Optional[Leitura]:
    return api.ler(id_)


def desbloqueadas(id_: str) -> Optional[list[Desbloqueio]]:
    return api.desbloqueadas(id_)


def chave_do_catalogo(id_: str) -> str:
    return api.chave_do_catalogo(id_)
