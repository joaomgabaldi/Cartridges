"""As conquistas desbloqueadas de cada jogo, guardadas pelo app.

Os arquivos dos emuladores não bastam: os que ficam na pasta do jogo vão embora
com a desinstalação, e trocar o crack ou reinstalar zera o arquivo. Então o app
guarda o que já leu, e a regra é a do Hydra (`mergeUnlockedAchievementLists`):
**só soma**. Conquista nova entra; conquista que some do arquivo fica; a mesma
conquista com outra data fica com a mais antiga.

Um arquivo por jogo, `conquistas/<id>.json`, para acompanhar o jogo como o resto
dos dados por id: Jogos Zerados (o id não muda), troca de id e Excluir
(`store.py`), ligação de zerado (`transferir`) e backup.

O arquivo também guarda de onde vêm as conquistas do jogo (`"fonte"`, como
`"xbox:123"` ou `"steam:570"`; ver `fontes.py`). A regra de só somar vale para as
desbloqueadas; a fonte é só um dado do jogo e pode trocar.

Não existir o arquivo é o que marca "nunca varrido": a primeira varredura grava
mesmo sem nada desbloqueado, e não conta como conquista nova.
"""

import enum
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


def _limpo(dados: Any) -> Optional[tuple[dict[str, int], Optional[str]]]:
    if not isinstance(dados, dict) or not isinstance(dados.get("desbloqueadas"), dict):
        return None
    desbloqueadas = {
        str(nome).upper(): int(quando)
        for nome, quando in dados["desbloqueadas"].items()
        if _data_valida(quando) and str(nome).strip()
    }
    fonte = dados.get("fonte")
    return desbloqueadas, fonte if isinstance(fonte, str) and fonte.strip() else None


def _data_valida(quando: Any) -> bool:
    """Número que cabe como data: nem bool, nem NaN/infinito, nem gigante demais."""
    if isinstance(quando, bool) or not isinstance(quando, (int, float)):
        return False
    if isinstance(quando, float) and not math.isfinite(quando):
        return False
    return -(2**63) <= quando < 2**63


class _Estado(enum.Enum):
    OK = enum.auto()
    # Existe e o conteúdo não presta (JSON inválido, formato errado): vai para o `.corrompido`.
    ILEGIVEL = enum.auto()
    # Existe, mas não deu para abrir agora (antivírus, indexador, disco): o
    # conteúdo pode estar perfeito, então nada é gravado nem renomeado.
    INDISPONIVEL = enum.auto()


def _ler_estado(
    game_id: str,
) -> tuple[Optional[tuple[dict[str, int], Optional[str]]], _Estado]:
    """``(dados, estado)``, com ``dados`` sendo ``(desbloqueadas, fonte)``.

    Sem arquivo: ``(None, OK)``, o jogo nunca foi varrido.
    """
    try:
        dados = ler_json(caminho(game_id))
    except FileNotFoundError:
        return None, _Estado.OK
    except OSError as erro:
        logging.warning("Conquistas guardadas indisponíveis (%s): %s", caminho(game_id).name, erro)
        return None, _Estado.INDISPONIVEL
    except (ValueError, RecursionError, OverflowError) as erro:
        logging.warning("Conquistas guardadas ilegíveis (%s): %s", caminho(game_id).name, erro)
        return None, _Estado.ILEGIVEL
    limpo = _limpo(dados)
    if limpo is None:
        logging.warning(
            "Conquistas guardadas ilegíveis (%s): formato inesperado", caminho(game_id).name
        )
        return None, _Estado.ILEGIVEL
    return limpo, _Estado.OK


def ler(game_id: str) -> Optional[dict[str, int]]:
    """O que está guardado, ou None se o jogo nunca foi varrido (ou não deu para ler)."""
    dados = _ler_estado(game_id)[0]
    return dados[0] if dados else None


def fonte(game_id: str) -> Optional[str]:
    """De onde vêm as conquistas do jogo (``"xbox:123"``), ou None se não há."""
    dados = _ler_estado(game_id)[0]
    return dados[1] if dados else None


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


def _gravar(game_id: str, desbloqueadas: dict[str, int], fonte: Optional[str] = None) -> None:
    destino = caminho(game_id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    conteudo: dict[str, Any] = {"desbloqueadas": desbloqueadas}
    if fonte is not None:
        conteudo["fonte"] = fonte
    temporario.write_text(
        json.dumps(conteudo, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporario.replace(destino)


def registrar(
    game_id: str, novos: Iterable[Desbloqueio], fonte: Optional[str] = None
) -> tuple[list[str], bool]:
    """Funde ``novos`` no que está guardado e grava.

    Com ``fonte``, grava também de onde vêm as conquistas (mesmo que nada novo
    tenha entrado); sem ela, a que já estava guardada fica.

    Devolve ``(as que entraram agora, se era a primeira vez)``.
    """
    with _trava:
        dados, estado = _ler_estado(game_id)
        if estado is _Estado.INDISPONIVEL:
            # Não é a primeira vez nem arquivo ruim: quem chama tenta de novo depois.
            return [], False
        if estado is _Estado.ILEGIVEL and not _guardar_ilegivel(game_id):
            return [], False
        atual, fonte_atual = dados if dados else (None, None)
        primeira = atual is None
        fonte_final = fonte if fonte is not None else fonte_atual
        resultado, entraram = fundir(atual or {}, novos)
        if primeira or resultado != atual or fonte_final != fonte_atual:
            try:
                _gravar(game_id, resultado, fonte_final)
            except OSError as erro:
                logging.warning("Conquistas de %s não gravadas: %s", game_id, erro)
                # O aviso de "conquista nova" não anuncia o que não foi guardado.
                return [], primeira
        return entraram, primeira


def esquecer_fonte(game_id: str) -> None:
    """Tira do arquivo a fonte gravada, sem mexer nas desbloqueadas.

    Não cria arquivo e não levanta: arquivo ausente, ilegível ou indisponível
    fica como está.
    """
    with _trava:
        dados, estado = _ler_estado(game_id)
        if estado is not _Estado.OK or not dados or dados[1] is None:
            return
        try:
            _gravar(game_id, dados[0], None)
        except OSError as erro:
            logging.warning("Fonte das conquistas de %s não esquecida: %s", game_id, erro)


def _por_a_origem_de_lado(game_id: str) -> None:
    """`<id>.json` vira `<id>.json.pendente`, onde o Excluir não alcança."""
    origem = caminho(game_id)
    try:
        origem.replace(origem.with_name(origem.name + ".pendente"))
    except OSError as erro:
        logging.warning("Conquistas de %s não guardadas à parte: %s", game_id, erro)
    else:
        logging.warning("Conquistas de %s guardadas em %s.pendente", game_id, origem.name)


def transferir(de_id: str, para_id: str) -> bool:
    """Funde o que ``de_id`` tem no que ``para_id`` tem (ligação de zerado).

    True: a fusão foi gravada, ou não havia o que transferir. False: não deu
    para gravar. Quem chama exclui a origem logo depois, e o Excluir apaga
    `<id>.json`; por isso, no False, a origem já saiu do caminho (vira
    `<id>.json.pendente`) e o fluxo de quem chama não precisa mudar.
    """
    with _trava:
        dados_da_origem, estado_da_origem = _ler_estado(de_id)
        if estado_da_origem is _Estado.ILEGIVEL:
            # Pô-lo à parte antes do Excluir, para o que não deu para ler
            # não ir embora junto.
            logging.warning("Conquistas de %s ilegíveis: nada a transferir", de_id)
            return _guardar_ilegivel(de_id)
        if estado_da_origem is _Estado.INDISPONIVEL:
            # O conteúdo pode estar bom: sem `.corrompido`, só fica à parte.
            logging.warning("Conquistas de %s indisponíveis: nada a transferir", de_id)
            _por_a_origem_de_lado(de_id)
            return False
        origem, fonte_da_origem = dados_da_origem if dados_da_origem else (None, None)
        if not origem:
            return True
        dados_do_destino, estado_do_destino = _ler_estado(para_id)
        if estado_do_destino is _Estado.INDISPONIVEL:
            _por_a_origem_de_lado(de_id)
            return False
        if estado_do_destino is _Estado.ILEGIVEL and not _guardar_ilegivel(para_id):
            _por_a_origem_de_lado(de_id)
            return False
        destino, fonte_do_destino = dados_do_destino if dados_do_destino else (None, None)
        resultado, _entraram = fundir(
            destino or {}, [Desbloqueio(nome, quando) for nome, quando in origem.items()]
        )
        try:
            _gravar(para_id, resultado, fonte_do_destino or fonte_da_origem)
        except OSError as erro:
            logging.warning("Conquistas de %s não transferidas: %s", de_id, erro)
            _por_a_origem_de_lado(de_id)
            return False
        return True


def mover(de_id: str, para_id: str) -> None:
    """Passa o arquivo de ``de_id`` para ``para_id`` (troca de id do jogo)."""
    with _trava:
        try:
            origem = caminho(de_id)
            if origem.exists():
                origem.replace(caminho(para_id))
        except OSError as erro:
            logging.warning("Conquistas de %s não movidas para %s: %s", de_id, para_id, erro)


def apagar(game_id: str) -> None:
    with _trava:
        try:
            caminho(game_id).unlink(missing_ok=True)
        except OSError as erro:
            logging.warning("Conquistas de %s não apagadas: %s", game_id, erro)
