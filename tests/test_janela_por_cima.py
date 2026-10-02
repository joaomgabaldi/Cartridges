"""A janela que fica por cima do jogo sem pegar o foco."""

import pytest
from gi.repository import Gtk

from cartridges.utils import janela_por_cima as jpc

MONITOR = (0, 0, 1920, 1080)


@pytest.mark.parametrize(
    ("canto", "esperado"),
    [
        ("superior-esquerdo", (24, 24)),
        ("superior-direito", (1920 - 300 - 24, 24)),
        ("inferior-esquerdo", (24, 1080 - 80 - 24)),
        ("inferior-direito", (1920 - 300 - 24, 1080 - 80 - 24)),
        ("qualquer-coisa", (1920 - 300 - 24, 1080 - 80 - 24)),
    ],
)
def test_posicao_nos_quatro_cantos(canto, esperado):
    assert jpc.posicao(canto, MONITOR, (300, 80), 24) == esperado


def test_posicao_no_segundo_monitor():
    assert jpc.posicao("superior-esquerdo", (1920, -200, 3840, 880), (300, 80), 24) == (1944, -176)


def test_sem_superficie_nao_ha_handle():
    janela = Gtk.Window()
    assert jpc.handle(janela) is None
    assert jpc.preparar(janela) is False


def test_preparar_aplica_os_estilos():
    janela = Gtk.Window(decorated=False)
    janela.realize()
    try:
        assert jpc.preparar(janela) is True
        estilos = jpc.estilos_de(janela)
        for bit in (jpc.WS_EX_NOACTIVATE, jpc.WS_EX_TOOLWINDOW, jpc.WS_EX_TOPMOST, jpc.WS_EX_TRANSPARENT):
            assert estilos & bit, hex(bit)
        assert bool(estilos & jpc.WS_EX_LAYERED) is jpc.USAR_CAMADAS
    finally:
        janela.destroy()


def test_falha_do_win32_nao_levanta(monkeypatch):
    janela = Gtk.Window(decorated=False)
    janela.realize()
    try:
        def explode(*_a):
            raise OSError("negado")

        monkeypatch.setattr(jpc, "_definir_estilos", explode)
        assert jpc.preparar(janela) is False
        monkeypatch.setattr(jpc, "_monitor_em_uso", explode)
        assert jpc.por_no_canto(janela, "inferior-direito") is False
    finally:
        janela.destroy()


def test_handle_e_estilos_nao_levantam_com_janela_estranha():
    class SemSuperficie:
        def get_surface(self):
            raise RuntimeError("sem superfície")

    assert jpc.handle(SemSuperficie()) is None
    assert jpc.estilos_de(SemSuperficie()) == 0
    assert jpc.preparar(SemSuperficie()) is False
    assert jpc.por_no_canto(SemSuperficie(), "inferior-direito") is False
