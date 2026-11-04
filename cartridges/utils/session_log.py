# session_log.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Histórico de sessões de jogo: uma linha por sessão terminada.

Guarda as sessões que ``game.playtime`` soma, para saber o que foi jogado esta semana e apagar uma sessão errada.

JSON Lines com ``append``: a linha de uma sessão chega ao disco sem reescrever o arquivo (só apagar reescreve).
Linhas ilegíveis (corte por queda de energia, edição à mão) são puladas: perder uma linha nunca pode custar a biblioteca.
"""

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from time import time
from typing import Any, Optional

from cartridges import shared


# Ano 3000: um `end` além disso é lixo, e o fromtimestamp do Windows o recusaria na tela.
_MAX_END = 32503680000

# `record` e as reescritas (`delete`, `apagar_jogo`, `mover_jogo`) rodam em threads diferentes sobre o mesmo arquivo:
# sem a trava, um `record` entre o `read_text` e o `replace` se perde e duas reescritas disputam o `.jsonl.tmp`.
_LOCK = threading.Lock()


def _path() -> Path:
    # A cada chamada, não no import: `shared.app_dir` é montado em execução e repontado pelos testes.
    return shared.app_dir / "sessions.jsonl"


def record(game_id: str, seconds: int, end: Optional[int] = None) -> None:
    """Anota uma sessão terminada (0 s não é anotada).

    ``end`` é o instante em que acabou (padrão: agora); o início é derivado dele, pois o tempo é contado
    com o relógio monotônico e o de parede pula: só o fim é um instante de parede confiável.
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
        path = _path()
        with _LOCK:
            # Sem quebra de linha final (append cortado, editor), esta sessão colaria na última e o `load` descartaria as duas.
            prefixo = ""
            try:
                with path.open("rb") as existente:
                    existente.seek(0, 2)
                    if existente.tell() > 0:
                        existente.seek(-1, 2)
                        if existente.read(1) != b"\n":
                            prefixo = "\n"
            except FileNotFoundError:
                pass
            with path.open("a", encoding="utf-8") as file:
                file.write(prefixo + line + "\n")
    except OSError:
        # O tempo já foi somado e salvo; falhar aqui não pode desfazer a sessão nem interromper o fechamento.
        logging.exception("Não foi possível anotar a sessão de %s", game_id)


def load(game_id: Optional[str] = None) -> list[dict[str, Any]]:
    """As sessões anotadas, da mais recente para a mais antiga; sem ``game_id``, todas. O arquivo é lido inteiro (poucos milhares de linhas por década)."""
    try:
        # errors="replace": um byte não-UTF-8 custa só a linha dele, não a leitura inteira (UnicodeDecodeError é ValueError, fora do guard de OSError).
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
        # Faixa, além de tipo: `end` fora do alcance do datetime.fromtimestamp do Windows, ou começo antes de
        # 03/01/1970 (OSError 22 em `datetime.timestamp()`), derrubaria a tela de histórico.
        if seconds < 0 or end < 0 or end > _MAX_END or end - seconds < 172800:
            logging.debug("Sessão fora de faixa no histórico, ignorada")
            continue
        if game_id is not None and entry_id != game_id:
            continue
        sessions.append({"game_id": entry_id, "end": end, "seconds": seconds})

    sessions.sort(key=lambda entry: entry["end"], reverse=True)
    return sessions


def _reescrever(path: Path, kept: list[str]) -> bool:
    """Grava ``kept`` por cima do histórico, via temporário + troca (uma queda no meio não deixa um histórico truncado)."""
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


def delete(game_id: str, end: int, seconds: int) -> bool:
    """Apaga uma sessão (identificada pelos três campos; só a primeira ocorrência sai). Devolve se alguma linha saiu."""
    path = _path()
    with _LOCK:
        try:
            # surrogateescape, não o "replace" do `load`: o arquivo volta ao disco, e um byte não-UTF-8 alheio tem de voltar igual.
            lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
        except FileNotFoundError:
            return False
        except OSError:
            logging.exception("Não foi possível ler o histórico de sessões")
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
                except (ValueError, TypeError, AttributeError):
                    pass
            kept.append(line)

        if not removed:
            return False

        return _reescrever(path, kept)


def apagar_jogo(game_id: str) -> None:
    """Apaga todas as sessões de um jogo (chamada por `Store.cleanup_game`): uma reinstalação não herda o histórico do jogo apagado."""
    path = _path()
    with _LOCK:
        try:
            lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
        except FileNotFoundError:
            return
        except OSError:
            logging.exception("Não foi possível ler o histórico de sessões")
            return

        kept: list[str] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                if str(json.loads(line).get("game_id")) == game_id:
                    continue
            except (ValueError, TypeError, AttributeError):
                pass
            kept.append(line)

        if len(kept) != sum(1 for line in lines if line.strip()):
            _reescrever(path, kept)


def mover_jogo(id_antigo: str, id_novo: str) -> None:
    """Passa as sessões de ``id_antigo`` para ``id_novo`` (adoção pela âncora do atalho, ligação de zerado pelo appID)."""
    path = _path()
    with _LOCK:
        try:
            lines = path.read_text(encoding="utf-8", errors="surrogateescape").splitlines()
        except FileNotFoundError:
            return
        except OSError:
            logging.exception("Não foi possível ler o histórico de sessões")
            return

        kept: list[str] = []
        mudou = False
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                if isinstance(entry, dict) and str(entry.get("game_id")) == id_antigo:
                    entry["game_id"] = id_novo
                    line = json.dumps(entry, ensure_ascii=False)
                    mudou = True
            except ValueError:
                pass
            kept.append(line)

        if mudou:
            _reescrever(path, kept)


def daily_seconds(
    sessions: list[dict[str, Any]], first: date, last: date
) -> list[tuple[date, int]]:
    """Quanto se jogou em cada dia de ``first`` a ``last``, inclusive.

    Uma sessão que atravessa a meia-noite é repartida entre os dois dias. As meias-noites são convertidas
    em timestamp, para um dia de horário de verão ter 23 ou 25 horas.
    """
    days = (last - first).days + 1
    if days <= 0:
        return []

    totals = [0] * days

    def midnight(day: date) -> int:
        return int(datetime.combine(day, datetime.min.time()).timestamp())

    range_start = midnight(first)
    range_end = midnight(last + timedelta(days=1))

    for entry in sessions:
        # Recortado à faixa antes de andar dia a dia: uma sessão editada à mão com anos de duração não pode custar um laço de anos.
        start = max(entry["end"] - entry["seconds"], range_start)
        end = min(entry["end"], range_end)
        while start < end:
            day = datetime.fromtimestamp(start).date()
            chunk_end = min(midnight(day + timedelta(days=1)), end)
            totals[(day - first).days] += chunk_end - start
            start = chunk_end

    return [(first + timedelta(days=i), totals[i]) for i in range(days)]
