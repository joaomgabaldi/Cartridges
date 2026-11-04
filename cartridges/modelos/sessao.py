# sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `ModeloDaSessao`: a camada da sessão e a janela principal.

`ProcessSession` e `SessionWindow` chamam aqui (`shared.sessao`) para mostrar e esconder a camada da sessão, avisar o
fim e trazer a janela de volta. O QML só lê as propriedades e chama os slots. Tudo na thread principal.
"""

import ctypes
import logging
import weakref
from ctypes import wintypes
from typing import Any

from PySide6.QtCore import Property, QCoreApplication, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QWindow

from cartridges import conquista_aviso, shared
from cartridges.conquistas import sessao as sessao_conquistas
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.ordem import _url_da_capa  # noqa: PLC2701
from cartridges.process_session import ProcessSession
from cartridges.saves import backup_de_saves
from cartridges.session_window import SessionWindow
from cartridges.utils import game_logo, session_fita, session_log, session_wallpaper, window_geometry
from cartridges.utils.format_playtime import format_playtime, format_stopwatch


def canto_inferior_direito(area: tuple[int, int, int, int], largura: int, altura: int, margem: int = 12) -> tuple[int, int]:
    """Onde a janela fica logo acima do relógio: o canto de baixo à direita da área de trabalho."""
    return area[2] - largura - margem, area[3] - altura - margem


def _user32() -> Any:
    return ctypes.windll.user32  # type: ignore[attr-defined]


def _area_de_trabalho() -> tuple[int, int, int, int]:
    area = wintypes.RECT()
    if not _user32().SystemParametersInfoW(0x0030, 0, ctypes.byref(area), 0):  # SPI_GETWORKAREA
        raise ctypes.WinError()
    return area.left, area.top, area.right, area.bottom


def _retangulo_da_janela(hwnd: int) -> tuple[int, int, int, int]:
    retangulo = wintypes.RECT()
    user32 = _user32()
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    if not user32.GetWindowRect(hwnd, ctypes.byref(retangulo)):
        raise ctypes.WinError()
    return retangulo.left, retangulo.top, retangulo.right, retangulo.bottom


def _posicionar(hwnd: int, x: int, y: int) -> None:
    user32 = _user32()
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, *([ctypes.c_int] * 4), wintypes.UINT]
    # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE: não redimensiona, não muda a ordem e nunca rouba o foco.
    user32.SetWindowPos(hwnd, 0, x, y, 0, 0, 0x0001 | 0x0004 | 0x0010)


def pode_anotar(jogo: Any) -> bool:
    """Onde a anotação se edita: num jogo sendo jogado, ou que já tem uma.

    A anotação responde "onde eu parei?", que só é pergunta enquanto se joga; o jogo que já tem
    uma precisa continuar tendo onde apagá-la. Num zerado ela é só leitura.
    """
    if jogo.zerado:
        return False
    return jogo.status == "playing" or bool((jogo.notes or "").strip())


class ModeloDaSessao(QObject):
    alterado = Signal()
    relogioMudou = Signal()  # noqa: N815
    anotarPedido = Signal(str)

    def __init__(
        self, avisos: FilaDeAvisos, controle: Any = None, big_picture: Any = None, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._controle = controle  # `ControleDaGrade`: suspenso a sessão inteira
        self._big_picture = big_picture  # `BigPicture`: aberto, volta ao carrossel no fim
        self._jogo: Any = None  # o jogo da sessão; None sem sessão (camada escondida)
        self._manual: SessionWindow | None = None
        self._janela: QWindow | None = None
        # O jogo cuja anotação o balão da camada edita: fica depois do fim da sessão, para o que foi
        # digitado com o balão aberto ainda chegar a ele ao fechar.
        self._anotando: Any = None
        self._logo = ""
        self._largura_do_logo = 0
        self._anotacao = ""
        # O relógio só existe onde se vê: com a janela levada ao monitor da sessão.
        self._relogio_visivel = False
        self._tique = QTimer(self)
        self._tique.setInterval(1000)
        # O tique só renova o relógio; o resto da camada não se renotifica a cada segundo.
        self._tique.timeout.connect(self.relogioMudou)
        self.alterado.connect(self.relogioMudou)
        self._sair = QCoreApplication.quit  # trocado nos testes: sair de verdade acabaria o laço do teste
        self._encerrado = False

    def definir_janela(self, janela: QWindow) -> None:
        self._janela = janela

    @Property(bool, notify=alterado)
    def emAndamento(self) -> bool:
        return self._jogo is not None

    @Property(str, notify=alterado)
    def jogoId(self) -> str:
        return self._jogo.game_id if self._jogo is not None else ""

    @Property(str, notify=alterado)
    def nome(self) -> str:
        return self._jogo.name if self._jogo is not None else ""

    @Property(str, notify=alterado)
    def logo(self) -> str:
        return self._logo

    @Property(int, notify=alterado)
    def larguraDoLogo(self) -> int:  # noqa: N802
        return self._largura_do_logo

    @Property(str, notify=alterado)
    def anotacao(self) -> str:
        return self._anotacao

    @Property(str, notify=relogioMudou)
    def relogio(self) -> str:
        return format_stopwatch(self.session_elapsed())

    @Property(bool, notify=alterado)
    def relogioVisivel(self) -> bool:
        return self._relogio_visivel

    @Property(bool, notify=alterado)
    def janelaManual(self) -> bool:
        return self._manual is not None

    @Property(str, notify=alterado)
    def tituloDaJanela(self) -> str:
        return _("Jogando {}").format(self.nome)

    def show_session_blocker(self, game: Any) -> None:
        # A mesma sessão trocando de rastreador (o `fall_back` de `ProcessSession` passando a vez à
        # janela manual): o jogo segue aberto e tudo o que veste a sessão já está vestido.
        if self._jogo is game:
            return
        self._jogo = self._anotando = game
        self._logo, self._largura_do_logo = "", 0
        if (caminho := game_logo.cached_logo_path(game)) and (carregado := game_logo.load_logo(caminho, 640, 140)):
            self._logo, self._largura_do_logo = _url_da_capa(carregado[0]), carregado[1]
        self._anotacao = game.notes or ""
        # O relógio só faz sentido onde pode ser visto: com a janela levada a outro monitor ela fica à
        # vista a sessão inteira; senão está minimizada. A pergunta é se a mudança aconteceu, e não se a
        # opção está ligada (com o monitor escolhido desligado a opção está ligada e a janela minimizou).
        self._relogio_visivel = window_geometry.session_geometry() is not None
        if self._relogio_visivel:
            self._tique.start()
        self.alterado.emit()
        # A arte nos outros monitores prepara numa thread: nada espera por ela.
        if shared.schema.get_boolean("session-wallpaper"):
            session_wallpaper.comecar(game)
        # As fitas de LED vestem a cor do jogo (a rede corre em threads). `comecar` volta sozinho com o recurso
        # desligado ou sem fita configurada.
        session_fita.comecar(game)
        # E o vigia das conquistas: a partir daqui, uma conquista que sair no jogo aparece por cima dele e pisca a
        # iluminação. Nunca levanta.
        sessao_conquistas.comecar(game)
        # O controle fica todo com o jogo: nenhuma leitura e, depois da vibração de abertura, nem a DLL.
        if self._controle is not None:
            self._controle.suspender()

    def hide_session_blocker(self) -> None:
        jogo = self._jogo
        self._tique.stop()
        self._relogio_visivel = False
        self._jogo = None
        self._manual = None
        self.alterado.emit()
        # Primeiro: uma falha no que vem depois não deixa o controle suspenso para sempre.
        if self._controle is not None:
            self._controle.retomar()
        # Antes do `present()` de quem chamou: a janela reaparece já no lugar de origem, sem pular.
        # Sem efeito quando ela não saiu do lugar.
        window_geometry.restore_from_monitor(self._janela)
        # O jogo foi aberto pelo Big Picture: de volta ao carrossel em tela cheia, com ele no centro.
        if self._big_picture is not None and self._big_picture.visivel:
            self._big_picture.voltouDoJogo()
        session_wallpaper.restaurar()
        # O vigia para antes de a iluminação voltar à cor do app: um pulso pedido depois disso não teria sessão.
        sessao_conquistas.parar()
        # Uma última leitura do jogo: o que saiu nos últimos instantes ainda não está no histórico (o vigia olha a
        # cada poucos segundos). Só no fim da sessão, nunca no fechamento do app (`encerrar` não passa por aqui).
        self._varrer_jogo_da_sessao(jogo)
        self._devolver_as_fitas(jogo)

    @staticmethod
    def _varrer_jogo_da_sessao(jogo: Any) -> None:
        """Pede a leitura final das conquistas do jogo da sessão, em segundo plano. Nunca levanta."""
        if jogo is None:
            return
        try:
            varredura = getattr(shared.aplicativo, "varredura_conquistas", None)
            if varredura is not None:
                varredura.varrer_jogo(jogo)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning("Falha ao ler as conquistas no fim da sessão", exc_info=True)

    def _devolver_as_fitas(self, jogo: Any) -> None:
        """De volta à cor do app, e os avisos do que faltou na sessão que acabou.

        Os avisos vão agora, e não durante o jogo: no meio da partida chamariam a atenção que a luz calma
        existe para não chamar. Uma falha aqui nunca impede a janela de voltar.
        """
        try:
            session_fita.voltar()
            # A cor não acompanhou a tela porque a captura veio bloqueada a sessão inteira.
            if jogo is not None and session_fita.captura_bloqueada():
                self._avisos.adicionar(
                    _("A iluminação não acompanhou a tela de {}. Use o modo janela sem bordas.").format(jogo.name)
                )
            # Dispositivo que passou parte da sessão sem responder: a cor voltou sozinha quando ele voltou, mas
            # a luz faltou nesse meio-tempo.
            fora_do_ar = session_fita.fitas_fora_do_ar()
            if len(fora_do_ar) == 1:
                self._avisos.adicionar(
                    _("O dispositivo {} não respondeu durante parte da sessão.").format(fora_do_ar[0])
                )
            elif fora_do_ar:
                self._avisos.adicionar(_("Alguns dispositivos não responderam durante parte da sessão."))
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Não foi possível devolver as fitas de LED")

    def avisar(self, texto: str) -> None:
        self._avisos.adicionar(texto)

    def session_toast(self, game: Any, seconds: int) -> None:
        """O aviso do fim da sessão, com atalho para a anotação quando há onde anotar."""
        texto = _("{}: {} de jogo").format(game.name, format_playtime(seconds))
        if not pode_anotar(game):
            self._avisos.adicionar(texto)
        else:
            eu, jogo_id = weakref.ref(self), game.game_id

            def anotar() -> None:
                if (modelo := eu()) is not None:
                    modelo.anotarPedido.emit(jogo_id)

            self._avisos.adicionar(texto, _("Anotar"), anotar)
        # Por último: uma falha ao iniciar o backup não pode levar o aviso junto.
        try:
            backup_de_saves.no_fim_da_sessao(game)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("O backup dos saves de %s não chegou a começar", game.name)

    @Slot()
    def minimizar(self) -> None:
        """Sai da frente guardando o estado: o `showMinimized()` do Qt 6 derrubaria o Maximizado."""
        janela = self._janela
        if janela is not None:
            janela.setWindowStates(janela.windowStates() | Qt.WindowState.WindowMinimized)

    def present(self) -> None:
        """Traz a janela de volta sem desmaximizá-la."""
        janela = self._janela
        if janela is None:
            return
        janela.setWindowStates(janela.windowStates() & ~Qt.WindowState.WindowMinimized)
        if not janela.isVisible():  # fechada com a janela manual ainda aberta
            janela.setVisible(True)  # `show()` perderia a maximização
        janela.raise_()
        janela.requestActivate()

    def move_to_session_monitor(self) -> bool:
        """Leva a janela, maximizada, ao monitor da sessão. Diz se foi (senão quem chamou minimiza).

        Sem monitor além do principal a opção é desligada aqui e fica desligada: se um segundo
        monitor voltar, quem religa é o usuário, nas Preferências.
        """
        if self._janela is None or not shared.schema.get_boolean("session-move-window"):
            return False
        if not window_geometry.has_secondary_monitor():
            shared.schema.set_boolean("session-move-window", False)
            return False
        return window_geometry.move_to_monitor(self._janela, shared.schema.get_string("session-monitor"))

    def vibrar_abertura(self) -> None:
        if self._controle is not None:
            self._controle.vibrarAbertura()

    def session_elapsed(self) -> int:
        """Os segundos que a sessão em andamento já contou. Zero sem sessão."""
        if ProcessSession.active is not None:
            return ProcessSession.active.elapsed
        if SessionWindow.active is not None:
            return SessionWindow.active.elapsed
        return 0

    def abrir_janela_manual(self, manual: SessionWindow) -> None:
        self._manual = manual
        self.alterado.emit()

    @Slot()
    def terminar(self) -> None:
        """O botão da camada: encerra a sessão com registro, seja qual for o rastreador."""
        if SessionWindow.active is not None:
            SessionWindow.active.close()
        if ProcessSession.active is not None:
            ProcessSession.active.stop(record=True)

    @Slot(str)
    def gravarAnotacao(self, texto: str) -> None:  # noqa: N802
        """A anotação do balão da camada. Grava também num jogo zerado: só uma caixa não editável deixa de gravar, e a
        da camada nunca é.
        """
        jogo = self._anotando
        if jogo is None:
            return
        texto = texto.strip()
        if texto == (jogo.notes or ""):
            return
        jogo.notes = texto
        jogo.save()
        jogo.update()
        self._anotacao = texto
        self.alterado.emit()

    @Slot(QWindow)
    def posicionarJanelaManual(self, janela: QWindow) -> None:  # noqa: N802
        """Põe a janela "Jogando" acima do relógio. Qualquer falha a deixa onde está."""
        try:
            hwnd = int(janela.winId())
            esquerda, topo, direita, base = _retangulo_da_janela(hwnd)
            # 37 px visíveis até a área de trabalho (12 + a sombra de 25); o retângulo já soma 8 de moldura invisível. O
            # retângulo e a área vêm em px físicos: a margem (lógica) é escalada pela razão de pixels da tela da janela.
            margem = round(29 * janela.devicePixelRatio())
            x, y = canto_inferior_direito(_area_de_trabalho(), direita - esquerda, base - topo, margem=margem)
            _posicionar(hwnd, x, y)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Não foi possível posicionar a janela Jogando")

    @Slot()
    def principalFechando(self) -> None:  # noqa: N802
        """Fechar a principal com a janela manual ou o aviso de conquista na tela fecha o app.

        Sem isto a manual ou o aviso (janela de topo sem dono), que também são janelas, manteriam o app vivo. O
        `encerrar()` grava a sessão e tira o aviso, no `QEvent.Quit` (`AplicacaoQt.saindo`), antes de o Qt fechar as
        janelas.
        """
        if self._manual is not None or conquista_aviso.na_tela() is not None:
            # Na volta do laço, com a principal já fora da tela: um `quit()` aqui dentro do `closing` emitiria o
            # `aboutToQuit` (a parede e as fitas, que esperam) com ela ainda à vista, congelada.
            QTimer.singleShot(0, self._sair)

    @Slot()
    def janelaManualFechada(self) -> None:
        manual, self._manual = self._manual, None
        if manual is None:
            return
        self.alterado.emit()
        manual.close()

    @Slot()
    def encerrar(self) -> None:
        """O app fechando no meio da sessão: grava o tempo e o histórico, sem tocar na interface.

        Vem no `QEvent.Quit` (`AplicacaoQt.saindo`), antes de o Qt fechar as janelas: só o que é rápido e tem de
        vir antes delas. A janela "Jogando" fica desarmada, e o `closing` que o Qt manda a ela depois não roda o fim
        normal da sessão (nem grava outra linha no histórico); o vigia das conquistas para e o aviso sai da tela. A
        parede e as fitas, que podem demorar, ficam para o `devolver()`, com as janelas já fora da tela. Só a
        primeira chamada faz algo.
        """
        # A janela não volta ao monitor de antes aqui: a geometria gravada ao fechar é a de antes da sessão
        # (`window_geometry.session_geometry`).
        if self._encerrado:
            return
        # Só vai num sentido: um `quit()` cancelado deixaria a sessão encerrada. O `closing` da principal nunca recusa
        # depois do `saindo` (`PainelDasTarefas.encerrando`).
        self._encerrado = True
        self._tique.stop()
        self._manual = None  # sem `alterado`: a interface já está indo embora
        if (manual := SessionWindow.active) is not None:
            SessionWindow.active = None
            manual._fechada = True  # noqa: SLF001
            manual.timer.stop()
            manual.flush()
            session_log.record(manual.game.game_id, manual.session_seconds)
        if (processo := ProcessSession.active) is not None:
            ProcessSession.active = None
            processo._parar_timer()  # noqa: SLF001
            processo.flush()
            if processo.started:
                session_log.record(processo.game.game_id, processo.session_seconds)
        # Antes de a parede e as fitas voltarem (no `devolver`); sem a leitura final, que é só do fim normal da sessão.
        # Nunca levanta.
        sessao_conquistas.parar()
        conquista_aviso.fechar()  # fora da sessão (sem vigia) o aviso também sai; nunca levanta

    def devolver(self) -> None:
        """O `aboutToQuit`, depois do `big_picture.encerrar()`: a parede e as fitas voltam ao que eram.

        Grava antes, se o `saindo` não veio (o desligar do Windows emite o `aboutToQuit` antes do `quit()`).
        """
        try:
            self.encerrar()
        except Exception:
            # Uma falha ao gravar não deixa a parede trocada nem as fitas acesas.
            logging.getLogger(__name__).exception("Não foi possível gravar a sessão ao fechar o app")
        # Depois de gravar: é a última chance de desfazer a troca, sem processo para fazê-la depois.
        session_wallpaper.restaurar()
        # As fitas voltam ao que eram quando o app abriu. Aqui se espera (com prazo): depois disto não há processo
        # para desfazer nada, e o que não couber no prazo fica para o `abrir` do próximo arranque.
        session_fita.fechar()
