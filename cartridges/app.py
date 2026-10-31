# app.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app Qt: `python -m cartridges`."""

import builtins
import logging
import subprocess
import sys
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# A interface é hardcoded em pt-BR (como em `cartridges.in`). Antes de importar
# `cartridges.jogo`, cujos STATUS_LABELS chamam `_()` na importação.
builtins._ = lambda message: message  # type: ignore[attr-defined]
builtins.ngettext = lambda singular, plural, n: singular if n == 1 else plural  # type: ignore[attr-defined]

# pylint: disable=wrong-import-position
from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal
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
from cartridges.modelos.preferencias import Preferencias
from cartridges.modelos.restauracao import ContinuacaoDaRestauracao
from cartridges.modelos.restaurando import Restaurando, entregar_so_ao_mudar
from cartridges.modelos.saves import SavesDoJogo
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.ponte import Ponte
from cartridges.saves import backup_de_saves
from cartridges.store.managers import async_manager
from cartridges.store.managers.exibicao_manager import ExibicaoManager
from cartridges.store.managers.file_manager import FileManager
from cartridges.store.managers.hltb_manager import HLTBManager
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.store.store import Store
from cartridges.utils import (
    backup,
    copias_animadas,
    redefinir,
    restauracao,
    session_fita,
    session_wallpaper,
    single_instance,
)
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


def _comecar_varreduras(aplicativo: Aplicativo, verificador, varredura_hltb, varredura_tamanho) -> None:  # noqa: ANN001
    """Na ordem da `main`: atualizações, HowLongToBeat, tamanho em disco, o cache dos saves e as conquistas."""
    verificador.start()
    varredura_hltb.start()
    varredura_tamanho.start()
    backup_de_saves.atualizar_cache()
    _ligar_conquistas(aplicativo)


def _parar_varredura_de_conquistas() -> None:
    if shared.aplicativo is not None and shared.aplicativo.varredura_conquistas is not None:
        shared.aplicativo.varredura_conquistas.stop()


@dataclass
class _Abertura:
    """O que a abertura já criou. O `aboutToQuit` pode vir antes de tudo existir (o Windows desligando durante a
    restauração): o que ainda é ``None`` o `_fechar` pula."""

    big_picture: Any = None
    sessao: Any = None
    verificador: Any = None
    varredura_hltb: Any = None
    varredura_tamanho: Any = None
    edicao: Any = None
    preferencias: Any = None
    continuacao: Any = None
    painel: Any = None
    motor: Any = None
    aplicativo: Any = None
    # O motor da janela "Restaurando o backup" (com o `Restaurando` dentro); vive até o fim do `main()`.
    restauracao: Any = None


def _de(objeto: Any, metodo: str) -> Callable[[], Any]:
    return (lambda: None) if objeto is None else getattr(objeto, metodo)


def _fechar(abertura: _Abertura) -> None:
    """O `aboutToQuit`, na ordem da `main`; o `stop()` de cada um vem antes do `encerrar()`."""
    a = abertura
    _encerrar_em_ordem(
        _de(a.big_picture, "encerrar"),  # a cortina preta do fade nunca fica no monitor (ADR 0003)
        # As Preferências com um modal aberto (calibração, assistente das fitas, brilho, contas): fecham antes de a
        # sessão devolver as fitas (a prévia que saem não as acende de novo) e antes do login pendente.
        _de(a.preferencias, "fechar"),
        _de(a.sessao, "devolver"),  # a parede e as fitas, com as janelas já fora da tela (grava antes se o `saindo` não veio)
        login.cancelar_pendente,  # um login da conta Microsoft esperando o navegador não sobrevive ao app
        ea_conta.gravar_pendente,  # o `remid` novo da EA que não coube no disco: última tentativa
        _de(a.verificador, "stop"),
        _de(a.varredura_hltb, "stop"),
        _de(a.varredura_tamanho, "stop"),
        _parar_varredura_de_conquistas,
        _de(a.edicao, "cancelar"),  # apaga os temporários de um editor ainda aberto
        async_manager.encerrar,  # drena as gravações, a do tempo da sessão inclusive
        copias_animadas.encerrar,
        icones.encerrar,  # os ícones na fila não seguram o processo com a rede travada
    )


def _avisos_da_abertura(aplicativo: Any, restauracao_falhou: bool) -> None:
    """Depois da janela, na ordem da `main`; pela fila da D72, um diálogo espera o anterior fechar."""
    if restauracao_falhou:
        aplicativo.pedir_dialogo(
            "Não foi possível restaurar", "Não foi possível restaurar o backup. Tente novamente.", [], lambda: None
        )
    if backup.pasta_dos_saves_desfeita:
        aplicativo.pedir_dialogo(
            "Cópias dos saves na pasta padrão",
            "As cópias dos saves do backup foram para a pasta padrão. Para voltar a usar {}, escolha-a novamente em "
            "Preferências.".format(backup.pasta_dos_saves_desfeita.replace("/", "\\")),
            [],
            lambda: None,
        )
    if redefinir.falha is not None:
        aplicativo.pedir_dialogo(
            "Não foi possível redefinir",
            "Não foi possível concluir a redefinição do Cartridges. Tente novamente.",
            [],
            lambda: None,
        )


def _importar_na_abertura(aplicativo: Any, continuacao: Any) -> None:
    """Depois de a janela aparecer. Com restauração pendente a importação é a da continuação (pasta de atalhos
    obrigatória, roda mesmo com a importação automática desligada); senão, a automática."""
    if restauracao.existe():
        QTimer.singleShot(0, continuacao.continuar)
    elif shared.schema.get_boolean("auto-import"):
        QTimer.singleShot(0, lambda: aplicativo.importar(silenciosa=True))


def _abrir(app: AplicacaoQt, argv: list[str], abertura: _Abertura) -> int | None:
    """A biblioteca e a janela principal, preenchendo ``abertura``. ``0`` no `--sair-apos-carregar`, ``1`` sem janela."""
    # A ponte para a thread principal nasce quando `thread_principal` é importado, aqui na principal.
    # O `stop()` de cada um vem antes do `encerrar()`: o que ainda entregariam não tem para onde ir.
    abertura.verificador = verificador = UpdatesChecker()
    abertura.varredura_hltb = varredura_hltb = HLTBBackfill()
    abertura.varredura_tamanho = varredura_tamanho = InstallSizeSweep()

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

    abertura.motor = motor = QQmlApplicationEngine()
    qwk.registrar(motor)
    abertura.aplicativo = aplicativo = Aplicativo(avisos)
    controle = ControleDaGrade()
    detalhes = DetalhesDoJogo(shared.store, avisos=avisos)
    abertura.edicao = edicao = ModeloDaEdicao(aplicativo)
    historico = HistoricoDeSessoes(shared.store)
    saves = SavesDoJogo(aplicativo)
    abertura.continuacao = continuacao = ContinuacaoDaRestauracao(aplicativo)
    abertura.painel = painel_das_tarefas = PainelDasTarefas()
    abertura.big_picture = big_picture = BigPicture(modelo, animacoes_do_sistema=aplicativo.animacoesDoSistema)
    abertura.sessao = sessao = ModeloDaSessao(avisos, controle=controle, big_picture=big_picture)
    shared.sessao = sessao
    # O domínio avisa por aqui quando o histórico, o catálogo ou uma conta das conquistas muda (D58).
    conquistas = ConquistasDoJogo(detalhes, sessao)
    shared.conquistas = conquistas
    # O Big Picture diz se há 3D; a referência fraca não prende o objeto Qt numa função guardada.
    big_picture_fraco = weakref.ref(big_picture)
    abertura.preferencias = preferencias = Preferencias(
        avisos, lambda: bool((b := big_picture_fraco()) and b.disponivel)
    )
    shared.preferencias = preferencias
    shared.edicao = edicao
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
        ("saves", saves), ("conquistasDoJogo", conquistas), ("preferencias", preferencias),
        ("painelDasTarefas", painel_das_tarefas),
        ("restauracao", continuacao),
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
    painel_das_tarefas.definir_janela(motor.rootObjects()[0])  # a que o fechamento esconde com trabalho em andamento
    # Antes de o Qt mandar o `closing` às janelas: um `quit()` não é recusado pelo trabalho em andamento (D78).
    app.saindo.connect(painel_das_tarefas.encerrando)
    shared.aplicativo = aplicativo
    aplicativo.verificador_de_atualizacoes = verificador  # a tela de preferências chama `check_async()` ao ligar o aviso
    _comecar_varreduras(aplicativo, verificador, varredura_hltb, varredura_tamanho)
    _importar_na_abertura(aplicativo, continuacao)
    return None


def _acordar(abertura: _Abertura) -> None:
    """A segunda abertura (o atalho clicado de novo): traz a principal, escondida pelas tarefas ou minimizada; sem ela
    ainda (a restauração em andamento), a janela da restauração."""
    if abertura.painel is not None:
        abertura.painel.mostrarPrincipal()
        return
    if abertura.restauracao is None:
        return
    for janela in abertura.restauracao.rootObjects():
        if janela.isVisible():  # já fechada (a abertura quebrou): o app está saindo
            janela.setWindowStates(janela.windowStates() & ~Qt.WindowState.WindowMinimized)
            janela.raise_()
            janela.requestActivate()


def _janela_da_restauracao() -> QQmlApplicationEngine:
    """A janela "Restaurando o backup" num motor próprio, com o `Restaurando` (filho do motor) no contexto."""
    motor = QQmlApplicationEngine()
    restaurando = Restaurando(motor)
    motor.rootContext().setContextProperty("restaurando", restaurando)
    motor.load(QUrl.fromLocalFile(str(_RAIZ / "qml" / "JanelaRestaurando.qml")))
    return motor


def _avancar(fraco: weakref.ref, fracao: float) -> None:
    if (restaurando := fraco()) is not None:
        restaurando.avancar(fracao)


def _restaurar_e_abrir(app: AplicacaoQt, argv: list[str], abertura: _Abertura) -> None:
    """Aplica o backup agendado numa thread, com a janela da restauração na tela; a abertura continua na thread
    principal quando ele termina. Volta na hora: quem chama roda o `exec()`.

    Os fechamentos não prendem objeto Qt: o motor (e o `Restaurando`, filho dele) mora na ``abertura``, e o resto vai
    por referência fraca. A thread de trabalho nunca solta a última referência a um QObject.
    """
    abertura.restauracao = _janela_da_restauracao()
    restaurando_fraco = weakref.ref(abertura.restauracao.rootContext().contextProperty("restaurando"))
    app_fraco = weakref.ref(app)

    def terminou(resultado: bool | None) -> None:
        codigo = None
        try:
            # A principal nasce antes de a da restauração sair: o app sem nenhuma janela, nem por um instante, sairia.
            codigo = _abrir(app_fraco(), argv, abertura)
            if codigo is None:
                _avisos_da_abertura(abertura.aplicativo, resultado is False)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Falha ao abrir o app depois da restauração do backup")
            codigo = 1
        finally:
            # Mesmo com a abertura quebrada: uma janela sem fechar, presa em 100%, só sairia pelo Gerenciador de Tarefas.
            if (restaurando := restaurando_fraco()) is not None:
                restaurando.terminar()
            for janela in abertura.restauracao.rootObjects():
                janela.close()
        if codigo is not None and (qt := app_fraco()) is not None:
            qt.exit(codigo)

    def restaurar() -> None:
        try:
            resultado = backup.aplicar_pendente(
                entregar_so_ao_mudar(lambda fracao: na_thread_principal(_avancar, restaurando_fraco, fracao))
            )
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Falha inesperada ao restaurar o backup")
            resultado = False
        # Pela mesma fila do progresso: o fim vem depois da última fração.
        na_thread_principal(terminou, resultado)

    # Não daemon: o app que sai no meio (o Windows desligando) espera a troca das pastas terminar.
    threading.Thread(target=restaurar, name="restauracao-do-backup").start()


def relancar() -> None:
    """Abre o app de novo, desacoplado deste processo, que já está saindo (D75)."""
    if Path(sys.executable).stem.lower() == "cartridges":
        # O Cartridges.exe já põe o `-m cartridges` sozinho.
        comando, pasta = [sys.executable, *sys.argv[1:]], None
    else:
        comando, pasta = [sys.executable, "-m", "cartridges", *sys.argv[1:]], str(_RAIZ.parent)
    _popen(
        comando,
        cwd=pasta,
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )


_popen = subprocess.Popen  # o ponto que o guarda dos testes troca (`sem_relancar_de_verdade`)


def main(argv: list[str]) -> int:
    # Antes de tudo: uma segunda cópia não lê os jogos, muito menos grava por cima da primeira (D76). Quem realça a
    # primeira é este processo, antes de sair: senão o segundo clique no atalho parece não fazer nada.
    if not single_instance.acquire():
        single_instance.present_running_instance()
        return 0
    app = AplicacaoQt(argv)
    app.setApplicationName("Cartridges")
    app.setApplicationDisplayName("Cartridges")
    app.setWindowIcon(QIcon(str(_ICONE)))
    abertura = _Abertura()
    app.aboutToQuit.connect(lambda: _fechar(abertura))
    # "Redefinir Cartridges", agendado nas Preferências: antes do log, que mora na pasta do app e a travaria.
    redefinido = redefinir.aplicar_pendente()
    _configurar_log()
    if redefinido:
        logging.info("Cartridges redefinido")
    elif redefinido is False:
        logging.error("Não foi possível redefinir o Cartridges", exc_info=redefinir.falha)
    _medidas_da_tela(app)
    # Controls no estilo Basic, redesenhado pelo Tema.qml (D38); antes do primeiro motor (o da restauração, se houver).
    QQuickStyle.setStyle("Basic")
    # A segunda abertura traz a principal; durante a restauração, a janela dela.
    single_instance.watch_second_launch(lambda: na_thread_principal(_acordar, abertura))

    # Um backup agendado nas Preferências é aplicado antes de qualquer leitura de dados: fitas, papel de parede e a
    # biblioteca já nascem do backup. Um backup grande leva minutos: roda numa thread, com a janela da restauração.
    if backup.ha_pendente():
        _restaurar_e_abrir(app, argv, abertura)
    else:
        # Sem backup agendado, só a recuperação de uma troca interrompida, que apenas renomeia pastas.
        restauracao_falhou = backup.aplicar_pendente() is False
        codigo = _abrir(app, argv, abertura)
        if codigo is not None:
            return codigo
        _avisos_da_abertura(abertura.aplicativo, restauracao_falhou)
    codigo = app.exec()
    if abertura.aplicativo is not None and abertura.aplicativo.reiniciar:
        # A trava sai antes: o processo novo precisa conseguir tomá-la.
        single_instance.release()
        relancar()
    return codigo
