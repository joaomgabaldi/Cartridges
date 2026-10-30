# app.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app Qt: `python -m cartridges`."""

import builtins
import logging
import sys
import threading
from pathlib import Path

# A interface é hardcoded em pt-BR (como em `cartridges.in`). Antes de importar
# `cartridges.jogo`, cujos STATUS_LABELS chamam `_()` na importação.
builtins._ = lambda message: message  # type: ignore[attr-defined]
builtins.ngettext = lambda singular, plural, n: singular if n == 1 else plural  # type: ignore[attr-defined]

# pylint: disable=wrong-import-position
from PySide6.QtCore import QEvent, QTimer, QUrl, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.carga import carregar_jogos_do_disco
from cartridges.conquistas import icones
from cartridges.conquistas.ea import conta as ea_conta
from cartridges.conquistas.epic import conta as epic_conta
from cartridges.conquistas.varredura import VarreduraConquistas
from cartridges.conquistas.xbox import conta, login
from cartridges.logging.session_file_handler import SessionFileHandler
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.detalhes import DetalhesDoJogo
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.ponte import Ponte
from cartridges.store.managers import async_manager
from cartridges.store.managers.exibicao_manager import ExibicaoManager
from cartridges.store.managers.file_manager import FileManager
from cartridges.store.managers.hltb_manager import HLTBManager
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.store.store import Store
from cartridges.utils import copias_animadas, restauracao, session_fita, session_wallpaper
from cartridges.utils.hltb_backfill import HLTBBackfill
from cartridges.utils.install_size import InstallSizeSweep
from cartridges.utils.thread_principal import na_thread_principal
from cartridges.utils.updates_checker import UpdatesChecker

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


def _limpar_e_ativar_copias(modelo: ModeloDaBiblioteca) -> None:
    """Limpa a pasta das cópias animadas numa thread e, só depois, libera o modelo a pedir as que faltam.

    A limpeza apaga todo `.tmp` da pasta, então nenhuma geração pode começar antes dela terminar.
    Os ids saem da loja aqui, na principal, antes de a thread começar.
    """
    ids = {jogo.game_id for jogo in shared.store}

    def limpar() -> None:
        copias_animadas.limpar(ids)
        na_thread_principal(modelo.ativar_copias)

    threading.Thread(target=limpar, daemon=True).start()


class AplicacaoQt(QGuiApplication):
    """O `QGuiApplication` do app, que avisa o `quit()` antes de o Qt fechar as janelas.

    No Qt 6 o `quit()` manda o `QEvent.Quit`, e é nele que cada janela de topo recebe o `closing`, antes do
    `aboutToQuit`. O `saindo` chega antes delas: a sessão é encerrada sem interface, e o `closing` da janela
    "Jogando" que vem depois já não tem o que fazer.
    """

    saindo = Signal()

    def event(self, evento: QEvent) -> bool:
        if evento.type() == QEvent.Type.Quit:
            self.saindo.emit()
        return super().event(evento)


def _encerrar_em_ordem(*passos) -> None:  # noqa: ANN002
    """Cada passo do fechamento roda, mesmo com a falha de um anterior: o drenar das gravações vem perto do fim."""
    for passo in passos:
        try:
            passo()
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Falha ao encerrar o app")


def _carregar_contas() -> None:
    """As contas Microsoft, Epic e EA são lidas do disco antes da interface, sem rede (nunca levantam)."""
    conta.carregar()
    epic_conta.carregar()
    ea_conta.carregar()


def _ligar_conquistas(aplicativo: Aplicativo) -> VarreduraConquistas:
    """A varredura de conquistas da abertura, depois das outras (como na `main`): uma passada por execução."""
    aplicativo.varredura_conquistas = VarreduraConquistas()
    aplicativo.varredura_conquistas.start()
    return aplicativo.varredura_conquistas


def _parar_varredura_de_conquistas() -> None:
    if shared.aplicativo is not None and shared.aplicativo.varredura_conquistas is not None:
        shared.aplicativo.varredura_conquistas.stop()


def _fechar(big_picture, sessao, verificador, varredura_hltb, varredura_tamanho, edicao) -> None:  # noqa: ANN001
    """O `aboutToQuit`, na ordem da `main`; o `stop()` de cada um vem antes do `encerrar()`."""
    _encerrar_em_ordem(
        big_picture.encerrar,  # a cortina preta do fade nunca fica no monitor (ADR 0003)
        sessao.devolver,  # a parede e as fitas, com as janelas já fora da tela (grava antes se o `saindo` não veio)
        login.cancelar_pendente,  # um login da conta Microsoft esperando o navegador não sobrevive ao app
        ea_conta.gravar_pendente,  # o `remid` novo da EA que não coube no disco: última tentativa
        verificador.stop,
        varredura_hltb.stop,
        varredura_tamanho.stop,
        _parar_varredura_de_conquistas,
        edicao.cancelar,  # apaga os temporários de um editor ainda aberto
        async_manager.encerrar,  # drena as gravações, a do tempo da sessão inclusive
        copias_animadas.encerrar,
        icones.encerrar,  # os ícones na fila não seguram o processo com a rede travada
    )


def main(argv: list[str]) -> int:
    app = AplicacaoQt(argv)
    app.setApplicationName("Cartridges")
    app.setApplicationDisplayName("Cartridges")
    app.setWindowIcon(QIcon(str(_ICONE)))
    # A ponte para a thread principal nasce quando `thread_principal` é importado, aqui na principal.
    # O `stop()` de cada um vem antes do `encerrar()`: o que ainda entregariam não tem para onde ir.
    verificador = UpdatesChecker()
    varredura_hltb = HLTBBackfill()
    varredura_tamanho = InstallSizeSweep()

    def encerrar() -> None:
        _fechar(big_picture, sessao, verificador, varredura_hltb, varredura_tamanho, edicao)

    app.aboutToQuit.connect(encerrar)
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
    carregados = carregar_jogos_do_disco(shared.store)

    # Os managers das importações entram depois da carga: ela não consulta a rede.
    shared.store.add_manager(SteamAPIManager())
    shared.store.add_manager(HLTBManager())
    shared.store.add_manager(SgdbManager())
    shared.store.toggle_manager_in_pipelines(FileManager, True)

    if "--sair-apos-carregar" in argv:
        if sys.stdout is not None:
            print(f"jogos carregados: {carregados}", flush=True)
        return 0

    _limpar_e_ativar_copias(modelo)
    _carregar_contas()

    from cartridges.janela import qwk  # noqa: PLC0415

    # Controls no estilo Basic, redesenhado pelo Tema.qml (D38); antes de criar o motor.
    QQuickStyle.setStyle("Basic")
    motor = QQmlApplicationEngine()
    qwk.registrar(motor)
    aplicativo = Aplicativo(avisos)
    controle = ControleDaGrade()
    detalhes = DetalhesDoJogo(shared.store, avisos=avisos)
    edicao = ModeloDaEdicao(aplicativo)
    historico = HistoricoDeSessoes(shared.store)
    big_picture = BigPicture(modelo, animacoes_do_sistema=aplicativo.animacoesDoSistema)
    sessao = ModeloDaSessao(avisos, controle=controle, big_picture=big_picture)
    shared.sessao = sessao
    # O domínio avisa por aqui quando o histórico, o catálogo ou uma conta das conquistas muda (D58).
    conquistas = ConquistasDoJogo(detalhes, sessao)
    shared.conquistas = conquistas
    # Antes de o Qt fechar as janelas: sem isto a janela "Jogando" fecharia pelo fim normal da sessão, com interface.
    # Só o rápido (gravar, parar o vigia); a parede e as fitas vão ao `aboutToQuit` (`_fechar`, `sessao.devolver`).
    # O desligar do Windows emite o `aboutToQuit` antes do `quit()`; lá o `devolver()` grava primeiro.
    app.saindo.connect(sessao.encerrar)
    motor.addImageProvider("desfoque", detalhes.provedor)
    motor.addImageProvider("fundo", ProvedorDoFundo())
    contexto = motor.rootContext()
    for nome, valor in (
        ("filtros", filtros), ("paginaTodos", pagina_biblioteca), ("paginaZerados", pagina_zerados),
        ("aplicativo", aplicativo), ("ponte", ponte), ("controle", controle), ("detalhes", detalhes),
        ("edicao", edicao), ("bigPicture", big_picture), ("sessao", sessao), ("historico", historico),
        ("conquistasDoJogo", conquistas),
    ):  # fmt: skip
        contexto.setContextProperty(nome, valor)
    # Um app morto no meio da sessão (ou a máquina desligada) não devolveu o papel de parede: desfaz agora.
    session_wallpaper.restaurar_orfaos()
    motor.load(QUrl.fromLocalFile(str(_RAIZ / "qml" / "Aplicativo.qml")))
    if not motor.rootObjects():
        return 1
    # As fitas de LED: desfaz o que uma execução anterior deixou e acende na cor do app (numa thread). Depois da
    # janela: sem ela não há `aboutToQuit`, e o `fechar()` (no fim do `ModeloDaSessao.devolver()`) nunca viria.
    session_fita.abrir()
    big_picture.definir_janela(motor.rootObjects()[0])  # a janela que vai à tela cheia
    sessao.definir_janela(motor.rootObjects()[0])  # a que volta da barra de tarefas no fim da sessão
    shared.aplicativo = aplicativo
    aplicativo.verificador_de_atualizacoes = verificador  # a tela de preferências chama `check_async()` ao ligar o aviso
    # Na ordem da `main`: atualizações, HowLongToBeat, tamanho em disco.
    verificador.start()
    varredura_hltb.start()
    varredura_tamanho.start()
    _ligar_conquistas(aplicativo)
    # Depois de a janela aparecer. Com restauração pendente a importação é outra (plano 8).
    # shortcut: sem `continuar_restauracao`, a abertura com restauração pendente não importa; entra no plano 8.
    if not restauracao.existe() and shared.schema.get_boolean("auto-import"):
        QTimer.singleShot(0, lambda: aplicativo.importar(silenciosa=True))
    return app.exec()
