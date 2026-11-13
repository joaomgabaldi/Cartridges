# miniaturas.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Miniaturas das capas no tamanho da grade.

A capa é um TIFF grande; a grade só a desenha em ``shared.display_size``. A miniatura (PNG sem compressão, um por jogo e
por tamanho) abre bem mais rápido. É só uma otimização: sem ela, ou com ela velha ou ilegível, a grade usa a capa.
"""

import logging
import queue
import threading
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, QUrl
from PySide6.QtGui import QImageReader

from kyron import shared
from kyron.utils.gravar_atomico import gravar_atomico


def _tamanho() -> tuple[int, int]:
    return int(shared.display_size[0]), int(shared.display_size[1])


def caminho_para(game_id: str) -> Path:
    largura, altura = _tamanho()
    return shared.miniaturas_dir / f"{game_id}-{largura}x{altura}.png"


def url(game_id: str, capa: Path | None) -> str:
    """URL ``file:`` da miniatura, ou "" se não há capa, miniatura ou ela é mais velha que a capa. O ``?v=`` a recarrega ao ser refeita."""
    # A capa provisória da sessão (fora de `covers_dir`) não tem miniatura: ela não sobrevive à sessão.
    if capa is None or capa.parent != shared.covers_dir:
        return ""
    miniatura = caminho_para(game_id)
    try:
        versao = miniatura.stat().st_mtime_ns
        if versao < capa.stat().st_mtime_ns:
            return ""
    except OSError:
        return ""
    return f"{QUrl.fromLocalFile(str(miniatura)).toString()}?v={versao}"


def gerar(capa: Path, destino: Path) -> bool:
    """Grava em ``destino`` a capa reduzida ao tamanho da grade; False se a capa não abre. Pode rodar fora da thread principal."""
    leitor = QImageReader(str(capa))
    leitor.setScaledSize(QSize(*_tamanho()))
    imagem = leitor.read()
    if imagem.isNull():
        return False
    dados = QByteArray()
    saida = QBuffer(dados)
    saida.open(QIODevice.OpenModeFlag.WriteOnly)
    # Qualidade 100 no PNG é sem compressão: decodifica mais rápido, e o arquivo é pequeno de qualquer jeito.
    if not imagem.save(saida, "PNG", 100):
        return False
    gravar_atomico(destino, bytes(dados))
    return True


_fila: "queue.SimpleQueue[tuple[Path, Path, int]]" = queue.SimpleQueue()
_trava = threading.Lock()
_thread: threading.Thread | None = None
# (destino, mtime_ns da capa) na fila ou que falharam (saem ao dar certo): não são tentados de novo enquanto a capa não mudar.
_vistos: set[tuple[Path, int]] = set()


def _trabalhar() -> None:
    while True:
        capa, destino, versao = _fila.get()
        try:
            if gerar(capa, destino):
                with _trava:
                    _vistos.discard((destino, versao))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Não foi possível gerar a miniatura de %s", capa.name, exc_info=True)


def preparar(capas: list[tuple[str, Path]]) -> None:
    """Gera, numa thread de segundo plano e na ordem dada, as miniaturas que faltam ou estão velhas. Não avisa ao terminar."""
    global _thread  # pylint: disable=global-statement
    for game_id, capa in capas:
        if capa.parent != shared.covers_dir:
            continue
        destino = caminho_para(game_id)
        try:
            versao = capa.stat().st_mtime_ns
        except OSError:
            continue
        if url(game_id, capa):
            continue
        with _trava:
            if (destino, versao) in _vistos:
                continue
            _vistos.add((destino, versao))
            if _thread is None:
                _thread = threading.Thread(target=_trabalhar, daemon=True)
                _thread.start()
        _fila.put((capa, destino, versao))


def limpar(ids: set[str]) -> None:
    """Apaga da pasta o que não é de um jogo vivo, o que é de outro tamanho e todo ``.tmp``."""
    largura, altura = _tamanho()
    for arquivo in list(shared.miniaturas_dir.glob("*")):
        try:
            if not arquivo.is_file():
                continue
            if arquivo.suffix == ".png":
                dono, _, tamanho = arquivo.stem.rpartition("-")
                if dono in ids and tamanho == f"{largura}x{altura}":
                    continue
            elif arquivo.suffix != ".tmp":
                continue
            arquivo.unlink()
        except OSError as erro:
            logging.debug("Miniatura %s não apagada: %s", arquivo.name, erro)


def apagar(game_id: str) -> None:
    try:
        caminho_para(game_id).unlink(missing_ok=True)
    except OSError:
        logging.warning("Não foi possível apagar a miniatura de %s", game_id)
