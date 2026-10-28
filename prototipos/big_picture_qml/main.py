"""Protótipo descartável do Big Picture em PySide6 + QML (passo 1 da migração, docs/TODO.md).

Lê a biblioteca real só para leitura (jogos e capas em %LOCALAPPDATA%) e mostra o
Cover Flow em tela cheia. Nada aqui é código do app: serve para decidir se o QML
dá conta do 3D, do reflexo, do controle, do segundo monitor e da escala 125%.

Uso:  .venv\\Scripts\\python main.py [--monitor N] [--multiplicar N] [--janela]
"""

import argparse
import ctypes
import json
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, QUrl, Signal, Slot, Property
from PySide6.QtTest import QTest
from PySide6.QtGui import QGuiApplication, QImage, QSurfaceFormat
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider

APP_DIR = Path(os.environ["LOCALAPPDATA"]) / "io.github.joaomgabaldi.Cartridges"
AQUI = Path(__file__).parent


# --- biblioteca (cópia de jogos_da_biblioteca, sem a restauração pendente) ---
def carregar_jogos(multiplicar: int) -> list[dict]:
    capas = {p.stem: p for p in (APP_DIR / "covers").iterdir()}
    jogos = []
    for arquivo in (APP_DIR / "games").glob("*.json"):
        try:
            j = json.loads(arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if j.get("blacklisted") or j.get("removed") or "game_id" not in j:
            continue
        capa = capas.get(j["game_id"])
        jogos.append(
            {
                "nome": j.get("name", ""),
                "desenvolvedora": (j.get("developer") or "").strip(),
                "capa": QUrl.fromLocalFile(str(capa)).toString() if capa else "",
                "ultimo": j.get("last_played", 0),
            }
        )
    jogos.sort(key=lambda j: j["nome"].casefold())
    jogos.sort(key=lambda j: j["ultimo"], reverse=True)
    # Cada cópia com um endereço próprio: o cache de imagens do Qt não as
    # reaproveita, então o teste decodifica e guarda capas distintas de verdade.
    return [
        {**j, "capa": f"{j['capa']}?copia={k}" if j["capa"] and k else j["capa"]}
        for k in range(multiplicar)
        for j in jogos
    ]


# --- fundo (cópia de big_picture.bytes_do_fundo) ---
FUNDO_TOPO = (28, 28, 30)
FUNDO_EXPOENTE = 1.6
_BAYER_8 = (
    (0, 32, 8, 40, 2, 34, 10, 42),
    (48, 16, 56, 24, 50, 18, 58, 26),
    (12, 44, 4, 36, 14, 46, 6, 38),
    (60, 28, 52, 20, 62, 30, 54, 22),
    (3, 35, 11, 43, 1, 33, 9, 41),
    (51, 19, 59, 27, 49, 17, 57, 25),
    (15, 47, 7, 39, 13, 45, 5, 37),
    (63, 31, 55, 23, 61, 29, 53, 21),
)
_LIMIARES = tuple(tuple((v + 0.5) / 64 for v in linha) for linha in _BAYER_8)


def bytes_do_fundo(largura: int, altura: int) -> bytes:
    repeticoes = -(-largura // 8)
    linhas = []
    for y in range(altura):
        k = (1 - y / (altura - 1)) ** FUNDO_EXPOENTE if altura > 1 else 1.0
        limiares = _LIMIARES[y % 8]
        exatos = [c * k for c in FUNDO_TOPO]
        base = [int(e) for e in exatos]
        fracao = [e - b for e, b in zip(exatos, base)]
        padrao = bytes(
            b + (f > limiar) for limiar in limiares for b, f in zip(base, fracao)
        )
        linhas.append((padrao * repeticoes)[: largura * 3])
    return b"".join(linhas)


class Fundo(QQuickImageProvider):
    """`image://fundo/LxA`: o degradê pontilhado no tamanho em pixels reais."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id_, size, requested):
        largura, altura = (max(1, int(v)) for v in id_.split("x"))
        t = time.monotonic()
        dados = bytes_do_fundo(largura, altura)  # vivo até o .copy(): o QImage não copia
        print(f"fundo {largura}x{altura} em {time.monotonic() - t:.2f}s")
        imagem = QImage(dados, largura, altura, largura * 3, QImage.Format.Format_RGB888)
        size.setWidth(largura)
        size.setHeight(altura)
        return imagem.copy()


# --- controle XInput (estruturas e calibração de cartridges/gamepad.py) ---
class XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XInputGamepad)]


class XInputVibration(ctypes.Structure):
    _fields_ = [("wLeftMotorSpeed", wintypes.WORD), ("wRightMotorSpeed", wintypes.WORD)]


DPAD_LEFT, DPAD_RIGHT = 0x0004, 0x0008
BOTAO_LB, BOTAO_RB, BOTAO_A, BOTAO_B = 0x0100, 0x0200, 0x1000, 0x2000
THUMB_PRESS, THUMB_RELEASE = 16_000, 10_000
REPEAT_DELAY_S = 0.4
INTERVALO_NORMAL_S, ACELERAR_APOS_S, INTERVALO_ACELERADO_S = 0.12, 1.0, 0.04
RUMBLE_CAPA = (0.5, 1.0, 90)
RUMBLE_PULO = (0.0, 0.35, 25)


class Controle(QObject):
    """Lê o primeiro controle XInput a 30 Hz e emite comandos para o QML."""

    mover = Signal(int)
    abrir = Signal()
    sair = Signal()

    def __init__(self) -> None:
        super().__init__()
        try:
            self._xi = ctypes.WinDLL("xinput1_4.dll")
        except OSError:
            self._xi = None
        self._botoes = 0
        self._direcao = 0  # -1, 0, 1 (cruz ou analógico)
        self._desde = 0.0
        self._proximo = 0.0
        self._fim_vibracao = QTimer(singleShot=True, timeout=lambda: self._vibrar(0, 0))
        self._timer = QTimer(interval=33, timeout=self._ler)
        if self._xi:
            self._timer.start()

    def _vibrar(self, esquerdo: float, direito: float, ms: int = 0) -> None:
        v = XInputVibration(int(esquerdo * 65535), int(direito * 65535))
        self._xi.XInputSetState(0, ctypes.byref(v))
        if ms:
            self._fim_vibracao.start(ms)

    def parar(self) -> None:
        if self._xi:
            self._timer.stop()
            self._vibrar(0, 0)

    @Slot(int)
    def tremer(self, delta: int) -> None:
        if self._xi:
            self._vibrar(*(RUMBLE_PULO if abs(delta) > 1 else RUMBLE_CAPA))

    def _ler(self) -> None:
        estado = XInputState()
        if self._xi.XInputGetState(0, ctypes.byref(estado)) != 0:
            return
        g = estado.Gamepad
        apertados = g.wButtons & ~self._botoes
        self._botoes = g.wButtons
        if apertados & BOTAO_A:
            self.abrir.emit()
        if apertados & BOTAO_B:
            self.sair.emit()
        if apertados & BOTAO_LB:
            self.mover.emit(-10)
        if apertados & BOTAO_RB:
            self.mover.emit(10)

        lx = g.sThumbLX
        limite = THUMB_RELEASE if self._direcao else THUMB_PRESS
        direcao = (
            -1 if g.wButtons & DPAD_LEFT or lx < -limite
            else 1 if g.wButtons & DPAD_RIGHT or lx > limite
            else 0
        )
        agora = time.monotonic()
        if direcao != self._direcao:
            self._direcao, self._desde = direcao, agora
            if direcao:
                self.mover.emit(direcao)
                self._proximo = agora + REPEAT_DELAY_S
        elif direcao and agora >= self._proximo:
            segurando = agora - self._desde
            self.mover.emit(direcao)
            self._proximo = agora + (
                INTERVALO_ACELERADO_S if segurando >= ACELERAR_APOS_S else INTERVALO_NORMAL_S
            )


class Medidor(QObject):
    """Quadros por segundo da janela (para a sobreposição de diagnóstico, tecla F)."""

    mudou = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._quadros = 0
        self._fps = 0
        self._timer = QTimer(interval=1000, timeout=self._fechar_segundo)
        self._timer.start()

    def contar(self) -> None:
        self._quadros += 1  # vem da thread de renderização; um int basta

    def _fechar_segundo(self) -> None:
        self._fps, self._quadros = self._quadros, 0
        self.mudou.emit()

    fps = Property(int, lambda self: self._fps, notify=mudou)


def main() -> int:
    argumentos = argparse.ArgumentParser()
    argumentos.add_argument("--monitor", type=int, default=0)
    argumentos.add_argument("--multiplicar", type=int, default=1)
    argumentos.add_argument("--janela", action="store_true", help="sem tela cheia")
    argumentos.add_argument("--captura", help="pasta: grava quadros de um roteiro e fecha")
    argumentos.add_argument("--medir", action="store_true", help="anda sozinho e imprime os fps")
    opcoes = argumentos.parse_args()

    if opcoes.medir:
        # Sem sincronia vertical: os fps mostram a folga, não o teto de 60.
        formato = QSurfaceFormat.defaultFormat()
        formato.setSwapInterval(0)
        QSurfaceFormat.setDefaultFormat(formato)
    app = QGuiApplication(sys.argv)
    controle = Controle()
    app.aboutToQuit.connect(controle.parar)
    medidor = Medidor()
    motor = QQmlApplicationEngine()
    motor.addImageProvider("fundo", Fundo())
    contexto = motor.rootContext()
    contexto.setContextProperty("jogosDaBiblioteca", carregar_jogos(opcoes.multiplicar))
    contexto.setContextProperty("controle", controle)
    contexto.setContextProperty("medidor", medidor)
    contexto.setContextProperty("diagnosticoInicial", bool(opcoes.captura))
    motor.load(QUrl.fromLocalFile(str(AQUI / "BigPicture.qml")))
    if not motor.rootObjects():
        return 1
    janela = motor.rootObjects()[0]
    janela.frameSwapped.connect(medidor.contar, Qt.ConnectionType.DirectConnection)

    telas = app.screens()
    tela = telas[min(opcoes.monitor, len(telas) - 1)]
    for i, t in enumerate(telas):
        print(f"monitor {i}: {t.name()} {t.geometry().getRect()} escala {t.devicePixelRatio()}")
    janela.setScreen(tela)
    janela.setGeometry(tela.availableGeometry().adjusted(80, 80, -80, -80))
    if opcoes.janela:
        janela.show()
    else:
        janela.showFullScreen()
    print("renderizador:", janela.rendererInterface().graphicsApi())
    if opcoes.captura:
        roteiro(janela, controle, Path(opcoes.captura))
    if opcoes.medir:
        medir(controle, medidor)
    return app.exec()


def medir(controle: Controle, medidor: Medidor) -> None:
    """Anda sem parar (ritmo do direcional segurado e saltos de 10) e imprime os fps."""
    passos = [1] * 40 + [-1] * 40 + [10, 10, 10, -10, -10, -10] * 4 + [10] * 110
    ritmo = QTimer(interval=120)
    ritmo.timeout.connect(lambda: controle.mover.emit(passos.pop(0)) if passos else QGuiApplication.quit())
    medidor.mudou.connect(lambda: print("fps", medidor.fps))
    QTimer.singleShot(2500, ritmo.start)  # depois da fila
    medidor._ritmo = ritmo  # mantém vivo


def roteiro(janela, controle: Controle, pasta: Path) -> None:
    """Para testar sem ver a tela: anda pelo carrossel e grava quadros."""
    pasta.mkdir(parents=True, exist_ok=True)
    inicio = time.monotonic()

    def capturar(nome: str) -> None:
        janela.grabWindow().save(str(pasta / f"{nome}.png"))
        print(
            f"{time.monotonic() - inicio:5.2f}s {nome}: indice {janela.property('indice')}"
            f" posicao {janela.property('posicao'):.2f}"
        )

    def clicar(x: int, y: int, esperado: int) -> None:
        QTest.mouseClick(janela, Qt.MouseButton.LeftButton, pos=QPoint(x, y))
        QTimer.singleShot(50, lambda: print(f"clique em ({x}, {y}): indice {janela.property('indice')}, esperado {esperado}"))

    # Cada passo espera o anterior: um bloqueio da interface não embaralha a ordem.
    passos = [
        (800, lambda: capturar("1-fila-entrando")),
        (1700, lambda: capturar("2-repouso")),
        (0, lambda: controle.mover.emit(3)),
        (170, lambda: capturar("3-meio-do-passo")),
        (600, lambda: capturar("4-depois-do-passo")),
        (0, lambda: controle.mover.emit(-10)),
        (600, lambda: capturar("5-inicio")),
        # Bordas da capa 1 (de 1217 a 1476 px em 1080p) e logo depois dela (capa 2).
        (0, lambda: clicar(1466, 430, 1)),
        (500, lambda: controle.mover.emit(-10)),
        (500, lambda: clicar(1225, 600, 1)),
        (500, lambda: controle.mover.emit(-10)),
        (500, lambda: clicar(1490, 430, 2)),
        (500, lambda: controle.mover.emit(-10)),
        (0, controle.abrir.emit),
        (250, lambda: capturar("6-abrindo")),
        (1500, QGuiApplication.quit),
    ]

    def seguir() -> None:
        espera, acao = passos.pop(0)
        QTimer.singleShot(espera, lambda: (acao(), passos and seguir()))

    QTimer.singleShot(0, seguir)


if __name__ == "__main__":
    sys.exit(main())
