"""Erro não tratado vai para o cartridges.log, não só para o console.

O app instalado roda no pythonw, sem console: um erro dentro de um callback do
GTK (abrir a tela de edição, salvar) sumia sem deixar rastro no log.
"""

import logging
import sys
import threading

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
