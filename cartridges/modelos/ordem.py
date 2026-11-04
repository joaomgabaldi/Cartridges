# ordem.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regras puras da biblioteca: ordem da grade, filtros, busca e opções do menu."""

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
    tem_atualizacao: bool = False

    @classmethod
    def de(cls, jogo: Jogo) -> "Linha":
        caminho = jogo.get_cover_path()
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
            bool(jogo.has_update and not jogo.zerado),
        )


def url_da_copia(caminho: Path | None, indice: int = 0) -> str:
    """URL da cópia animada da capa (``indice`` 0: a da grade; 1: a de detalhes), ou "" se não há."""
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
    ano, mes, dia = parse_release_date(linha.lancamento)
    return -1 if ano is None else ano * 10000 + (mes or 0) * 100 + (dia or 0)


@functools.lru_cache(maxsize=16384)  # a `Linha` é congelada (hashável); sem isto cada comparação refaz a data
def chave(linha: Linha, modo: str) -> tuple:
    nome = (chave_alfabetica(linha.nome), linha.jogo_id)
    if modo == "a-z":
        return (nome,)
    if modo == "z-a":
        return (_Inverso(nome),)
    if modo in ("released_newest", "released_oldest"):
        data = _data_de_lancamento(linha)
        if data < 0:
            return (1, 0, nome)
        return (0, -data if modo == "released_newest" else data, nome)
    if modo == "rating":
        return (1, 0, nome) if not linha.estrelas else (0, -linha.estrelas, nome)
    if modo == "newest":
        return (-linha.adicionado, nome)
    if modo == "oldest":
        return (linha.adicionado, nome)
    if modo == "playtime":
        return (-linha.tempo_de_jogo, nome)
    if modo == "install_size":
        return (-linha.tamanho, nome)
    return (-linha.jogado_em, nome)


def passa(linha: Linha, busca: str, genero: str, ano: str, status: str) -> bool:
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
    decomposto = unicodedata.normalize("NFKD", texto.casefold())
    return "".join(c for c in decomposto if not unicodedata.combining(c))


def opcoes(linhas: Iterable[Linha]) -> tuple[list[str], list[str]]:
    generos: set[str] = set()
    anos: set[str] = set()
    for linha in linhas:
        if linha.genero:
            generos.add(linha.genero)
        if ano := parse_release_date(linha.lancamento)[0]:
            anos.add(str(ano))
    return sorted(generos, key=lambda g: (chave_alfabetica(g), g)), sorted(anos, reverse=True)
