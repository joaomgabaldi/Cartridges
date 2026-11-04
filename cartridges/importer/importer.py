# importer.py
#
# Copyright 2022-2023 kramo
# Copyright 2023 Geoffrey Coulaud
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

import logging
import threading
import weakref
from time import time
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import Qt, QTimer

from cartridges import shared
from cartridges.errors.error_producer import ErrorProducer
from cartridges.errors.friendly_error import FriendlyError
from cartridges.importer.source import Source, SourceScanError
from cartridges.jogo import Jogo
from cartridges.modelos import tarefas
from cartridges.store.managers import async_manager
from cartridges.store.managers.async_manager import AsyncManager
from cartridges.store.pipeline import Pipeline
from cartridges.utils import restauracao
from cartridges.utils.thread_principal import na_thread_principal

if TYPE_CHECKING:
    from cartridges.aplicativo import Aplicativo


# pylint: disable=too-many-instance-attributes
class Importer(ErrorProducer):

    # O id do aviso do resumo na fila (`FilaDeAvisos`); o da importação anterior
    # sai da tela quando a próxima começa.
    summary_toast: Optional[int] = None

    sources: set[Source]

    n_source_tasks_created: int = 0
    n_source_tasks_done: int = 0
    n_pipelines_done: int = 0
    game_pipelines: set[Pipeline]

    removed_game_ids: set[str]
    imported_game_ids: set[str]
    scanned_source_ids: set[str]

    def __init__(self, aplicativo: Optional["Aplicativo"] = None) -> None:
        super().__init__()
        # Dono do estado "importando", da fila de avisos e do diálogo de erros.
        self.aplicativo = aplicativo
        self._relogio: Optional[QTimer] = None

        shared.import_time = int(time())

        shared.store.new_game_ids = set()
        shared.store.duplicate_game_ids = set()

        self.removed_game_ids = set()
        self.imported_game_ids = set()
        self.scanned_source_ids = set()
        # Chamado no fim de `finish_import`, na thread principal. A
        # restauração de backup o usa para abrir a janela dos jogos sem
        # atalho só depois de a importação da abertura terminar.
        self.ao_terminar: Optional[Callable[[], None]] = None
        # A importação que o app dispara sozinho não avisa quando não acha
        # nada; ver `on_import_action`.
        self.silenciosa = False
        # A tarefa na janela de tarefas nasce com o primeiro jogo novo e
        # termina com a importação; ver `monitor_import`.
        self.tarefa: Optional[tarefas.Tarefa] = None
        # O último (feitos, total) entregue à tarefa: o monitor roda a cada
        # 100 ms e só entrega quando o par muda.
        self._progresso: Optional[tuple[int, int]] = None

        self.game_pipelines = set()
        self.sources = set()

        # game_pipelines recebe pelas threads das fontes e é lido pela principal: o lock evita "Set changed size during iteration".
        self._pipelines_lock = threading.Lock()
        # Pipelines já contados: o sinal "advanced" vem de várias threads, e sem esta deduplicação duas emissões contariam em dobro (ou perderiam um `+= 1`) e a importação nunca terminaria.
        self._counted_done_pipelines: set[Pipeline] = set()

    @property
    def finished(self) -> bool:
        with self._pipelines_lock:
            n_pipelines = len(self.game_pipelines)
            n_pipelines_done = self.n_pipelines_done
        return (
            self.n_source_tasks_created == self.n_source_tasks_done
            and n_pipelines == n_pipelines_done
        )

    def add_source(self, source: Source) -> None:
        self.sources.add(source)

    def run(self) -> None:
        """Roda as fontes no executor de rede; o `monitor_import` acompanha na thread principal."""
        if self.__class__.summary_toast is not None:
            self.aplicativo.avisos.dispensar(self.__class__.summary_toast)
            self.__class__.summary_toast = None

        self.aplicativo.definir_importando(True)

        self.n_pipelines_done = 0
        self.n_source_tasks_done = 0
        with self._pipelines_lock:
            self._counted_done_pipelines.clear()

        self._relogio = QTimer()
        self._relogio.setInterval(100)
        self._relogio.timeout.connect(self._tic)
        self._relogio.start()

        # Uma importação por vez: coleta os erros e reinicia os cancellables dos managers.
        self.collect_errors()
        for manager in shared.store.managers.values():
            manager.collect_errors()
            if isinstance(manager, AsyncManager):
                manager.reset_cancellable()

        for source in self.sources:
            logging.debug("Importing games from source %s", source.source_id)
            self.n_source_tasks_created += 1
            async_manager.rodar_na_rede(self._tarefa_da_fonte, source)

    def _tarefa_da_fonte(self, source: Source) -> None:
        """Na thread de rede; a conclusão sempre volta à principal, senão a importação nunca acaba."""
        try:
            self.source_task_thread_func((source,))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.exception("Erro inesperado na fonte %s", source.source_id)
        finally:
            na_thread_principal(self.source_callback, source)

    def _tic(self) -> None:
        # Um tique que já estava na fila quando o relógio parou não repete o fim.
        if self._relogio is not None and self._relogio.isActive():
            self.monitor_import()

    def monitor_import(self) -> bool:
        """Acompanha a importação: a tarefa na janela de tarefas nasce com o primeiro jogo novo (a verificação que não acha nada nunca aparece) e o fim dispara a limpeza."""
        with self._pipelines_lock:
            total = len(self.game_pipelines)
            feitos = self.n_pipelines_done
        if total and self.tarefa is None:
            self.tarefa = tarefas.comecar(_("Importação"), total)
        if self.tarefa is not None and (feitos, total) != self._progresso:
            self._progresso = (feitos, total)
            self.tarefa.atualizar(feitos, total)

        if not self.finished:
            return True

        # Parado antes de tudo: um erro no fim não pode repetir o `finish_import` a cada tique.
        if self._relogio is not None:
            self._relogio.stop()
        if self.tarefa is not None:
            tarefa, self.tarefa, self._progresso = self.tarefa, None, None
            try:
                tarefa.terminar()
            except Exception:  # noqa: BLE001
                # O `finish_import` roda mesmo assim: senão `importando` ficaria ligado.
                logging.exception("Erro ao terminar a tarefa da importação")
        self.finish_import()
        return False

    def finish_import(self) -> None:
        logging.info("Import done")
        # Antes de `remove_games` e do reset abaixo: as duas leem
        # `duplicate_game_ids`.
        try:
            self.resolver_pendencias()
            self.remove_games()
        except Exception:  # noqa: BLE001
            logging.exception("Erro ao encerrar a importação")
        # Fora do `try`: com erro acima, os jogos novos ainda chegam à varredura.
        self.imported_game_ids = shared.store.new_game_ids
        shared.store.new_game_ids = set()
        shared.store.duplicate_game_ids = set()
        try:
            self.__class__.summary_toast = self.create_summary_toast()
            self.create_error_dialog()
        except Exception:  # noqa: BLE001
            # Com erro ou sem, a importação acaba: `importando` desliga e o resto roda.
            logging.exception("Erro ao encerrar a importação")
        self.aplicativo.definir_importando(False)
        self.varrer_conquistas_dos_importados()
        if self.ao_terminar is not None:
            self.ao_terminar()

    def varrer_conquistas_dos_importados(self) -> None:
        """Dá catálogo e histórico aos jogos recém-importados, em silêncio.

        O vigia da sessão só usa o catálogo já guardado: sem isto, um jogo importado com o app aberto ficaria sem o cartão de conquistas até a próxima abertura. Nunca levanta.
        """
        try:
            varredura = getattr(self.aplicativo, "varredura_conquistas", None)
            if varredura is None:
                return
            jogos = [
                game
                for game_id in self.imported_game_ids
                if (game := shared.store.get(game_id)) is not None
            ]
            if jogos:
                varredura.varrer_jogos(jogos)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning(
                "Falha ao ler as conquistas dos jogos importados", exc_info=True
            )

    def resolver_pendencias(self) -> None:
        """Tira das pendências da restauração os jogos que esta importação achou, só depois de varrer a pasta de atalhos até o fim."""
        if "shortcuts" in self.scanned_source_ids and restauracao.existe():
            antes = restauracao.ids()
            restauracao.resolver(shared.store.duplicate_game_ids)
            # O modelo só avalia "pendente" em `atualizar`: quem saiu da lista volta à grade.
            for game_id in antes - restauracao.ids():
                if (jogo := shared.store.get(game_id)) is not None:
                    jogo.update()

    def remove_games(self) -> None:
        if not shared.schema.get_boolean("remove-missing"):
            return

        keys = shared.schema.list_keys()

        for game in shared.store:
            if game.removed:
                continue
            if game.source == "imported":
                continue
            # Um jogo restaurado cujo atalho ainda não foi achado espera na
            # janela de pendências, não vira desinstalado.
            if restauracao.e_pendente(game.game_id):
                continue
            # Só remove jogos de fonte realmente varrida: uma pasta ausente (disco desconectado) não pode virar "tudo foi desinstalado".
            if game.base_source not in self.scanned_source_ids:
                continue
            if (game.base_source in keys) and (
                not shared.schema.get_boolean(game.base_source)
            ):
                continue
            if game.game_id in shared.store.duplicate_game_ids:
                continue
            if game.game_id in shared.store.new_game_ids:
                continue

            logging.debug("Removing missing game %s (%s)", game.name, game.game_id)

            game.removed = True
            game.save()
            game.update()
            self.removed_game_ids.add(game.game_id)

    """Import Actions — Threaded; None of this should touch GUI"""

    def source_task_thread_func(self, data: tuple) -> None:
        source: Source
        source, *_rest = data

        if not source.is_available:
            logging.info("Source %s skipped, not available", source.source_id)
            return
        iterator = iter(source)

        logging.info("Scanning source %s", source.source_id)
        # Se a varredura foi até o fim: só assim `remove_games` pode agir sobre os jogos desta fonte, pois uma varredura incompleta não distingue jogo ausente de não visto.
        scan_complete = False
        scan_failed = False
        while True:
            try:
                iteration_result = next(iterator)
            except StopIteration:
                scan_complete = True
                break
            except SourceScanError as error:
                # A fonte avisou que a varredura falhou: reportado como erro, não só logado, porque metade de uma biblioteca em silêncio é pior.
                logging.warning("Scan of %s incomplete: %s", source.source_id, error)
                self.report_error(error)
                break
            except Exception as error:  # pylint: disable=broad-exception-caught
                # Um gerador que levantou está fechado: o próximo `next()` dá StopIteration, igual a um fim limpo, por isso a varredura incompleta precisa de flag própria.
                logging.exception("%s in %s", type(error).__name__, source.source_id)
                self.report_error(error)
                scan_failed = True
                continue

            if isinstance(iteration_result, Jogo):
                game = iteration_result
                additional_data = {}
            elif isinstance(iteration_result, tuple):
                game, additional_data = iteration_result
            elif iteration_result is None:
                continue
            else:
                # Avisa quem implementa fontes: tipo inválido (não deve ocorrer em produção)
                logging.warning(
                    "%s produced an invalid iteration return type %s",
                    source.source_id,
                    type(iteration_result),
                )
                continue

            pipeline: Optional[Pipeline] = shared.store.add_game(
                game, additional_data
            )
            if pipeline is not None:
                logging.info("Imported %s (%s)", game.name, game.game_id)
                with self._pipelines_lock:
                    self.game_pipelines.add(pipeline)
                self._contar_ao_avancar(pipeline)

        if scan_complete and not scan_failed:
            self.scanned_source_ids.add(source.source_id)
        else:
            logging.info(
                "Keeping %s games: the scan did not finish", source.source_id
            )

    def _contar_ao_avancar(self, pipeline: Pipeline) -> None:
        """Conta o fim do pipeline quando ele avançar. Um escopo por pipeline: uma lambda criada
        no laço das fontes enxergaria sempre o último."""
        # Direta, porque o sinal sai de qualquer thread; referências fracas, para a
        # conexão (lado C++) não prender o pipeline nem a importação.
        eu, ref = weakref.ref(self), weakref.ref(pipeline)
        pipeline.advanced.connect(
            lambda: (i := eu()) and (p := ref()) and i.pipeline_advanced_callback(p),
            Qt.ConnectionType.DirectConnection,
        )
        # Um pipeline sem manager assíncrono pode ter terminado dentro do `add_game`.
        self.pipeline_advanced_callback(pipeline)

    def source_callback(self, source: Source) -> None:
        logging.debug("Import done for source %s", source.source_id)
        self.n_source_tasks_done += 1

    def pipeline_advanced_callback(self, pipeline: Pipeline) -> None:
        """Chamado quando o pipeline de um jogo avança; pode rodar em qualquer thread e conta uma vez por pipeline."""
        if pipeline.is_done:
            with self._pipelines_lock:
                if pipeline not in self._counted_done_pipelines:
                    self._counted_done_pipelines.add(pipeline)
                    self.n_pipelines_done += 1

    """GUI Actions"""

    def create_error_dialog(self) -> None:
        errors = []
        errors.extend(self.collect_errors())
        for manager in shared.store.managers.values():
            errors.extend(manager.collect_errors())

        errors = sorted(
            set(
                tuple(
                    (error.title, error.subtitle)
                    for error in (
                        filter(lambda error: isinstance(error, FriendlyError), errors)
                    )
                )
            )
        )

        if not errors:
            self.timeout_toast()
            return

        # O QML mostra tudo em texto puro: o "&" de um caminho chega como está.
        if len(errors) == 1:
            titulo, corpo = errors[0]
            itens = []
        else:
            titulo = _("Aviso")
            corpo = _("Os seguintes erros ocorreram durante a importação:")
            itens = [{"titulo": t, "subtitulo": s} for t, s in errors]
        self.aplicativo.pedir_dialogo(titulo, corpo, itens, self.timeout_toast, preferencias="")

    def undo_import(self, *_args: object) -> None:
        # O jogo pode ter sumido desde a importação (removido à mão): ids ausentes são pulados.
        for game_id in self.imported_game_ids:
            if game := shared.store.get(game_id):
                game.removed = True
                game.update()
                game.save()

        for game_id in self.removed_game_ids:
            if game := shared.store.get(game_id):
                game.removed = False
                game.update()
                game.save()

        self.imported_game_ids = set()
        self.removed_game_ids = set()
        if self.__class__.summary_toast is not None:
            self.aplicativo.avisos.dispensar(self.__class__.summary_toast)
            self.__class__.summary_toast = None

        logging.info("Import undone")

    @staticmethod
    def summarize_names(names: list[str], singular: str, plural: str) -> str:
        if len(names) <= 3:
            return (singular if len(names) == 1 else plural).format(
                ", ".join(sorted(names, key=str.casefold))
            )
        return plural.format(
            ngettext("{} jogo", "{} jogos", len(names)).format(len(names))
        )

    def create_summary_toast(self) -> Optional[int]:
        with self._pipelines_lock:
            pipelines = list(self.game_pipelines)
        added_names = [
            pipeline.game.name
            for pipeline in pipelines
            if not (pipeline.game.blacklisted or pipeline.game.removed)
        ]
        removed_names = [
            game.name
            for game_id in self.removed_game_ids
            if (game := shared.store.get(game_id))
        ]

        parts = []
        if added_names:
            parts.append(
                self.summarize_names(
                    added_names, _("Importado: {}"), _("Importados: {}")
                )
            )
        if removed_names:
            parts.append(
                self.summarize_names(
                    removed_names, _("Removido: {}"), _("Removidos: {}")
                )
            )

        if parts:
            titulo, botao, ao_clicar = " · ".join(parts), _("Desfazer"), self.undo_import
        else:
            titulo, botao, ao_clicar = _("Nenhum jogo novo encontrado"), _("Preferências"), self._abrir_preferencias

        if not parts and self.silenciosa:
            return None
        # segundos=0: quanto o resumo fica é decidido por `timeout_toast`, depois dos diálogos.
        return self.aplicativo.avisos.adicionar(titulo, botao, ao_clicar, segundos=0)

    @staticmethod
    def _abrir_preferencias() -> None:
        if shared.preferencias is not None:
            shared.preferencias.abrir("import")

    def timeout_toast(self, *_args: object) -> None:
        """Dá 5 segundos ao resumo depois que o usuário dispensou os avisos (pela fila: o resumo pode esperar atrás de outro aviso)."""
        if self.__class__.summary_toast is not None:
            self.aplicativo.avisos.dispensar_depois(self.__class__.summary_toast, 5)
