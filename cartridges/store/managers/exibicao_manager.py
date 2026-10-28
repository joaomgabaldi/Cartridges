# exibicao_manager.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

from cartridges.jogo import Jogo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.store.managers.manager import Manager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.utils.thread_principal import na_thread_principal


try:
    from cartridges.store.managers.sgdb_manager import SgdbManager
except ImportError:  # shortcut: o SgdbManager ainda depende do gi; sai quando ele for portado
    SgdbManager = SteamAPIManager


class ExibicaoManager(Manager):
    """Leva o jogo à grade: o modelo só muda na thread principal, de onde o manager rodar."""

    run_after = (SteamAPIManager, SgdbManager)
    signals = {"atualizado", "salvar"}

    def __init__(self, modelo: ModeloDaBiblioteca) -> None:
        super().__init__()
        self.modelo = modelo

    def main(self, game: Jogo, _additional_data: dict) -> None:
        na_thread_principal(self.modelo.atualizar, game)
