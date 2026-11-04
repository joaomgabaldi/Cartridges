"""Protótipo descartável da janela sem moldura com o QWindowKit (passo 2 da migração, docs/TODO.md).

A `qwk_ponte.dll` (compilar.bat) registra os tipos QML do QWindowKit no motor do
PySide6. Com --teste, confere pela API do Windows o que se veria na tela: o que
cada ponto da janela é para o Windows, a borda fantasma, o snap e o maximizar
no segundo monitor, e grava capturas com a sombra.

Uso:  ..\\big_picture_qml\\.venv\\Scripts\\python main.py [--teste]
"""

import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

import PySide6
import shiboken6
from PySide6.QtCore import QRect, QTimer, QUrl, qVersion
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

AQUI = Path(__file__).parent
user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.GetForegroundWindow.restype = wintypes.HWND
user32.WindowFromPoint.argtypes = [wintypes.POINT]
user32.WindowFromPoint.restype = wintypes.HWND
user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.MonitorFromWindow.restype = wintypes.HMONITOR


def registrar_qwindowkit(motor: QQmlApplicationEngine) -> None:
    # As dependências (Qt6Core/Gui/Qml/Quick) são as DLLs que o próprio PySide6 traz.
    os.add_dll_directory(str(Path(PySide6.__file__).parent))
    ponte = ctypes.CDLL(str(AQUI / "qwk_ponte.dll"))
    ponte.qwk_registrar.argtypes = [ctypes.c_void_p]
    ponte.qwk_registrar.restype = ctypes.c_int
    if not ponte.qwk_registrar(shiboken6.getCppPointer(motor)[0]):
        raise RuntimeError(
            f"qwk_ponte.dll foi compilada para outro Qt (o PySide6 traz o {qVersion()}): rode compilar.bat"
        )


# --- conferências pela API do Windows ---
NOMES_DO_HITTEST = {
    1: "conteúdo", 2: "barra (arrastar)", 8: "minimizar", 9: "maximizar (Snap Layouts)",
    20: "fechar", 10: "borda esquerda", 11: "borda direita", 12: "borda de cima",
    15: "borda de baixo", 13: "canto sup. esq.", 17: "canto inf. dir.",
}


def retangulo_da_janela(hwnd) -> tuple:
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def moldura_visivel(hwnd) -> tuple:
    r = wintypes.RECT()
    dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r))  # EXTENDED_FRAME_BOUNDS
    return r.left, r.top, r.right, r.bottom


def hittest(hwnd, x: int, y: int) -> str:
    resultado = user32.SendMessageW(hwnd, 0x0084, 0, (y & 0xFFFF) << 16 | (x & 0xFFFF))
    return NOMES_DO_HITTEST.get(resultado, str(resultado))


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def area_util(hwnd) -> tuple:
    info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(info))
    r = info.rcWork
    return r.left, r.top, r.right, r.bottom


def win_seta(hwnd, tecla_seta: int) -> bool:
    """Win + seta, pelo teclado virtual, só com a nossa janela em primeiro plano."""
    VK_LWIN, SOLTAR = 0x5B, 0x0002
    if user32.GetForegroundWindow() != hwnd:  # conferido logo antes: nunca mexer em outra janela
        return False
    for vk, flags in ((VK_LWIN, 0), (tecla_seta, 0), (tecla_seta, SOLTAR), (VK_LWIN, SOLTAR)):
        user32.keybd_event(vk, 0, flags, 0)
    return True


def teste(app: QGuiApplication, janela) -> None:
    hwnd = int(janela.winId())
    pasta = AQUI / "capturas"
    pasta.mkdir(exist_ok=True)

    def capturar(nome: str) -> None:
        esq, topo, dir_, base = retangulo_da_janela(hwnd)
        tela = app.screenAt(janela.geometry().center()) or app.primaryScreen()
        g = tela.geometry()
        area = QRect(esq - 40, topo - 40, dir_ - esq + 80, base - topo + 80).intersected(g)
        tela.grabWindow(0, area.x() - g.x(), area.y() - g.y(), area.width(), area.height()).save(
            str(pasta / f"{nome}.png"))

    def medir_bordas(rotulo: str) -> None:
        janela_r, moldura = retangulo_da_janela(hwnd), moldura_visivel(hwnd)
        sobra = [moldura[0] - janela_r[0], moldura[1] - janela_r[1],
                 janela_r[2] - moldura[2], janela_r[3] - moldura[3]]
        print(f"[{rotulo}] janela {janela_r}, moldura visível {moldura}, "
              f"faixa invisível (esq, cima, dir, baixo) {sobra}")

    def pontos() -> None:
        esq, topo, dir_, base = moldura_visivel(hwnd)
        # Win32 fala em pixels físicos; a barra e os botões estão em pixels lógicos.
        escala = janela.screen().devicePixelRatio()
        barra = round(janela.property("alturaDaBarra") * escala)
        botao = round(janela.property("larguraDoBotao") * escala)
        meio_y = topo + barra // 2
        casos = [
            ("barra, no meio", (esq + dir_) // 2 - 200, meio_y, "barra (arrastar)"),
            ("botão minimizar", dir_ - 2 * botao - botao // 2, meio_y, "minimizar"),
            ("botão maximizar", dir_ - botao - botao // 2, meio_y, "maximizar (Snap Layouts)"),
            ("botão fechar", dir_ - botao // 2, meio_y, "fechar"),
            ("conteúdo", (esq + dir_) // 2, (topo + base) // 2, "conteúdo"),
            ("3 px fora, à esquerda", esq - 3, (topo + base) // 2, "borda esquerda"),
            ("3 px fora, à direita", dir_ + 2, (topo + base) // 2, "borda direita"),
            ("3 px fora, embaixo", (esq + dir_) // 2, base + 2, "borda de baixo"),
            ("1 px dentro, em cima", (esq + dir_) // 2 - 200, topo + 1, "borda de cima"),
        ]
        for nome, x, y, esperado in casos:
            obtido = hittest(hwnd, x, y)
            print(f"  {'ok ' if obtido == esperado else 'ERRO'} {nome}: {obtido}")
        # O primeiro pixel depois da faixa de redimensionar (7 px): o clique vai para o que está atrás.
        faixa = esq - retangulo_da_janela(hwnd)[0]
        fora = user32.WindowFromPoint(wintypes.POINT(esq - faixa - 1, (topo + base) // 2))
        print(f"  {'ok ' if fora != hwnd else 'ERRO'} {faixa + 1} px fora: "
              f"{'outra janela' if fora != hwnd else 'a nossa janela engole o clique'}")

    def snap() -> None:
        if win_seta(hwnd, 0x25):  # Win + ←
            QTimer.singleShot(900, conferir_snap)
        else:
            print("[snap] pulado: a janela não está em primeiro plano")

    def conferir_snap() -> None:
        m, a = moldura_visivel(hwnd), area_util(hwnd)
        metade = (a[0], a[1], (a[0] + a[2]) // 2, a[3])
        desvio = [m[i] - metade[i] for i in range(4)]
        print(f"[snap Win+←] moldura {m}, metade da área útil {metade}, desvio {desvio}")
        capturar("2-snap-esquerda")
        janela.showNormal()

    def segundo_monitor() -> None:
        telas = app.screens()
        if len(telas) < 2:
            print("[monitor 2] pulado: só um monitor")
            return
        g = telas[1].availableGeometry()
        janela.setPosition(g.x() + 100, g.y() + 100)
        QTimer.singleShot(400, lambda: (janela.showMaximized(), QTimer.singleShot(700, conferir_maximizada)))

    def conferir_maximizada() -> None:
        tela = app.screenAt(janela.geometry().center())
        if tela is not app.screens()[1]:
            print(f"[maximizada no monitor 2] ERRO: a janela está em {tela.name() if tela else '?'}")
        m, a = moldura_visivel(hwnd), area_util(hwnd)
        desvio = [m[i] - a[i] for i in range(4)]
        print(f"[maximizada no monitor 2] moldura {m}, área útil {a}, desvio {desvio}")
        medir_bordas("maximizada")
        capturar("3-maximizada-monitor-2")
        janela.showNormal()

    passos = [
        (800, lambda: (medir_bordas("normal"), print("[pontos da janela]"), pontos(), capturar("1-normal"))),
        (300, lambda: (janela.requestActivate(), user32.SetForegroundWindow(hwnd))),
        (500, snap),
        (2000, segundo_monitor),
        (2500, QGuiApplication.quit),
    ]
    atraso = 0
    for espera, acao in passos:
        atraso += espera
        QTimer.singleShot(atraso, acao)


def main() -> int:
    app = QGuiApplication(sys.argv)
    motor = QQmlApplicationEngine()
    registrar_qwindowkit(motor)
    motor.load(QUrl.fromLocalFile(str(AQUI / "Janela.qml")))
    if not motor.rootObjects():
        return 1
    janela = motor.rootObjects()[0]
    janela.show()
    if "--teste" in sys.argv:
        teste(app, janela)
    codigo = app.exec()
    del janela, motor  # o motor antes do app: a ordem do coletor não é garantida
    return codigo


if __name__ == "__main__":
    sys.exit(main())
