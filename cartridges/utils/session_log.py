# session_log.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Histórico de sessões de jogo: uma linha por sessão terminada.

``game.playtime`` é um número só, e um número só não responde nada além de
"quanto no total": não dá para saber o que foi jogado esta semana, nem para
apagar uma sessão que contou errado sem editar o total à mão. Este módulo
guarda as sessões que o total soma.

O formato é JSON Lines — um objeto por linha, gravado com ``append``. Foi
escolhido por causa de como as escritas acontecem: uma sessão termina e sua
linha precisa chegar ao disco sem reler nem reescrever o arquivo inteiro, que é
o que um JSON único exigiria a cada partida. Apagar uma sessão reescreve tudo,
mas isso acontece por escolha de alguém olhando a tela, não a cada partida.

Linhas ilegíveis (um arquivo cortado por queda de energia no meio de um append,
um arquivo editado à mão) são puladas em vez de derrubar a leitura: o histórico
é um registro secundário, e perder uma linha dele nunca pode custar a
biblioteca.
"""

import json
import logging
from pathlib import Path
from time import time
from typing import Any, Optional

from cartridges import shared


# Ano 3000. Qualquer `end` além disto é edição manual ou lixo, e aceitar um
# valor que o fromtimestamp do Windows recusa só move o erro para quem exibe.
_MAX_END = 32503680000


def _path() -> Path:
    # Resolvido a cada chamada, não no import: `shared.app_dir` é montado pelo
    # meson e repontado pelos testes, e uma constante de módulo congelaria o
    # valor de quem importasse primeiro.
    return shared.app_dir / "sessions.jsonl"


def record(game_id: str, seconds: int, end: Optional[int] = None) -> None:
    """Anota uma sessão terminada. Sessões de 0 s não são anotadas.

    ``end`` é o instante em que a sessão acabou (padrão: agora). O início é
    derivado dele, e não medido: quem conta o tempo usa o relógio monotônico
    justamente porque o relógio de parede pula, então o único instante de
    parede confiável de uma sessão é o momento em que ela termina.
    """
    if seconds <= 0:
        return

    end = int(time()) if end is None else int(end)
    line = json.dumps(
        {"game_id": game_id, "end": end, "seconds": int(seconds)},
        ensure_ascii=False,
    )
    try:
        shared.app_dir.mkdir(parents=True, exist_ok=True)
        with _path().open("a", encoding="utf-8") as file:
            file.write(line + "\n")
    except OSError:
        # O tempo já foi somado ao jogo e salvo; o histórico é o extra. Falhar
        # aqui não pode desfazer a sessão nem interromper o fechamento dela.
        logging.exception("Não foi possível anotar a sessão de %s", game_id)


def load(game_id: Optional[str] = None) -> list[dict[str, Any]]:
    """As sessões anotadas, da mais recente para a mais antiga.

    Sem ``game_id``, devolve todas. O arquivo é lido inteiro: uma sessão por
    partida jogada é da ordem de alguns milhares de linhas por década, o que é
    menos que uma única capa.
    """
    try:
        # errors="replace": um byte não-UTF-8 (cauda rasgada pós-queda, edição
        # salva em ANSI) custa a linha em que está — o replacement char quebra o
        # json.loads dela — e não a leitura inteira, que era o que o
        # UnicodeDecodeError fazia por ser ValueError, fora do guard de OSError.
        text = _path().read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    except OSError:
        logging.exception("Não foi possível ler o histórico de sessões")
        return []

    sessions = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
            entry_id = str(entry["game_id"])
            seconds = int(entry["seconds"])
            end = int(entry["end"])
        except (ValueError, TypeError, KeyError):
            logging.debug("Linha ilegível no histórico de sessões, ignorada")
            continue
        # Faixa, além de tipo: um `end` negativo ou além do alcance do
        # datetime.fromtimestamp do Windows derrubaria o diálogo de histórico —
        # e o contrato daqui é que uma linha editada à mão custa a linha.
        if seconds < 0 or end < 0 or end > _MAX_END:
            logging.debug("Sessão fora de faixa no histórico, ignorada")
            continue
        if game_id is not None and entry_id != game_id:
            continue
        sessions.append({"game_id": entry_id, "end": end, "seconds": seconds})

    sessions.sort(key=lambda entry: entry["end"], reverse=True)
    return sessions


def delete(game_id: str, end: int, seconds: int) -> bool:
    """Apaga uma sessão. Devolve se alguma linha saiu de fato.

    A sessão é identificada pelos três campos juntos, e só a primeira ocorrência
    é removida: duas sessões idênticas do mesmo jogo no mesmo segundo são
    registros distintos, e apagar uma não pode levar a outra junto.
    """
    path = _path()
    try:
        # surrogateescape, e não o "replace" do `load`: o arquivo volta ao disco
        # inteiro, e um byte não-UTF-8 numa linha alheia tem que voltar igual.
        # Sem isto, o UnicodeDecodeError (ValueError) escapava do guard abaixo.
        lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
    except (FileNotFoundError, OSError):
        return False

    kept: list[str] = []
    removed = False
    for line in lines:
        if not removed and line.strip():
            try:
                entry = json.loads(line)
                if (
                    str(entry.get("game_id")) == game_id
                    and int(entry.get("end", 0)) == int(end)
                    and int(entry.get("seconds", 0)) == int(seconds)
                ):
                    removed = True
                    continue
            except (ValueError, TypeError):
                pass
        kept.append(line)

    if not removed:
        return False

    # Mesmo cuidado do FileManager: grava num temporário e substitui, para que
    # uma queda no meio não deixe um histórico truncado no lugar do inteiro.
    tmp = path.with_suffix(".jsonl.tmp")
    try:
        tmp.write_text(
            "".join(line + "\n" for line in kept if line.strip()),
            encoding="utf-8",
            errors="surrogateescape",
        )
        tmp.replace(path)
    except OSError:
        logging.exception("Não foi possível reescrever o histórico de sessões")
        tmp.unlink(missing_ok=True)
        return False
    return True


def seconds_since(sessions: list[dict[str, Any]], days: int) -> int:
    """Quanto tempo somam as sessões dos últimos ``days`` dias.

    Recebe a lista já carregada em vez de reler o arquivo, para que a tela do
    histórico calcule seus dois resumos a partir da mesma leitura que desenha
    as linhas.
    """
    cutoff = int(time()) - days * 86400
    return sum(entry["seconds"] for entry in sessions if entry["end"] >= cutoff)
