# controle.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox na grade: lê o XInput e entrega sinais que o QML liga à interface."""

import weakref
from collections.abc import Callable

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent, QWindow

from cartridges import shared
from cartridges.xinput import (
    POLL_INTERVAL_MS,
    REPEAT_DELAY_US,
    REPEAT_INTERVAL_US,
    RUMBLE_CAPA,
    RUMBLE_EDGE,
    RUMBLE_LAUNCH,
    RUMBLE_MOVE,
    RUMBLE_PULO,
    THUMB_PRESS,
    THUMB_RELEASE,
    THUMB_WAKE,
    XINPUT_A,
    XINPUT_B,
    XINPUT_BACK,
    XINPUT_DPAD_DOWN,
    XINPUT_DPAD_LEFT,
    XINPUT_DPAD_RIGHT,
    XINPUT_DPAD_UP,
    XINPUT_LEFT_SHOULDER,
    XINPUT_RIGHT_SHOULDER,
    XINPUT_START,
    XINPUT_Y,
    LeitorXInput,
    agora_us,
    intervalo_de_repeticao_us,
)

Direcao = tuple[int, int]


def _estado_do_app() -> Qt.ApplicationState:
    return QGuiApplication.applicationState()


class ControleDaGrade(QObject):
    mover = Signal(int, int)
    ativar = Signal()
    voltar = Signal()
    menuPrincipal = Signal()  # Start  # noqa: N815
    menuDoJogo = Signal()  # Y  # noqa: N815
    buscar = Signal()
    usado = Signal()
    presente = Signal()
    pular = Signal(int)
    conectado = Signal()
    modoBigPictureMudou = Signal()  # noqa: N815

    def __init__(
        self,
        fabrica_do_leitor: Callable[[], LeitorXInput] = LeitorXInput,
        estado_do_app: Callable[[], Qt.ApplicationState] = _estado_do_app,
        relogio: Callable[[], int] = agora_us,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._fabrica = fabrica_do_leitor
        self._estado_do_app = estado_do_app
        self._relogio = relogio
        self._leitor = None
        self._timer = QTimer(self)
        self._timer.setInterval(POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._ler)
        self._botoes = 0
        self._modo_big_picture = False
        self._sem_controle = True
        self._janela: QWindow | None = None
        self._ultimo_toque_capa_us: int | None = None
        self._ajustar_base()
        self._geracao_de_vibracao = 0
        # Durante uma sessão o controle é do jogo: nada lê, e a DLL sai depois da vibração de abertura.
        self._suspenso = False
        self._soltura = QTimer(self, singleShot=True, interval=RUMBLE_LAUNCH[2] + 60)
        self._soltura.timeout.connect(self._soltar)
        eu = weakref.ref(self)
        shared.schema.connect("changed::gamepad", lambda *_: (c := eu()) and c.sincronizar())
        QGuiApplication.instance().applicationStateChanged.connect(lambda *_: (c := eu()) and c.sincronizar())
        self.sincronizar()

    @Property(bool, notify=modoBigPictureMudou)
    def modoBigPicture(self) -> bool:  # noqa: N802
        return self._modo_big_picture

    @modoBigPicture.setter
    def modoBigPicture(self, valor: bool) -> None:  # noqa: N802
        if valor != self._modo_big_picture:
            self._modo_big_picture = valor
            self.modoBigPictureMudou.emit()

    @property
    def lendo(self) -> bool:
        return self._timer.isActive()

    def _ajustar_base(self) -> None:
        self._ressincronizar = True
        self._engajado = False
        self._direcao: Direcao | None = None
        self._desde = 0
        self._repeticoes = 0
        self._ultimo_passo = 0
        self._travada = False

    def definir_janela(self, janela: QWindow) -> None:
        self._janela = janela
        janela.activeChanged.connect(self.sincronizar)
        self.sincronizar()

    @Slot()
    def sincronizar(self) -> None:
        if self._janela is not None:
            ativa = self._janela.isActive()
        else:
            ativa = self._estado_do_app() == Qt.ApplicationState.ApplicationActive
        desejado = not self._suspenso and ativa and shared.schema.get_boolean("gamepad")
        if desejado and not self._timer.isActive():
            if self._leitor is None:
                leitor = self._fabrica()
                if not leitor.disponivel:
                    return
                self._leitor = leitor
            self._ajustar_base()
            self._timer.start()
        elif not desejado and self._timer.isActive():
            # Só para de ler.
            self._timer.stop()
            self._direcao = None

    @Slot()
    def suspender(self) -> None:
        if self._suspenso:
            return
        self._suspenso = True
        self._timer.stop()
        self._direcao = None
        self._soltura.start()

    def _soltar(self) -> None:
        if not self._suspenso or self._leitor is None:
            return  # retomado dentro do prazo: a DLL carregada fica
        self._leitor.vibrar()  # os motores parados antes de a DLL sair
        self._leitor.soltar()
        self._leitor = None
        self._sem_controle = False

    @Slot()
    def retomar(self) -> None:
        if not self._suspenso:
            return
        self._suspenso = False
        self._soltura.stop()
        self.sincronizar()

    @Slot()
    def vibrarAbertura(self) -> None:  # noqa: N802
        self._vibrar(RUMBLE_LAUNCH)

    def _ler(self) -> None:
        pad = self._leitor.ler()
        if pad is None:
            self._sem_controle = True
            self._ajustar_base()
            return
        if self._ressincronizar:
            self._ressincronizar = False
            self._botoes = pad.wButtons
            self._direcao = self._direcao_de(pad)
            self._travada = self._direcao is not None
            self._desde = self._relogio()
            self._repeticoes = 0
            self._ultimo_passo = self._desde
            self.presente.emit()
            if self._sem_controle:
                self._sem_controle = False
                self.conectado.emit()
            return
        self._tratar_direcao(pad)
        self._tratar_botoes(pad)

    def _direcao_de(self, pad) -> Direcao | None:
        botoes = pad.wButtons
        if botoes & XINPUT_DPAD_UP:
            return (0, -1)
        if botoes & XINPUT_DPAD_DOWN:
            return (0, 1)
        if botoes & XINPUT_DPAD_LEFT:
            return (-1, 0)
        if botoes & XINPUT_DPAD_RIGHT:
            return (1, 0)
        # O analógico dorme até o controle ser acordado: a deriva da conexão não pode mover a seleção.
        if not self._engajado:
            if abs(pad.sThumbLX) >= THUMB_WAKE or abs(pad.sThumbLY) >= THUMB_WAKE:
                self._engajado = True
            else:
                return None
        limite = THUMB_RELEASE if self._direcao is not None else THUMB_PRESS
        x, y = pad.sThumbLX, pad.sThumbLY
        if abs(x) > abs(y):
            if x > limite:
                return (1, 0)
            if x < -limite:
                return (-1, 0)
        elif y > limite:
            return (0, -1)
        elif y < -limite:
            return (0, 1)
        return None

    def _tratar_direcao(self, pad) -> None:
        direcao = self._direcao_de(pad)
        agora = self._relogio()
        if direcao != self._direcao:
            self._direcao = direcao
            self._desde = self._ultimo_passo = agora
            self._repeticoes = 0
            self._travada = False
            if direcao is not None:
                self._mover(direcao)
            return
        if direcao is None or self._travada:
            return
        if self._modo_big_picture:
            if self._repeticoes == 0:
                devido = agora - self._desde >= REPEAT_DELAY_US
            else:
                devido = agora - self._ultimo_passo >= intervalo_de_repeticao_us(agora - self._desde)
        else:
            devido = agora - self._desde >= REPEAT_DELAY_US + REPEAT_INTERVAL_US * self._repeticoes
        if devido:
            self._repeticoes += 1
            self._ultimo_passo = agora
            self._mover(direcao)

    def _mover(self, direcao: Direcao) -> None:
        self.usado.emit()
        self.mover.emit(*direcao)

    def _tratar_botoes(self, pad) -> None:
        apertados = pad.wButtons & ~self._botoes
        self._botoes = pad.wButtons
        if not apertados:
            return
        self._engajado = True
        self.usado.emit()
        if self._modo_big_picture:
            apertados &= XINPUT_A | XINPUT_B | XINPUT_LEFT_SHOULDER | XINPUT_RIGHT_SHOULDER
        if apertados & XINPUT_A:
            self.ativar.emit()
        elif apertados & XINPUT_B:
            self.voltar.emit()
        elif apertados & XINPUT_START:
            self.menuPrincipal.emit()
        elif apertados & XINPUT_Y:
            self.menuDoJogo.emit()
        elif apertados & XINPUT_BACK:
            self.buscar.emit()
        elif apertados & (XINPUT_LEFT_SHOULDER | XINPUT_RIGHT_SHOULDER):
            self.pular.emit(-10 if apertados & XINPUT_LEFT_SHOULDER else 10)

    @Slot(int)
    def teclar(self, tecla: int) -> None:
        janela = QGuiApplication.focusWindow()
        if janela is None:
            return
        for tipo in (QKeyEvent.Type.KeyPress, QKeyEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(janela, QKeyEvent(tipo, tecla, Qt.KeyboardModifier.NoModifier))

    @Slot()
    def encerrar(self) -> None:
        self._timer.stop()
        self._soltura.stop()
        self._geracao_de_vibracao += 1
        if self._leitor is not None:
            self._leitor.vibrar()

    @Slot()
    def bater(self) -> None:
        self._vibrar(RUMBLE_EDGE)

    @Slot()
    def passar(self) -> None:
        self._vibrar(RUMBLE_MOVE)

    @Slot()
    def trocarCapa(self) -> None:  # noqa: N802
        """A capa central mudou no Big Picture; no máximo um toque por duração + 60 ms, para ficarem distintos."""
        agora = self._relogio()
        if self._ultimo_toque_capa_us is not None and agora - self._ultimo_toque_capa_us < (RUMBLE_CAPA[2] + 60) * 1000:
            return
        if self._vibrar(RUMBLE_CAPA):
            self._ultimo_toque_capa_us = agora

    @Slot()
    def saltar(self) -> None:
        self._vibrar(RUMBLE_PULO)

    def _vibrar(self, preset: tuple[float, float, int]) -> bool:
        if self._leitor is None or not shared.schema.get_boolean("gamepad-rumble"):
            return False
        esquerdo, direito, duracao_ms = preset
        self._leitor.vibrar(esquerdo, direito)
        self._geracao_de_vibracao += 1
        geracao = self._geracao_de_vibracao
        eu = weakref.ref(self)

        def parar() -> None:
            controle = eu()
            if controle is not None and controle._leitor is not None and geracao == controle._geracao_de_vibracao:
                controle._leitor.vibrar()

        QTimer.singleShot(duracao_ms, parar)
        return True
