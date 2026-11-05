# app.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app Qt: `python -m cartridges`."""

import builtins
import logging
import os
import subprocess
import sys
import threading
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# A interface é hardcoded em pt-BR; antes de importar `cartridges.jogo`, cujos STATUS_LABELS chamam `_()` na importação.
builtins._ = lambda message: message  # type: ignore[attr-defined]
builtins.ngettext = lambda singular, plural, n: singular if n == 1 else plural  # type: ignore[attr-defined]

# pylint: disable=wrong-import-position
from PySide6.QtCore import QEvent, Qt, QTimer, QUrl, Signal, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from cartridges import assistente, shared
from cartridges.aplicativo import Aplicativo
from cartridges.carga import carregar_jogos_do_disco
from cartridges.conquistas import icones
from cartridges.conquistas.ea import conta as ea_conta
from cartridges.conquistas.epic import conta as epic_conta
from cartridges.conquistas.varredura import VarreduraConquistas
from cartridges.conquistas.xbox import conta, login
from cartridges.janela.cortina_da_abertura import CortinaDaAbertura
from cartridges.logging import detalhado
from cartridges.logging.detalhado import instalar_filtro
from cartridges.logging.session_file_handler import SessionFileHandler
from cartridges.logging.setup import log_system_info, setup_logging
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.detalhes import DetalhesDoJogo
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.modelos.novidades import Novidades
from cartridges.modelos.preferencias import Preferencias
from cartridges.modelos.provedor_de_icones import ProvedorDeIcones
from cartridges.modelos.restauracao import ContinuacaoDaRestauracao
from cartridges.modelos.restaurando import Restaurando, entregar_so_ao_mudar
from cartridges.modelos.saves import SavesDoJogo
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.modelos.sobre import Sobre
from cartridges.modelos.zerados_manuais import SeletorDeZerados
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
from cartridges.utils.ajustes_do_windows import FiltroDeAjustes, aplicar_cor_de_destaque
from cartridges.utils.app_updater import AppUpdater
from cartridges.utils.caixa_redimensionavel import CaixaDaAnotacao
from cartridges.utils.hltb_backfill import HLTBBackfill
from cartridges.utils.install_size import InstallSizeSweep
from cartridges.utils.news_checker import NewsChecker
from cartridges.utils.thread_principal import na_thread_principal
from cartridges.utils.updates_checker import UpdatesChecker
from cartridges.utils.window_geometry import GeometriaDaJanela

_RAIZ = Path(__file__).resolve().parent
_ICONE = _RAIZ.parent / "data" / "icons" / "hicolor" / "scalable" / "apps" / f"{shared.APP_ID}.svg"


def _configurar_log() -> None:
    """O log completo: arquivo, console, ganchos de exceção, avisos do Qt e quedas nativas."""
    try:
        setup_logging()
    except ValueError:
        # dictConfig embrulha falhas dos handlers em ValueError (rotação que não sobreviveu a uma queda, log preso por outro
        # processo). Sem log NENHUM é o pior resultado e o app instalado não tem console: usa um arquivo só desta sessão.
        try:
            reserva = SessionFileHandler(
                shared.log_dir / f"cartridges-{os.getpid()}.log", backup_count=0, sem_limite=detalhado.ativo()
            )
            logging.basicConfig(level=logging.DEBUG, handlers=[reserva])
        except OSError:
            logging.basicConfig(level=logging.DEBUG)
        logging.exception("Não foi possível configurar o log em arquivo")
    log_system_info()


def _medidas_da_tela(app: QGuiApplication) -> None:
    escala = max((tela.devicePixelRatio() for tela in app.screens()), default=1.0)
    shared.scale_factor = escala
    shared.display_size = (round(200 * escala), round(300 * escala))
    shared.details_size = (round(420 * escala), round(630 * escala))


def _limpar_e_ativar_copias(modelo: ModeloDaBiblioteca) -> None:
    """Limpa a pasta das cópias animadas numa thread e só depois libera o modelo a pedir as que faltam (a limpeza apaga todo `.tmp`)."""
    ids = {jogo.game_id for jogo in shared.store}

    def limpar() -> None:
        copias_animadas.limpar(ids)
        na_thread_principal(modelo.ativar_copias)

    threading.Thread(target=limpar, daemon=True).start()


class AplicacaoQt(QGuiApplication):
    """O `QGuiApplication` que avisa o `quit()` antes de o Qt fechar as janelas.

    No Qt 6 o `quit()` manda o `QEvent.Quit`, que faz cada janela receber o `closing` antes do `aboutToQuit`: o `saindo`
    chega antes e encerra a sessão sem interface.
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
    """A varredura de conquistas da abertura, depois das outras: uma passada por execução."""
    aplicativo.varredura_conquistas = VarreduraConquistas()
    aplicativo.varredura_conquistas.start()
    return aplicativo.varredura_conquistas


def _comecar_varreduras(aplicativo: Aplicativo, verificador, novidades, varredura_hltb, varredura_tamanho) -> None:  # noqa: ANN001
    verificador.start()
    novidades.acompanhar_a_chave()
    novidades.ligar()
    varredura_hltb.start()
    varredura_tamanho.start()
    backup_de_saves.atualizar_cache()
    _ligar_conquistas(aplicativo)


def _parar_varredura_de_conquistas() -> None:
    if shared.aplicativo is not None and shared.aplicativo.varredura_conquistas is not None:
        shared.aplicativo.varredura_conquistas.stop()


@dataclass
class _Abertura:
    """O que a abertura já criou; o `aboutToQuit` pode vir antes de tudo existir (Windows desligando) e o `_fechar` pula o que é ``None``."""

    geometria: Any = None
    big_picture: Any = None
    controle: Any = None
    sessao: Any = None
    verificador: Any = None
    novidades: Any = None
    varredura_hltb: Any = None
    varredura_tamanho: Any = None
    edicao: Any = None
    preferencias: Any = None
    continuacao: Any = None
    atualizador: Any = None
    painel: Any = None
    motor: Any = None
    aplicativo: Any = None
    # Motor da janela "Restaurando o backup"; vive até o fim do `main()`.
    restauracao: Any = None
    # Motor do assistente da primeira abertura; vive até o fim do `main()`.
    assistente: Any = None
    # Filtro do `WM_SETTINGCHANGE`, instalado no app; sai no fim do `_fechar`.
    ajustes: Any = None
    # A janela da restauração ou do assistente fecha quando a principal é revelada.
    cortina: Any = None
    # Objetos que só o contexto do QML conhece: o Qt não é dono deles, e sem referência aqui sairiam da memória.
    mantidos: Any = None


def _de(objeto: Any, metodo: str) -> Callable[[], Any]:
    return (lambda: None) if objeto is None else getattr(objeto, metodo)


def _fechar(abertura: _Abertura) -> None:
    a = abertura
    _encerrar_em_ordem(
        # Primeiro: um `aboutToQuit` sem `closing` antes (Windows desligando) grava a geometria aqui.
        _de(a.geometria, "gravar"),
        _de(a.big_picture, "encerrar"),
        _de(a.controle, "encerrar"),
        # As Preferências com um modal aberto fecham antes de a sessão devolver as fitas (a prévia que sai não as acende de novo) e antes do login pendente.
        _de(a.preferencias, "fechar"),
        _de(a.sessao, "devolver"),
        login.cancelar_pendente,
        ea_conta.gravar_pendente,  # o `remid` novo da EA que não coube no disco: última tentativa
        _de(a.novidades, "parar"),  # antes do `stop` do verificador: nenhum resultado do feed chega a uma tela que fecha
        _de(a.verificador, "stop"),
        _de(a.varredura_hltb, "stop"),
        _de(a.varredura_tamanho, "stop"),
        _parar_varredura_de_conquistas,
        _de(a.edicao, "cancelar"),
        async_manager.encerrar,
        copias_animadas.encerrar,
        icones.encerrar,
        # por último: um resultado do download já na fila só é tratado depois deste `stop()` e é descartado
        _de(a.atualizador, "stop"),
        _de(a.ajustes, "desligar"),  # o Qt guarda só o ponteiro: o filtro sai antes de o objeto Python poder morrer
    )


def _avisos_da_abertura(aplicativo: Any, restauracao_falhou: bool) -> None:
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
            "Não foi possível concluir a redefinição do Kyron. Tente novamente.",
            [],
            lambda: None,
        )


def _importar_na_abertura(aplicativo: Any, continuacao: Any) -> None:
    """Depois de a janela aparecer. Com restauração pendente a importação é a da continuação (roda mesmo com a automática desligada); senão, a automática."""
    if restauracao.existe():
        QTimer.singleShot(0, continuacao.continuar)
    elif shared.schema.get_boolean("auto-import"):
        QTimer.singleShot(0, lambda: aplicativo.importar(silenciosa=True))


def _seguir_animacoes(aplicativo: Aplicativo, big_picture: BigPicture) -> None:
    aplicativo_fraco, big_picture_fraco = weakref.ref(aplicativo), weakref.ref(big_picture)

    def seguir() -> None:
        if (a := aplicativo_fraco()) is not None and (b := big_picture_fraco()) is not None:
            b.definir_animacoes_do_sistema(a.animacoesDoSistema)

    aplicativo.animacoesDoSistemaChanged.connect(seguir)


def _instalar_filtro_de_ajustes(app: AplicacaoQt, aplicativo: Aplicativo) -> FiltroDeAjustes:
    aplicativo_fraco = weakref.ref(aplicativo)

    def ao_mudar() -> None:
        aplicar_cor_de_destaque()
        if (a := aplicativo_fraco()) is not None:
            a.reler_animacoes()

    filtro = FiltroDeAjustes(ao_mudar)
    app.installNativeEventFilter(filtro)
    return filtro


def _abrir(app: AplicacaoQt, argv: list[str], abertura: _Abertura) -> int | None:
    """A biblioteca e a janela principal, preenchendo ``abertura``. ``0`` no `--sair-apos-carregar`, ``1`` sem janela."""
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
    abertura.controle = controle = ControleDaGrade()
    detalhes = DetalhesDoJogo(shared.store, avisos=avisos)
    abertura.edicao = edicao = ModeloDaEdicao(aplicativo)
    historico = HistoricoDeSessoes(shared.store)
    saves = SavesDoJogo(aplicativo)
    abertura.continuacao = continuacao = ContinuacaoDaRestauracao(aplicativo)
    abertura.painel = painel_das_tarefas = PainelDasTarefas()
    abertura.atualizador = atualizador = AppUpdater()
    abertura.novidades = novidades = Novidades(avisos, NewsChecker())
    sobre = Sobre(avisos)
    zerados_manuais = SeletorDeZerados()
    caixa_da_anotacao = CaixaDaAnotacao()
    abertura.cortina = cortina_da_abertura = CortinaDaAbertura()
    abertura.big_picture = big_picture = BigPicture(modelo, animacoes_do_sistema=aplicativo.animacoesDoSistema)
    _seguir_animacoes(aplicativo, big_picture)
    abertura.geometria = geometria = GeometriaDaJanela()
    painel_das_tarefas.gravar_geometria = geometria.gravar
    abertura.sessao = sessao = ModeloDaSessao(avisos, controle=controle, big_picture=big_picture)
    shared.sessao = sessao
    conquistas = ConquistasDoJogo(detalhes, sessao)
    shared.conquistas = conquistas
    big_picture_fraco = weakref.ref(big_picture)
    abertura.preferencias = preferencias = Preferencias(
        avisos, lambda: bool((b := big_picture_fraco()) and b.disponivel)
    )
    shared.preferencias = preferencias
    shared.edicao = edicao
    # Antes de o Qt fechar as janelas: sem isto a janela "Jogando" fecharia pelo fim normal da sessão, com interface. Parede e fitas vão ao `aboutToQuit`.
    app.saindo.connect(sessao.encerrar)
    motor.addImageProvider("desfoque", detalhes.provedor)
    motor.addImageProvider("fundo", ProvedorDoFundo())
    motor.addImageProvider("icone", ProvedorDeIcones())
    contexto = motor.rootContext()
    for nome, valor in (
        ("filtros", filtros), ("paginaTodos", pagina_biblioteca), ("paginaZerados", pagina_zerados),
        ("aplicativo", aplicativo), ("ponte", ponte), ("controle", controle), ("detalhes", detalhes),
        ("edicao", edicao), ("bigPicture", big_picture), ("sessao", sessao), ("historico", historico),
        ("saves", saves), ("conquistasDoJogo", conquistas), ("preferencias", preferencias),
        ("painelDasTarefas", painel_das_tarefas),
        ("restauracao", continuacao), ("atualizador", atualizador), ("novidades", novidades), ("sobre", sobre),
        ("zeradosManuais", zerados_manuais), ("geometria", geometria), ("caixaDaAnotacao", caixa_da_anotacao),
        ("cortinaDaAbertura", cortina_da_abertura),
    ):  # fmt: skip
        contexto.setContextProperty(nome, valor)
    abertura.mantidos = (
        modelo, filtros, pagina_biblioteca, pagina_zerados, ponte, controle, detalhes, avisos, historico, saves, sobre, zerados_manuais,
        caixa_da_anotacao, cortina_da_abertura,
    )  # fmt: skip
    # Um app morto no meio da sessão (ou a máquina desligada) não devolveu o papel de parede: desfaz agora.
    session_wallpaper.restaurar_orfaos()
    # Desfaz o que uma execução anterior deixou nas fitas e acende na cor do app (numa thread), antes do QML, que segura a thread principal por um ou dois segundos.
    session_fita.migrar_roxo_antigo()  # antes de acender: o roxo de antes do Kyron vira o azul
    session_fita.abrir()
    motor.load(QUrl.fromLocalFile(str(_RAIZ / "qml" / "Aplicativo.qml")))
    if not motor.rootObjects():
        # Sem janela o `app.exec()` não roda e o `aboutToQuit` (o `fechar()` no `ModeloDaSessao.devolver()`) não vem.
        session_fita.fechar()
        return 1
    big_picture.definir_janela(motor.rootObjects()[0])
    controle.definir_janela(motor.rootObjects()[0])  # só a principal ativa dá o controle
    sessao.definir_janela(motor.rootObjects()[0])
    painel_das_tarefas.definir_janela(motor.rootObjects()[0])
    # Antes de o Qt mandar o `closing` às janelas: um `quit()` não é recusado pelo trabalho em andamento.
    app.saindo.connect(painel_das_tarefas.encerrando)
    shared.aplicativo = aplicativo
    abertura.ajustes = _instalar_filtro_de_ajustes(app, aplicativo)
    aplicativo.verificador_de_atualizacoes = verificador
    _comecar_varreduras(aplicativo, verificador, novidades, varredura_hltb, varredura_tamanho)
    # Depois da janela e antes dos avisos da abertura. A pergunta da versão nova fica fora da fila de pedidos: com um diálogo aberto, espera escondida (`DialogoDaAtualizacao.outroAberto`).
    atualizador.start()
    _importar_na_abertura(aplicativo, continuacao)
    return None


def _acordar(abertura: _Abertura) -> None:
    """A segunda abertura (o atalho clicado de novo): traz a principal, escondida pelas tarefas ou minimizada; sem ela, a janela da restauração ou do assistente."""
    if abertura.painel is not None:
        abertura.painel.mostrarPrincipal()
        return
    for motor in (abertura.restauracao, abertura.assistente):
        for janela in motor.rootObjects() if motor is not None else ():
            if janela.isVisible():
                janela.setWindowStates(janela.windowStates() & ~Qt.WindowState.WindowMinimized)
                janela.raise_()
                janela.requestActivate()


def _com_barra_propria(motor: QQmlApplicationEngine) -> None:
    """As janelas da abertura (restauração e assistente) têm a barra do app: o QWindowKit e a marca `comAgente` no contexto. Os testes carregam o QML sem isto."""
    from cartridges.janela import qwk  # noqa: PLC0415

    qwk.registrar(motor)
    motor.rootContext().setContextProperty("comAgente", True)


def _janela_da_restauracao() -> QQmlApplicationEngine:
    motor = QQmlApplicationEngine()
    _com_barra_propria(motor)
    motor.addImageProvider("icone", ProvedorDeIcones())
    restaurando = Restaurando(motor)
    motor.rootContext().setContextProperty("restaurando", restaurando)
    motor.load(QUrl.fromLocalFile(str(_RAIZ / "qml" / "JanelaRestaurando.qml")))
    return motor


def _avancar(fraco: weakref.ref, fracao: float) -> None:
    if (restaurando := fraco()) is not None:
        restaurando.avancar(fracao)


def _fechar_quando_a_principal_aparecer(abertura: _Abertura, motor: QQmlApplicationEngine, codigo: int | None) -> None:
    """Fecha a janela da restauração ou do assistente; com a principal aberta, só quando ela aparece (a cortina a esconde até as capas carregarem), senão o app pareceria fechado."""

    def fechar() -> None:
        for janela in motor.rootObjects():
            janela.close()

    if codigo is None and abertura.cortina is not None:
        abertura.cortina.depois_de_revelar(fechar)
    else:
        fechar()


def _restaurar_e_abrir(app: AplicacaoQt, argv: list[str], abertura: _Abertura) -> None:
    """Aplica o backup agendado numa thread, com a janela da restauração na tela; a abertura continua
    na principal quando ele termina. Volta na hora.

    Os fechamentos não prendem objeto Qt: o motor mora na ``abertura`` e o resto vai por referência fraca;
    a thread de trabalho nunca solta a última referência a um QObject.
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
            # Mesmo com a abertura quebrada: uma janela presa em 100% só sairia pelo Gerenciador de Tarefas.
            if (restaurando := restaurando_fraco()) is not None:
                restaurando.terminar()
            _fechar_quando_a_principal_aparecer(abertura, abertura.restauracao, codigo)
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
        na_thread_principal(terminou, resultado)

    # Não daemon: o app que sai no meio (o Windows desligando) espera a troca das pastas terminar.
    threading.Thread(target=restaurar, name="restauracao-do-backup").start()


def _mostrar_assistente(app: AplicacaoQt, argv: list[str], abertura: _Abertura, restauracao_falhou: bool = False) -> bool:
    """O assistente da primeira abertura, antes da biblioteca: ``True`` se está na tela (quem chama vai ao `exec()`; o `_abrir`
    vem quando ele termina), ``False`` para seguir ao `_abrir`. Nunca no `--sair-apos-carregar`; cada saída fecha a janela
    num `finally`, depois de a próxima existir.
    """
    if "--sair-apos-carregar" in argv or not assistente.precisa_mostrar():
        return False
    # Conectar uma conta no assistente lê os jogos da loja: sem biblioteca ainda, sobre uma store vazia.
    shared.store = Store()
    app_fraco = weakref.ref(app)

    def fechar_a_janela() -> None:
        for janela in abertura.assistente.rootObjects():
            janela.close()

    def ao_terminar() -> None:
        codigo = None
        try:
            codigo = _abrir(app_fraco(), argv, abertura)
            if codigo is None:
                _avisos_da_abertura(abertura.aplicativo, restauracao_falhou)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Falha ao abrir o app depois do assistente")
            codigo = 1
        finally:
            _fechar_quando_a_principal_aparecer(abertura, abertura.assistente, codigo)
        if codigo is not None and (qt := app_fraco()) is not None:
            qt.exit(codigo)

    def ao_restaurar() -> None:
        try:
            _restaurar_e_abrir(app_fraco(), argv, abertura)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Falha ao restaurar o backup agendado pelo assistente")
        finally:
            fechar_a_janela()

    abertura.assistente = motor = QQmlApplicationEngine()
    _com_barra_propria(motor)
    motor.addImageProvider("icone", ProvedorDeIcones())
    modelo = assistente.Assistente(ao_terminar, ao_restaurar, parent=motor)
    motor.rootContext().setContextProperty("assistente", modelo)
    motor.load(QUrl.fromLocalFile(str(_RAIZ / "qml" / "JanelaDoAssistente.qml")))
    if not motor.rootObjects():
        logging.getLogger(__name__).error("A janela do assistente não carregou; a biblioteca abre sem ele")
        return False
    modelo.definir_janela(motor.rootObjects()[0])
    return True


def relancar() -> None:
    if Path(sys.executable).stem.lower() == "kyron":
        # O Kyron.exe já põe o `-m cartridges` sozinho.
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
    # Antes de tudo: uma segunda cópia não lê os jogos nem grava por cima da primeira; este processo realça a primeira antes de sair.
    if not single_instance.acquire():
        single_instance.present_running_instance()
        return 0
    app = AplicacaoQt(argv)
    app.setApplicationName("Kyron")
    app.setApplicationDisplayName("Kyron")
    app.setWindowIcon(QIcon(str(_ICONE)))
    aplicar_cor_de_destaque()
    abertura = _Abertura()
    app.aboutToQuit.connect(lambda: _fechar(abertura))
    # "Redefinir Kyron", agendado nas Preferências: antes do log, que mora na pasta do app e a travaria.
    redefinido = redefinir.aplicar_pendente()
    _configurar_log()
    filtro = instalar_filtro(app)  # noqa: F841  # a referência vive até o fim do main
    if redefinido:
        logging.info("Cartridges redefinido")
    elif redefinido is False:
        logging.error("Não foi possível redefinir o Cartridges", exc_info=redefinir.falha)
    _medidas_da_tela(app)
    # Controls no estilo Basic, redesenhado pelo Tema.qml; antes do primeiro motor.
    QQuickStyle.setStyle("Basic")
    single_instance.watch_second_launch(lambda: na_thread_principal(_acordar, abertura))

    # Um backup agendado é aplicado antes de qualquer leitura de dados; leva minutos, por isso numa thread com a janela da restauração.
    if backup.ha_pendente():
        _restaurar_e_abrir(app, argv, abertura)
    else:
        # Sem backup agendado, só a recuperação de uma troca interrompida, que apenas renomeia pastas.
        restauracao_falhou = backup.aplicar_pendente() is False
        if not _mostrar_assistente(app, argv, abertura, restauracao_falhou):
            codigo = _abrir(app, argv, abertura)
            if codigo is not None:
                return codigo
            _avisos_da_abertura(abertura.aplicativo, restauracao_falhou)
    codigo = app.exec()
    # O gancho do log sai antes da destruição do app e do interpretador: um aviso tardio do Qt vai ao stderr.
    qInstallMessageHandler(None)
    if abertura.aplicativo is not None and abertura.aplicativo.reiniciar:
        # A trava sai antes: o processo novo precisa conseguir tomá-la.
        single_instance.release()
        relancar()
    return codigo
