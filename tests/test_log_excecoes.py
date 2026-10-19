"""Erro não tratado vai para o cartridges.log, não só para o console.

O app instalado roda no pythonw, sem console: um erro dentro de um callback do
GTK (abrir a tela de edição, salvar) sumia sem deixar rastro no log.
"""

import logging
import sys
import threading
import types

import pytest

from gi.repository import GLib, Gtk

from cartridges.logging import setup


def test_aviso_critico_do_gtk_vai_para_o_log(caplog):
    # Uma vez por processo: o GLib aborta se o destino for trocado duas vezes.
    setup.registrar_avisos_do_glib()
    setup.registrar_avisos_do_glib()

    Gtk.Box().remove(Gtk.Label())

    registro = next(r for r in caplog.records if "gtk_box_remove" in r.getMessage())
    assert registro.levelno == logging.ERROR
    assert "Gtk-CRITICAL" in registro.getMessage()


def test_erro_num_callback_do_glib_vai_para_o_log(monkeypatch, caplog):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    setup.registrar_excecoes_nao_tratadas()

    loop = GLib.MainLoop()

    def falha():
        GLib.idle_add(loop.quit)
        raise RuntimeError("erro no callback")

    GLib.idle_add(falha)
    loop.run()

    registro = next(r for r in caplog.records if r.exc_info)
    assert registro.exc_info[1].args == ("erro no callback",)


def test_erro_numa_thread_vai_para_o_log(monkeypatch, caplog):
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    setup.registrar_excecoes_nao_tratadas()

    def falha():
        raise RuntimeError("erro na thread")

    thread = threading.Thread(target=falha)
    thread.start()
    thread.join()

    registro = next(r for r in caplog.records if r.exc_info)
    assert registro.exc_info[1].args == ("erro na thread",)


def test_aviso_do_gtk_com_acento_chega_inteiro_ao_log(caplog):
    # O GLib devolvia o texto formatado na codificação do Windows, não em
    # UTF-8: qualquer acento derrubava o registro e a mensagem se perdia.
    import ctypes  # pylint: disable=import-outside-toplevel

    setup.registrar_avisos_do_glib()
    glib = ctypes.CDLL("libglib-2.0-0.dll")
    glib.g_log_structured(
        b"Gtk", 1 << 4, b"MESSAGE", b"%s", "Capa de Plaž — ação".encode("utf-8"), None
    )

    registro = next(r for r in caplog.records if "Capa de" in r.getMessage())
    assert registro.levelno == logging.WARNING
    assert registro.getMessage() == "Gtk-WARNING: Capa de Plaž — ação"


def test_erro_nao_levantavel_vai_para_o_log(monkeypatch, caplog):
    # Um erro num __del__ não sobe para ninguém: o Python o entrega ao
    # sys.unraisablehook, que por padrão só escreve no stderr.
    import gc  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    monkeypatch.setattr(sys, "unraisablehook", sys.unraisablehook)
    setup.registrar_excecoes_nao_tratadas()

    class Quebra:
        def __del__(self):
            raise RuntimeError("erro no destrutor")

    Quebra()
    gc.collect()

    registro = next(r for r in caplog.records if r.exc_info)
    assert registro.getMessage().startswith("Erro não tratado (não levantável)")
    assert registro.exc_info[1].args == ("erro no destrutor",)


def test_queda_nativa_fica_no_arquivo_de_log(tmp_path):
    # Uma queda em C (driver de vídeo, GTK) mata o processo sem passar pelo
    # Python: só o faulthandler, apontado para o arquivo, deixa a pilha.
    import subprocess  # pylint: disable=import-outside-toplevel
    import textwrap  # pylint: disable=import-outside-toplevel
    from pathlib import Path  # pylint: disable=import-outside-toplevel

    raiz = Path(__file__).resolve().parent.parent
    log = tmp_path / "cartridges.log"
    script = textwrap.dedent(
        f"""
        import faulthandler, sys, types
        sys.path.insert(0, {str(raiz)!r})
        import cartridges
        cartridges.shared = sys.modules["cartridges.shared"] = types.ModuleType("cartridges.shared")
        from cartridges.logging import setup
        arquivo = open({str(log)!r}, "w", encoding="utf-8")
        arquivo.write("antes da queda\\n")
        arquivo.flush()
        setup.registrar_quedas_nativas(arquivo)
        faulthandler._sigsegv()
        """
    )
    filho = subprocess.run(
        [sys.executable, "-c", script], check=False, capture_output=True, text=True
    )

    assert log.exists(), filho.stderr
    texto = log.read_text(encoding="utf-8", errors="replace")
    assert texto.startswith("antes da queda")
    assert "Fatal Python error" in texto


# --- Aviso ao usuário ------------------------------------------------------


@pytest.fixture
def aviso(monkeypatch):
    """Janela falsa e diálogo trocado por um registro; estado do módulo zerado."""
    from cartridges import shared  # pylint: disable=import-outside-toplevel
    from cartridges.utils import erro_inesperado  # pylint: disable=import-outside-toplevel

    abertos = []

    class Dialogo:
        def __init__(self):
            self.fechar = []

        def connect(self, _sinal, funcao):
            self.fechar.append(funcao)

    def abrir(janela, titulo, corpo, *_a, **_k):
        abertos.append((janela, titulo, corpo))
        abertos_dialogos.append(Dialogo())
        return abertos_dialogos[-1]

    abertos_dialogos = []
    monkeypatch.setattr(erro_inesperado, "create_dialog", abrir)
    monkeypatch.setattr(erro_inesperado, "_ja_avisados", set())
    monkeypatch.setattr(erro_inesperado, "_aberto", False)
    monkeypatch.setattr(shared, "win", object(), raising=False)
    monkeypatch.setattr(sys, "excepthook", sys.excepthook)
    monkeypatch.setattr(threading, "excepthook", threading.excepthook)
    setup.registrar_excecoes_nao_tratadas()
    return types.SimpleNamespace(abertos=abertos, dialogos=abertos_dialogos, modulo=erro_inesperado)


def _rodar_ate_ocioso():
    contexto = GLib.MainContext.default()
    while contexto.iteration(False):
        pass


def _erro_no_callback(texto):
    loop = GLib.MainLoop()

    def falha():
        GLib.idle_add(loop.quit)
        raise RuntimeError(texto)

    GLib.idle_add(falha)
    loop.run()
    _rodar_ate_ocioso()


def test_erro_num_callback_do_glib_abre_o_dialogo(aviso):
    _erro_no_callback("a")
    assert len(aviso.abertos) == 1
    assert aviso.abertos[0][1] == "Ocorreu um erro inesperado"


def test_erro_numa_thread_abre_o_dialogo(aviso):
    def falha():
        raise ValueError("na thread")

    thread = threading.Thread(target=falha)
    thread.start()
    thread.join()
    _rodar_ate_ocioso()
    assert len(aviso.abertos) == 1


def test_o_mesmo_erro_abre_um_dialogo_so(aviso):
    def mesmo_ponto():
        raise RuntimeError("repete")

    for _ in range(2):
        try:
            mesmo_ponto()
        except RuntimeError:
            aviso.modulo.avisar(*sys.exc_info()[::2])
        _rodar_ate_ocioso()
        for fechar in (aviso.dialogos[-1].fechar if aviso.dialogos else []):
            fechar()
    assert len(aviso.abertos) == 1


def test_com_um_dialogo_aberto_outro_erro_so_vai_para_o_log(aviso):
    _erro_no_callback("primeiro")

    def outro_ponto():
        raise KeyError("outro")

    try:
        outro_ponto()
    except KeyError:
        aviso.modulo.avisar(*sys.exc_info()[::2])
    _rodar_ate_ocioso()
    assert len(aviso.abertos) == 1
    aviso.dialogos[0].fechar[0]()
    try:
        outro_ponto()
    except KeyError:
        aviso.modulo.avisar(*sys.exc_info()[::2])
    _rodar_ate_ocioso()
    assert len(aviso.abertos) == 2


def test_sem_janela_so_loga(aviso, monkeypatch, caplog):
    from cartridges import shared  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(shared, "win", None, raising=False)
    _erro_no_callback("sem janela")
    assert aviso.abertos == []
    assert any(r.exc_info for r in caplog.records)


def test_falha_ao_montar_o_dialogo_nao_derruba_e_libera(aviso, monkeypatch):
    def quebra(*_a, **_k):
        raise RuntimeError("sem tela")

    monkeypatch.setattr(aviso.modulo, "create_dialog", quebra)
    _erro_no_callback("x")
    assert aviso.modulo._aberto is False  # pylint: disable=protected-access


def test_dialogo_real_monta_com_a_janela_de_verdade(real_window, monkeypatch, caplog):
    from cartridges.utils import erro_inesperado  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(erro_inesperado, "_ja_avisados", set())
    monkeypatch.setattr(erro_inesperado, "_aberto", False)
    assert erro_inesperado._abrir(real_window) is False  # pylint: disable=protected-access
    assert not any("Falha ao abrir" in r.getMessage() for r in caplog.records)


def _avisar_erro(aviso, erro):
    try:
        raise erro
    except BaseException:  # pylint: disable=broad-except
        aviso.modulo.avisar(*sys.exc_info()[::2])
    _rodar_ate_ocioso()


@pytest.mark.parametrize("erro", [KeyboardInterrupt(), SystemExit(1), GeneratorExit()])
def test_so_exception_abre_dialogo(aviso, erro):
    _avisar_erro(aviso, erro)
    assert aviso.abertos == []


def test_system_exit_de_thread_nao_vira_critico(aviso, caplog):
    def sai():
        raise SystemExit(0)

    thread = threading.Thread(target=sai)
    thread.start()
    thread.join()
    _rodar_ate_ocioso()
    assert aviso.abertos == []
    assert not any(r.levelno >= logging.CRITICAL for r in caplog.records)


def test_falha_no_import_ou_no_aviso_nao_escapa_do_gancho(aviso, monkeypatch):
    def quebra(*_a):
        raise RuntimeError("encerrando")

    monkeypatch.setattr(aviso.modulo, "avisar", quebra)
    try:
        raise ValueError("x")
    except ValueError:
        sys.excepthook(*sys.exc_info())  # não levanta


def test_chave_usa_o_ultimo_quadro_do_app_e_nao_o_da_biblioteca(aviso):
    # Dois erros do app que estouram na mesma linha de uma biblioteca: chaves distintas.
    chave_a = aviso.modulo._chave(RuntimeError, _rastro_do_app(1))  # pylint: disable=protected-access
    chave_b = aviso.modulo._chave(RuntimeError, _rastro_do_app(2))  # pylint: disable=protected-access
    assert chave_a != chave_b
    assert chave_a[1].endswith("erro_inesperado.py")


def _rastro_do_app(n):
    """Rastro de um quadro do app (arquivo do pacote cartridges, linha n) chamando
    uma função de biblioteca (outro arquivo, sempre a mesma linha)."""
    from cartridges.utils import erro_inesperado  # pylint: disable=import-outside-toplevel

    ambiente = {}
    exec(  # pylint: disable=exec-used
        compile("def estoura():\n    raise RuntimeError('x')", "/site-packages/requests/api.py", "exec"),
        ambiente,
    )
    app = compile("\n" * (n - 1) + "estoura()", erro_inesperado.__file__, "exec")
    try:
        exec(app, ambiente)  # pylint: disable=exec-used
    except RuntimeError:
        return sys.exc_info()[2]
    return None


def test_janela_principal_escondida_usa_a_janela_ativa(aviso, monkeypatch):
    from cartridges import shared  # pylint: disable=import-outside-toplevel

    ativa = object()
    escondida = types.SimpleNamespace(
        is_visible=lambda: False, get_application=lambda: types.SimpleNamespace(get_active_window=lambda: ativa)
    )
    monkeypatch.setattr(shared, "win", escondida, raising=False)
    _erro_no_callback("escondida")
    assert aviso.abertos[0][0] is ativa


def test_janela_principal_escondida_sem_ativa_usa_a_principal(aviso, monkeypatch):
    from cartridges import shared  # pylint: disable=import-outside-toplevel

    escondida = types.SimpleNamespace(
        is_visible=lambda: False, get_application=lambda: types.SimpleNamespace(get_active_window=lambda: None)
    )
    monkeypatch.setattr(shared, "win", escondida, raising=False)
    _erro_no_callback("escondida")
    assert aviso.abertos[0][0] is escondida
