"""Testes do rastreio de chamadas do log detalhado (sys.monitoring)."""

import json
import logging
import re
import sys
import threading

import pytest

from kyron.logging import detalhado

# Módulo de exemplo com __name__ em kyron.*, para ser reconhecido como do app.
_FONTE = '''
def x(a):
    return a + 1

def v():
    return w()

def w():
    return x(a=1)

def levanta():
    raise ValueError("falhou")

def captura():
    try:
        levanta()
    except ValueError:
        return "ok"

class Ruim:
    def __repr__(self):
        raise RuntimeError("sem repr")

class ReprDoApp:
    def __repr__(self):
        return "<ReprDoApp>"

def recebe(valor):
    return None

def gerador():
    yield 1
    yield 2

def abandona():
    g = gerador()
    next(g)
    g.close()
    return x(1)
'''


@pytest.fixture
def app():
    espaco = {"__name__": "kyron.teste_rastreio"}
    exec(compile(_FONTE, "<teste>", "exec"), espaco)  # pylint: disable=exec-used
    detalhado.instalar_rastreio()
    try:
        yield type("Modulo", (), espaco)
    finally:
        detalhado.remover_rastreio()


def _linhas(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "kyron.rastreio"]


def _com_log(caplog):
    caplog.set_level(logging.DEBUG, logger="kyron.rastreio")


def test_cadeia_em_ordem_com_profundidade(app, caplog):
    _com_log(caplog)
    app.v()
    linhas = _linhas(caplog)
    esperado = [
        r"^1 > kyron\.teste_rastreio\.v\(",
        r"^2 > kyron\.teste_rastreio\.w\(",
        r"^3 > kyron\.teste_rastreio\.x\(",
        r"^3 < kyron\.teste_rastreio\.x ",
        r"^2 < kyron\.teste_rastreio\.w ",
        r"^1 < kyron\.teste_rastreio\.v ",
    ]
    assert len(linhas) == 6
    for linha, padrao in zip(linhas, esperado):
        assert re.search(padrao, linha), linha


def test_argumentos_e_retorno_aparecem(app, caplog):
    _com_log(caplog)
    app.x(1)
    linhas = _linhas(caplog)
    assert "x(a=1)" in linhas[0]
    assert " = 2 (" in linhas[1] and linhas[1].endswith(" ms)")


def test_excecao_registrada_e_profundidade_volta(app, caplog):
    _com_log(caplog)
    assert app.captura() == "ok"
    linhas = _linhas(caplog)
    assert any(" ! kyron.teste_rastreio.levanta levantou ValueError" in l for l in linhas)
    caplog.clear()
    app.v()
    assert _linhas(caplog)[0].startswith("1 > ")


def test_thread_secundaria_e_rastreada(app, caplog):
    _com_log(caplog)
    t = threading.Thread(target=app.x, args=(1,), name="fio-de-teste")
    t.start()
    t.join()
    nomes = {r.threadName for r in caplog.records if r.name == "kyron.rastreio"}
    assert nomes == {"fio-de-teste"}


def test_repr_que_levanta_nao_quebra(app, caplog):
    _com_log(caplog)
    assert app.recebe(app.Ruim()) is None
    assert "<repr falhou>" in _linhas(caplog)[0]


def test_repr_do_app_nao_gera_linha_aninhada(app, caplog):
    _com_log(caplog)
    app.recebe(app.ReprDoApp())
    linhas = _linhas(caplog)
    assert len(linhas) == 2
    assert "<ReprDoApp>" in linhas[0]
    assert not any("__repr__" in l for l in linhas)


def test_valor_longo_cortado_em_500(app, caplog):
    _com_log(caplog)
    app.recebe("a" * 10_000)
    assert len(_linhas(caplog)[0]) < 500 + 100
    assert "a" * 501 not in _linhas(caplog)[0]


def test_quebra_de_linha_nao_abre_outra_linha(app, caplog):
    _com_log(caplog)
    app.recebe("a\nb")
    linha = _linhas(caplog)[0]
    assert "\n" not in linha and "\r" not in linha


def test_gerador_nao_acumula_profundidade(app, caplog):
    _com_log(caplog)
    assert list(app.gerador()) == [1, 2]
    caplog.clear()
    app.x(1)
    assert _linhas(caplog)[0].startswith("1 > ")


def test_gerador_abandonado_nao_acumula_profundidade(app, caplog):
    _com_log(caplog)
    # Dentro de outra função: um `close()` que desempilhasse a mais comeria a profundidade dela.
    app.abandona()
    assert [l for l in _linhas(caplog) if ".x(" in l][0].startswith("2 > ")


def test_codigo_de_fora_nao_aparece(app, caplog):
    _com_log(caplog)
    json.dumps({"a": 1})
    assert _linhas(caplog) == []


def test_parser_de_keyvalues_fica_fora_do_rastreio(app, caplog):
    from kyron.conquistas import keyvalues  # noqa: PLC0415

    _com_log(caplog)
    assert keyvalues._texto(b"abc\0", 0) == ("abc", 4)  # noqa: SLF001
    assert _linhas(caplog) == []


def test_remover_libera_a_ferramenta(app, caplog):
    detalhado.remover_rastreio()
    assert sys.monitoring.get_tool(sys.monitoring.PROFILER_ID) is None
    _com_log(caplog)
    app.x(1)
    assert _linhas(caplog) == []


def test_ativo_variavel_vence_constante(monkeypatch):
    monkeypatch.setattr(detalhado, "ATIVO", True)
    monkeypatch.setenv("KYRON_LOG_DETALHADO", "0")
    assert detalhado.ativo() is False
    monkeypatch.setattr(detalhado, "ATIVO", False)
    monkeypatch.setenv("KYRON_LOG_DETALHADO", "1")
    assert detalhado.ativo() is True
    monkeypatch.delenv("KYRON_LOG_DETALHADO")
    assert detalhado.ativo() is False
    monkeypatch.setattr(detalhado, "ATIVO", True)
    assert detalhado.ativo() is True


def _modulo(nome, fonte):
    espaco = {"__name__": nome}
    exec(compile(fonte, "<teste>", "exec"), espaco)  # pylint: disable=exec-used
    return type("Modulo", (), espaco)


def test_excecao_de_terceiro_atravessa_o_rastreio_intacta(app, caplog):
    _com_log(caplog)
    terceiro = _modulo("terceiro.a", "def levanta():\n    raise KeyError('x')\n")
    erro = None
    try:
        terceiro.levanta()
    except KeyError as e:
        erro = e
    assert erro is not None and erro.args == ("x",)
    assert _linhas(caplog) == []


_IDENTICA = "def f():\n    return 1\n"


def test_funcao_identica_de_terceiro_nao_esconde_a_do_app(app, caplog):  # pylint: disable=unused-argument
    _com_log(caplog)
    detalhado.remover_rastreio()
    terceiro = _modulo("terceiro.b", _IDENTICA)
    meu = _modulo("kyron.a", _IDENTICA)
    detalhado.instalar_rastreio()
    terceiro.f()
    meu.f()
    assert any("kyron.a.f" in l for l in _linhas(caplog))


def test_ferramenta_ocupada_so_gera_aviso(monkeypatch, caplog):
    from kyron.logging import setup  # pylint: disable=import-outside-toplevel

    monkeypatch.setenv("KYRON_LOG_DETALHADO", "1")
    sys.monitoring.use_tool_id(sys.monitoring.PROFILER_ID, "outra")
    try:
        setup._ligar_rastreio()  # pylint: disable=protected-access
    finally:
        sys.monitoring.free_tool_id(sys.monitoring.PROFILER_ID)
    assert any("Log detalhado desligado" in r.getMessage() for r in caplog.records)


@pytest.fixture
def filtro(app_qt, monkeypatch, caplog):
    """O filtro instalado no app de teste; ao fim sai do app (o app_qt vive a sessão toda)."""
    monkeypatch.setenv("KYRON_LOG_DETALHADO", "1")
    caplog.set_level(logging.DEBUG, logger="kyron.interface")
    instalado = detalhado.instalar_filtro(app_qt)
    yield instalado
    app_qt.removeEventFilter(instalado)
    instalado.setParent(None)


def _ui(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "kyron.interface"]


@pytest.fixture
def janela(app_qt):
    from PySide6.QtGui import QWindow  # pylint: disable=import-outside-toplevel

    j = QWindow()
    j.setObjectName("janelaTeste")
    j.resize(100, 100)
    yield j
    j.destroy()


def test_clique_e_registrado(filtro, janela, caplog):  # pylint: disable=unused-argument
    from PySide6.QtCore import Qt  # pylint: disable=import-outside-toplevel
    from PySide6.QtTest import QTest  # pylint: disable=import-outside-toplevel

    janela.show()
    QTest.mouseClick(janela, Qt.MouseButton.LeftButton)
    assert any(l.startswith("clique em QWindow('janelaTeste')") for l in _ui(caplog))


def test_tecla_e_registrada(filtro, janela, caplog):  # pylint: disable=unused-argument
    from PySide6.QtCore import Qt  # pylint: disable=import-outside-toplevel
    from PySide6.QtTest import QTest  # pylint: disable=import-outside-toplevel

    janela.show()
    QTest.keyClick(janela, Qt.Key.Key_A)
    assert any(l.startswith("tecla em QWindow('janelaTeste')") for l in _ui(caplog))


def test_janela_mostrar_e_esconder(filtro, janela, caplog):  # pylint: disable=unused-argument
    janela.show()
    janela.hide()
    linhas = _ui(caplog)
    assert any(l.startswith("mostrou em QWindow") for l in linhas)
    assert any(l.startswith("escondeu em QWindow") for l in linhas)


def test_movimento_do_mouse_fica_de_fora(filtro, janela, caplog):  # pylint: disable=unused-argument
    from PySide6.QtCore import QPoint  # pylint: disable=import-outside-toplevel
    from PySide6.QtTest import QTest  # pylint: disable=import-outside-toplevel

    janela.show()
    caplog.clear()
    QTest.mouseMove(janela, QPoint(10, 10))
    assert _ui(caplog) == []


_QML_POPUP = b"""
import QtQuick
import QtQuick.Controls
Item {
    property alias p: popup
    Popup { id: popup; objectName: "meuPopup"; width: 10; height: 10 }
}
"""

_QML_LOADER = b"""
import QtQuick
Item {
    Loader { objectName: "meuLoader"; source: "Filha.qml" }
}
"""


def _criar_qml(fonte, pasta):
    from PySide6.QtCore import QUrl  # pylint: disable=import-outside-toplevel
    from PySide6.QtQml import QQmlComponent, QQmlEngine  # pylint: disable=import-outside-toplevel

    motor = QQmlEngine()
    from kyron.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    componente = QQmlComponent(motor)
    componente.setData(fonte, QUrl.fromLocalFile(str(pasta / "Tela.qml")))
    objeto = componente.create()
    assert objeto is not None, componente.errorString()
    return motor, componente, objeto


def _processar():
    from PySide6.QtCore import QCoreApplication  # pylint: disable=import-outside-toplevel

    for _ in range(5):
        QCoreApplication.processEvents()


def test_popup_do_qml_abrir_e_fechar(filtro, caplog, tmp_path):  # pylint: disable=unused-argument
    from PySide6.QtCore import QMetaObject, QObject  # pylint: disable=import-outside-toplevel
    from PySide6.QtQuick import QQuickWindow  # pylint: disable=import-outside-toplevel

    motor, componente, raiz = _criar_qml(_QML_POPUP, tmp_path)
    janela = QQuickWindow()
    raiz.setParentItem(janela.contentItem())
    _processar()
    popup = raiz.findChild(QObject, "meuPopup")
    QMetaObject.invokeMethod(popup, "open")
    _processar()
    QMetaObject.invokeMethod(popup, "close")
    _processar()
    linhas = _ui(caplog)
    assert any("popup aberto" in l and "meuPopup" in l for l in linhas), linhas
    assert any("popup fechado" in l and "meuPopup" in l for l in linhas), linhas
    del janela, raiz, componente, motor


def test_loader_do_qml_registra_a_tela(filtro, caplog, tmp_path):  # pylint: disable=unused-argument
    (tmp_path / "Filha.qml").write_text("import QtQuick\nItem {}\n", encoding="utf-8")
    motor, componente, raiz = _criar_qml(_QML_LOADER, tmp_path)
    _processar()
    linhas = _ui(caplog)
    assert any("tela carregada" in l and "meuLoader" in l for l in linhas), linhas
    del raiz, componente, motor


def test_destinatario_destruido_nao_levanta(filtro):
    import shiboken6  # pylint: disable=import-outside-toplevel
    from PySide6.QtCore import QEvent, QObject  # pylint: disable=import-outside-toplevel

    alvo = QObject()
    shiboken6.delete(alvo)
    assert filtro.eventFilter(alvo, QEvent(QEvent.Type.Show)) is False


def test_desligado_nao_instala(monkeypatch, app_qt):
    from kyron.logging import setup  # pylint: disable=import-outside-toplevel

    monkeypatch.setenv("KYRON_LOG_DETALHADO", "0")
    assert detalhado.instalar_filtro(app_qt) is None
    chamadas = []
    monkeypatch.setattr(detalhado, "instalar_rastreio", lambda: chamadas.append(1))
    setup._ligar_rastreio()  # pylint: disable=protected-access
    assert chamadas == []


@pytest.fixture
def config_capturada(monkeypatch):
    """Roda o setup_logging sem mexer no logging do processo: devolve o dicionário entregue ao dictConfig."""
    from kyron.logging import setup  # pylint: disable=import-outside-toplevel

    capturado = {}
    monkeypatch.setattr(setup.logging_dot_config, "dictConfig", capturado.update)
    monkeypatch.setattr(setup, "_enable_windows_ansi", lambda: None)
    monkeypatch.setattr(setup, "registrar_excecoes_nao_tratadas", lambda: None)
    monkeypatch.setattr(setup, "registrar_avisos_do_qt", lambda: None)
    monkeypatch.setattr(detalhado, "instalar_rastreio", lambda: None)
    antes = dict(setup.LIB_LOGGERS["urllib3"])
    yield setup, capturado
    assert setup.LIB_LOGGERS["urllib3"] == antes


def test_config_ligada_abre_niveis(monkeypatch, config_capturada):
    setup, config = config_capturada
    monkeypatch.setenv("KYRON_LOG_DETALHADO", "1")
    setup.setup_logging()
    assert config["loggers"]["urllib3"]["level"] == "DEBUG"
    assert config["loggers"]["PIL"]["level"] == "WARNING" and config["loggers"]["tinytuya"]["level"] == "WARNING"
    assert config["formatters"]["file_formatter"]["format"] == (
        "%(asctime)s.%(msecs)03d [%(threadName)s] %(levelname)s: %(message)s"
    )
    assert config["handlers"]["file_handler"]["sem_limite"] is True


def test_config_desligada_igual_a_hoje(monkeypatch, config_capturada):
    setup, config = config_capturada
    monkeypatch.setenv("KYRON_LOG_DETALHADO", "0")
    setup.setup_logging()
    assert config["loggers"]["urllib3"]["level"] == "INFO"
    assert config["formatters"]["file_formatter"]["format"] == "%(asctime)s - %(levelname)s: %(message)s"
    assert config["handlers"]["file_handler"]["sem_limite"] is False


def test_depuracao_do_qt_so_no_modo_detalhado(monkeypatch, caplog):
    from types import SimpleNamespace  # pylint: disable=import-outside-toplevel

    from PySide6.QtCore import QtMsgType  # pylint: disable=import-outside-toplevel

    from kyron.logging import setup  # pylint: disable=import-outside-toplevel

    caplog.set_level(logging.DEBUG)
    contexto = SimpleNamespace(file=None, line=0)
    monkeypatch.setenv("KYRON_LOG_DETALHADO", "0")
    setup._registrar_do_qt(QtMsgType.QtDebugMsg, contexto, "fora")  # pylint: disable=protected-access
    monkeypatch.setenv("KYRON_LOG_DETALHADO", "1")
    setup._registrar_do_qt(QtMsgType.QtDebugMsg, contexto, "dentro")  # pylint: disable=protected-access
    mensagens = [r.getMessage() for r in caplog.records]
    assert "Qt-DEBUG: dentro" in mensagens and not any("fora" in m for m in mensagens)


def test_subclasse_python_com_pai_continua_inteira_sob_o_filtro(filtro):  # pylint: disable=unused-argument
    """O ChildAdded dispara dentro do construtor; o filtro não pode tocar nem guardar o filho (sem processEvents aqui)."""
    from PySide6.QtCore import Property, QEvent, QObject, QMetaObject, Slot  # pylint: disable=import-outside-toplevel

    chamadas = []

    class Filho(QObject):
        def __init__(self, pai):
            super().__init__(pai)
            self._valor = 7

        def event(self, e):
            if e.type() == QEvent.Type.User:
                chamadas.append("event")
            return super().event(e)

        @Slot()
        def tocar(self):
            chamadas.append("slot")

        def _ler(self):
            return self._valor

        valor = Property(int, _ler)

    pai = QObject()
    filho = Filho(pai)
    filho.setObjectName("f")
    from PySide6.QtCore import QCoreApplication  # pylint: disable=import-outside-toplevel

    QCoreApplication.sendEvent(filho, QEvent(QEvent.Type.User))
    assert QMetaObject.invokeMethod(filho, "tocar")
    assert chamadas == ["event", "slot"]
    assert filho.property("valor") == 7
    assert type(pai.children()[0]) is Filho  # pylint: disable=unidiomatic-typecheck


@pytest.fixture
def logging_do_processo(monkeypatch):
    """Devolve o logging do processo ao que era e neutraliza os ganchos globais do setup_logging."""
    from kyron.logging import setup  # pylint: disable=import-outside-toplevel

    raiz = logging.getLogger()
    antes_raiz = (list(raiz.handlers), raiz.level)
    antes = {
        n: (lg.disabled, lg.level, list(lg.handlers), lg.propagate)
        for n, lg in logging.root.manager.loggerDict.items()
        if isinstance(lg, logging.Logger)
    }
    for nome in ("_enable_windows_ansi", "registrar_excecoes_nao_tratadas", "registrar_avisos_do_qt"):
        monkeypatch.setattr(setup, nome, lambda: None)
    monkeypatch.setattr(setup, "registrar_quedas_nativas", lambda _arquivo: None)
    yield setup
    detalhado.remover_rastreio()
    for handler in list(raiz.handlers):
        if handler not in antes_raiz[0]:
            raiz.removeHandler(handler)
            handler.close()
    raiz.setLevel(antes_raiz[1])
    for nome, lg in list(logging.root.manager.loggerDict.items()):
        if not isinstance(lg, logging.Logger):
            continue
        if nome in antes:
            lg.disabled, lg.level, lg.handlers, lg.propagate = antes[nome][0], antes[nome][1], antes[nome][2], antes[nome][3]
        else:
            for handler in list(lg.handlers):
                lg.removeHandler(handler)
                handler.close()
            lg.level, lg.propagate = logging.NOTSET, True


def _setup_real(setup, monkeypatch, tmp_path, ligado):
    from kyron import shared  # pylint: disable=import-outside-toplevel

    monkeypatch.setenv("KYRON_LOG_DETALHADO", "1" if ligado else "0")
    monkeypatch.setattr(shared, "log_dir", tmp_path)
    setup.setup_logging()
    return tmp_path / "cartridges.log"


def _ler_log(arquivo):
    for handler in logging.getLogger().handlers:
        handler.flush()
    return arquivo.read_text(encoding="utf-8")


def test_setup_real_grava_rastreio_e_interface_no_arquivo(logging_do_processo, monkeypatch, tmp_path):
    modulo = _modulo("kyron.teste_setup_real", "def f(a):\n    return a\n")
    arquivo = _setup_real(logging_do_processo, monkeypatch, tmp_path, True)
    modulo.f(41)
    logging.getLogger("kyron.interface").debug("clique em teste")
    texto = _ler_log(arquivo)
    assert "kyron.teste_setup_real.f(a=41)" in texto
    assert "clique em teste" in texto
    assert "[MainThread]" in texto


def test_logger_de_modulo_criado_antes_do_setup_continua_escrevendo(logging_do_processo, monkeypatch, tmp_path):
    previo = logging.getLogger("kyron.teste_previo_ao_setup")
    for ligado in (True, False):
        detalhado.remover_rastreio()
        arquivo = _setup_real(logging_do_processo, monkeypatch, tmp_path / str(ligado), ligado)
        previo.warning("linha do modulo %s", ligado)
        assert f"linha do modulo {ligado}" in _ler_log(arquivo)


def test_qml_real_com_filtro_e_rastreio_nao_gera_erros_do_qt(filtro, tmp_path):  # pylint: disable=unused-argument
    """Modo ligado, QML de verdade: o filtro e o rastreio não podem quebrar objetos Python com pai."""
    from PySide6.QtCore import qInstallMessageHandler  # pylint: disable=import-outside-toplevel

    from tests.apoio_janela_atualizacao import Janela, esperar  # pylint: disable=import-outside-toplevel

    mensagens = []
    anterior = qInstallMessageHandler(lambda _t, _c, m: mensagens.append(m))
    detalhado.instalar_rastreio()
    janela = None
    try:
        janela = Janela()
        esperar()
    finally:
        if janela is not None:
            janela.fechar()
            esperar()
        detalhado.remover_rastreio()
        qInstallMessageHandler(anterior)
    ruins = [m for m in mensagens if "undefined" in m or "is not a function" in m or "No Wrapper found" in m]
    assert ruins == []


_QML_BOTAO = b"""
import QtQuick
Item { property string text: ""; width: 80; height: 30 }
"""

_QML_DIALOGO = b"""
import QtQuick
Item { width: 100; height: 100 }
"""

_QML_CAIXA = b"""
import QtQuick
Item { width: 10; height: 10 }
"""

_QML_PAGINA = b"""
import QtQuick
Item {
    objectName: "paginaDeTeste"
    Caixa { objectName: "caixaDaPagina" }
}
"""

_QML_BOTOES = b"""
import QtQuick
Item {
    width: 300; height: 300
    Dialogo {
        objectName: "confirmaTeste"
        Botao { objectName: "botaoCancelarTeste"; text: "Cancelar"; MouseArea { objectName: "" } }
    }
}
"""

_QML_PILHA = b"""
import QtQuick
import QtQuick.Controls
Item {
    width: 200; height: 200
    StackView { id: pilha; objectName: "pilhaTeste"; anchors.fill: parent }
    Component { id: pagina; Pagina {} }
    function empurrar() { pilha.push(pagina) }
}
"""


def _tipos_qml(pasta):
    for nome, fonte in (("Botao", _QML_BOTAO), ("Dialogo", _QML_DIALOGO), ("Caixa", _QML_CAIXA), ("Pagina", _QML_PAGINA)):
        (pasta / f"{nome}.qml").write_bytes(fonte)


def _janela_com(fonte, pasta):
    from PySide6.QtQuick import QQuickWindow  # pylint: disable=import-outside-toplevel

    _tipos_qml(pasta)
    motor, componente, raiz = _criar_qml(fonte, pasta)
    janela = QQuickWindow()
    raiz.setParentItem(janela.contentItem())
    janela.resize(300, 300)
    janela.show()
    _processar()
    return motor, componente, raiz, janela


def test_quem_nomeia_o_botao_com_texto_e_o_dialogo_que_o_contem(filtro, tmp_path):  # pylint: disable=unused-argument
    from PySide6.QtCore import QObject  # pylint: disable=import-outside-toplevel
    from PySide6.QtQuick import QQuickItem  # pylint: disable=import-outside-toplevel

    motor, componente, raiz, janela = _janela_com(_QML_BOTOES, tmp_path)
    botao = raiz.findChild(QObject, "botaoCancelarTeste")
    mouse = botao.childItems()[0]
    assert detalhado._quem(botao) == "Botao('botaoCancelarTeste') texto='Cancelar' dentro de Dialogo('confirmaTeste')"  # pylint: disable=protected-access
    assert detalhado._quem(mouse) == "QQuickMouseArea('') dentro de Botao('botaoCancelarTeste')"  # pylint: disable=protected-access
    assert isinstance(botao, QQuickItem)
    janela.destroy()
    del raiz, componente, motor


def test_dialogo_que_so_alterna_visible_gera_uma_linha_por_mudanca(filtro, caplog, tmp_path):  # pylint: disable=unused-argument
    from PySide6.QtCore import QObject  # pylint: disable=import-outside-toplevel

    motor, componente, raiz, janela = _janela_com(_QML_BOTOES, tmp_path)
    dialogo = raiz.findChild(QObject, "confirmaTeste")
    caplog.clear()
    dialogo.setProperty("visible", False)
    _processar()
    dialogo.setProperty("visible", True)
    _processar()
    linhas = _ui(caplog)
    sumiu = [l for l in linhas if l.startswith("sumiu")]
    assert len(sumiu) == 1 and sumiu[0].startswith("sumiu: Dialogo('confirmaTeste')"), linhas
    assert len([l for l in linhas if l.startswith("apareceu")]) == 1, linhas  # os filhos não entram na enxurrada
    assert not any("botaoCancelarTeste" in l and l.startswith(("apareceu:", "sumiu:")) for l in linhas), linhas
    janela.destroy()
    del raiz, componente, motor


def test_pagina_empurrada_na_pilha_e_nomeada_e_seus_filhos_vigiados(filtro, caplog, tmp_path):  # pylint: disable=unused-argument
    from PySide6.QtCore import QMetaObject, QObject  # pylint: disable=import-outside-toplevel

    motor, componente, raiz, janela = _janela_com(_QML_PILHA, tmp_path)
    caplog.clear()
    QMetaObject.invokeMethod(raiz, "empurrar")
    _processar()
    assert any(l.startswith("tela na pilha:") and "paginaDeTeste" in l for l in _ui(caplog)), _ui(caplog)
    caixa = raiz.findChild(QObject, "caixaDaPagina")
    caplog.clear()
    caixa.setProperty("visible", False)
    _processar()
    assert any(l.startswith("sumiu:") and "caixaDaPagina" in l for l in _ui(caplog)), _ui(caplog)
    janela.destroy()
    del raiz, componente, motor


def test_dialogo_real_do_aplicativo_abrir_e_fechar_uma_linha_cada(filtro, caplog):  # pylint: disable=unused-argument
    from PySide6.QtCore import QMetaObject  # pylint: disable=import-outside-toplevel

    from tests.apoio_janela_atualizacao import Janela, avaliar, esperar  # pylint: disable=import-outside-toplevel

    janela = Janela()
    try:
        janela.janela.show()
        esperar()
        dialogo = janela.achar("confirmacaoDoApp")
        caplog.clear()
        QMetaObject.invokeMethod(dialogo, "abrir")
        esperar()
        abriu = [l for l in _ui(caplog) if l.startswith(("apareceu", "sumiu"))]
        avaliar(dialogo, "resolver(false)")
        esperar()
        fechou = [l for l in _ui(caplog) if l.startswith(("apareceu", "sumiu"))][len(abriu) :]
    finally:
        janela.fechar()
        esperar()
    assert len(abriu) == 1 and abriu[0].startswith("apareceu: DialogoDeConfirmacao('confirmacaoDoApp')"), abriu
    assert "dentro de Avisos('camadaDeAvisos')" in abriu[0]
    assert len(fechou) == 1 and fechou[0].startswith("sumiu: DialogoDeConfirmacao('confirmacaoDoApp')"), fechou


def test_pagina_de_zerados_no_aplicativo_real_e_nomeada(filtro, caplog):  # pylint: disable=unused-argument
    from PySide6.QtCore import QPoint, QPointF, Qt  # pylint: disable=import-outside-toplevel
    from PySide6.QtTest import QTest  # pylint: disable=import-outside-toplevel

    from tests.apoio_janela_atualizacao import Janela, esperar  # pylint: disable=import-outside-toplevel

    janela = Janela()
    try:
        janela.janela.show()
        esperar()
        botao = janela.achar("botaoZerados")
        centro = botao.mapToScene(QPointF(botao.width() / 2, botao.height() / 2))
        caplog.clear()
        QTest.mouseClick(janela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(int(centro.x()), int(centro.y())))
        esperar()
    finally:
        janela.fechar()
        esperar()
    linhas = _ui(caplog)
    assert any(l.startswith("tela na pilha:") and "paginaDeZerados" in l for l in linhas), linhas
    assert any(l.startswith("clique em") and "botaoZerados" in l for l in linhas), linhas


def test_loader_com_source_component_nomeia_o_item(filtro, caplog, tmp_path):  # pylint: disable=unused-argument
    """O Loader é achado pela varredura da janela; o item carregado depois entra na linha."""
    fonte = b"""
import QtQuick
Item {
    property bool ligado: false
    Component { id: comp; Item { objectName: "itemCarregado" } }
    Loader { objectName: "loaderDeComponente"; sourceComponent: comp; active: parent.ligado }
}
"""
    motor, componente, raiz, janela = _janela_com(fonte, tmp_path)
    caplog.clear()
    raiz.setProperty("ligado", True)
    _processar()
    linhas = [l for l in _ui(caplog) if l.startswith("tela carregada")]
    assert linhas and "itemCarregado" in linhas[0] and "source=" not in linhas[0], linhas
    janela.destroy()
    del raiz, componente, motor
