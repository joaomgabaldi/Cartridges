# session_fita.py
#
# Copyright 2026 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As fitas de LED atrás dos monitores, acompanhando o app e a sessão.

O ciclo tem quatro momentos: o app abre e as fitas acendem no roxo dele, o jogo
abre e elas vestem a cor daquele jogo, o jogo fecha e elas voltam ao roxo, o app
fecha e elas voltam exatamente ao que eram antes de tudo — inclusive apagadas.

O estado de antes fica no GSettings, e não em memória, pela mesma razão do papel
de parede de sessão: o app morto no meio da sessão deixaria as três fitas
vestidas de um jogo que já acabou, e só o arranque seguinte pode desfazer isso.

A conversa é local. A nuvem da Tuya entra uma única vez, no assistente, para
buscar a chave de cada módulo; daí em diante é o PC falando direto com a fita.
"""

import json
import logging
import time
from typing import Any, NamedTuple, Optional, TYPE_CHECKING

from cartridges import shared
from cartridges.utils.cor_da_capa import dominante

if TYPE_CHECKING:
    from cartridges.game import Game

# Matiz e saturação do #9141ac, o roxo da paleta do app. O brilho não entra:
# ele é do usuário.
ROXO_DO_APP = (284, 620)


class Fita(NamedTuple):
    """Um módulo Tuya, do jeito que ele fica no `fitas.json`."""

    nome: str
    id: str
    ip: str
    key: str
    versao: str = "3.3"


class Cor(NamedTuple):
    """Matiz (0–359), saturação (0–1000) e brilho (0–1000)."""

    matiz: int
    saturacao: int
    brilho: int


# region Configuração


def fitas() -> list[Fita]:
    """As fitas configuradas. Lista vazia quando não há configuração válida."""
    try:
        dados = json.loads(shared.fitas_arquivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(dados, dict):
        return []
    achadas = []
    for item in dados.get("fitas", []):
        try:
            achadas.append(
                Fita(
                    str(item["nome"]),
                    str(item["id"]),
                    str(item["ip"]),
                    str(item["key"]),
                    str(item.get("versao", "3.3")),
                )
            )
        except (KeyError, TypeError):
            logging.warning("Fita ignorada por estar incompleta no arquivo")
    return achadas


def gravar_fitas(lista: list[Fita]) -> None:
    """Grava a configuração. Escreve num temporário e troca, para não perder o
    arquivo se a energia cair no meio."""
    shared.fitas_arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = shared.fitas_arquivo.with_suffix(".json.tmp")
    conteudo = {"fitas": [fita._asdict() for fita in lista]}
    try:
        temporario.write_text(json.dumps(conteudo), encoding="utf-8")
        temporario.replace(shared.fitas_arquivo)
    except OSError as erro:
        logging.warning("Não foi possível gravar as fitas: %s", erro)


# endregion
# region Cor por jogo


def _sidecar(game_id: str):
    return shared.fitas_dir / f"{game_id}.json"


def _ler_sidecar(game_id: str) -> Optional[dict[str, Any]]:
    try:
        dados = json.loads(_sidecar(game_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


def escolhida(game_id: str) -> bool:
    """Se a cor deste jogo foi escolhida por gente, e não pela capa."""
    dados = _ler_sidecar(game_id)
    return bool(dados and dados.get("locked"))


def salvar_cor(game_id: str, name: str, cor: Cor) -> None:
    """Guarda a escolha manual de um jogo."""
    shared.fitas_dir.mkdir(parents=True, exist_ok=True)
    dados = {
        "name": name,
        "matiz": cor.matiz,
        "saturacao": cor.saturacao,
        "brilho": cor.brilho,
        "locked": True,
        "timestamp": int(time.time()),
    }
    try:
        _sidecar(game_id).write_text(json.dumps(dados), encoding="utf-8")
    except OSError as erro:
        logging.warning("Não foi possível gravar a cor da fita: %s", erro)


def redefinir(game_id: str) -> None:
    """Devolve o jogo à cor automática."""
    _sidecar(game_id).unlink(missing_ok=True)


def brilho_padrao() -> int:
    return shared.schema.get_int("fita-brilho-padrao")


def cor_do_jogo(game: "Game") -> Cor:
    """A cor que este jogo veste: a escolhida, a da capa, ou o roxo do app."""
    dados = _ler_sidecar(game.game_id)
    if dados and dados.get("locked"):
        return Cor(
            int(dados.get("matiz", ROXO_DO_APP[0])),
            int(dados.get("saturacao", ROXO_DO_APP[1])),
            int(dados.get("brilho", brilho_padrao())),
        )

    capa = game.get_cover_path()
    da_capa = dominante(capa) if capa else None
    matiz, saturacao = da_capa if da_capa else ROXO_DO_APP
    return Cor(matiz, saturacao, brilho_padrao())


# endregion
