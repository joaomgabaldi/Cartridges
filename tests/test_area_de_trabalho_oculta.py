"""A suíte roda numa área de trabalho do Windows que nunca aparece."""

import os
import subprocess
import sys

import pytest
from gi.repository import GLib, Gtk

from cartridges.utils import janela_por_cima as jpc


def test_janela_apresentada_nao_aparece_para_outro_processo():
    if os.environ.get("CARTRIDGES_TESTES_NA_TELA") == "1":
        pytest.skip("CARTRIDGES_TESTES_NA_TELA=1: as janelas aparecem de propósito")
    titulo = "teste-area-oculta-cartridges"
    janela = Gtk.Window(title=titulo)
    janela.set_child(Gtk.Label(label="oi"))
    janela.present()
    try:
        contexto = GLib.MainContext.default()
        for _ in range(200):
            while contexto.iteration(False):
                pass
        hwnd = jpc.handle(janela)
        assert hwnd and jpc._api().IsWindowVisible(hwnd)  # existe e está mapeada aqui
        achou = subprocess.run(
            [sys.executable, "-I", "-c",
             f"import ctypes;print(ctypes.windll.user32.FindWindowW(None,{titulo!r}))"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        assert achou == "0"
    finally:
        janela.destroy()
