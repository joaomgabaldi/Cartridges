"""As conquistas desbloqueadas de cada jogo, guardadas pelo app.

Os arquivos dos emuladores não bastam: os que ficam na pasta do jogo vão embora
com a desinstalação, e trocar o crack ou reinstalar zera o arquivo. Então o app
guarda o que já leu, e a regra é a do Hydra (`mergeUnlockedAchievementLists`):
**só soma**. Conquista nova entra; conquista que some do arquivo fica; a mesma
conquista com outra data fica com a mais antiga.

Um arquivo por jogo, `conquistas/<id>.json`, para acompanhar o jogo como o resto
dos dados por id: Jogos Zerados (o id não muda), troca de id e Excluir
(`store.py`), ligação de zerado (`transferir`) e backup.

Não existir o arquivo é o que marca "nunca varrido": a primeira varredura grava
mesmo sem nada desbloqueado, e não conta como conquista nova.
"""

import json
import logging
import math
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

from cartridges import shared
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.utils.ler_json import ler_json

_trava = threading.Lock()


def caminho(game_id: str) -> Path:
    return shared.conquistas_dir / f"{game_id}.json"


def _limpo(dados: Any) -> Optional[dict[str, int]]:
    if not isinstance(dados, dict) or not isinstance(dados.get("desbloqueadas"), dict):
        return None
    return {
        str(nome).upper(): int(quando)
        for nome, quando in dados["desbloqueadas"].items()
        if _data_valida(quando) and str(nome).strip()
    }


def _data_valida(quando: Any) -> bool:
    """Número que cabe como data: nem bool, nem NaN/infinito, nem gigante demais."""
    if isinstance(quando, bool) or not isinstance(quando, (int, float)):
        return False
    if isinstance(quando, float) and not math.isfinite(quando):
        return False
    return -(2**63) <= quando < 2**63


def _ler_estado(game_id: str) -> tuple[Optional[dict[str, int]], bool]:
    """``(dados, ilegivel)``: ``ilegivel`` é True se o arquivo existe e não deu para ler."""
    try:
        dados = ler_json(caminho(game_id))
    except FileNotFoundError:
        return None, False
    except (OSError, ValueError, RecursionError, OverflowError) as erro:
        logging.warning("Conquistas guardadas ilegíveis (%s): %s", caminho(game_id).name, erro)
        return None, True
    limpo = _limpo(dados)
    if limpo is None:
        logging.warning(
            "Conquistas guardadas ilegíveis (%s): formato inesperado", caminho(game_id).name
        )
        return None, True
    return limpo, False


def ler(game_id: str) -> Optional[dict[str, int]]:
    """O que está guardado, ou None se o jogo nunca foi varrido (ou está ilegível)."""
    return _ler_estado(game_id)[0]


def _guardar_ilegivel(game_id: str) -> bool:
    """Põe de lado o arquivo ilegível, para não ser sobrescrito. False se não deu."""
    origem = caminho(game_id)
    try:
        origem.replace(origem.with_name(origem.name + ".corrompido"))
    except OSError as erro:
        logging.warning("Conquistas de %s ilegíveis e não guardadas à parte: %s", game_id, erro)
        return False
    logging.warning("Conquistas de %s ilegíveis; guardadas em %s.corrompido", game_id, origem.name)
    return True


def fundir(
    atual: dict[str, int], novos: Iterable[Desbloqueio]
) -> tuple[dict[str, int], list[str]]:
    """``atual`` mais ``novos``, sem tirar nada. Devolve também as que entraram."""
    resultado = dict(atual)
    entraram: list[str] = []
    for desbloqueio in novos:
        nome = desbloqueio.nome.strip().upper()
        if not nome:
            continue
        quando = max(int(desbloqueio.quando), 0)
        if nome not in resultado:
            resultado[nome] = quando
            entraram.append(nome)
        elif quando and (not resultado[nome] or quando < resultado[nome]):
            resultado[nome] = quando
    return resultado, entraram


def _gravar(game_id: str, desbloqueadas: dict[str, int]) -> None:
    destino = caminho(game_id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    temporario.write_text(
        json.dumps({"desbloqueadas": desbloqueadas}, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporario.replace(destino)


def registrar(game_id: str, novos: Iterable[Desbloqueio]) -> tuple[list[str], bool]:
    """Funde ``novos`` no que está guardado e grava.

    Devolve ``(as que entraram agora, se era a primeira vez)``.
    """
    with _trava:
        atual, ilegivel = _ler_estado(game_id)
        if ilegivel and not _guardar_ilegivel(game_id):
            return [], False
        primeira = atual is None
        resultado, entraram = fundir(atual or {}, novos)
        if primeira or resultado != atual:
            try:
                _gravar(game_id, resultado)
            except OSError as erro:
                logging.warning("Conquistas de %s não gravadas: %s", game_id, erro)
        return entraram, primeira


def transferir(de_id: str, para_id: str) -> None:
    """Funde o que ``de_id`` tem no que ``para_id`` tem (ligação de zerado)."""
    with _trava:
        origem, origem_ilegivel = _ler_estado(de_id)
        if origem_ilegivel:
            # Quem chama exclui a origem logo depois, e o Excluir apaga
            # `<id>.json`: pô-lo à parte antes, para o que não deu para ler
            # não ir embora junto.
            logging.warning("Conquistas de %s ilegíveis: nada a transferir", de_id)
            _guardar_ilegivel(de_id)
            return
        if not origem:
            return
        destino, destino_ilegivel = _ler_estado(para_id)
        if destino_ilegivel and not _guardar_ilegivel(para_id):
            return
        resultado, _entraram = fundir(
            destino or {}, [Desbloqueio(nome, quando) for nome, quando in origem.items()]
        )
        try:
            _gravar(para_id, resultado)
        except OSError as erro:
            logging.warning("Conquistas de %s não transferidas: %s", de_id, erro)


def apagar(game_id: str) -> None:
    with _trava:
        try:
            caminho(game_id).unlink(missing_ok=True)
        except OSError as erro:
            logging.warning("Conquistas de %s não apagadas: %s", game_id, erro)
