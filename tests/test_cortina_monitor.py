# test_cortina_monitor.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""CortinaMonitor com um Win32 falso: nada de janela de verdade."""

import pytest

from cartridges.utils import cortina_monitor as cm
from cartridges.utils import janela_por_cima as jpc


class _Win32Falso:
    def __init__(self, falha=None):
        self.chamadas = []
        self.falha = falha

    def __getattr__(self, nome):
        def chamar(*args):
            self.chamadas.append((nome, args))
            if nome == self.falha:
                return 0
            if nome == "GetMonitorInfoW":
                info = args[1]._obj
                info.rcMonitor.left, info.rcMonitor.top = 100, 50
                info.rcMonitor.right, info.rcMonitor.bottom = 2020, 1130
                return 1
            if nome == "MonitorFromWindow":
                return 77
            return 1

        return chamar

    def nomes(self):
        return [n for n, _ in self.chamadas]

    def args(self, nome):
        return next(a for n, a in self.chamadas if n == nome)


@pytest.fixture
def win32(monkeypatch):
    falso = _Win32Falso()
    monkeypatch.setattr(cm, "_api", lambda: falso)
    monkeypatch.setattr(cm, "_classe_registrada", True)
    monkeypatch.setattr(jpc, "dono_oculto", lambda: 999)
    return falso


def test_cria_no_monitor_da_janela_por_cima_de_tudo_sem_foco(win32):
    cm.CortinaMonitor(1234)
    assert win32.args("MonitorFromWindow") == (1234, cm.MONITOR_DEFAULTTONEAREST)
    (estilos, classe, _t, estilo, x, y, w, h, dono, *_), = [
        a for n, a in win32.chamadas if n == "CreateWindowExW"
    ]
    assert estilos == (
        jpc.WS_EX_LAYERED | jpc.WS_EX_TOPMOST | jpc.WS_EX_TRANSPARENT
        | jpc.WS_EX_TOOLWINDOW | jpc.WS_EX_NOACTIVATE
    )
    assert estilo == jpc.WS_POPUP and classe == cm.CLASSE and dono == 999
    assert (x, y, w, h) == (100, 50, 1920, 1080)
    assert win32.args("ShowWindow")[1] == cm.SW_SHOWNOACTIVATE
    pos = win32.args("SetWindowPos")
    assert pos[1] == jpc.HWND_TOPMOST and pos[6] & jpc.SWP_NOACTIVATE


@pytest.mark.parametrize(
    "valor, byte", [(0, 0), (0.5, 128), (1, 255), (-1, 0), (7, 255)]
)
def test_alfa_vira_byte(win32, valor, byte):
    c = cm.CortinaMonitor(1)
    c.alfa(valor)
    ultimo = [a for n, a in win32.chamadas if n == "SetLayeredWindowAttributes"][-1]
    assert ultimo[2] == byte and ultimo[3] == jpc.LWA_ALPHA


def test_fechar_e_idempotente(win32):
    c = cm.CortinaMonitor(1)
    c.fechar()
    c.fechar()
    assert win32.nomes().count("DestroyWindow") == 1


@pytest.mark.parametrize(
    "funcao", ["CreateWindowExW", "GetMonitorInfoW", "SetWindowPos"]
)
def test_falha_ao_criar_levanta_oserror(monkeypatch, win32, funcao):
    win32.falha = funcao
    with pytest.raises(OSError):
        cm.CortinaMonitor(1)
    if funcao == "SetWindowPos":  # a janela já existia: não pode ficar para trás
        assert "DestroyWindow" in win32.nomes()
