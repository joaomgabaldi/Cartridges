# test_ajustes_do_windows.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As animações do Windows relidas no `WM_SETTINGCHANGE` (D88). Nenhum filtro é instalado no app dos testes."""

import ctypes
import os
import subprocess
import sys
import textwrap
from ctypes import wintypes
from pathlib import Path

import shiboken6

from cartridges import aplicativo as aplicativo_modulo
from cartridges.aplicativo import Aplicativo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.modelos.big_picture import BigPicture
from cartridges.utils import ajustes_do_windows
from cartridges.utils.ajustes_do_windows import FiltroDeAjustes, e_mudanca_de_ajuste

_WM_SETTINGCHANGE = 0x001A
_GENERICA = b"windows_generic_MSG"
RAIZ = Path(__file__).resolve().parent.parent

# Plataforma `windows` (a offscreen não tem procedimento de janela): uma `QWindow` criada aqui e nunca mostrada
# recebe um `WM_SETTINGCHANGE` só dela, por `SendMessageW` direto ao HWND (nunca `HWND_BROADCAST`).
_FILTRO_NUMA_JANELA_NATIVA = textwrap.dedent("""
    import ctypes
    from PySide6.QtGui import QGuiApplication, QWindow
    app = QGuiApplication([])
    from cartridges.utils.ajustes_do_windows import FiltroDeAjustes
    chamadas = []
    filtro = FiltroDeAjustes(lambda: chamadas.append(1))
    app.installNativeEventFilter(filtro)
    janela = QWindow()
    hwnd = int(janela.winId())
    ctypes.windll.user32.SendMessageW(hwnd, 0x001A, 0, 0)
    for _ in range(5):
        app.processEvents()
    filtro.desligar()
    janela.destroy()
    print("visivel:", janela.isVisible(), "chamadas:", len(chamadas))
""")


def _msg(mensagem):
    """Um `MSG` do ctypes de verdade; o filtro recebe o endereço dele como `VoidPtr`, o tipo que o PySide entrega."""
    msg = wintypes.MSG()
    msg.message = mensagem
    return msg, shiboken6.VoidPtr(ctypes.addressof(msg))


def test_wm_settingchange_e_mudanca_de_ajuste():
    msg, endereco = _msg(_WM_SETTINGCHANGE)
    assert e_mudanca_de_ajuste(_GENERICA, endereco) is True
    del msg


def test_outra_mensagem_nao_e():
    msg, endereco = _msg(0x0005)  # WM_SIZE
    assert e_mudanca_de_ajuste(_GENERICA, endereco) is False
    assert e_mudanca_de_ajuste(b"windows_dispatcher_MSG", endereco) is False
    assert e_mudanca_de_ajuste(_GENERICA, shiboken6.VoidPtr(0)) is False  # sem mensagem: não lê o endereço zero
    del msg


def test_filtro_nunca_consome_a_mensagem(app_qt, flush_idle, monkeypatch):  # noqa: ARG001
    chamadas = []
    filtro = FiltroDeAjustes(lambda: chamadas.append(1))
    msg, endereco = _msg(_WM_SETTINGCHANGE)
    assert filtro.nativeEventFilter(_GENERICA, endereco) == (False, 0)
    outra, endereco_outra = _msg(0x0005)
    assert filtro.nativeEventFilter(_GENERICA, endereco_outra) == (False, 0)
    assert chamadas == []  # pela thread principal, depois: nunca dentro do procedimento da janela
    flush_idle()
    assert chamadas == [1]

    # Um retorno que levanta ou uma mensagem ilegível não sobem para o Qt.
    monkeypatch.setattr(ajustes_do_windows, "e_mudanca_de_ajuste", lambda *_a: 1 / 0)
    assert filtro.nativeEventFilter(_GENERICA, endereco) == (False, 0)
    del msg, outra


def test_filtro_instalado_ve_o_wm_settingchange_de_uma_janela_nativa(tmp_path):
    """O tipo que o PySide entrega de verdade, numa janela do próprio teste, em subprocesso (o app dos testes é
    offscreen)."""
    ambiente = {**os.environ, "CARTRIDGES_DADOS": str(tmp_path), "QT_QPA_PLATFORM": "windows"}
    resultado = subprocess.run(
        [sys.executable, "-c", _FILTRO_NUMA_JANELA_NATIVA], cwd=RAIZ, env=ambiente, capture_output=True, text=True,
        timeout=60, check=False,
    )  # fmt: skip
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip().splitlines()[-1] == "visivel: False chamadas: 1"


def test_reler_animacoes_avisa_so_quando_muda(app_qt, monkeypatch):  # noqa: ARG001
    ligadas = [True]
    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: ligadas[0])
    aplicativo = Aplicativo()
    avisos = []
    aplicativo.animacoesDoSistemaChanged.connect(lambda: avisos.append(aplicativo.animacoesDoSistema))
    aplicativo.reler_animacoes()
    assert avisos == []
    ligadas[0] = False
    aplicativo.reler_animacoes()
    aplicativo.reler_animacoes()
    assert avisos == [False]
    ligadas[0] = True
    aplicativo.reler_animacoes()
    assert avisos == [False, True]


def test_big_picture_segue_as_animacoes_relidas(app_qt, monkeypatch, schema):  # noqa: ARG001
    from cartridges import app as modulo_app  # noqa: PLC0415

    schema.set_boolean("cover-autoplay", True)
    ligadas = [True]
    monkeypatch.setattr(aplicativo_modulo, "_animacoes_do_sistema", lambda: ligadas[0])
    aplicativo = Aplicativo()
    big_picture = BigPicture(ModeloDaBiblioteca(), animacoes_do_sistema=aplicativo.animacoesDoSistema)
    modulo_app._seguir_animacoes(aplicativo, big_picture)  # noqa: SLF001
    mudou = []
    big_picture.animarCentralMudou.connect(lambda: mudou.append(big_picture.animarCentral))
    assert big_picture.animacoes and big_picture.animarCentral

    ligadas[0] = False
    aplicativo.reler_animacoes()
    assert not big_picture.animacoes and not big_picture.animarCentral
    assert mudou == [False]

    ligadas[0] = True
    aplicativo.reler_animacoes()
    assert big_picture.animacoes and big_picture.animarCentral
    assert mudou == [False, True]
