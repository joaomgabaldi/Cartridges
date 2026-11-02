# ordem.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regras puras da biblioteca: ordem da grade, filtros, busca e opções do menu.

Sem Qt: a `Linha` é a fotografia de um jogo e as funções só olham para ela. O modelo e os
proxies (`biblioteca.py`) apenas aplicam estas regras, que repetem `sort_func`, `filter_func`
e `rebuild_filter_menu` da janela GTK.
"""

import functools
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import QUrl

from cartridges.jogo import ANIMATED_SUFFIXES, Jogo
from cartridges.utils import copias_animadas
from cartridges.utils.steam import parse_release_date

MODOS = (
    "last_played", "a-z", "z-a", "released_newest", "released_oldest",
    "newest", "oldest", "playtime", "rating", "install_size",
)  # fmt: skip


@dataclass(frozen=True)
class Linha:
    jogo_id: str
    nome: str
    capa: str
    zerado: bool
    removido: bool
    status: str
    genero: str
    desenvolvedora: str
    publicadora: str
    anotacoes: str
    lancamento: str
    adicionado: int
    jogado_em: int
    tempo_de_jogo: int
    tamanho: int
    estrelas: int
    carregando: bool
    # URL da cópia WebP animada no tamanho da grade, quando já existe; senão "".
    capa_animada: str = ""

    @classmethod
    def de(cls, jogo: Jogo) -> "Linha":
        caminho = jogo.get_cover_path()  # uma só leitura: a capa e a cópia animada olham o mesmo arquivo
        return cls(
            jogo.game_id,
            jogo.name,
            _url_da_capa(caminho),
            jogo.zerado,
            jogo.removed,
            jogo.status or "",
            jogo.genre or "",
            jogo.developer or "",
            jogo.publisher or "",
            jogo.notes or "",
            jogo.release_date or "",
            jogo.added,
            jogo.last_played,
            jogo.playtime,
            jogo.install_size,
            jogo.stars,
            jogo.loading > 0,
            url_da_copia(caminho),
        )


def url_da_copia(caminho: Path | None, indice: int = 0) -> str:
    """URL da cópia animada da capa (``indice`` 0: a da grade; 1: a de detalhes), ou "" se não há.

    "" também quando a capa é parada, a cópia não existe ou é mais velha que a capa (a tela a larga
    e o ``preparar`` a refaz).
    """
    if caminho is None or caminho.suffix not in ANIMATED_SUFFIXES:
        return ""
    copia = copias_animadas.caminho_para(caminho, copias_animadas.tamanhos()[indice])
    try:
        if copia.stat().st_mtime_ns < caminho.stat().st_mtime_ns:
            return ""
    except OSError:
        return ""
    return _url_da_capa(copia)


def _url_da_capa(caminho: Path | None) -> str:
    """URL `file:` da capa; o `?v=` muda quando o arquivo é regravado, e a grade recarrega."""
    if caminho is None:
        return ""
    try:
        versao = caminho.stat().st_mtime_ns
    except OSError:
        return ""
    return f"{QUrl.fromLocalFile(str(caminho)).toString()}?v={versao}"


class _Inverso:
    """Envolve uma chave para que a ordem crescente dela seja a decrescente (z-a)."""

    __slots__ = ("valor",)

    def __init__(self, valor: Any) -> None:
        self.valor = valor

    def __eq__(self, outro: object) -> bool:
        return isinstance(outro, _Inverso) and self.valor == outro.valor

    def __lt__(self, outro: "_Inverso") -> bool:
        return outro.valor < self.valor


def _data_de_lancamento(linha: Linha) -> int:
    """Ano*10000 + mês*100 + dia (0 se faltar), ou -1 sem data utilizável."""
    ano, mes, dia = parse_release_date(linha.lancamento)
    return -1 if ano is None else ano * 10000 + (mes or 0) * 100 + (dia or 0)


@functools.lru_cache(maxsize=16384)  # a `Linha` é congelada (hashável); sem isto cada comparação refaz a data
def chave(linha: Linha, modo: str) -> tuple:
    """Chave de ordenação: a ordem crescente das chaves é a ordem da grade."""
    nome = (chave_alfabetica(linha.nome), linha.jogo_id)  # o id desempata dois jogos de mesmo nome
    if modo == "a-z":
        return (nome,)
    if modo == "z-a":
        return (_Inverso(nome),)
    if modo in ("released_newest", "released_oldest"):
        data = _data_de_lancamento(linha)
        if data < 0:  # sem data: fim, nos dois sentidos
            return (1, 0, nome)
        return (0, -data if modo == "released_newest" else data, nome)
    if modo == "rating":
        # Nota 0 é ausência de nota: vai para o fim, e não abaixo das notas baixas.
        return (1, 0, nome) if not linha.estrelas else (0, -linha.estrelas, nome)
    # Tamanho 0 ("não medido") cai no fim sozinho: é o menor valor, e a ordem é decrescente.
    if modo == "newest":
        return (-linha.adicionado, nome)
    if modo == "oldest":
        return (linha.adicionado, nome)
    if modo == "playtime":
        return (-linha.tempo_de_jogo, nome)
    if modo == "install_size":
        return (-linha.tamanho, nome)
    return (-linha.jogado_em, nome)  # last_played, e qualquer modo desconhecido


def passa(linha: Linha, busca: str, genero: str, ano: str, status: str) -> bool:
    """Se a linha passa pela busca e pelos filtros; `""` é "Todos". Campo ausente só passa em "Todos"."""
    if busca:
        busca = busca.lower()
        if not any(busca in campo.lower() for campo in (linha.nome, linha.desenvolvedora, linha.publicadora, linha.anotacoes)):
            return False
    if genero and linha.genero != genero:
        return False
    if ano and str(parse_release_date(linha.lancamento)[0] or "") != ano:
        return False
    return not (status and linha.status != status)


def chave_alfabetica(texto: str) -> str:
    """Ordem alfabética que não exila os acentos: NFKD separa a marca da letra-base e a marca é descartada."""
    decomposto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def opcoes(linhas: Iterable[Linha]) -> tuple[list[str], list[str]]:
    """Gêneros (ordem alfabética) e anos (decrescente) do que a biblioteca e os zerados têm."""
    generos: set[str] = set()
    anos: set[str] = set()
    for linha in linhas:
        if linha.genero:
            generos.add(linha.genero)
        if ano := parse_release_date(linha.lancamento)[0]:
            anos.add(str(ano))
    return sorted(generos, key=lambda g: (chave_alfabetica(g), g)), sorted(anos, reverse=True)
