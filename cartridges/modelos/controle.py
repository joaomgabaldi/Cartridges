# controle.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox na grade: lê o XInput e entrega sinais que o QML liga à interface.

Só lê com a janela ativa e a preferência `gamepad` ligada. A DLL continua carregada e só é solta durante uma sessão de jogo
(`suspender`), para o jogo ficar com o controle. Tudo na thread principal.
"""

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

Direcao = tuple[int, int]  # (dx, dy), com y para baixo


def _estado_do_app() -> Qt.ApplicationState:
    return QGuiApplication.applicationState()


class ControleDaGrade(QObject):
    mover = Signal(int, int)
    ativar = Signal()
    voltar = Signal()
    menuPrincipal = Signal()  # Start  # noqa: N815
    menuDoJogo = Signal()  # Y  # noqa: N815
    buscar = Signal()
    usado = Signal()  # qualquer comando: o QML esconde o ponteiro do mouse
    presente = Signal()  # um controle apareceu (ou o foco voltou): o QML acende a seleção
    pular = Signal(int)  # LB (-10) e RB (+10): só o Big Picture usa
    conectado = Signal()  # um controle lido depois de uma leitura sem controle, ou o primeiro; não o foco de volta
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
        self._sem_controle = True  # a última leitura (ou o início) não tinha controle: o próximo é uma conexão
        self._janela: QWindow | None = None  # a principal: só ela dá o controle
        self._ultimo_toque_capa_us: int | None = None
        self._ajustar_base()
        self._geracao_de_vibracao = 0
        # Durante uma sessão o controle é do jogo: nada lê, e a DLL sai depois da vibração de abertura.
        self._suspenso = self._com_foco = False
        self._soltura = QTimer(self, singleShot=True, interval=RUMBLE_LAUNCH[2] + 60)
        self._soltura.timeout.connect(self._soltar)
        eu = weakref.ref(self)
        shared.schema.connect("changed::gamepad", lambda *_: (c := eu()) and c.sincronizar())
        QGuiApplication.instance().applicationStateChanged.connect(lambda *_: (c := eu()) and c.sincronizar())
        self.sincronizar()

    @Property(bool, notify=modoBigPictureMudou)
    def modoBigPicture(self) -> bool:  # noqa: N802
        """Com o Big Picture à vista a repetição do direcional acelera; sem ele, a da grade não muda."""
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
        """O que já estava pressionado ao voltar o foco é a base, não um comando novo."""
        self._ressincronizar = True
        self._engajado = False
        self._direcao: Direcao | None = None
        self._desde = 0
        self._repeticoes = 0
        self._ultimo_passo = 0
        self._travada = False

    def definir_janela(self, janela: QWindow) -> None:
        """A janela principal: com Tarefas, Login ou o assistente em foco, o controle não mexe na grade de trás."""
        self._janela = janela
        janela.activeChanged.connect(self.sincronizar)
        self.sincronizar()

    @Slot()
    def sincronizar(self) -> None:
        if self._janela is not None:
            ativa = self._janela.isActive()
        else:
            ativa = self._estado_do_app() == Qt.ApplicationState.ApplicationActive
        desejado = (not self._suspenso or self._com_foco) and ativa and shared.schema.get_boolean("gamepad")
        if desejado and not self._timer.isActive():
            if self._leitor is None:
                leitor = self._fabrica()
                if not leitor.disponivel:
                    return
                self._leitor = leitor
            self._ajustar_base()
            self._timer.start()
        elif not desejado and self._timer.isActive():
            # Só para de ler. A vibração em curso termina sozinha e a DLL fica carregada.
            self._timer.stop()
            self._direcao = None

    @Slot()
    def suspender(self, com_foco: bool = False) -> None:
        """Entrega o controle ao jogo da sessão: para de ler na hora e solta a DLL depois do prazo da vibração de abertura
        (soltar antes deixaria os motores ligados: o desligamento agendado dela não acharia a DLL).
        Com `com_foco` (sessão no Big Picture) o Kyron lê enquanto a janela está ativa; sem foco, o jogo fica com o controle.
        """
        if self._suspenso:
            return
        self._suspenso, self._com_foco = True, com_foco
        self._direcao = None
        self._soltura.start()
        if com_foco:
            self.sincronizar()  # janela ativa: segue lendo; inativa: para
        else:
            self._timer.stop()

    def _soltar(self) -> None:
        if not self._suspenso or self._leitor is None or self._timer.isActive():
            return  # retomado dentro do prazo, ou lendo com o Kyron em foco: a DLL carregada fica
        self._leitor.vibrar()  # os motores parados antes de a DLL sair
        self._leitor.soltar()
        self._leitor = None
        # Redescoberta: o controle que estava aí ao voltar não é uma conexão nova; só uma leitura sem controle rearma o `conectado`.
        self._sem_controle = False

    @Slot()
    def retomar(self) -> None:
        """A sessão acabou: a leitura volta (com a DLL recarregada pela fábrica, se saiu) e a base é refeita."""
        if not self._suspenso:
            return
        self._suspenso = self._com_foco = False
        self._soltura.stop()
        if self._timer.isActive():
            self._ajustar_base()  # já lia (sessão no Big Picture): o que apertaram no jogo não é comando
        self.sincronizar()  # o que o controle fez durante o jogo não é comando: a base vem do `_ajustar_base`

    @Slot()
    def vibrarAbertura(self) -> None:  # noqa: N802
        """Um jogo iniciando: a vibração mais longa, com a preferência `gamepad-rumble`."""
        self._vibrar(RUMBLE_LAUNCH)

    def _ler(self) -> None:
        pad = self._leitor.ler()
        if pad is None:
            # Sem controle: o próximo é uma conexão nova, com base refeita e analógico dormindo.
            self._sem_controle = True
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
            self._ultimo_passo = self._desde
            self.presente.emit()
            if self._sem_controle:
                self._sem_controle = False
                self.conectado.emit()
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
            self._desde = self._ultimo_passo = agora
            self._repeticoes = 0
            self._travada = False
            if direcao is not None:
                self._mover(direcao)
            return
        if direcao is None or self._travada:
            return
        if self._modo_big_picture:
            # A primeira repetição espera o atraso; as outras aceleram quanto mais tempo se segura.
            if self._repeticoes == 0:
                devido = agora - self._desde >= REPEAT_DELAY_US
            else:
                devido = agora - self._ultimo_passo >= intervalo_de_repeticao_us(agora - self._desde)
        else:
            # A primeira repetição espera o atraso; as outras vêm em ritmo constante.
            devido = agora - self._desde >= REPEAT_DELAY_US + REPEAT_INTERVAL_US * self._repeticoes
        if devido:
            self._repeticoes += 1
            self._ultimo_passo = agora
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
        if self._modo_big_picture:
            # No Big Picture só valem A, B e os ombros: outro botão na mesma leitura não anula o salto.
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
        """Entrega uma tecla ao item em foco da janela: é assim que o controle navega menus e diálogos."""
        janela = QGuiApplication.focusWindow()
        if janela is None:
            return
        for tipo in (QKeyEvent.Type.KeyPress, QKeyEvent.Type.KeyRelease):
            QGuiApplication.sendEvent(janela, QKeyEvent(tipo, tecla, Qt.KeyboardModifier.NoModifier))

    @Slot()
    def encerrar(self) -> None:
        """O app fecha: para a leitura e os motores; uma vibração em curso não sobrevive."""
        self._timer.stop()
        self._soltura.stop()
        self._geracao_de_vibracao += 1  # o desligamento agendado de uma vibração antiga não vale mais
        if self._leitor is not None:
            self._leitor.vibrar()

    @Slot()
    def bater(self) -> None:
        """Não há para onde ir: o toque firme da borda."""
        self._vibrar(RUMBLE_EDGE)

    @Slot()
    def passar(self) -> None:
        """Um cartão atravessado: o tique leve."""
        self._vibrar(RUMBLE_MOVE)

    @Slot()
    def trocarCapa(self) -> None:  # noqa: N802
        """A capa central mudou no Big Picture; no máximo um toque por duração + 60 ms."""
        agora = self._relogio()
        if self._ultimo_toque_capa_us is not None and agora - self._ultimo_toque_capa_us < (RUMBLE_CAPA[2] + 60) * 1000:
            return
        if self._vibrar(RUMBLE_CAPA):  # um toque que não vibrou não ocupa a vez do próximo
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
            # Uma vibração mais nova é dona do próprio desligamento.
            controle = eu()
            if controle is not None and controle._leitor is not None and geracao == controle._geracao_de_vibracao:
                controle._leitor.vibrar()

        QTimer.singleShot(duracao_ms, parar)
        return True
