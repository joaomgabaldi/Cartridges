# controle.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox na grade: lê o XInput e entrega sinais que o QML liga à interface.

Só lê enquanto a janela está ativa e a preferência `gamepad` está ligada; com a janela inativa o
`QTimer` para e a DLL é solta (um jogo aberto fica com o controle só para ele). Tudo roda na
thread principal. A lógica de direção e botões é a do `gamepad.py` da `main`.
"""

import weakref
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QKeyEvent

from cartridges import shared
from cartridges.xinput import (
    POLL_INTERVAL_MS,
    REPEAT_DELAY_US,
    REPEAT_INTERVAL_US,
    RUMBLE_EDGE,
    RUMBLE_MOVE,
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
    XINPUT_START,
    XINPUT_Y,
    LeitorXInput,
    agora_us,
)

Direcao = tuple[int, int]  # (dx, dy), com y para baixo


def _estado_do_app() -> Qt.ApplicationState:
    return QGuiApplication.applicationState()


class ControleDaGrade(QObject):
    mover = Signal(int, int)
    ativar = Signal()  # A
    voltar = Signal()  # B
    menuPrincipal = Signal()  # Start  # noqa: N815
    menuDoJogo = Signal()  # Y  # noqa: N815
    buscar = Signal()  # Back
    usado = Signal()  # qualquer comando: o QML esconde o ponteiro do mouse
    presente = Signal()  # um controle apareceu (ou o foco voltou): o QML acende a seleção

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
        self._ajustar_base()
        self._geracao_de_vibracao = 0
        # shortcut: sem suspender/retomar enquanto um jogo é rastreado (sessões, plano 5) nem entrada automática no Big Picture ao conectar (plano 4).
        eu = weakref.ref(self)
        shared.schema.connect("changed::gamepad", lambda *_: (c := eu()) and c.sincronizar())
        QGuiApplication.instance().applicationStateChanged.connect(lambda *_: (c := eu()) and c.sincronizar())
        self.sincronizar()

    @property
    def lendo(self) -> bool:
        return self._timer.isActive()

    def _ajustar_base(self) -> None:
        """O que já estava pressionado ao voltar o foco é a base, não um comando novo."""
        self._ressincronizar = True
        self._engajado = False
        self._direcao: Direcao | None = None
        self._desde = 0
        self._repeticoes = 0
        self._travada = False

    @Slot()
    def sincronizar(self) -> None:
        ativa = self._estado_do_app() == Qt.ApplicationState.ApplicationActive
        desejado = ativa and shared.schema.get_boolean("gamepad")
        if desejado and not self._timer.isActive():
            if self._leitor is None:
                leitor = self._fabrica()
                if not leitor.disponivel:
                    return
                self._leitor = leitor
            self._ajustar_base()
            self._timer.start()
        elif not desejado and self._timer.isActive():
            # Só para de ler. A vibração em curso termina sozinha e a DLL fica carregada, como na `main`.
            # shortcut: a DLL só é solta durante uma sessão de jogo (`LeitorXInput.soltar`); entra com as sessões, no plano 5.
            self._timer.stop()
            self._direcao = None

    # Leitura ----------------------------------------------------------------

    def _ler(self) -> None:
        pad = self._leitor.ler()
        if pad is None:
            # Sem controle: o próximo é uma conexão nova, com base refeita e analógico dormindo.
            self._ajustar_base()
            return
        if self._ressincronizar:
            self._ressincronizar = False
            self._botoes = pad.wButtons
            self._direcao = self._direcao_de(pad)
            # Direcional já segurado ao voltar o foco não repete sozinho: fica travado até soltar.
            self._travada = self._direcao is not None
            self._desde = self._relogio()
            self._repeticoes = 0
            self.presente.emit()
            return
        self._tratar_direcao(pad)
        self._tratar_botoes(pad)

    def _direcao_de(self, pad) -> Direcao | None:
        """O direcional vence o analógico; o analógico escolhe o eixo dominante."""
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
            self._desde = agora
            self._repeticoes = 0
            self._travada = False
            if direcao is not None:
                self._mover(direcao)
            return
        if direcao is None or self._travada:
            return
        # A primeira repetição espera o atraso; as outras vêm em ritmo constante.
        if agora - self._desde >= REPEAT_DELAY_US + REPEAT_INTERVAL_US * self._repeticoes:
            self._repeticoes += 1
            self._mover(direcao)

    def _mover(self, direcao: Direcao) -> None:
        self.usado.emit()
        self.mover.emit(*direcao)

    def _tratar_botoes(self, pad) -> None:
        apertados = pad.wButtons & ~self._botoes  # só a borda de subida
        self._botoes = pad.wButtons
        if not apertados:
            return
        self._engajado = True
        self.usado.emit()
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

    @Slot(int)
    def teclar(self, tecla: int) -> None:
        """Entrega uma tecla ao item em foco da janela: é assim que o controle navega menus e diálogos."""
        janela = QGuiApplication.focusWindow()
        if janela is None:
            return
        for tipo in (QKeyEvent.Type.KeyPress, QKeyEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(janela, QKeyEvent(tipo, tecla, Qt.KeyboardModifier.NoModifier))

    # Vibração ---------------------------------------------------------------

    @Slot()
    def bater(self) -> None:
        """Não há para onde ir: o toque firme da borda."""
        self._vibrar(RUMBLE_EDGE)

    @Slot()
    def passar(self) -> None:
        """Um cartão atravessado: o tique leve."""
        self._vibrar(RUMBLE_MOVE)

    def _vibrar(self, preset: tuple[float, float, int]) -> None:
        if self._leitor is None or not shared.schema.get_boolean("gamepad-rumble"):
            return
        esquerdo, direito, duracao_ms = preset
        self._leitor.vibrar(esquerdo, direito)
        self._geracao_de_vibracao += 1
        geracao = self._geracao_de_vibracao
        eu = weakref.ref(self)

        def parar() -> None:
            # Uma vibração mais nova é dona do próprio desligamento.
            controle = eu()
            if controle is not None and controle._leitor is not None and geracao == controle._geracao_de_vibracao:
                controle._leitor.vibrar()

        QTimer.singleShot(duracao_ms, parar)
