# metadata_refresh.py
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

"""Atualiza os metadados dos jogos já na biblioteca.

Não pertence à tela de Preferências: atualizar a biblioteca inteira leva minutos e a tela pode ser fechada. A execução
vive aqui, durante o processo, e a tela só a mostra (``AtualizacoesDaBiblioteca``): lê os contadores ao abrir e
acompanha o sinal ``progress``.
"""

import logging
from threading import Thread
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

from cartridges import shared
from cartridges.errors.friendly_error import FriendlyError
from cartridges.jogo import Jogo
from cartridges.store.managers.hltb_manager import HLTBManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.modelos import tarefas
from cartridges.utils.steam import STEAM_METADATA_VERSION
from cartridges.utils.thread_principal import na_thread_principal


class MetadataRefresh(QObject):
    """A atualização de metadados da biblioteca inteira, em curso ou parada."""

    # Emitido quando um jogo termina, e quando a atualização começa ou termina.
    progress = Signal()

    running: bool = False
    cancelled: bool = False
    done: int = 0
    total: int = 0

    def __init__(self) -> None:
        super().__init__()
        self._queue: list[Jogo] = []
        self._managers: list[Any] = []
        self._only_missing: bool = False
        self._tarefa: Optional[tarefas.Tarefa] = None

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0

    @staticmethod
    def needs_steam(game: Jogo) -> bool:
        """A busca na Steam ainda tem algo a dar a este jogo?

        Julgado por dois critérios. Os campos sempre produzidos (desenvolvedora, data de lançamento, gênero) vêm em
        toda busca bem-sucedida: faltar um deles é que o jogo nunca teve. Os demais não servem assim: gamepad e
        suporte a controle vazios são respostas, não lacunas, e tratá-los como trabalho recolocaria a biblioteca
        inteira na fila a cada execução.

        `steam_checked` cobre o que o vazio não diz: um jogo buscado antes de um campo existir tem uma versão antiga e
        volta uma única vez.
        """
        if not game.steam_appid:
            return True
        # Convertido, não comparado direto: o valor vem do JSON do jogo, e um registro editado à mão pode ter `null` ou
        # texto ali; `None < 2` levantaria TypeError numa compreensão sobre a biblioteca inteira na thread principal. O
        # que não é número lê-se como "nunca verificado".
        try:
            checked = int(game.steam_checked)
        except (TypeError, ValueError):
            return True
        if checked < STEAM_METADATA_VERSION:
            return True
        return not (game.developer and game.release_date and game.genre)

    @staticmethod
    def needs_hltb(game: Jogo) -> bool:
        """O HowLongToBeat ainda tem algo a dar a este jogo? A mesma regra do manager, para nunca enfileirar um jogo
        que a busca recusaria.
        """
        return not game.has_hltb_times

    @classmethod
    def is_incomplete(cls, game: Jogo) -> bool:
        """Whether any source still has something for this game."""
        return cls.needs_steam(game) or cls.needs_hltb(game)

    @staticmethod
    def library() -> list[Jogo]:
        """The games a refresh would consider: everything the user can see."""
        return [game for game in shared.store if not (game.removed or game.blacklisted)]

    @staticmethod
    def _in_library(game: Jogo) -> bool:
        """A store ainda guarda este exato jogo sob o id? Identidade, não só o id: um jogo removido e reimportado
        durante a fila é outro registro, e gravar este desfaria a importação.
        """
        store = getattr(shared, "store", None)
        if store is None:
            return False
        return store.get(game.game_id) is game

    def start(self, games: list[Jogo], only_missing: bool = False) -> bool:
        """Começa a atualizar ``games``; devolve False se não há nada a fazer.

        Com ``only_missing`` cada jogo é perguntado sobre quais fontes ainda lhe devem algo, e só essas rodam.
        """
        if self.running or not games:
            return False

        self._managers = [
            shared.store.managers[SteamAPIManager],
            shared.store.managers[HLTBManager],
        ]
        for manager in self._managers:
            manager.reset_cancellable()

        self._only_missing = only_missing
        self._queue = list(games)
        self.running = True
        self.cancelled = False
        self.done = 0
        self.total = len(games)
        self.progress.emit()
        self._tarefa = tarefas.comecar(_("Metadados"), self.total)

        # As tags de todos os jogos em uma ou duas requisições, fora da thread principal (é rede) e antes de tudo, pois
        # as buscas por jogo as consomem.
        def prefetch() -> None:
            tags: dict[str, list[int]] = {}
            try:
                # Só dos jogos cuja busca na Steam vai rodar.
                wanted = [
                    game
                    for game in games
                    if not self._only_missing or self.needs_steam(game)
                ]
                # `str`: `steam_appid` vem do JSON do jogo, onde um registro editado à mão pode ter o número sem aspas,
                # e o manager busca as tags por `str(appid)`.
                appids = [str(game.steam_appid) for game in wanted if game.steam_appid]
                helper = shared.store.managers[SteamAPIManager].steam_api_helper
                if appids:
                    tags = helper.get_store_tags_bulk(
                        appids, should_stop=lambda: self.cancelled
                    )
            except Exception:  # pylint: disable=broad-exception-caught
                # Nada pode escapar desta thread: ela é a única que agenda `_run_queue`, e uma exceção deixaria
                # `running` True sem fila, sem o botão voltar nem nova atualização possível. Um mapa vazio é o estado
                # conservador de uma requisição em massa que falhou.
                logging.exception("Metadata refresh: could not prefetch Steam tags")
            na_thread_principal(self._run_queue, tags)

        Thread(target=prefetch, daemon=True).start()
        return True

    def cancel(self) -> None:
        """Para depois do jogo em andamento: só a fila para, e a busca em curso termina para o registro ficar
        consistente.
        """
        if self.running:
            self.cancelled = True

    def managers_for(self, game: Jogo) -> list[Any]:
        """As fontes a rodar para ``game`` nesta execução.

        A ordem é mantida: o HowLongToBeat vem depois porque a busca na Steam corrige o título que ele pesquisa. A
        granularidade é por fonte, não por campo: uma requisição appdetails responde tudo junto.
        """
        if not self._only_missing:
            return list(self._managers)
        wanted = (self.needs_steam(game), self.needs_hltb(game))
        return [manager for manager, needed in zip(self._managers, wanted) if needed]

    def _run_queue(self, tags: dict[str, list[int]]) -> None:
        """Percorre a fila, um jogo e um manager por vez.

        Sequencial de propósito: o limitador da Steam espaça as requisições em 1,5 s de qualquer jeito, então
        paralelizar não ganharia nada e tornaria o progresso sem sentido e o cancelamento impossível.
        """
        # "Buscar tudo" tem de valer para tudo, inclusive os tempos do HowLongToBeat que o manager recusa buscar duas
        # vezes: uma opção que busca tudo menos uma coisa ninguém lembra como funciona.
        additional_data = {
            "steam_tags": tags,
            "refresh_hltb": not self._only_missing,
            # Lido pelo SteamAPIManager: no modo só-o-que-falta os campos editáveis à mão só preenchem o que está vazio,
            # sem reverter edições do usuário. A fila escolhe os jogos, isto escolhe os campos.
            "only_missing": self._only_missing,
        }

        def next_game() -> None:
            if self.cancelled or not self._queue:
                self._finish()
                return
            game = self._queue.pop(0)
            managers = self.managers_for(game)

            def next_manager(index: int) -> None:
                if index >= len(managers):
                    # Só se o jogo ainda é o que a biblioteca guarda sob esse id: uma redefinição apaga a store e os
                    # arquivos enquanto a fila percorre a própria lista, e `save()` gravaria de volta os jogos que o
                    # usuário acabou de excluir. `cancel()` não cobre: deixa o jogo em andamento terminar.
                    # `additional_data` é um só para toda a fila, então a marca de appID mudado precisa sair daqui mesmo
                    # sem nada a ligar, senão o próximo jogo a herdaria.
                    precisa_ligar = additional_data.pop("ligar_zerado", False)
                    if self._in_library(game):
                        game.save()
                        game.update()
                        if precisa_ligar:
                            # Sem o SGDB nesta fila, a corrida de capa que a ligação evita no import não existe: pode
                            # ligar assim que este jogo termina.
                            from cartridges.utils import ligacao_zerado  # noqa: PLC0415

                            ligacao_zerado.agendar(game)
                    self.done += 1
                    if self._tarefa is not None:
                        self._tarefa.atualizar(self.done)
                    self.progress.emit()
                    next_game()
                    return
                managers[index].process_game(
                    game, additional_data, lambda _manager: next_manager(index + 1)
                )

            next_manager(0)

        next_game()

    def _finish(self) -> None:
        # Só o log fica: não perder o rastro de uma falha silenciosa num refresh longo.
        for manager in self._managers:
            for error in manager.collect_errors():
                if isinstance(error, FriendlyError):
                    logging.warning("Metadata refresh: %s", error.title)

        done, total, cancelled = self.done, self.total, self.cancelled
        if self._tarefa is not None:
            self._tarefa.terminar()
            self._tarefa = None
        self.running = False
        self._queue = []
        self._managers = []
        self.progress.emit()
        self._announce(done, total, cancelled)

    @staticmethod
    def _announce(done: int, total: int, cancelled: bool) -> None:
        """Avisa como foi, na janela principal e não no diálogo: ao fim de uma execução longa as Preferências costumam
        estar fechadas.
        """
        if cancelled:
            # As variáveis são quantos jogos foram atualizados e quantos havia
            message = _("Atualização cancelada após {} de {} jogos").format(done, total)
        else:
            # A variável é quantos jogos foram atualizados
            message = ngettext(
                "Metadados atualizados: {} jogo", "Metadados atualizados: {} jogos", done
            ).format(done)
        aplicativo = getattr(shared, "aplicativo", None)
        if aplicativo is not None:
            aplicativo.avisos.adicionar(message)


_refresh: Optional[MetadataRefresh] = None  # pylint: disable=invalid-name


def get_metadata_refresh() -> MetadataRefresh:
    """Devolve a atualização compartilhada. Uma por processo: uma segunda instância seria uma segunda fila disputando
    os mesmos jogos e o mesmo limite de requisições.
    """
    global _refresh  # pylint: disable=global-statement
    if _refresh is None:
        _refresh = MetadataRefresh()
    return _refresh
