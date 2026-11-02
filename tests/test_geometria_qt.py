# test_geometria_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A geometria da janela principal (D87, P20): gravada ao fechar, restaurada ao abrir.

Nenhuma janela de verdade é movida: `_place`, `read` e `session_geometry` são falsos, e o estado é o `state_schema`
temporário do conftest.
"""

import os
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlComponent, QQmlEngine

from cartridges import shared
from cartridges.modelos import tarefas
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.saves import backup_de_saves
from cartridges.utils import window_geometry
from cartridges.utils.window_geometry import UNSET, Geometry, GeometriaDaJanela

RAIZ = Path(__file__).resolve().parent.parent
QML = RAIZ / "cartridges" / "qml"


def _esperar(ms=50):
    laco = QEventLoop()
    QTimer.singleShot(ms, laco.quit)
    laco.exec()


@pytest.fixture
def win32_falso(monkeypatch):
    """`_place`, `read` e `session_geometry` falsos: anotam o que pediriam ao Windows."""
    falso = SimpleNamespace(colocadas=[], lida=Geometry(100, 50, 900, 600, False), sessao=None, aceita=True)

    def colocar(janela, geometria):
        falso.colocadas.append((janela, geometria))
        return falso.aceita

    monkeypatch.setattr(window_geometry, "_place", colocar)
    monkeypatch.setattr(window_geometry, "read", lambda _janela: falso.lida)
    monkeypatch.setattr(window_geometry, "session_geometry", lambda: falso.sessao)
    return falso


def _gravado(schema):
    return window_geometry.stored(schema)


class _JanelaFalsa:
    """O que a geometria pergunta a uma `QWindow`."""

    def __init__(self, visibilidade=QWindow.Visibility.Windowed, visivel=True):
        self.visibilidade = visibilidade
        self.visivel = visivel
        self.maximizada = 0

    def visibility(self):
        return self.visibilidade

    def isVisible(self):  # noqa: N802
        return self.visivel

    def showMaximized(self):  # noqa: N802
        self.maximizada += 1


# --- trazidos de test_ui_logic.py --------------------------------------------------------------------------------


def test_a_geometry_needs_a_size_to_be_usable():
    """Um retângulo sem tamanho é o que uma janela ainda sem lugar informa."""
    assert Geometry(0, 0, 0, 0, False).usable is False
    assert Geometry(10, 10, 1170, 795, False).usable is True


def test_stored_monta_a_geometria_das_chaves_do_estado():
    """A janela reaparecida volta ao que o fechamento gravou, não à abertura."""
    valores = {"x": -7, "y": 20, "width": 900, "height": 600, "is-maximized": True}
    schema = SimpleNamespace(get_int=lambda chave: valores[chave], get_boolean=lambda chave: valores[chave])
    assert window_geometry.stored(schema) == Geometry(-7, 20, 900, 600, True)
    valores["x"], valores["is-maximized"] = 50, False  # gravado depois
    assert window_geometry.stored(schema) == Geometry(50, 20, 900, 600, False)


def test_a_maximized_geometry_keeps_the_restored_size():
    """Gravar o tamanho maximizado faria a janela crescer a cada abertura."""
    geometry = Geometry(10, 10, 1170, 795, True)
    assert geometry.maximized is True
    assert (geometry.width, geometry.height) == (1170, 795)



def test_a_negative_coordinate_is_usable():
    """Um monitor real em coordenada negativa vale como posição gravada."""
    assert Geometry(-476, 100, 800, 600, False).usable


def test_a_minimized_window_is_not_read(monkeypatch):
    """A1: fechar pela taskbar com a janela minimizada (o estado normal
    enquanto um jogo roda) gravava o retângulo icônico como geometria."""

    class FakeUser32:
        @staticmethod
        def IsIconic(_hwnd):  # noqa: N802
            return 1

        @staticmethod
        def GetWindowRect(*_args):  # noqa: N802
            raise AssertionError("não se pergunta o rect de uma janela icônica")

    monkeypatch.setattr(window_geometry, "_user32", FakeUser32())
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _window: 42)

    assert window_geometry.read(object()) is None

# --- gravar --------------------------------------------------------------------------------------------------------


def test_fechar_em_tela_cheia_nao_grava_a_geometria(monkeypatch, state_schema):
    """P20: em tela cheia (Big Picture) o retângulo é o da tela, não o da janela; vale o gravado antes."""

    def nao_le(*_args):
        # `pytest.fail` (BaseException): um AssertionError seria engolido pelo `except Exception` do `gravar()`.
        pytest.fail("não se lê a geometria de uma janela em tela cheia")

    monkeypatch.setattr(window_geometry, "session_geometry", nao_le)
    monkeypatch.setattr(window_geometry, "read", nao_le)
    antes = _gravado(state_schema)
    assert window_geometry.gravar(state_schema, object(), tela_cheia=True) is False
    assert _gravado(state_schema) == antes

    # Pelo objeto do contexto: a tela cheia vem da `visibility()` da janela.
    geometria = GeometriaDaJanela()
    geometria.restaurar(_JanelaFalsa(QWindow.Visibility.FullScreen))
    geometria.gravar()
    assert _gravado(state_schema) == antes


def test_fechar_minimizada_nao_grava(monkeypatch, state_schema):
    """Minimizada (o estado normal durante um jogo), o retângulo é o do ícone: fica o gravado antes."""

    class User32Minimizada:
        @staticmethod
        def IsIconic(_hwnd):  # noqa: N802
            return 1

        @staticmethod
        def GetWindowRect(*_args):  # noqa: N802
            raise AssertionError("não se pergunta o retângulo de uma janela minimizada")

    monkeypatch.setattr(window_geometry, "_user32", User32Minimizada())
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _janela: 42)
    monkeypatch.setattr(window_geometry, "session_geometry", lambda: None)
    antes = _gravado(state_schema)
    assert window_geometry.gravar(state_schema, object(), tela_cheia=False) is False
    assert _gravado(state_schema) == antes


def test_fechar_durante_a_sessao_grava_a_geometria_de_antes(win32_falso, state_schema):
    """D52: a janela está no monitor do jogo; o que fica é onde ela estava antes da sessão."""
    win32_falso.lida = Geometry(1920, 0, 1080, 1920, True)  # estacionada, maximizada no segundo monitor
    win32_falso.sessao = Geometry(200, 100, 1000, 700, False)
    assert window_geometry.gravar(state_schema, object(), tela_cheia=False) is True
    assert _gravado(state_schema) == Geometry(200, 100, 1000, 700, False)


def test_maximizada_grava_so_a_posicao(win32_falso, state_schema):
    state_schema.set_int("width", 1000)
    state_schema.set_int("height", 650)
    win32_falso.lida = Geometry(-8, -8, 1936, 1056, True)
    assert window_geometry.gravar(state_schema, object(), tela_cheia=False) is True
    assert _gravado(state_schema) == Geometry(-8, -8, 1000, 650, True)


def test_gravar_janela_normal_grava_tudo(win32_falso, state_schema):
    assert window_geometry.gravar(state_schema, object(), tela_cheia=False) is True
    assert _gravado(state_schema) == Geometry(100, 50, 900, 600, False)


def test_janela_que_nao_responde_nao_grava(win32_falso, state_schema):
    win32_falso.lida = None
    antes = _gravado(state_schema)
    assert window_geometry.gravar(state_schema, object(), tela_cheia=False) is False
    assert _gravado(state_schema) == antes


def test_janela_ja_fechada_nao_e_lida_de_novo(monkeypatch, win32_falso, state_schema):
    """O `close()` do Qt destrói a janela nativa: o `winId()` criaria outra, num lugar qualquer. O `closing` já gravou."""
    monkeypatch.setattr(window_geometry, "read", lambda _j: pytest.fail("leu uma janela já fechada"))
    antes = _gravado(state_schema)
    geometria = GeometriaDaJanela()
    geometria.restaurar(_JanelaFalsa(visivel=False))
    geometria.gravar()
    assert _gravado(state_schema) == antes


def test_gravar_sem_janela_nao_levanta(state_schema):
    antes = _gravado(state_schema)
    GeometriaDaJanela().gravar()
    assert _gravado(state_schema) == antes


# --- restaurar -----------------------------------------------------------------------------------------------------


def test_posicao_fora_dos_monitores_e_ignorada(monkeypatch):
    """Um monitor desligado: a posição gravada não existe mais; a janela fica onde o Windows a pôs, no tamanho gravado."""
    movidas = []

    class User32SoOPrincipal:
        @staticmethod
        def MonitorFromRect(retangulo, _bandeiras):  # noqa: N802
            return 1 if retangulo._obj.left < 1920 else None  # só o principal, de 0 a 1920

        @staticmethod
        def SetWindowPos(_hwnd, _depois, x, y, largura, altura, _bandeiras):  # noqa: N802
            movidas.append((x, y, largura, altura))
            return 1

    monkeypatch.setattr(window_geometry, "_user32", User32SoOPrincipal())
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _janela: 42)
    monkeypatch.setattr(window_geometry, "read", lambda _janela: Geometry(402, 135, 1116, 739, False))
    janela = _JanelaFalsa()
    window_geometry.restaurar(janela, Geometry(5000, 5000, 900, 600, False))
    assert movidas == [(402, 135, 900, 600)]
    assert janela.maximizada == 0


def test_restaurar_poe_no_lugar_gravado(win32_falso):
    janela = _JanelaFalsa()
    window_geometry.restaurar(janela, Geometry(100, 50, 900, 600, False))
    assert win32_falso.colocadas == [(janela, Geometry(100, 50, 900, 600, False))]
    assert janela.maximizada == 0


def test_maximizada_maximiza_mesmo_sem_posicao_aceita(win32_falso):
    """O usuário deixou a janela maximizada: ela volta maximizada onde o Windows a puser."""
    win32_falso.aceita = False
    janela = _JanelaFalsa()
    window_geometry.restaurar(janela, Geometry(5000, 5000, 900, 600, True))
    assert win32_falso.colocadas[0][1] == Geometry(5000, 5000, 900, 600, True)
    assert janela.maximizada == 1


def test_nada_gravado_nao_mexe_na_janela(win32_falso):
    janela = _JanelaFalsa()
    window_geometry.restaurar(janela, Geometry(UNSET, UNSET, 1170, 795, False))
    assert win32_falso.colocadas == []
    assert janela.maximizada == 0


def _principal(geometria):
    motor = QQmlEngine()
    from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    motor.rootContext().setContextProperty("geometria", geometria)
    componente = QQmlComponent(motor, QUrl.fromLocalFile(str(QML / "Principal.qml")))
    janela = componente.createWithInitialProperties({"semAgente": True})
    assert janela is not None, componente.errorString()
    return motor, componente, janela


def test_sem_geometria_gravada_usa_o_tamanho_do_qt(app_qt, win32_falso, state_schema):  # noqa: ARG001
    """Nada gravado (a primeira abertura): a janela fica no tamanho padrão da `main`, 1170×795."""
    assert state_schema.get_int("x") == UNSET
    geometria = GeometriaDaJanela()
    motor, componente, janela = _principal(geometria)
    try:
        assert (janela.width(), janela.height()) == (1170, 795)
        assert win32_falso.colocadas == []
        assert janela.visibility() != QWindow.Visibility.Maximized
    finally:
        janela.deleteLater()
        _esperar()
    del motor, componente


def test_principal_restaura_depois_do_tamanho(app_qt, monkeypatch, win32_falso, state_schema):  # noqa: ARG001
    """O `onCompleted` pede a restauração depois do tamanho de hoje: o gravado vence o 1170×795."""
    for chave, valor in (("x", 100), ("y", 50), ("width", 900), ("height", 600)):
        state_schema.set_int(chave, valor)
    tamanhos = []
    original = window_geometry._place  # o falso do `win32_falso`

    def colocar(janela, geometria):
        tamanhos.append((janela.width(), janela.height()))
        return original(janela, geometria)

    monkeypatch.setattr(window_geometry, "_place", colocar)
    motor, componente, janela = _principal(GeometriaDaJanela())
    try:
        assert tamanhos == [(1170, 795)]
        assert win32_falso.colocadas[0][1] == Geometry(100, 50, 900, 600, False)
    finally:
        janela.deleteLater()
        _esperar()
    del motor, componente


# --- os pontos que gravam ------------------------------------------------------------------------------------------


class _SessaoFalsa:
    def principalFechando(self):  # noqa: N802
        pass


def test_principal_fechando_grava_antes_de_esconder(app_qt, monkeypatch):  # noqa: ARG001
    """D78, caso 1: com saves em andamento a principal se esconde; a geometria é gravada antes, com ela à vista."""
    monkeypatch.setattr(backup_de_saves, "_tarefas_abertas", 0)
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    monkeypatch.setattr(shared, "sessao", _SessaoFalsa(), raising=False)
    monkeypatch.setattr(tarefas, "_sair", lambda: None)
    principal = QWindow()
    principal.resize(200, 200)
    principal.show()
    painel = PainelDasTarefas()
    painel.definir_janela(principal)
    gravadas = []
    painel.gravar_geometria = lambda: gravadas.append(principal.isVisible())
    try:
        assert painel.principalFechando() is False
        assert gravadas == [True]
        assert not principal.isVisible()
    finally:
        painel.mostrarPrincipal()
        QGuiApplication.setQuitOnLastWindowClosed(True)
        principal.destroy()
        _esperar()


def test_fechar_grava_a_geometria_primeiro(monkeypatch):
    """O primeiro passo do `_fechar` grava a geometria (o `aboutToQuit` que chega sem `closing`).

    No `quit()` do reinício e da atualização o Qt fecha a janela antes: quem grava é o `closing`, e este passo vira
    no-op (a janela já não está visível). Aqui só a ordem.
    """
    from cartridges import app as modulo_app  # noqa: PLC0415

    passos = []

    class _Passo:
        def __init__(self, nome):
            self.nome = nome

        def __getattr__(self, metodo):
            return lambda *_a: passos.append(f"{self.nome}.{metodo}")

    for nome in ("login", "ea_conta", "icones", "async_manager", "copias_animadas"):
        monkeypatch.setattr(modulo_app, nome, _Passo(nome))
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    modulo_app._fechar(  # noqa: SLF001
        modulo_app._Abertura(geometria=_Passo("geometria"), big_picture=_Passo("bp"))  # noqa: SLF001
    )
    assert passos[:2] == ["geometria.gravar", "bp.encerrar"]


def test_window_geometry_sem_gi(tmp_path):
    """O módulo e a geometria importam e rodam com o `gi` bloqueado."""
    script = textwrap.dedent(
        """
        import sys
        sys.modules["gi"] = None
        from cartridges.utils import window_geometry
        assert not hasattr(window_geometry, "apply_size")
        assert not hasattr(window_geometry, "apply_placement")
        assert window_geometry._hwnd(object()) is None
        print("ok")
        """
    )
    ambiente = {**os.environ, "CARTRIDGES_DADOS": str(tmp_path), "QT_QPA_PLATFORM": "offscreen"}
    ambiente["CARTRIDGES_REGISTRO"] = rf"Software\CartridgesTestes\geometria-{uuid.uuid4()}"
    resultado = subprocess.run(
        [sys.executable, "-c", script], cwd=RAIZ, env=ambiente, capture_output=True, text=True, timeout=60, check=False
    )
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip() == "ok"
