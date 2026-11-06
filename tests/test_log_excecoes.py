"""Erro não tratado vai para o cartridges.log, não só para o console.

O app instalado roda no pythonw, sem console: um erro dentro de um slot do Qt (abrir a tela de edição, salvar) sumia
sem deixar rastro no log. Todo teste devolve os ganchos do processo (`sys.excepthook`, `threading.excepthook`,
`sys.unraisablehook`, o gancho de mensagens do Qt) e o estado do `erro_inesperado` antes e depois.
"""

import logging
import os
import subprocess
import sys
import textwrap
import threading
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer, qInstallMessageHandler, qWarning

from kyron import shared
from kyron.logging import setup
from kyron.logging.session_file_handler import SessionFileHandler
from kyron.utils import erro_inesperado

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def ganchos_do_processo(monkeypatch):
    """Antes e depois: os ganchos de exceção, o de mensagens do Qt e o estado do aviso voltam ao que eram."""
    guardados = (sys.excepthook, threading.excepthook, sys.unraisablehook)
    anterior_do_qt = qInstallMessageHandler(None)
    monkeypatch.setattr(setup, "_qt_registrado", False)
    monkeypatch.setattr(erro_inesperado, "_ja_avisados", set())
    monkeypatch.setattr(erro_inesperado, "_aberto", False)
    yield
    sys.excepthook, threading.excepthook, sys.unraisablehook = guardados
    qInstallMessageHandler(anterior_do_qt)


def test_aviso_critico_do_qt_vai_para_o_log(app_qt, caplog):  # noqa: ARG001
    from PySide6.QtCore import qCritical  # noqa: PLC0415

    setup.registrar_avisos_do_qt()
    qCritical("a cena parou de responder")

    registro = next(r for r in caplog.records if "a cena parou" in r.getMessage())
    assert registro.levelno == logging.ERROR
    assert registro.getMessage().startswith("Qt-CRITICAL: ")


def test_aviso_do_qt_com_acento_chega_inteiro_ao_log(app_qt, caplog):  # noqa: ARG001
    setup.registrar_avisos_do_qt()
    qWarning("Capa de Plaž — ação")

    registro = next(r for r in caplog.records if "Capa de" in r.getMessage())
    assert registro.levelno == logging.WARNING
    assert registro.getMessage() == "Qt-WARNING: Capa de Plaž — ação"


def test_aviso_do_qml_leva_o_arquivo_e_a_linha(app_qt, caplog):  # noqa: ARG001
    from PySide6.QtCore import QUrl  # noqa: PLC0415
    from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: PLC0415

    setup.registrar_avisos_do_qt()
    motor = QQmlEngine()
    from kyron.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    componente = QQmlComponent(motor)
    componente.setData(b"import QtQml\nQtObject {\n    Component.onCompleted: console.warn('aviso do qml')\n}\n", QUrl("file:///teste/Aviso.qml"))
    objeto = componente.create()

    registro = next(r for r in caplog.records if "aviso do qml" in r.getMessage())
    assert registro.levelno == logging.WARNING
    assert "Aviso.qml:3" in registro.getMessage()
    del objeto, componente, motor


def test_depuracao_do_qt_e_descartada_e_informacao_vira_info(app_qt, caplog):  # noqa: ARG001
    from PySide6.QtCore import qDebug, qInfo  # noqa: PLC0415

    caplog.set_level(logging.DEBUG)
    setup.registrar_avisos_do_qt()
    qDebug("so de depuracao")
    qInfo("uma informacao")
    assert not any("so de depuracao" in r.getMessage() for r in caplog.records)
    registro = next(r for r in caplog.records if "uma informacao" in r.getMessage())
    assert registro.levelno == logging.INFO and registro.getMessage() == "Qt-INFO: uma informacao"


def test_gancho_do_qt_registra_uma_vez_so(app_qt, monkeypatch):  # noqa: ARG001
    instalados = []
    monkeypatch.setattr(setup, "qInstallMessageHandler", lambda gancho: instalados.append(gancho))
    setup.registrar_avisos_do_qt()
    setup.registrar_avisos_do_qt()
    assert len(instalados) == 1


def test_aviso_do_qt_no_gancho_nao_entra_em_laco(app_qt, caplog):  # noqa: ARG001
    """Um aviso do Qt nascido enquanto outro é registrado (um handler do log que avisa) nunca gera outro registro.

    O Qt 6 já manda ao stderr o `qWarning` aninhado; o gancho também se protege, para a mensagem que chega por outro
    caminho (outra entrada do Qt, ou o gancho chamado de novo na mesma thread).
    """
    from types import SimpleNamespace  # noqa: PLC0415

    from PySide6.QtCore import QtMsgType  # noqa: PLC0415

    class AvisaDeNovo(logging.Handler):
        def emit(self, registro):
            if registro.getMessage().startswith("Qt-"):
                qWarning("de dentro do gancho")
                setup._registrar_do_qt(QtMsgType.QtWarningMsg, SimpleNamespace(file=None, line=0), "de dentro, direto")  # noqa: SLF001

    setup.registrar_avisos_do_qt()
    raiz = logging.getLogger()
    handler = AvisaDeNovo()
    raiz.addHandler(handler)
    try:
        qWarning("o primeiro")
    finally:
        raiz.removeHandler(handler)
    mensagens = [r.getMessage() for r in caplog.records]
    assert "Qt-WARNING: o primeiro" in mensagens
    assert not any("de dentro" in m for m in mensagens)


def test_gancho_do_qt_que_falha_nao_levanta(app_qt, monkeypatch):  # noqa: ARG001
    setup.registrar_avisos_do_qt()
    monkeypatch.setattr(setup.logging, "log", lambda *_a, **_k: 1 / 0)
    qWarning("nada sobe para o Qt")  # não levanta nem derruba


def test_erro_num_slot_do_qt_vai_para_o_log(app_qt, flush_idle, caplog):  # noqa: ARG001
    setup.registrar_excecoes_nao_tratadas()

    def falha():
        raise RuntimeError("erro no slot")

    QTimer.singleShot(0, falha)
    flush_idle()

    registro = next(r for r in caplog.records if r.exc_info)
    assert registro.exc_info[1].args == ("erro no slot",)


def test_erro_numa_thread_vai_para_o_log(caplog):
    setup.registrar_excecoes_nao_tratadas()

    def falha():
        raise RuntimeError("erro na thread")

    thread = threading.Thread(target=falha)
    thread.start()
    thread.join()

    registro = next(r for r in caplog.records if r.exc_info)
    assert registro.exc_info[1].args == ("erro na thread",)


def test_erro_nao_levantavel_vai_para_o_log(caplog):
    # Um erro num __del__ não sobe para ninguém: o Python o entrega ao sys.unraisablehook.
    import gc  # noqa: PLC0415

    setup.registrar_excecoes_nao_tratadas()

    class Quebra:
        def __del__(self):
            raise RuntimeError("erro no destrutor")

    Quebra()
    gc.collect()

    registro = next(r for r in caplog.records if r.exc_info)
    assert registro.getMessage().startswith("Erro não tratado (não levantável)")
    assert registro.exc_info[1].args == ("erro no destrutor",)


def _rodar(script, tmp_path):
    ambiente = {
        **os.environ,
        "KYRON_DADOS": str(tmp_path),
        "KYRON_REGISTRO": rf"Software\KyronTestes\log-{uuid.uuid4()}",
        "QT_QPA_PLATFORM": "offscreen",
    }
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)], cwd=RAIZ, env=ambiente, capture_output=True, text=True,
        timeout=60, check=False,
    )  # fmt: skip


def test_queda_nativa_fica_no_arquivo_de_log(tmp_path):
    # Uma queda em C (driver de vídeo, Qt) mata o processo sem passar pelo Python: só o faulthandler deixa a pilha.
    log = tmp_path / "cartridges.log"
    filho = _rodar(
        f"""
        import faulthandler
        from kyron.logging import setup
        arquivo = open({str(log)!r}, "w", encoding="utf-8")
        arquivo.write("antes da queda\\n")
        arquivo.flush()
        setup.registrar_quedas_nativas(arquivo)
        faulthandler._sigsegv()
        """,
        tmp_path,
    )
    assert log.exists(), filho.stderr
    texto = log.read_text(encoding="utf-8", errors="replace")
    assert texto.startswith("antes da queda")
    assert "Fatal Python error" in texto


def test_logging_setup_sem_gi(tmp_path):
    """O log completo (arquivo, console, ganchos, informações do sistema) sem o `gi`."""
    filho = _rodar(
        """
        import sys
        sys.modules["gi"] = None
        import logging
        from kyron import shared
        from kyron.logging import setup
        from kyron.utils import erro_inesperado
        setup.setup_logging()
        setup.log_system_info()
        logging.getLogger().handlers[0].flush()
        for h in logging.getLogger().handlers:
            h.flush()
        texto = (shared.log_dir / "cartridges.log").read_text(encoding="utf-8")
        assert "Starting " in texto and "Python version" in texto, texto
        print("ok")
        """,
        tmp_path,
    )
    assert filho.returncode == 0, filho.stderr
    assert filho.stdout.strip().splitlines()[-1] == "ok"


@pytest.mark.parametrize("detalhado_ativo", [False, True])
def test_setup_logging_que_falha_grava_num_arquivo_da_sessao(monkeypatch, caplog, tmp_path, detalhado_ativo):
    """`dictConfig` embrulha a falha de um handler em `ValueError`: sem console no app instalado, o log vai a um arquivo
    próprio da sessão, na pasta dos logs, que a rotação seguinte comprime e descarta como os outros. Com os guards do
    log normal: o teto de 32 MiB, sem ele só com o log detalhado."""
    from kyron import app as modulo_app  # noqa: PLC0415

    monkeypatch.setattr(modulo_app.detalhado, "ativo", lambda: detalhado_ativo)
    monkeypatch.setattr(shared, "log_dir", tmp_path / "logs")
    chamadas = []

    def falha():
        raise ValueError("rotação quebrada")

    monkeypatch.setattr(modulo_app, "setup_logging", falha)
    monkeypatch.setattr(modulo_app, "log_system_info", lambda: chamadas.append("info"))
    monkeypatch.setattr(modulo_app.logging, "basicConfig", lambda **k: chamadas.append(("basicConfig", k)))
    modulo_app._configurar_log()  # noqa: SLF001
    arquivo = tmp_path / "logs" / f"cartridges-{os.getpid()}.log"
    (nome, argumentos), info = chamadas
    assert (nome, info, argumentos["level"]) == ("basicConfig", "info", logging.DEBUG)
    [reserva] = argumentos["handlers"]
    assert isinstance(reserva, SessionFileHandler)
    assert reserva.sem_limite is detalhado_ativo
    assert reserva.filename == arquivo and arquivo.is_file()
    reserva.close()
    registro = next(r for r in caplog.records if "Não foi possível configurar o log em arquivo" in r.getMessage())
    assert registro.exc_info[1].args == ("rotação quebrada",)


class _AplicativoQueAnota:
    """O `pedir_dialogo` do `Aplicativo`, anotado; ``ao_fechar`` fica para o teste dispensar."""

    def __init__(self, quebra=False):
        self.dialogos = []
        self.quebra = quebra

    def pedir_dialogo(self, titulo, corpo, itens, ao_fechar, preferencias=None):  # noqa: ARG002
        if self.quebra:
            raise RuntimeError("sem tela")
        self.dialogos.append({"titulo": titulo, "corpo": corpo, "itens": itens, "ao_fechar": ao_fechar})


@pytest.fixture
def aviso(app_qt, monkeypatch):  # noqa: ARG001
    aplicativo = _AplicativoQueAnota()
    monkeypatch.setattr(shared, "aplicativo", aplicativo, raising=False)
    setup.registrar_excecoes_nao_tratadas()
    return aplicativo


def _erro_no_slot(texto, flush_idle):
    def falha():
        raise RuntimeError(texto)

    QTimer.singleShot(0, falha)
    flush_idle()


def _avisar(erro, flush_idle):
    try:
        raise erro
    except BaseException:  # noqa: BLE001
        erro_inesperado.avisar(*sys.exc_info()[::2])
    flush_idle()


def test_erro_num_slot_do_qt_abre_o_dialogo(aviso, flush_idle):
    _erro_no_slot("a", flush_idle)
    assert [(d["titulo"], d["corpo"], d["itens"]) for d in aviso.dialogos] == [
        ("Ocorreu um erro inesperado",
         "Uma ação do aplicativo não foi concluída. Os detalhes foram registrados no log.", []),
    ]  # fmt: skip


def test_erro_numa_thread_abre_o_dialogo(aviso, flush_idle):
    def falha():
        raise ValueError("na thread")

    thread = threading.Thread(target=falha)
    thread.start()
    thread.join()
    flush_idle()
    assert len(aviso.dialogos) == 1


def test_o_mesmo_erro_abre_um_dialogo_so(aviso, flush_idle):
    def mesmo_ponto():
        raise RuntimeError("repete")

    for _ in range(2):
        try:
            mesmo_ponto()
        except RuntimeError:
            erro_inesperado.avisar(*sys.exc_info()[::2])
        flush_idle()
        for dialogo in aviso.dialogos:
            dialogo["ao_fechar"]()
    assert len(aviso.dialogos) == 1


def test_com_um_dialogo_aberto_outro_erro_so_vai_para_o_log(aviso, flush_idle):
    _erro_no_slot("primeiro", flush_idle)

    def outro_ponto():
        raise KeyError("outro")

    try:
        outro_ponto()
    except KeyError:
        erro_inesperado.avisar(*sys.exc_info()[::2])
    flush_idle()
    assert len(aviso.dialogos) == 1
    aviso.dialogos[0]["ao_fechar"]()
    try:
        outro_ponto()
    except KeyError:
        erro_inesperado.avisar(*sys.exc_info()[::2])
    flush_idle()
    assert len(aviso.dialogos) == 2


def test_sem_janela_so_loga(aviso, monkeypatch, flush_idle, caplog):
    """O assistente, a restauração e o fim do app: sem `shared.aplicativo`, só o log."""
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    _erro_no_slot("sem janela", flush_idle)
    assert aviso.dialogos == []
    assert any(r.exc_info for r in caplog.records)
    assert erro_inesperado._aberto is False  # noqa: SLF001


def test_aplicativo_que_some_antes_da_entrega_libera(aviso, monkeypatch, flush_idle):
    """O erro numa thread com o app aberto e o app fechando antes da entrega: nada abre e o próximo pode abrir."""
    try:
        raise ValueError("x")
    except ValueError:
        erro_inesperado.avisar(*sys.exc_info()[::2])
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    flush_idle()
    assert aviso.dialogos == []
    assert erro_inesperado._aberto is False  # noqa: SLF001


def test_falha_ao_montar_o_dialogo_nao_derruba_e_libera(aviso, monkeypatch, flush_idle, caplog):
    monkeypatch.setattr(shared, "aplicativo", _AplicativoQueAnota(quebra=True), raising=False)
    _erro_no_slot("x", flush_idle)
    assert erro_inesperado._aberto is False  # noqa: SLF001
    assert any("Falha ao abrir o aviso de erro inesperado" in r.getMessage() for r in caplog.records)


def test_principal_escondida_o_dialogo_espera_na_fila(app_qt, monkeypatch, flush_idle):  # noqa: ARG001
    """Sem a janela das tarefas, o pedido vai à pilha, por cima, e está lá quando a principal voltar."""
    from kyron.aplicativo import Aplicativo  # noqa: PLC0415

    aplicativo = Aplicativo()
    monkeypatch.setattr(shared, "aplicativo", aplicativo, raising=False)
    pedidos = []
    aplicativo.dialogoPedido.connect(lambda titulo, corpo, itens: pedidos.append(titulo))
    aplicativo.pedir_dialogo("Outro aviso", "Antes deste.", [], lambda: None)
    _avisar(RuntimeError("escondida"), flush_idle)
    assert pedidos == ["Outro aviso", "Ocorreu um erro inesperado"]  # cobre o anterior
    aplicativo.dialogoFechado(False)
    assert pedidos[-1] == "Outro aviso"  # que volta ao fechar


def test_dialogo_real_monta_com_a_janela_de_verdade(app_qt, monkeypatch, flush_idle):  # noqa: ARG001
    """Sobre o `Aplicativo.qml` (`semAgente: true`): o diálogo da camada dos avisos mostra os dois textos."""
    from tests.apoio_janela_atualizacao import Janela, esperar  # noqa: PLC0415

    janela = Janela()
    try:
        monkeypatch.setattr(shared, "aplicativo", janela.aplicativo, raising=False)
        _avisar(RuntimeError("na tela"), flush_idle)
        dialogo = janela.achar("dialogoDeErros")
        assert esperar(lambda: dialogo.property("visible"))
        assert dialogo.property("titulo") == "Ocorreu um erro inesperado"
        assert dialogo.property("corpo") == (
            "Uma ação do aplicativo não foi concluída. Os detalhes foram registrados no log."
        )
        dialogo.fechar()
        esperar()
        assert erro_inesperado._aberto is False  # noqa: SLF001
    finally:
        janela.fechar()
        esperar()


@pytest.mark.parametrize("erro", [KeyboardInterrupt(), SystemExit(1), GeneratorExit()])
def test_so_exception_abre_dialogo(aviso, flush_idle, erro):
    _avisar(erro, flush_idle)
    assert aviso.dialogos == []


def test_system_exit_de_thread_nao_vira_critico(aviso, flush_idle, caplog):
    def sai():
        raise SystemExit(0)

    thread = threading.Thread(target=sai)
    thread.start()
    thread.join()
    flush_idle()
    assert aviso.dialogos == []
    assert not any(r.levelno >= logging.CRITICAL for r in caplog.records)


def test_falha_no_import_ou_no_aviso_nao_escapa_do_gancho(aviso, monkeypatch):  # noqa: ARG001
    def quebra(*_a):
        raise RuntimeError("encerrando")

    monkeypatch.setattr(erro_inesperado, "avisar", quebra)
    try:
        raise ValueError("x")
    except ValueError:
        sys.excepthook(*sys.exc_info())  # não levanta


def test_chave_usa_o_ultimo_quadro_do_app_e_nao_o_da_biblioteca():
    # Dois erros do app que estouram na mesma linha de uma biblioteca: chaves distintas.
    chave_a = erro_inesperado._chave(RuntimeError, _rastro_do_app(1))  # noqa: SLF001
    chave_b = erro_inesperado._chave(RuntimeError, _rastro_do_app(2))  # noqa: SLF001
    assert chave_a != chave_b
    assert chave_a[1].endswith("erro_inesperado.py")


def _rastro_do_app(n):
    """Rastro de um quadro do app (arquivo do pacote kyron, linha n) chamando uma função de biblioteca (outro
    arquivo, sempre a mesma linha)."""
    ambiente = {}
    exec(  # noqa: S102
        compile("def estoura():\n    raise RuntimeError('x')", "/site-packages/requests/api.py", "exec"),
        ambiente,
    )
    app = compile("\n" * (n - 1) + "estoura()", erro_inesperado.__file__, "exec")
    try:
        exec(app, ambiente)  # noqa: S102
    except RuntimeError:
        return sys.exc_info()[2]
    return None


def _registro(mensagem="hello"):
    return logging.LogRecord("test", logging.INFO, __file__, 1, mensagem, None, None)


def test_the_log_stops_at_the_cap_and_says_so(tmp_path, monkeypatch):
    """An unbounded session log made the next startup read it all back."""
    monkeypatch.setattr(SessionFileHandler, "MAX_BYTES", 2000)
    handler = SessionFileHandler(filename=tmp_path / "cartridges.log", backup_count=2)
    handler.setFormatter(logging.Formatter("%(message)s"))

    for index in range(500):
        handler.emit(_registro(f"line {index} " + "x" * 50))
    handler.close()

    text = (tmp_path / "cartridges.log").read_text(encoding="utf-8")
    assert "Log capped at 2000 bytes" in text
    assert "line 0 " in text, "the beginning is what is kept"
    assert "line 499 " not in text


def test_emit_never_raises_into_the_caller(tmp_path):
    """This runs inside somebody's logging call, often while handling an error."""
    handler = SessionFileHandler(filename=tmp_path / "cartridges.log", backup_count=2)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.close()

    handler.emit(_registro("after close"))  # must not raise


def test_rotation_keeps_the_previous_session(tmp_path):
    """backup_count limits how many sessions are kept, not their size."""
    path = tmp_path / "cartridges.log"
    first = SessionFileHandler(filename=path, backup_count=2)
    first.setFormatter(logging.Formatter("%(message)s"))
    first.emit(_registro("session one"))
    first.close()

    second = SessionFileHandler(filename=path, backup_count=2)
    second.close()

    archived = [item for item in tmp_path.iterdir() if item.name != "cartridges.log"]
    assert archived, "the previous session should have been rotated away"


def test_rotation_survives_an_undecodable_log(tmp_path):
    """A half-written file from a crash must not stop the app from starting."""
    path = tmp_path / "cartridges.log"
    path.write_bytes(b"\xff\xfe invalid \x00 bytes")

    handler = SessionFileHandler(filename=path, backup_count=2)
    handler.close()

    assert path.exists()


def test_rotation_survives_a_crash_between_compress_and_unlink(tmp_path):
    """A queda deixava `.log` e `.log.xz` no mesmo número; a próxima
    inicialização levantava na rotação, o dictConfig virava ValueError e a
    sessão rodava sem log nenhum — justamente a sessão depois de um crash."""
    import lzma  # noqa: PLC0415

    path = tmp_path / "cartridges.log"
    path.write_text("sessão interrompida\n", encoding="utf-8")
    with lzma.open(tmp_path / "cartridges.log.xz", "wb") as file:
        file.write(b"metade comprimida")

    handler = SessionFileHandler(filename=path, backup_count=2)  # não pode levantar
    handler.close()


def test_o_log_de_reserva_da_sessao_some_em_tres_rotacoes(tmp_path):
    """O `cartridges-<pid>.log` do `_configurar_log` que falhou entra na rotação como os outros: comprimido na sessão
    seguinte e descartado depois de `backup_count` sessões, sem acumular na pasta."""
    (tmp_path / "cartridges-123.log").write_text("sessão sem rotação\n", encoding="utf-8")

    for _ in range(3):
        SessionFileHandler(filename=tmp_path / "cartridges.log", backup_count=2).close()
        nomes = {item.name for item in tmp_path.iterdir()}
        assert "cartridges-123.log" not in nomes
    assert not any(nome.startswith("cartridges-123") for nome in nomes)
