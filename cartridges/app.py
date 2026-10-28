# app.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app Qt: `python -m cartridges`."""

import builtins
import logging
import sys
from pathlib import Path
from typing import Any, Callable

# A interface é hardcoded em pt-BR (como em `cartridges.in`). Antes de importar
# `cartridges.jogo`, cujos STATUS_LABELS chamam `_()` na importação.
builtins._ = lambda message: message  # type: ignore[attr-defined]
builtins.ngettext = lambda singular, plural, n: singular if n == 1 else plural  # type: ignore[attr-defined]

# pylint: disable=wrong-import-position
from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine

from cartridges import shared
from cartridges.carga import carregar_jogos_do_disco
from cartridges.jogo import Jogo
from cartridges.logging.session_file_handler import SessionFileHandler
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.store.managers import async_manager
from cartridges.store.managers.exibicao_manager import ExibicaoManager
from cartridges.store.managers.file_manager import FileManager
from cartridges.store.store import Store
from cartridges.utils.thread_principal import na_thread_principal

_RAIZ = Path(__file__).resolve().parent
_ICONE = _RAIZ.parent / "data" / "icons" / "hicolor" / "scalable" / "apps" / f"{shared.APP_ID}.svg"


class Ponte(QObject):
    """Leva os sinais dos jogos ao QML. Os textos seguem como texto puro (o QML os mostra em PlainText)."""

    avisoRecebido = Signal(str)
    confirmacaoPedida = Signal(str, str)
    sairDaFrente = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._pendente: Callable[[], Any] | None = None

    def ligar(self, jogo: Jogo) -> None:
        jogo.aviso.connect(lambda texto, _acao: self.avisoRecebido.emit(texto))
        jogo.sair_da_frente.connect(self.sairDaFrente)
        jogo.confirmar_comando.connect(lambda lancar, j=jogo: self._pedir(j, lancar))

    def _pedir(self, jogo: Jogo, lancar: Callable[[], Any]) -> None:
        self._pendente = lancar
        corpo = (
            "Este jogo foi restaurado de um backup. Antes de iniciá-lo pela primeira vez, "
            f"confira se o comando abaixo é o esperado:\n\n{jogo.comando_visivel}"
        )
        if jogo.run_as_admin:
            corpo += "\n\nO jogo será executado como administrador."
        self.confirmacaoPedida.emit(f"Iniciar {jogo.name}?", corpo)

    @Slot()
    def confirmar(self) -> None:
        lancar, self._pendente = self._pendente, None
        if lancar is not None:
            lancar()

    @Slot()
    def cancelar(self) -> None:
        self._pendente = None


def _configurar_log() -> None:
    # O `setup_logging` da versão GTK ainda importa o `gi`; este é o mínimo até ele ser portado.
    try:
        arquivo = SessionFileHandler(shared.log_dir / "cartridges.log")
    except (OSError, ValueError):
        logging.basicConfig(level=logging.DEBUG)
        logging.exception("Não foi possível configurar o log em arquivo")
        return
    arquivo.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    logging.basicConfig(level=logging.NOTSET, handlers=[arquivo, console])


def _medidas_da_tela(app: QGuiApplication) -> None:
    escala = max((tela.devicePixelRatio() for tela in app.screens()), default=1.0)
    shared.scale_factor = escala
    shared.display_size = (round(200 * escala), round(300 * escala))
    shared.details_size = (round(420 * escala), round(630 * escala))


def main(argv: list[str]) -> int:
    app = QGuiApplication(argv)
    app.setApplicationName("Cartridges")
    app.setApplicationDisplayName("Cartridges")
    app.setWindowIcon(QIcon(str(_ICONE)))
    # A ponte para a thread principal nasce aqui, antes de qualquer thread de trabalho.
    na_thread_principal(lambda: None)
    app.aboutToQuit.connect(async_manager.encerrar)
    _configurar_log()
    _medidas_da_tela(app)

    modelo = ModeloDaBiblioteca()
    shared.store = Store()
    shared.store.add_manager(FileManager(), False)
    shared.store.add_manager(ExibicaoManager(modelo))
    shared.store.toggle_manager_in_pipelines(FileManager, True)
    carregados = carregar_jogos_do_disco(shared.store)

    if "--sair-apos-carregar" in argv:
        if sys.stdout is not None:
            print(f"jogos carregados: {carregados}", flush=True)
        return 0

    ponte = Ponte()
    # shortcut: só os jogos da carga inicial ficam ligados; os da importação entram quando ela for portada
    for jogo in shared.store.games_by_id.values():
        ponte.ligar(jogo)

    from cartridges.janela import qwk  # noqa: PLC0415

    motor = QQmlApplicationEngine()
    qwk.registrar(motor)
    motor.rootContext().setContextProperty("biblioteca", modelo)
    motor.rootContext().setContextProperty("ponte", ponte)
    motor.load(QUrl.fromLocalFile(str(_RAIZ / "qml" / "Aplicativo.qml")))
    if not motor.rootObjects():
        return 1
    return app.exec()
