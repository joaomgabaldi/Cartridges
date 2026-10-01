# restauracao.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que sobra de uma restauração de backup depois da troca: os jogos
restaurados cujo atalho ainda não foi encontrado.

Tudo aqui só existe enquanto `restauracao_pendente.json` existir na pasta do
app. Sem o arquivo, a importação, a biblioteca e a abertura seguem como
sempre. O arquivo nasce na troca (`backup.aplicar_pendente`) e morre quando a
última pendência sai.
"""

import difflib
import json
import logging
import shutil
from pathlib import Path
from typing import Iterable, Optional

from cartridges import shared
from cartridges.conquistas import historico
from cartridges.game import Game
from cartridges.importer.shortcuts_source import atalhos_da_pasta
from cartridges.store.store import _path_key
from cartridges.utils import session_log
from cartridges.utils.name_cleaner import clean_for_search

_NOME = "restauracao_pendente.json"

# Lido uma vez por caminho: `e_pendente` roda para cada card em todo filtro da
# biblioteca. A chave é o caminho, e não um valor único, porque os testes
# repontam `shared.app_dir` a cada teste. Só `gravar` escreve o arquivo, e ela
# descarta a entrada.
_cache: dict[str, tuple[frozenset[str], int]] = {}


def _arquivo() -> Path:
    return shared.app_dir / _NOME


def _ler() -> tuple[frozenset[str], int]:
    caminho = _arquivo()
    chave = str(caminho)
    if chave not in _cache:
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
            lidos = (
                frozenset(str(game_id) for game_id in dados.get("jogos", [])),
                int(dados.get("restaurado_em", 0)),
            )
        except FileNotFoundError:
            lidos = (frozenset(), 0)
        except (OSError, ValueError, TypeError, AttributeError):
            # Ilegível: sem pendências. A próxima importação regrava a lista
            # vazia e o arquivo some, encerrando o fluxo.
            logging.warning("%s ilegível; pendências da restauração ignoradas", caminho)
            lidos = (frozenset(), 0)
        _cache[chave] = lidos
    return _cache[chave]


def existe() -> bool:
    return _arquivo().is_file()


def ids() -> frozenset[str]:
    return _ler()[0]


def restaurado_em() -> int:
    return _ler()[1]


def e_pendente(game_id: str) -> bool:
    return game_id in _ler()[0]


def gravar(game_ids: Iterable[str], quando: int) -> None:
    """Grava as pendências. Lista vazia apaga o arquivo e encerra o fluxo."""
    caminho = _arquivo()
    _cache.pop(str(caminho), None)
    ordenados = sorted(set(game_ids))
    if not ordenados:
        caminho.unlink(missing_ok=True)
        return
    temporario = caminho.with_name(_NOME + ".tmp")
    temporario.write_text(
        json.dumps({"restaurado_em": quando, "jogos": ordenados}, ensure_ascii=False),
        encoding="utf-8",
    )
    temporario.replace(caminho)


def remover(game_id: str) -> None:
    if e_pendente(game_id):
        gravar(ids() - {game_id}, restaurado_em())


def resolver(encontrados: set[str]) -> None:
    """Depois de uma importação que varreu a pasta de atalhos até o fim.

    Sai da lista o pendente que a varredura achou (``encontrados`` é o
    ``duplicate_game_ids`` da store) e o que não está mais na store com esse id:
    a âncora do atalho o adotou sob um id novo, ou ele foi excluído.
    """
    restantes = []
    for game_id in ids():
        jogo = shared.store.get(game_id)
        if jogo is None or jogo.removed or game_id in encontrados:
            continue
        restantes.append(game_id)
    gravar(restantes, restaurado_em())


def pendentes() -> list[Game]:
    jogos = [jogo for game_id in ids() if (jogo := shared.store.get(game_id)) is not None]
    return sorted(jogos, key=lambda jogo: jogo.name.casefold())


def ids_que_dependem_de_atalho(pasta_games: Path) -> list[str]:
    """Os jogos de ``pasta_games`` que só abrem com um atalho: vivos, visíveis
    e de fonte de atalhos. Um manual (``imported``) ou um zerado não dependem
    de atalho nenhum para aparecer."""
    game_ids = []
    for arquivo in sorted(pasta_games.glob("*.json")):
        try:
            dados = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(dados, dict)
            and isinstance(dados.get("game_id"), str)
            and dados.get("source") != "imported"
            and not dados.get("removed")
            and not dados.get("blacklisted")
        ):
            game_ids.append(dados["game_id"])
    return game_ids


# region Escolher atalho


class AtalhoJaExiste(Exception):
    """Já existe na pasta de atalhos um arquivo com o nome do escolhido."""


def _do_backup(jogo: Game) -> bool:
    """Veio no backup, e não da importação depois dele."""
    return (jogo.added or 0) < restaurado_em()


def _pasta() -> Path:
    return Path(shared.schema.get_string("shortcuts-location")).expanduser()


def candidatos(jogo: Game) -> list[Path]:
    """Os atalhos da pasta que nenhum jogo do backup usa, os de nome mais
    parecido com o de ``jogo`` primeiro. Os de jogos que a importação criou
    depois da restauração entram: escolher um deles resolve o conflito."""
    usados = {
        _path_key(outro.shortcut_path)
        for outro in shared.store
        if outro.shortcut_path and _do_backup(outro)
    }
    alvo = clean_for_search(jogo.name).casefold()

    def parecido(caminho: Path) -> float:
        nome = clean_for_search(caminho.stem).casefold()
        return difflib.SequenceMatcher(None, alvo, nome).ratio()

    livres = [c for c in atalhos_da_pasta() if _path_key(str(c)) not in usados]
    return sorted(livres, key=lambda c: (-parecido(c), c.name.casefold()))


def copiar_para_a_pasta(origem: Path) -> Path:
    """``origem`` como a importação vai enxergá-lo: dentro da pasta de
    atalhos. Um arquivo de fora é copiado para a raiz dela (o original fica
    onde está). ``AtalhoJaExiste`` se já houver lá um arquivo com esse nome:
    dois atalhos do mesmo jogo virariam um jogo duplicado na importação."""
    raiz = _pasta()
    chave_raiz = _path_key(str(raiz)).rstrip("\\")
    chave_pai = _path_key(str(origem.parent)).rstrip("\\")
    if chave_pai == chave_raiz or (
        shared.schema.get_boolean("shortcuts-recursive")
        and chave_pai.startswith(chave_raiz + "\\")
    ):
        return origem
    destino = raiz / origem.name
    if destino.exists():
        raise AtalhoJaExiste(origem.name)
    shutil.copy2(origem, destino)
    return destino


def jogo_do_atalho(caminho: Path) -> Optional[Game]:
    """O jogo que a importação criou a partir de ``caminho`` depois da
    restauração, se houver."""
    chave = _path_key(str(caminho))
    for jogo in shared.store:
        if (
            jogo.shortcut_path
            and not jogo.removed
            and not jogo.blacklisted
            and not _do_backup(jogo)
            and _path_key(jogo.shortcut_path) == chave
        ):
            return jogo
    return None


def tem_historico(jogo: Game) -> bool:
    """Horas jogadas ou sessões. As duas, e não só as sessões: o tempo é
    gravado a cada minuto de jogo, e a sessão só entra no histórico quando
    termina bem. Um jogo cuja sessão caiu no meio tem horas e nenhuma sessão,
    e excluí-lo sem perguntar apagaria esse tempo."""
    return bool(jogo.playtime) or bool(session_log.load(jogo.game_id))


def resumo(jogo: Game) -> tuple[int, int, int]:
    """(segundos jogados, número de sessões, última vez jogado) para os
    cartões da tela de conflito."""
    return jogo.playtime or 0, len(session_log.load(jogo.game_id)), jogo.last_played or 0


def excluir(jogo: Game) -> None:
    """Exclui ``jogo`` de vez, sem tumba, e o tira das pendências."""
    shared.win.retirar_da_grade(jogo)
    shared.store.excluir(jogo)
    remover(jogo.game_id)


def decidir(restaurado: Game, caminho: Path, novo: Optional[Game], decisao: str) -> None:
    """Aplica a escolha feita para ``restaurado`` com o atalho ``caminho``.

    ``novo`` é o jogo que a importação já criou a partir de ``caminho``, se
    houver. ``"backup"`` e ``"mesclar"`` ficam com o restaurado (a mescla leva
    antes as sessões e o tempo do novo); ``"este_pc"`` fica com o novo. Quem
    chama importa em seguida, exceto em ``"este_pc"``: é a varredura que adota
    o restaurado pelo atalho novo e o tira das pendências.
    """
    if decisao == "este_pc":
        excluir(restaurado)
        return
    if novo is not None:
        if decisao == "mesclar":
            session_log.mover_jogo(novo.game_id, restaurado.game_id)
            # As conquistas do jogo novo também são somadas, não perdidas
            # com o Excluir logo abaixo.
            historico.transferir(novo.game_id, restaurado.game_id)
            restaurado.playtime = (restaurado.playtime or 0) + (novo.playtime or 0)
            restaurado.last_played = max(restaurado.last_played or 0, novo.last_played or 0)
        excluir(novo)
    shared.store.apontar_atalho(restaurado, str(caminho))


# endregion
