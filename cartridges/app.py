# app.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app Qt: `python -m cartridges`."""

import builtins
import logging
import sys
from pathlib import Path

# A interface é hardcoded em pt-BR (como em `cartridges.in`). Antes de importar
# `cartridges.jogo`, cujos STATUS_LABELS chamam `_()` na importação.
builtins._ = lambda message: message  # type: ignore[attr-defined]
builtins.ngettext = lambda singular, plural, n: singular if n == 1 else plural  # type: ignore[attr-defined]

# pylint: disable=wrong-import-position
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.carga import carregar_jogos_do_disco
from cartridges.logging.session_file_handler import SessionFileHandler
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.ponte import Ponte
from cartridges.store.managers import async_manager
from cartridges.store.managers.exibicao_manager import ExibicaoManager
from cartridges.store.managers.file_manager import FileManager
from cartridges.store.store import Store

_RAIZ = Path(__file__).resolve().parent
_ICONE = _RAIZ.parent / "data" / "icons" / "hicolor" / "scalable" / "apps" / f"{shared.APP_ID}.svg"


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
    # A ponte para a thread principal nasce quando `thread_principal` é importado, aqui na principal.
    app.aboutToQuit.connect(async_manager.encerrar)
    _configurar_log()
    _medidas_da_tela(app)

    modelo = ModeloDaBiblioteca()
    filtros = FiltrosDaBiblioteca(modelo)
    pagina_biblioteca = FiltroDaPagina(modelo, filtros, "biblioteca")
    pagina_zerados = FiltroDaPagina(modelo, filtros, "zerados")
    shared.store = Store()
    shared.store.add_manager(FileManager(), False)
    avisos = FilaDeAvisos()
    ponte = Ponte(avisos)
    ponte.ligar_store(shared.store)
    shared.store.add_manager(ExibicaoManager(modelo, ao_ver=ponte.ligar))
    modelo.ligar_store(shared.store)
    shared.store.toggle_manager_in_pipelines(FileManager, True)
    carregados = carregar_jogos_do_disco(shared.store)

    if "--sair-apos-carregar" in argv:
        if sys.stdout is not None:
            print(f"jogos carregados: {carregados}", flush=True)
        return 0

    from cartridges.janela import qwk  # noqa: PLC0415

    # Controls no estilo Basic, redesenhado pelo Tema.qml (D38); antes de criar o motor.
    QQuickStyle.setStyle("Basic")
    motor = QQmlApplicationEngine()
    qwk.registrar(motor)
    aplicativo = Aplicativo(avisos)
    contexto = motor.rootContext()
    for nome, valor in (
        ("filtros", filtros), ("paginaTodos", pagina_biblioteca), ("paginaZerados", pagina_zerados),
        ("aplicativo", aplicativo), ("ponte", ponte),
    ):  # fmt: skip
        contexto.setContextProperty(nome, valor)
    motor.load(QUrl.fromLocalFile(str(_RAIZ / "qml" / "Aplicativo.qml")))
    if not motor.rootObjects():
        return 1
    return app.exec()
