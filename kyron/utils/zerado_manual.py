# zerado_manual.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Jogos Zerados adicionados à mão: jogos terminados fora do app (console, outro PC, anos atrás).

Viram um jogo zerado ``imported_N``, sem atalho, executável nem tempo de jogo; backup, edição, Excluir e
ordenação não precisam saber que ele existe. Sem repetição: o que já está em Jogos Zerados ou na biblioteca
não é criado de novo, e um desinstalado com a mesma identidade é marcado em vez de ganhar cópia.
"""

from time import time
from typing import Optional

from kyron import shared
from kyron.jogo import Jogo
from kyron.store.managers.hltb_manager import HLTBManager
from kyron.store.managers.sgdb_manager import SgdbManager
from kyron.store.managers.steam_api_manager import SteamAPIManager
from kyron.utils.name_cleaner import clean_for_search, clean_game_name
from kyron.utils.steam import SteamAPIHelper, SteamRateLimiter


def _chaves(nome: str, appid: Optional[str]) -> set[str]:
    """As duas identidades de um jogo, appID e nome limpo."""
    chaves = {f"nome:{clean_for_search(nome or '').casefold()}"}
    if appid:
        chaves.add(f"steam:{appid}")
    return chaves


# Chave de `_chaves` → os jogos (fora da lista negra) com ela e a posição de cada um na store (o último da biblioteca vence).
Indice = dict[str, list[tuple[int, Jogo]]]


def indice() -> Indice:
    """Os jogos por chave, para várias `situacao` seguidas sem relimpar cada nome da biblioteca."""
    por_chave: Indice = {}
    for posicao, jogo in enumerate(shared.store):
        if jogo.blacklisted:
            continue
        for chave in _chaves(jogo.name, jogo.steam_appid):
            por_chave.setdefault(chave, []).append((posicao, jogo))
    return por_chave


def situacao(
    nome: str, appid: Optional[str] = None, jogos: Optional[Indice] = None
) -> tuple[str, Optional[Jogo]]:
    """Onde o jogo já está: ``"zerado"``, ``"biblioteca"``, ``"desinstalado"`` (o jogado por último) ou ``"novo"``.

    ``jogos``: um `indice` já montado."""
    por_chave = indice() if jogos is None else jogos
    # Pela posição: o jogo com as duas chaves conta uma vez.
    achados = {
        posicao: jogo
        for chave in _chaves(nome, appid)
        for posicao, jogo in por_chave.get(chave, ())
    }
    na_biblioteca: Optional[Jogo] = None
    desinstalados: list[Jogo] = []
    for _posicao, jogo in sorted(achados.items(), key=lambda item: item[0]):
        if jogo.zerado:
            return ("zerado", jogo)
        if not jogo.removed:
            na_biblioteca = jogo
        else:
            desinstalados.append(jogo)
    if na_biblioteca is not None:
        return ("biblioteca", na_biblioteca)
    if desinstalados:
        return ("desinstalado", max(desinstalados, key=lambda j: j.last_played or 0))
    return ("novo", None)


def criar(nome: str, appid: Optional[str] = None) -> Jogo:
    """Cria o jogo zerado, já na grade de Jogos Zerados."""
    dados = {
        "game_id": shared.store.proximo_id_importado(),
        "source": "imported",
        "name": clean_game_name(nome),
        "executable": "",
        "added": int(time()),
        "removed": True,
        "status": "beaten",
    }
    if appid:
        dados["steam_appid"] = str(appid)
    jogo = Jogo(dados)
    shared.store.add_game(jogo, {})
    jogo.save()
    return jogo


def buscar_dados(jogo: Jogo) -> None:
    """Steam → HowLongToBeat → SteamGridDB, em sequência, como na atualização de metadados.

    Sem appID não há o que buscar. `sem_ligacao`: `situacao` já impede um zerado com o appID de um jogo da biblioteca.
    """
    ordem = [
        manager
        for manager in (
            shared.store.managers.get(classe)
            for classe in (SteamAPIManager, HLTBManager, SgdbManager)
        )
        if manager is not None
    ]
    if not jogo.steam_appid or not ordem:
        return

    dados = {"zerado_manual": True, "sem_ligacao": True}
    jogo.set_loading(1)

    def proximo(indice: int) -> None:
        if indice >= len(ordem):
            jogo.set_loading(-1)
            # Excluído enquanto buscava: não grava de volta no disco.
            if shared.store.get(jogo.game_id) is jogo:
                jogo.save()
                jogo.update()
            return
        ordem[indice].process_game(jogo, dados, lambda _m: proximo(indice + 1))

    proximo(0)


def adicionar(nome: str, appid: Optional[str] = None) -> Optional[Jogo]:
    """O clique no diálogo. ``None`` se o jogo já está em Jogos Zerados ou na biblioteca (segunda trava)."""
    estado, existente = situacao(nome, appid)
    if estado == "desinstalado" and existente is not None:
        existente.definir_status("beaten")
        existente.save()
        existente.update()
        return existente
    if estado != "novo":
        return None
    jogo = criar(nome, appid)
    buscar_dados(jogo)
    return jogo


def helper_da_steam() -> SteamAPIHelper:
    """O helper do manager: um `SteamRateLimiter` por busca vazaria a thread de recarga dele."""
    manager = shared.store.managers.get(SteamAPIManager)
    return manager.steam_api_helper if manager else SteamAPIHelper(SteamRateLimiter())
