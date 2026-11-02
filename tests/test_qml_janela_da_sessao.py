# test_qml_janela_da_sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A janela "Jogando {nome}" da sessão manual (D50, R3): sem moldura (barra própria), 300x150, canto da área de trabalho."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos import sessao as modulo
from cartridges.modelos.sessao import canto_inferior_direito
from cartridges.process_session import ProcessSession
from cartridges.session_window import SessionWindow
from cartridges.utils import session_fita, session_log
from tests.apoio_qml_biblioteca import _achar, _App, _esperar, _jogos

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def isolado(monkeypatch):
    """Nenhuma chamada Win32 de verdade e nenhum histórico gravado."""
    monkeypatch.setattr(modulo, "_area_de_trabalho", lambda: (0, 0, 1920, 1040))
    monkeypatch.setattr(modulo, "_retangulo_da_janela", lambda _hwnd: (0, 0, 316, 189))
    monkeypatch.setattr(modulo, "_user32", lambda: pytest.fail("Win32 de verdade"))
    registros = []
    monkeypatch.setattr(session_log, "record", lambda jogo_id, s: registros.append((jogo_id, s)))
    return registros


def _app(monkeypatch, nome="A & B"):
    app = _App(_jogos((1, nome, {"status": "playing"})))
    app.jogos[0].save = lambda: None
    app.jogos[0].update = lambda: None
    monkeypatch.setattr(shared, "sessao", app.sessao, raising=False)
    app.sessao.definir_janela(app.janela)
    return app


def _abrir(app):
    SessionWindow(app.jogos[0]).present()
    carregador = app.achar("carregadorDaJanelaManual")
    _esperar(lambda: carregador.property("item") is not None)
    return carregador.property("item")


def test_titulo_e_tamanho_fixo(app_qt, monkeypatch):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    janela = _abrir(app)
    assert janela.title() == "Jogando A & B"
    assert (janela.width(), janela.height()) == (300, 150)
    assert (janela.minimumWidth(), janela.minimumHeight()) == (300, 150)
    assert (janela.maximumWidth(), janela.maximumHeight()) == (300, 150)
    assert _achar(janela, "botaoTermineiDaJanela") is not None
    app.fechar()


def test_barra_propria_de_47_com_titulo_minimizar_e_fechar_e_o_botao_no_resto(app_qt, monkeypatch):
    """SES-01/02/03/04: a `Adw.HeaderBar` da `main` (47 px, título centrado, sem maximizar) e o botão pílula no meio do resto."""
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    janela = _abrir(app)
    barra = _achar(janela, "barraDaJanelaDaSessao")
    assert (barra.width(), barra.height()) == (300, 47)
    assert barra.property("comMaximizar") is False  # só minimizar e fechar, como a janela das tarefas
    assert barra.property("titulo") == "Jogando A & B"
    assert _achar(barra, "tituloDaBarraTexto").property("text") == "Jogando A & B"
    assert not janela.flags() & Qt.WindowType.WindowMaximizeButtonHint
    botao = _achar(janela, "botaoTermineiDaJanela")
    assert (botao.height(), botao.property("estilo"), botao.property("pilula")) == (44, "sugestao", True)
    # No meio do que sobra abaixo da barra: (150 - 47) / 2 + 47 = 98,5.
    centro = botao.mapToScene(botao.boundingRect().center())
    assert (centro.x(), abs(centro.y() - 98.5) <= 0.5) == (150.0, True)
    app.fechar()


def test_enter_no_botao_da_janela_encerra_a_sessao(app_qt, monkeypatch, isolado):
    """SES-08: Enter aciona o botão da janela (o `Gtk.Button` responde a Enter e a Espaço)."""
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    janela = _abrir(app)
    assert _esperar(lambda: janela.activeFocusItem() is not None)
    QTest.keyClick(janela, Qt.Key.Key_Return)
    assert _esperar(lambda: not app.sessao.janelaManual)
    assert SessionWindow.active is None
    assert [r[0] for r in isolado] == ["imported_1"]
    app.fechar()


def test_botao_encerra_e_registra(app_qt, monkeypatch, isolado):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    janela = _abrir(app)
    botao = _achar(janela, "botaoTermineiDaJanela")
    assert botao.property("text") == "Já terminei de jogar"
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: not app.sessao.janelaManual)
    assert SessionWindow.active is None
    assert app.sessao.emAndamento is False
    assert [r[0] for r in isolado] == ["imported_1"]
    _esperar(lambda: app.achar("carregadorDaJanelaManual").property("item") is None)
    app.fechar()


def test_fechar_pela_moldura_encerra_e_registra(app_qt, monkeypatch, isolado):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    janela = _abrir(app)
    janela.close()
    _esperar(lambda: SessionWindow.active is None)
    assert SessionWindow.active is None
    assert app.sessao.emAndamento is False
    assert len(isolado) == 1
    app.fechar()


def test_canto_inferior_direito():
    assert canto_inferior_direito((0, 0, 1920, 1040), 300, 150) == (1608, 878)
    assert canto_inferior_direito((100, 50, 1100, 650), 300, 150, margem=0) == (800, 500)


def test_posicionar_usa_o_hwnd_da_janela_e_nao_rouba_o_foco(app_qt, monkeypatch):
    chamadas = []

    class Funcao:
        def __call__(self, *args):
            chamadas.append(args)

    class Fake:
        SetWindowPos = Funcao()  # noqa: N815

    monkeypatch.setattr(modulo, "_user32", lambda: Fake())

    class Janela:
        def winId(self):  # noqa: N802
            return 4242

    modelo = modulo.ModeloDaSessao(None)
    modelo.posicionarJanelaManual(Janela())
    # Janela 316x189 (com moldura) na área 1920x1040, margem 12: o canto fica em 1592,839.
    assert chamadas == [(4242, 0, 1592, 839, 0, 0, 0x0015)]


def test_falha_no_win32_deixa_onde_esta(app_qt, monkeypatch, caplog):
    def falha():
        raise OSError("sem Win32")

    monkeypatch.setattr(modulo, "_area_de_trabalho", falha)

    class Janela:
        def winId(self):  # noqa: N802
            return 1

    with caplog.at_level("ERROR"):
        modulo.ModeloDaSessao(None).posicionarJanelaManual(Janela())  # não levanta
    assert "Não foi possível posicionar a janela Jogando" in caplog.text


def test_queda_para_a_manual_mantem_a_camada_e_um_relogio_so(app_qt, monkeypatch):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    jogo = app.jogos[0]
    camada = app.achar("camadaDaSessao")
    app.sessao.show_session_blocker(jogo)  # o rastreio por processo veste a sessão
    assert app.sessao.emAndamento and not app.sessao.janelaManual
    SessionWindow(jogo).present()  # o `fall_back`: só o rastreador muda de mãos
    assert app.sessao.emAndamento and app.sessao.janelaManual
    assert ProcessSession.active is None
    assert SessionWindow.active is not None
    carregador = app.achar("carregadorDaJanelaManual")
    _esperar(lambda: carregador.property("item") is not None)
    assert camada.property("visible") is True
    app.sessao.terminar()
    assert app.sessao.emAndamento is False and SessionWindow.active is None
    app.fechar()


def test_fechar_a_principal_com_a_manual_aberta_sai_e_grava(app_qt, monkeypatch, isolado):
    """Como na `main`: o app sai; o `encerrar()` grava o tempo no jogo e uma linha no histórico.

    O `quit()` de verdade está no teste `test_quit_real_com_a_manual_aberta_encerra_antes_de_fechar_as_janelas`."""
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    jogo = app.jogos[0]
    app.janela.show()
    _abrir(app)
    saidas = []
    # O que o `QEvent.Quit` faz (`AplicacaoQt.saindo`): `encerrar()`. O `quit` de verdade acabaria o laço dos testes.
    app.sessao._sair = lambda: (saidas.append(1), app.sessao.encerrar())  # noqa: SLF001
    SessionWindow.active.session_start -= 42  # 42 s jogados
    app.janela.close()
    assert saidas == []  # o `quit()` vem na volta do laço, com a principal já fora da tela
    assert _esperar(lambda: saidas == [1])
    assert jogo.playtime == 42
    assert isolado == [("imported_1", 42)]
    app.fechar()


def test_closing_da_manual_depois_do_encerrar_nao_roda_o_fim_normal(app_qt, monkeypatch, isolado):
    """I1: no `quit()` o Qt fecha a janela "Jogando" depois do `encerrar()`; o `closing` dela não faz nada."""
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    # Registrados, e não `pytest.fail`: num slot chamado pelo QML a exceção é engolida.
    chamadas = []
    monkeypatch.setattr(session_fita, "voltar", lambda: chamadas.append("voltar"))
    app = _app(monkeypatch)
    jogo = app.jogos[0]
    app.janela.show()
    janela = _abrir(app)
    for nome in ("hide_session_blocker", "session_toast", "present", "_sair"):
        monkeypatch.setattr(app.sessao, nome, lambda *_a, nome=nome: chamadas.append(nome))
    SessionWindow.active.session_start -= 42

    app.sessao.encerrar()  # o `QEvent.Quit`, antes de as janelas fecharem
    janela.close()  # o `closing` real da manual
    app.janela.close()  # e o da principal
    _esperar()

    assert chamadas == []
    assert jogo.playtime == 42
    assert isolado == [("imported_1", 42)]
    app.fechar()


_SAIDA_REAL = r"""
import json, sys
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from cartridges import app as modulo_app, shared
from cartridges.modelos import sessao as modulo
from cartridges.session_window import SessionWindow
from cartridges.utils import game_logo, session_fita, session_log, session_wallpaper, window_geometry

ordem = []
def anota(nome):
    return lambda *_a: ordem.append(nome)
def visiveis():
    return sorted(janela.title() for janela in QGuiApplication.topLevelWindows() if janela.isVisible())
def anota_com_as_janelas(nome):
    # R1: a parede e as fitas (que podem demorar) só depois de as janelas sumirem da tela.
    return lambda *_a: ordem.append([nome, visiveis()])
# Nenhum dispositivo, papel de parede ou chamada Win32 de verdade.
for alvo, nome in ((session_fita, "abrir"), (session_fita, "comecar"), (session_fita, "voltar"),
                   (session_wallpaper, "comecar"), (window_geometry, "restore_from_monitor")):
    setattr(alvo, nome, anota(nome))
session_fita.fechar = anota_com_as_janelas("fechar")
session_wallpaper.restaurar = anota_com_as_janelas("restaurar")
window_geometry.session_geometry = lambda: None
game_logo.cached_logo_path = lambda _jogo: None
session_log.record = lambda _id, segundos: ordem.append(["record", segundos])
modulo._posicionar = lambda *_a: None
modulo._retangulo_da_janela = lambda _h: (0, 0, 316, 189)
modulo._area_de_trabalho = lambda: (0, 0, 1920, 1040)

app = modulo_app.AplicacaoQt(sys.argv[:1])
sessao = modulo.ModeloDaSessao(SimpleNamespace(adicionar=anota("aviso")))
shared.sessao = sessao
for nome in ("hide_session_blocker", "session_toast", "present"):
    setattr(sessao, nome, anota(nome))
# A ligação do `app.py`.
app.saindo.connect(sessao.encerrar)
app.aboutToQuit.connect(lambda: (ordem.append("aboutToQuit"), sessao.devolver()))

motor = QQmlApplicationEngine()
from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
motor.addImageProvider("icone", ProvedorDeIcones())
motor.rootContext().setContextProperty("sessao", sessao)
motor.loadData(b'''import QtQuick
Window {
    visible: true; width: 200; height: 100
    onClosing: sessao.principalFechando()
    Loader { active: sessao.janelaManual; source: "JanelaDaSessao.qml" }
}''', QUrl.fromLocalFile(str(Path("cartridges/qml/_saida.qml").resolve())))
principal = motor.rootObjects()[0]
sessao.definir_janela(principal)
jogo = SimpleNamespace(game_id="imported_1", name="Alfa", notes="", status="playing", zerado=False, playtime=0,
                       save=lambda: None, update=lambda: None)
SessionWindow(jogo).present()
SessionWindow.active.session_start -= 42
def fechar():
    ordem.append(["antes", visiveis()])
    ordem.append("principal.close")
    principal.close()
QTimer.singleShot(500, fechar)
QTimer.singleShot(15000, lambda: (ordem.append("prazo"), app.exit(2)))
codigo = app.exec()
print(json.dumps({"codigo": codigo, "ordem": ordem, "playtime": jogo.playtime}))
"""


def test_quit_real_com_a_manual_aberta_encerra_antes_de_fechar_as_janelas():
    """I1: o `quit()` de verdade (Alt+F4 na principal). O Qt fecha as janelas dentro do `QEvent.Quit`, antes
    do `aboutToQuit`; o `encerrar()` vem antes delas, e o fim normal da sessão não roda."""
    ambiente = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    resultado = subprocess.run(
        [sys.executable, "-c", _SAIDA_REAL], cwd=RAIZ, env=ambiente, capture_output=True, text=True, timeout=60,
        check=False,
    )  # fmt: skip
    assert resultado.returncode == 0, resultado.stderr
    saida = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert saida["codigo"] == 0
    ordem = saida["ordem"]
    # R4: a janela "Jogando" estava aberta (junto com a principal) quando o fechamento começou.
    assert ordem[ordem.index("principal.close") - 1] == ["antes", ["", "Jogando Alfa"]]
    depois = ordem[ordem.index("principal.close") + 1 :]
    # R1: no `saindo` só a gravação; a parede e as fitas vêm no `aboutToQuit`, com as janelas já fora da tela.
    assert depois == [["record", 42], "aboutToQuit", ["restaurar", []], ["fechar", []]]
    assert saida["playtime"] == 42


_SAIDA_COM_O_AVISO = r"""
import json, sys
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QWindow
from PySide6.QtQml import QQmlApplicationEngine
from cartridges import app as modulo_app, conquista_aviso, janela_do_aviso, shared
from cartridges.modelos import sessao as modulo
from cartridges.session_window import SessionWindow
from cartridges.utils import game_logo, session_fita, session_log, session_wallpaper, window_geometry

com_sessao = sys.argv[1] == "com"
ordem = []
def visiveis():
    return sorted(janela.title() for janela in QGuiApplication.topLevelWindows() if janela.isVisible())
# Nenhum dispositivo, papel de parede, som ou chamada Win32 de verdade.
for alvo, nome in ((session_fita, "abrir"), (session_fita, "comecar"), (session_fita, "voltar"),
                   (session_fita, "fechar"), (session_wallpaper, "comecar"), (session_wallpaper, "restaurar"),
                   (window_geometry, "restore_from_monitor")):
    setattr(alvo, nome, lambda *_a: None)
window_geometry.session_geometry = lambda: None
game_logo.cached_logo_path = lambda _jogo: None
session_log.record = lambda *_a: None
modulo._posicionar = lambda *_a: None
modulo._retangulo_da_janela = lambda _h: (0, 0, 316, 189)
modulo._area_de_trabalho = lambda: (0, 0, 1920, 1040)
shared.schema = SimpleNamespace(get_string=lambda _c: "inferior-direito", get_boolean=lambda _c: False)
conquista_aviso._agendar = lambda *_a: None  # o aviso fica na tela até o fechamento

class AvisoFalso(QWindow):
    # Uma janela de topo com as flags do aviso, sem o Win32 do `janela_por_cima` (D59: sem dono no Qt).
    def __init__(self, aviso):
        super().__init__()
        self.titulo = aviso.titulo
        self.setTitle("aviso")
        self.setFlags(janela_do_aviso._FLAGS)
        self.resize(50, 50)
    def entrar(self, _canto):
        self.show()
    def fechar(self):
        ordem.append("aviso.fechar")
        self.destroy()
        self.deleteLater()
conquista_aviso._criar_janela = AvisoFalso

app = modulo_app.AplicacaoQt(sys.argv[:1])
sessao = modulo.ModeloDaSessao(SimpleNamespace(adicionar=lambda *_a: None))
shared.sessao = sessao
for nome in ("hide_session_blocker", "session_toast", "present"):
    setattr(sessao, nome, lambda *_a: None)
# A ligação do `app.py`.
app.saindo.connect(sessao.encerrar)
app.aboutToQuit.connect(lambda: (ordem.append(["aboutToQuit", visiveis()]), sessao.devolver()))

motor = QQmlApplicationEngine()
from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
motor.addImageProvider("icone", ProvedorDeIcones())
motor.rootContext().setContextProperty("sessao", sessao)
motor.loadData(b'''import QtQuick
Window {
    visible: true; width: 200; height: 100; title: "principal"
    onClosing: sessao.principalFechando()
    Loader { active: sessao.janelaManual; source: "JanelaDaSessao.qml" }
}''', QUrl.fromLocalFile(str(Path("cartridges/qml/_saida.qml").resolve())))
principal = motor.rootObjects()[0]
sessao.definir_janela(principal)
if com_sessao:
    jogo = SimpleNamespace(game_id="imported_1", name="Alfa", notes="", status="playing", zerado=False,
                           playtime=0, save=lambda: None, update=lambda: None)
    SessionWindow(jogo).present()
conquista_aviso.mostrar(conquista_aviso.Aviso("Conquista desbloqueada", "Primeira", "", ""))
def fechar():
    ordem.append(["antes", visiveis()])
    principal.close()
QTimer.singleShot(500, fechar)
QTimer.singleShot(5000, lambda: (ordem.append(["prazo", visiveis()]), app.exit(2)))
codigo = app.exec()
print(json.dumps({"codigo": codigo, "ordem": ordem, "na_tela": conquista_aviso.na_tela()}))
"""


@pytest.mark.parametrize(("sessao", "antes"), [
    ("sem", ["aviso", "principal"]),
    ("com", ["Jogando Alfa", "aviso", "principal"]),
])  # fmt: skip
def test_fechar_a_principal_com_o_aviso_na_tela_encerra_o_app(sessao, antes):
    """I1 da revisão final do plano 6: o aviso (janela de topo sem dono, D59) não segura o app aberto."""
    ambiente = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    resultado = subprocess.run(
        [sys.executable, "-c", _SAIDA_COM_O_AVISO, sessao], cwd=RAIZ, env=ambiente, capture_output=True,
        text=True, timeout=60, check=False,
    )  # fmt: skip
    assert resultado.returncode == 0, resultado.stderr
    saida = json.loads(resultado.stdout.strip().splitlines()[-1])
    # O aviso sai no `saindo`, sem depender do vigia; no `aboutToQuit` nenhuma janela sobrou na tela.
    assert saida["ordem"] == [["antes", antes], "aviso.fechar", ["aboutToQuit", []]]
    assert saida["codigo"] == 0
    assert saida["na_tela"] is None


def test_fechar_a_principal_sem_sessao_nao_sai(app_qt, monkeypatch):
    app = _app(monkeypatch)
    app.sessao._sair = lambda: pytest.fail("saiu sem sessão manual")  # noqa: SLF001
    app.janela.show()
    app.janela.close()
    _esperar()
    app.fechar()


def test_terminar_pela_manual_com_a_principal_escondida(app_qt, monkeypatch, isolado):
    monkeypatch.setattr(modulo, "_posicionar", lambda *a: None)
    app = _app(monkeypatch)
    app.janela.show()
    janela = _abrir(app)
    app.janela.hide()  # fechada pela barra de tarefas, sem passar pelo `closing`
    _esperar()
    assert SessionWindow.active is not None and janela.isVisible()
    QMetaObject.invokeMethod(_achar(janela, "botaoTermineiDaJanela"), "click", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: SessionWindow.active is None)
    assert app.janela.isVisible()  # a principal volta
    assert len(isolado) == 1
    app.fechar()
