# test_barra_hit_test.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que o QWindowKit
 responde ao WM_NCHITTEST do Windows, numa janela real, com e sem modal.

O arrasto, os botões do sistema e o Snap Layouts (HTMAXBUTTON) nascem desta resposta, antes de qualquer evento do Qt:
um modal desenhado por cima da barra não basta. Roda em outro processo porque o resto dos testes é offscreen.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from kyron.janela import qwk

pytestmark = pytest.mark.skipif(
    not (Path(qwk.__file__).parent / "qwk_ponte.dll").exists(),
    reason="qwk_ponte.dll é um artefato de build: rode build-aux/windows/qwk/compilar.bat",
)

_SCRIPT = r"""
import builtins, ctypes, json, sys
from pathlib import Path
builtins._ = lambda m: m
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, QPoint, QPointF, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from kyron.janela import qwk
from kyron.modelos.provedor_de_icones import ProvedorDeIcones
from kyron.utils.ajustes_do_windows import FiltroDeAjustes

app = QGuiApplication(sys.argv)
motor = QQmlApplicationEngine()
qwk.registrar(motor)
motor.addImageProvider("icone", ProvedorDeIcones())
motor.load(QUrl.fromLocalFile(sys.argv[1]))
janela = motor.rootObjects()[0]
janela.show()


def girar(ms=150):
    laco = QEventLoop()
    QTimer.singleShot(ms, laco.quit)
    laco.exec()


girar(500)
hwnd = int(janela.winId())
user32 = ctypes.windll.user32
user32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
user32.SendMessageW.restype = ctypes.c_ssize_t


def teste(x, y):
    p = janela.mapToGlobal(QPoint(int(x), int(y)))
    return int(user32.SendMessageW(hwnd, 0x0084, 0, (p.y() & 0xFFFF) << 16 | (p.x() & 0xFFFF)))  # WM_NCHITTEST


def medir():
    r = janela.devicePixelRatio()
    largura = janela.width()
    # Os botões do sistema: 34 de largura, 3 entre eles, 6 da borda direita.
    return {
        "titulo": teste(largura / 2, 23),
        "fechar": teste(largura - 23, 23),
        "maximizar": teste(largura - 60, 23),
        "minimizar": teste(largura - 97, 23),
        "botao_da_pagina": teste(23, 23),
        "conteudo": teste(largura / 2, 300),
    }


saida = {"livre": medir()}
janela.setProperty("barraTrancada", True)
girar()
saida["trancada"] = medir()
janela.setProperty("barraTrancada", False)
girar()
saida["de_novo"] = medir()

filtro = FiltroDeAjustes(lambda: None)
app.installNativeEventFilter(filtro)
menu, fixo = janela.findChild(QObject, "menuTeste"), janela.findChild(QObject, "fixoTeste")
QMetaObject.invokeMethod(menu, "open")
QMetaObject.invokeMethod(fixo, "open")
girar()
abertos = [menu.property("opened"), fixo.property("opened")]
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
p = janela.mapToGlobal(QPoint(janela.width() // 2, 23))
coordenadas = (p.y() & 0xFFFF) << 16 | (p.x() & 0xFFFF)
user32.PostMessageW(hwnd, 0x00A1, 2, coordenadas)  # WM_NCLBUTTONDOWN em HTCAPTION
user32.PostMessageW(hwnd, 0x00A2, 2, coordenadas)
girar(500)
saida["menus"] = {"abertos": abertos, "menu": menu.property("visible"), "fixo": fixo.property("visible")}
app.removeNativeEventFilter(filtro)
print("RESULTADO" + json.dumps(saida))
janela.close()
"""

_QML = """
import QtQuick
import QtQuick.Controls
import "file:///{qml}"
Principal {{
    inicio: [ BotaoDaBarra {{ icone: "list-add" }} ]
    Popup {{ objectName: "menuTeste"; width: 50; height: 50; closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside; enter: null; exit: null }}
    Popup {{ objectName: "fixoTeste"; width: 50; height: 50; closePolicy: Popup.NoAutoClose; enter: null; exit: null }}
}}
"""

HTCLIENT, HTCAPTION, HTMINBUTTON, HTMAXBUTTON, HTCLOSE = 1, 2, 8, 9, 20


@pytest.fixture(scope="module")
def medidas(tmp_path_factory):
    raiz = Path(__file__).resolve().parent.parent
    pasta = tmp_path_factory.mktemp("hit")
    arquivo = pasta / "janela.qml"
    arquivo.write_text(_QML.format(qml=(raiz / "kyron" / "qml").as_posix()), encoding="utf-8")
    ambiente = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    ambiente["PYTHONPATH"] = str(raiz)
    rodou = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(arquivo)], env=ambiente, capture_output=True, text=True, timeout=60, check=False
    )
    linha = [l for l in rodou.stdout.splitlines() if l.startswith("RESULTADO")]
    assert linha, rodou.stdout + rodou.stderr
    import json  # noqa: PLC0415

    return json.loads(linha[0][len("RESULTADO"):])


def test_sem_modal_a_barra_arrasta_e_o_maximizar_da_snap_layouts(medidas):
    livre = medidas["livre"]
    assert livre["titulo"] == HTCAPTION
    assert livre["maximizar"] == HTMAXBUTTON  # é o que o Windows pede para mostrar o Snap Layouts
    assert livre["minimizar"] == HTMINBUTTON
    assert livre["fechar"] == HTCLOSE
    assert livre["botao_da_pagina"] == HTCLIENT  # setHitTestVisible: o clique é do botão, não arrasto
    assert livre["conteudo"] == HTCLIENT


def test_com_modal_a_barra_inteira_e_area_de_cliente(medidas):
    """Sem arrasto, sem botões do sistema: o clique cai no Qt, e o escurecimento do modal o segura."""
    trancada = medidas["trancada"]
    assert set(trancada.values()) == {HTCLIENT}, trancada


def test_ao_fechar_o_modal_a_barra_volta(medidas):
    assert medidas["de_novo"] == medidas["livre"]


def test_clique_na_barra_fecha_o_menu_aberto(medidas):
    """O clique em HTCAPTION não vira evento de mouse do Qt: sem o filtro, o menu ficaria aberto. Um popup sem fechamento automático fica."""
    menus = medidas["menus"]
    assert menus["abertos"] == [True, True]
    assert menus["menu"] is False
    assert menus["fixo"] is True
