# exibicao_manager.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

import threading
from typing import Any, Callable

from cartridges.jogo import Jogo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.store.managers.manager import Manager
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils.thread_principal import na_thread_principal


class ExibicaoManager(Manager):
    """Leva o jogo à grade: o modelo só muda na thread principal, de onde o manager rodar."""

    run_after = (SteamAPIManager, SgdbManager)
    signals = {"atualizado", "salvar"}

    def __init__(self, modelo: ModeloDaBiblioteca, ao_ver: Callable[[Jogo], None] | None = None) -> None:
        super().__init__()
        self.modelo = modelo
        self.ao_ver = ao_ver

    def process_game(self, game: Jogo, additional_data: dict, callback: Callable[[Manager], Any]) -> None:
        """Roda a exibição na thread principal e só então deixa o pipeline avançar: o fim da importação não pode passar à frente do último jogo entrar na grade."""
        if threading.current_thread() is threading.main_thread():
            super().process_game(game, additional_data, callback)
            return
        na_thread_principal(super().process_game, game, additional_data, callback)

    def main(self, game: Jogo, _additional_data: dict) -> None:
        # Já na principal (o pipeline subiu até lá em `process_game`): na hora. De fora (`save`), pela ponte.
        if threading.current_thread() is threading.main_thread():
            self._ver(game)
        else:
            na_thread_principal(self._ver, game)

    def _ver(self, jogo: Jogo) -> None:
        if self.ao_ver is not None:
            self.ao_ver(jogo)
        self.modelo.atualizar(jogo)
