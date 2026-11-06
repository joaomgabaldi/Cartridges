# window_geometry.py
#
# Copyright 2026 joaomgabaldi
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Remember the main window's size, position and state across runs.

Position is read and applied through Win32, so the app reopens on the right monitor. Size is a Win32 frame rectangle (the same in both directions: the version before Qt, on GTK, reported a width 28 px smaller after a maximize/restore, and the saved size ratcheted down every run), saved only while not maximized. The same handle gives the monitor list, since parking the window on another screen during a game (:func:`move_to_monitor`) is the startup restore done twice.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import weakref
from collections.abc import Callable
from ctypes import wintypes
from pathlib import Path
from typing import Any, NamedTuple, Optional

from PySide6.QtCore import QObject, QTimer, Slot
from PySide6.QtGui import QWindow

from kyron import shared

_MONITOR_DEFAULTTONULL = 0x00000000
# SWP_NOZORDER | SWP_NOACTIVATE: posiciona sem elevar nem focar
_PLACE = 0x0004 | 0x0010
# O retângulo gravado pela versão anterior (GTK) inclui a sombra da janela (28x29), que o Qt não tem: esquerda/topo e largura/altura
# a descontar na primeira abertura depois dela. O reparte é aproximado (14 e 14; o 1 a mais de altura fica embaixo).
_SOMBRA_DO_GTK = (14, 14, 28, 29)
_FOLGA_BOTAO = 12
_MONITORINFOF_PRIMARY = 0x00000001
_SW_HIDE = 0
_SW_SHOWNORMAL = 1
_SW_SHOWMAXIMIZED = 3

# Declarados, e não os padrões do ctypes (C int): o handle é um ponteiro de 64 bits, e um HMONITOR truncado leria como "sem monitor" e descartaria toda posição gravada.
_user32 = ctypes.windll.user32  # type: ignore
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND,
    wintypes.HWND,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    ctypes.c_int,
    wintypes.UINT,
]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.MonitorFromRect.argtypes = [ctypes.POINTER(wintypes.RECT), wintypes.DWORD]
_user32.MonitorFromRect.restype = wintypes.HANDLE
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.IsZoomed.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


_user32.GetWindowPlacement.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(_WINDOWPLACEMENT),
]
_user32.GetWindowPlacement.restype = wintypes.BOOL
_user32.SetWindowPlacement.argtypes = [
    wintypes.HWND,
    ctypes.POINTER(_WINDOWPLACEMENT),
]
_user32.SetWindowPlacement.restype = wintypes.BOOL

_MONITORENUMPROC = ctypes.WINFUNCTYPE(
    wintypes.BOOL,
    wintypes.HMONITOR,
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    wintypes.LPARAM,
)
_user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(wintypes.RECT),
    _MONITORENUMPROC,
    wintypes.LPARAM,
]
_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(_MONITORINFOEXW)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


_user32.EnumDisplayDevicesW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    ctypes.POINTER(_DISPLAY_DEVICEW),
    wintypes.DWORD,
]
_user32.EnumDisplayDevicesW.restype = wintypes.BOOL
_EDD_GET_DEVICE_INTERFACE_NAME = 0x00000001
_DISPLAY_DEVICE_ACTIVE = 0x00000001

# O que o schema guarda até a janela fechar uma vez. Não 0 (coordenada real) nem -1 (um segundo monitor acima do principal o produz de verdade).
UNSET = -(2**31)


class Geometry(NamedTuple):
    """The window's frame rectangle, and whether it was showing maximized."""

    x: int
    y: int
    width: int
    height: int
    maximized: bool

    @property
    def usable(self) -> bool:
        return self.width > 0 and self.height > 0 and self.x != UNSET


def stored(schema: Any) -> Geometry:
    """A geometria gravada no schema de estado. Lida de novo a cada "map": a janela principal pode ser escondida e reaparecer, e deve voltar a onde o usuário a deixou."""
    return Geometry(
        schema.get_int("x"),
        schema.get_int("y"),
        schema.get_int("width"),
        schema.get_int("height"),
        schema.get_boolean("is-maximized"),
    )


class Monitor(NamedTuple):
    """An attached screen, in the same physical coordinates as :class:`Geometry`."""

    device: str  # "\\\\.\\DISPLAY2", o nome com que o desktop numera os monitores
    x: int  # a tela inteira, barra de tarefas incluída: a janela enviada para cá é maximizada sobre ela
    y: int
    width: int
    height: int
    primary: bool
    ordinal: int = 0  # posição (de 1) em :func:`monitors`; 0 se montado à mão
    # O caminho do monitor (``\\\\?\\DISPLAY#DEL4123#5&...#{e6f07b5f-...}``): modelo e saída de vídeo. Vazio se o Windows não o informa; então vale o ``device``.
    path: str = ""

    @property
    def key(self) -> str:
        """O que a preferência ``session-monitor`` guarda: não o ``device`` (o Windows troca os nomes ``DISPLAYn`` entre as telas
        ao dormir, religar ou reiniciar o driver), mas o caminho, que só muda se o cabo mudar de porta."""
        return self.path or self.device

    def is_stored(self, stored: str) -> bool:
        """Se ``stored`` (o valor da preferência) aponta para esta tela; aceita também o ``device`` que as versões anteriores gravavam."""
        return bool(stored) and stored in (self.path, self.device)

    @property
    def number(self) -> str:
        """O nome da tela na lista de preferências e na placa de identificação: a posição na lista, não o "22" de ``\\\\.\\DISPLAY22`` (o desktop continua contando enquanto telas e drivers vêm e vão, e as configurações do Windows dizem 1, 2, 3)."""
        if self.ordinal:
            return str(self.ordinal)
        return self.device.rsplit("DISPLAY", 1)[-1] or "?"


def _device_order(monitor: Monitor) -> tuple[int, str]:
    """DISPLAY2 antes de DISPLAY10, que a ordem de texto inverte."""
    digits = monitor.device.rsplit("DISPLAY", 1)[-1]
    return (int(digits) if digits.isdigit() else 0, monitor.device)


def _place_order(monitor: Monitor) -> tuple[bool, int, int, tuple[int, str]]:
    """O principal primeiro; os outros da esquerda para a direita e de cima para baixo; o nome só desempata."""
    return (not monitor.primary, monitor.x, monitor.y, _device_order(monitor))


def numbered(found: list[Monitor]) -> list[Monitor]:
    """Os monitores em ordem de posição, cada um com o seu número (1, 2, 3...): pela posição na área de trabalho e não pelos nomes ``DISPLAYn``, que o Windows troca (:attr:`Monitor.key`)."""
    return [
        monitor._replace(ordinal=place)
        for place, monitor in enumerate(sorted(found, key=_place_order), 1)
    ]


def _monitor_path(device: str) -> str:
    """O caminho do monitor ligado em ``device``, ou "" se o Windows não diz."""
    for index in range(4):  # mais de uma só em telas espelhadas
        info = _DISPLAY_DEVICEW()
        info.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
        if not _user32.EnumDisplayDevicesW(
            device, index, ctypes.byref(info), _EDD_GET_DEVICE_INTERFACE_NAME
        ):
            break
        if info.StateFlags & _DISPLAY_DEVICE_ACTIVE and info.DeviceID:
            return info.DeviceID
    return ""


def monitors() -> list[Monitor]:
    """Todos os monitores, em ordem. Vazio se a enumeração falha: quem chama trata como "não mover a janela", não como erro."""
    found: list[Monitor] = []

    def collect(handle: int, _hdc: int, _rect: Any, _param: int) -> bool:
        info = _MONITORINFOEXW()
        info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
        if _user32.GetMonitorInfoW(handle, ctypes.byref(info)):
            area = info.rcMonitor
            found.append(
                Monitor(
                    info.szDevice,
                    area.left,
                    area.top,
                    area.right - area.left,
                    area.bottom - area.top,
                    bool(info.dwFlags & _MONITORINFOF_PRIMARY),
                    path=_monitor_path(info.szDevice),
                )
            )
        return True

    try:
        _user32.EnumDisplayMonitors(None, None, _MONITORENUMPROC(collect), 0)
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not list the monitors: %s", error)
        return []

    # Por posição, não pela ordem do callback (a do driver): uma lista que embaralha faria o "Monitor 2" mudar de tela.
    return numbered(found)


def has_secondary_monitor() -> bool:
    """True se algum monitor não é o principal. As opções de sessão que usam outras telas precisam disso (o jogo roda no principal). Enumeração que falha dá False, o lado seguro: a opção é desligada."""
    return any(not monitor.primary for monitor in monitors())


def monitores_da_sessao() -> list[Monitor]:
    """Os monitores que a sessão pode usar: todos menos o principal, onde o jogo roda."""
    return [monitor for monitor in monitors() if not monitor.primary]


def escolha_de_monitor(monitores: list[Monitor], gravado: str) -> tuple[list[str], int]:
    """Os rótulos da lista de monitores e a posição do que está gravado (o caminho, :attr:`Monitor.key`; um nome antigo também vale, :meth:`Monitor.is_stored`). Gravado desligado (ou o principal) cai no primeiro, e quem chama grava essa escolha. O rótulo é só o número: resolução e posição empatam entre telas iguais, e "Identificar monitores" mostra qual é qual."""
    rotulos = [_("Monitor {}").format(m.number) for m in monitores]
    escolhido = next((i for i, m in enumerate(monitores) if m.is_stored(gravado)), 0)
    return rotulos, escolhido


# As placas na tela, seguradas até fecharem: quem as pediu (as Preferências) pode já ter fechado.
_placas: list[Any] = []
_PLACA = Path(__file__).resolve().parent.parent / "qml" / "PlacaDoMonitor.qml"


def _criar_placa(monitor: Monitor, lado: int) -> Any:
    """A placa do ``monitor``: uma ``QQuickView`` sem moldura com o número, no centro da tela."""
    from PySide6.QtCore import QUrl, Qt  # noqa: PLC0415
    from PySide6.QtQuick import QQuickView  # noqa: PLC0415

    placa = QQuickView()
    # Janela comum sem moldura: recebe foco e aparece na barra de tarefas.
    placa.setFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
    placa.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    placa.setInitialProperties({"numero": monitor.number})
    placa.setSource(QUrl.fromLocalFile(str(_PLACA)))
    if placa.rootObject() is None:
        erros = "; ".join(erro.toString() for erro in placa.errors())
        placa.deleteLater()
        raise RuntimeError(f"a placa do monitor não carregou: {erros}")
    placa.resize(lado, lado)
    placa.show()
    # Depois do `show`: antes dele a janela não tem lugar na área de trabalho.
    _place(
        placa,
        Geometry(
            monitor.x + (monitor.width - lado) // 2,
            monitor.y + (monitor.height - lado) // 2,
            lado,
            lado,
            False,
        ),
    )
    return placa


def _fechar_placa(ref: Any) -> None:
    placa = ref()
    if placa is None:
        return
    if placa in _placas:
        _placas.remove(placa)
    try:
        placa.close()
        placa.deleteLater()
    except RuntimeError:  # o objeto Qt já foi apagado
        pass


def identificar_monitores(segundos: int = 3, criar: Optional[Callable[[Monitor, int], Any]] = None) -> None:
    """Pisca o número de cada monitor sobre ele, como as configurações do Windows ("qual deles é o 2?" não tem resposta em texto). Só na thread principal."""
    criar = criar or _criar_placa
    for monitor in monitors():
        # Um quarto do lado menor da tela, para o número sair do mesmo tamanho relativo.
        lado = max(200, min(monitor.width, monitor.height) // 4)
        placa = criar(monitor, lado)
        if placa is None:
            continue
        _placas.append(placa)
        QTimer.singleShot(segundos * 1000, functools.partial(_fechar_placa, weakref.ref(placa)))


def read(window: Any) -> Optional[Geometry]:
    """O retângulo da moldura, ou None se não dá mais para perguntar. Maximizada, é a área de trabalho do monitor: serve de posição, não de tamanho."""
    if (hwnd := _hwnd(window)) is None:
        return None

    # O retângulo de uma janela minimizada é o ponto de estacionamento do ícone (-32000,-32000, ~160x28), não uma geometria; e minimizada é o
    # estado normal durante um jogo: fechar assim gravaria o fiapo e reabriria minúscula. Vale como não perguntável: a gravada fica.
    if _user32.IsIconic(hwnd):
        return None

    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None

    return Geometry(
        rect.left,
        rect.top,
        rect.right - rect.left,
        rect.bottom - rect.top,
        bool(_user32.IsZoomed(hwnd)),
    )


def gravar(schema: Any, janela: Any, tela_cheia: bool) -> bool:
    """Grava onde a janela está, se ainda dá para perguntar; diz se gravou.

    Em tela cheia (Big Picture) o retângulo é o da tela: vale a gravada antes. Fechar no meio de uma sessão: a janela está
    estacionada no monitor do jogo, e o que se lembra é de onde ela saiu. Minimizada, `read` não responde e fica a gravada.
    """
    if tela_cheia:
        return False
    geometry = session_geometry() or read(janela)
    if geometry is None:
        return False
    schema.set_int("x", geometry.x)
    schema.set_int("y", geometry.y)
    schema.set_boolean("is-maximized", geometry.maximized)
    # O retângulo de uma maximizada é o do monitor: o último tamanho real fica para a restauração.
    if not geometry.maximized:
        schema.set_int("width", geometry.width)
        schema.set_int("height", geometry.height)
    return True


def restaurar(janela: Any, geometria: Geometry) -> None:
    """Põe a janela de volta no lugar e no tamanho gravados; sem nada gravado (`usable` falso), não mexe.

    A ordem importa: move primeiro e maximiza depois, pois maximizar preenche o monitor em que a janela está (ao contrário, sempre o principal).
    """
    if not geometria.usable:
        # Primeira abertura: o 1170x795 lógico já vem do `Principal.qml`; o `SetWindowPos` usa pixels físicos e o encolheria fora de 100% de escala.
        return
    if not _place(janela, geometria) and (atual := read(janela)) is not None:
        # A posição gravada não existe mais (monitor desligado): a janela fica onde o Windows a pôs, no tamanho gravado.
        _place(janela, geometria._replace(x=atual.x, y=atual.y))
    if geometria.maximized:
        # Não depende de `_place` ter dado certo: com a posição recusada, a pessoa ainda pediu maximizada.
        janela.showMaximized()


def sem_a_sombra_do_gtk(geometria: Geometry) -> Geometry:
    """A geometria gravada pela versão anterior (GTK) convertida para o Qt: tira a sombra do retângulo. Maximizada não muda."""
    if not geometria.usable or geometria.maximized:
        return geometria
    esquerda, topo, largura, altura = _SOMBRA_DO_GTK
    return geometria._replace(
        x=geometria.x + esquerda,
        y=geometria.y + topo,
        width=max(1, geometria.width - largura),
        height=max(1, geometria.height - altura),
    )


# Existe depois que o Qt gravou a geometria pela primeira vez: dali em diante o retângulo gravado já é o dele.
_MARCA_DO_QT = "geometria-qt"


class GeometriaDaJanela(QObject):
    """A geometria da principal no contexto do QML (`geometria`): restaurada no `onCompleted` do `Principal.qml`, gravada no `closing` e no primeiro passo do `_fechar`.

    A janela fica numa referência comum: não segura o objeto C++ (o dono é o motor), e uma destruída responde com `RuntimeError`. Uma fraca morreria com o invólucro Python, que o PySide solta a qualquer momento.
    """

    def __init__(self, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._janela: Any = None

    @Slot(QObject)
    def restaurar(self, janela: Any) -> None:
        self._janela = janela
        try:
            geometria = stored(shared.state_schema)
            if not (shared.app_dir / _MARCA_DO_QT).exists():
                geometria = sem_a_sombra_do_gtk(geometria)
            restaurar(janela, geometria)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Could not restore the window geometry", exc_info=True)

    @Slot()
    def gravar(self) -> None:
        """Nunca levanta: roda no fechamento."""
        janela = self._janela
        try:
            # Já fechada pelo `quit()`: o `close()` do Qt destrói a janela nativa e o `winId()` criaria outra, num lugar qualquer; o `closing` já gravou.
            if janela is None or not janela.isVisible():
                return
            if gravar(shared.state_schema, janela, janela.visibility() == QWindow.Visibility.FullScreen):
                (shared.app_dir / _MARCA_DO_QT).parent.mkdir(parents=True, exist_ok=True)
                (shared.app_dir / _MARCA_DO_QT).touch()
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Could not save the window geometry", exc_info=True)


# Onde a janela estava antes de uma sessão a enviar a outro monitor (e o sinal de que a sessão a segura lá). Estado do módulo porque lançamento,
# fim da sessão e saída do app concordam numa resposta, e só uma sessão roda por vez.
_before_session: Optional[Geometry] = None
_before_placement: "Optional[_WINDOWPLACEMENT]" = None

def session_geometry() -> Optional[Geometry]:
    """Onde a janela estaria sem jogo rodando, ou None. É o que se grava ao fechar no meio da sessão: salvar o monitor do jogo faria dele o lugar de reabertura para sempre."""
    return _before_session


def move_to_monitor(window: Any, stored: str) -> bool:
    """Estaciona ``window`` maximizada no monitor que ``stored`` nomeia (a preferência ``session-monitor``) e diz se foi.

    False por qualquer razão para não mover (monitor ausente ou principal, sem handle, nada legível para voltar): quem chama minimiza. Perder a janela fora da tela é pior que não mover.
    Usa ``WINDOWPLACEMENT`` e não ``SetWindowPos``: a colocação leva onde a janela fica desmaximizada e se está maximizada, então ler antes e gravar depois restaura as duas coisas. As gravações são síncronas: a desmaximização termina antes de mover.
    """
    global _before_session, _before_placement  # pylint: disable=global-statement

    target = next((m for m in monitors() if m.is_stored(stored)), None)
    if target is None:
        logging.info("Monitor %s is not attached; leaving the window alone", stored)
        return False
    if target.primary:
        logging.info("Monitor %s is the primary one; leaving the window alone", stored)
        return False

    if (hwnd := _hwnd(window)) is None or (current := read(window)) is None:
        return False
    if (placement := _get_placement(hwnd)) is None:
        return False

    # Duas gravações, na ordem da restauração da abertura: monitor primeiro, maximizar depois. Pedir as duas juntas não faz nada a uma
    # janela já maximizada (o Windows toma o retângulo como onde *restaurá-la* e segue maximizando no monitor atual).
    if not _set_placement(hwnd, placement, _SW_SHOWNORMAL, target):
        return False
    # Best effort: a janela que chegou ao monitor certo sem maximizar ainda está no lugar certo e o fim da sessão a devolve.
    _set_placement(hwnd, placement, _SW_SHOWMAXIMIZED, target)

    _before_session, _before_placement = current, placement
    logging.info("Window parked on %s (%s) for the session", target.device, target.number)
    return True


def restore_from_monitor(window: Any) -> None:
    """Devolve a janela exatamente a onde :func:`move_to_monitor` a achou; sem efeito se nada foi movido.

    Uma janela escondida no meio da sessão recebe a colocação como ``SW_HIDE``: mostrá-la aqui a deixaria sem foco de teclado depois do `present()` seguinte. Escondida basta para trazer de volta o retângulo de ao desmaximizar e se estava maximizada.
    """
    global _before_session, _before_placement  # pylint: disable=global-statement

    placement = _before_placement
    _before_session, _before_placement = None, None

    if placement is None or (hwnd := _hwnd(window)) is None:
        return

    if not _user32.IsWindowVisible(hwnd):
        _set_placement(hwnd, placement, _SW_HIDE)
        return

    # O espelho de `move_to_monitor`: a janela que estava maximizada antes do jogo é desmaximizada no próprio monitor primeiro, senão "maximizada, lá" a deixa maximizada aqui.
    if placement.showCmd == _SW_SHOWMAXIMIZED:
        _set_placement(hwnd, placement, _SW_SHOWNORMAL)
    _user32.SetWindowPlacement(hwnd, ctypes.byref(placement))


def _set_placement(
    hwnd: int,
    placement: "_WINDOWPLACEMENT",
    show: int,
    target: Optional[Monitor] = None,
) -> bool:
    """Mostra ``hwnd`` como ``show``, mantendo o resto de ``placement``. Com ``target``, o retângulo é trocado pelo daquele monitor, a única forma de o ``WINDOWPLACEMENT``
    dizer *onde* (o Windows maximiza sobre a tela em que o retângulo cai); sem ele, a janela mantém o retângulo que carrega."""
    wanted = _WINDOWPLACEMENT.from_buffer_copy(placement)
    wanted.showCmd = show
    if target is not None:
        wanted.rcNormalPosition.left = target.x
        wanted.rcNormalPosition.top = target.y
        wanted.rcNormalPosition.right = target.x + target.width
        wanted.rcNormalPosition.bottom = target.y + target.height
    return bool(_user32.SetWindowPlacement(hwnd, ctypes.byref(wanted)))


def _get_placement(hwnd: int) -> "Optional[_WINDOWPLACEMENT]":
    placement = _WINDOWPLACEMENT()
    placement.length = ctypes.sizeof(_WINDOWPLACEMENT)
    if not _user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
        return None
    return placement


def posicao_acima_do_botao(botao: tuple[int, int, int, int], altura_da_janela: int) -> tuple[int, int]:
    """O canto (x, y) da moldura de uma janela solta logo acima do botão das tarefas, alinhada à esquerda dele com folga de 12 px.

    `botao` é (x, y, largura, altura) em coordenadas lógicas da tela (as do Qt); `altura_da_janela` é a da moldura inteira.
    """
    return botao[0], botao[1] - _FOLGA_BOTAO - altura_da_janela


def _place(window: Any, geometry: Geometry) -> bool:
    """Move e dimensiona a moldura para ``geometry``. A posição gravada não é confiável: monitores são desligados e arranjos mudam, e restaurar num lugar que não existe deixaria a janela onde ela não se vê nem se arrasta de volta."""
    if not geometry.usable or (hwnd := _hwnd(window)) is None:
        return False

    rect = wintypes.RECT()
    rect.left = geometry.x
    rect.top = geometry.y
    rect.right = geometry.x + geometry.width
    rect.bottom = geometry.y + geometry.height
    if not _user32.MonitorFromRect(ctypes.byref(rect), _MONITOR_DEFAULTTONULL):
        logging.info(
            "Stored window position %d,%d %dx%d is on no attached monitor; ignoring it",
            geometry.x,
            geometry.y,
            geometry.width,
            geometry.height,
        )
        return False

    return bool(
        _user32.SetWindowPos(
            hwnd, 0, geometry.x, geometry.y, geometry.width, geometry.height, _PLACE
        )
    )


def _hwnd(window: Any) -> Optional[int]:
    """O handle Win32 da janela, ou None antes de ela existir. Uma `QWindow` dá o ``winId()``, que no Windows já é o HWND.

    Tudo aqui é best-effort: uma falha custa uma janela que abre onde abriu da última vez, e nunca pode derrubar o app.
    """
    if window is None or not isinstance(window, QWindow):
        return None
    try:
        return int(window.winId()) or None
    except Exception as error:  # pylint: disable=broad-exception-caught
        logging.warning("Could not read the window handle: %s", error)
        return None
