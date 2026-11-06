# install_size.py
#
# Copyright 2026 joaomgabaldi
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

"""Quanto cada jogo ocupa no disco, medido em segundo plano ("preciso de espaço, o que eu apago?").

A pasta medida é a que o rastreio de processo vigia (:func:`install_dir_from_command`), não a do executável (:func:`game_folder`): um jogo que abre por ``SP\\bf6.exe`` mora na pasta acima. Jogos abertos por URL de loja ficam sem tamanho (só o lançador sabe onde estão).
Uma varredura por execução, sequencial e sem pressa (é o mais pesado que o app faz com o disco): pula o jogo medido há menos de uma semana e espera a importação terminar.
"""

import logging
import os
import threading
from time import time
from typing import Optional

from kyron import shared
from kyron.jogo import Jogo
from kyron.modelos import tarefas
from kyron.utils.format_playtime import format_size  # noqa: F401  (reexportado)
from kyron.utils.game_folder import game_folder
from kyron.utils.passada_agendada import PassadaAgendada
from kyron.utils.process_monitor import install_dir_from_command
from kyron.utils.run_executable import aumid_from_command
from kyron.utils.thread_principal import na_thread_principal

_START_DELAY_SECONDS = 25
_IMPORT_RETRY_SECONDS = 30

# Uma medição vale uma semana: remedir tudo a cada início torraria disco para mudar poucos números.
_REFRESH_AFTER_SECONDS = 7 * 24 * 60 * 60


# Pastas que guardam uma biblioteca inteira: quem tem uma dentro é onde os jogos moram, não um jogo. Subconjunto de
# `_CONTAINER_DIRS` do monitor de processos, de propósito: um nome ambíguo como "common" ou "games" apareceria dentro de algum jogo.
_LIBRARY_DIRS = frozenset({"steamapps", "xboxgames", "windowsapps"})


def install_size_folder(command: str) -> str:
    """A pasta a medir para ``command``, ou "" se não for possível saber: o executável clássico (raiz achada pelo rastreio de processo) ou o jogo empacotado (:func:`game_folder` dá a raiz real).

    Um atalho manual para ``steam.exe -applaunch 440`` nomeia o cliente, cuja pasta contém *toda* a biblioteca Steam: abri-la é defensável, mas dizer que o jogo ocupa 400 GB não. Pasta que contém uma biblioteca inteira é recusada.
    """
    if not (command or "").strip():
        return ""

    if aumid_from_command(command):
        folder = game_folder(command) or ""
    else:
        folder = install_dir_from_command(command)

    return "" if _holds_a_library(folder) else folder


def _holds_a_library(directory: str) -> bool:
    if not directory:
        return False

    try:
        with os.scandir(directory) as entries:
            return any(
                entry.name.casefold() in _LIBRARY_DIRS and entry.is_dir()
                for entry in entries
            )
    except OSError:
        # Ilegível: quem vai medir descobre a mesma coisa e devolve zero.
        return False


def folder_size(directory: str) -> int:
    """Soma o tamanho dos arquivos sob ``directory``, em bytes.

    O que não dá para ler conta zero (pastas do Game Pass negam acesso no meio do caminho). Links e junções não
    são seguidos: seguir contaria duas vezes o que está dos dois lados e arriscaria andar em círculo.
    """
    total = 0
    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        # follow_symlinks=False só filtra symlink; a junção (mklink /J) precisa do is_junction().
                        if entry.is_dir(follow_symlinks=False) and not entry.is_junction():
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


class InstallSizeSweep(PassadaAgendada):
    """Uma varredura em segundo plano pelo tamanho de cada jogo no disco."""

    atraso_inicial = _START_DELAY_SECONDS
    espera_da_importacao = _IMPORT_RETRY_SECONDS

    def run_async(self) -> None:
        if self._stopped:
            return

        # Retrato na thread principal: a importação muda os mapas da store.
        games = [
            game
            for game in shared.store
            if not game.removed and not game.blacklisted and self._is_stale(game)
        ]
        if not games:
            return

        if not self._reservar():
            return

        logging.info("Install size sweep queued for %d games", len(games))
        threading.Thread(
            target=self._worker, args=(games, self._generation), daemon=True
        ).start()

    @staticmethod
    def _is_stale(game: Jogo) -> bool:
        return (int(time()) - (game.install_size_ts or 0)) >= _REFRESH_AFTER_SECONDS

    def _worker(self, games: list[Jogo], generation: int) -> None:
        measured = 0
        tarefa: Optional[tarefas.Tarefa] = None
        try:
            # Sem pasta conhecida não há o que medir nem mostrar nas tarefas (o botão do canto piscaria por nada).
            com_pasta: list[tuple[Jogo, str]] = []
            for game in games:
                if self._deve_parar(generation):
                    return
                # Reconferido por jogo: uma importação pode tê-lo removido.
                if game.removed or not self._is_stale(game):
                    continue
                folder = install_size_folder(game.executable)
                if folder:
                    com_pasta.append((game, folder))
                elif game.install_size:
                    na_thread_principal(self._apply, game, 0)
            if not com_pasta:
                return

            tarefa = tarefas.comecar(_("Tamanho em disco"), len(com_pasta))
            for feitos, (game, folder) in enumerate(com_pasta):
                tarefa.atualizar(feitos)
                if self._deve_parar(generation):
                    break
                if game.removed:
                    continue

                # shortcut: uma pasta por vez; uma biblioteca grande leva minutos na primeira execução (melhor medir só o que a tela mostra do que abrir threads no mesmo disco).
                # Pasta vazia ou ilegível vira tamanho desconhecido (zero): um número antigo ficaria no topo do "o que apagar".
                size = folder_size(folder)
                if not size:
                    if game.install_size:
                        na_thread_principal(self._apply, game, 0)
                    continue

                measured += 1
                na_thread_principal(self._apply, game, size)
        finally:
            if tarefa is not None:
                tarefa.terminar()
            self._liberar()
            logging.info(
                "Install size sweep done: %d of %d games measured",
                measured,
                len(games),
            )

    def _apply(self, game: Jogo, size: int) -> None:
        if self._stopped or game.removed:
            return
        # Identidade na store: um reset apaga a biblioteca enquanto o worker anda, e o `save()` ressuscitaria o jogo apagado.
        store = getattr(shared, "store", None)
        if store is None or store.get(game.game_id) is not game:
            return

        game.install_size = size
        # Sem carimbo quando o tamanho some: a próxima varredura mede de novo (disco externo que volta).
        if size:
            game.install_size_ts = int(time())
        game.save()
        game.update()
