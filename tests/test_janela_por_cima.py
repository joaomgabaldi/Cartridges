"""A janela que fica por cima do jogo sem pegar o foco."""

import importlib
import time

import pytest
from gi.repository import GLib, Gtk

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


class _Win32ComFalha:
    """O user32 de verdade, menos as funções em ``trocas``."""

    def __init__(self, real, **trocas):
        self._real, self._trocas = real, trocas

    def __getattr__(self, nome):
        return self._trocas.get(nome, getattr(self._real, nome))


@pytest.mark.parametrize(
    "falha",
    [
        {"SetWindowLongPtrW": lambda *_a: 0},  # o estilo não pega: o foco seria roubado
        {"SetWindowPos": lambda *_a: 0},
        {"SetLayeredWindowAttributes": lambda *_a: 0},
    ],
    ids=["estilo-nao-pega", "setwindowpos-falha", "camadas-falham"],
)
def test_preparar_so_devolve_true_com_os_estilos_aplicados(monkeypatch, falha):
    janela = Gtk.Window(decorated=False)
    janela.realize()
    try:
        monkeypatch.setattr(jpc, "_api", lambda real=jpc._api(): _Win32ComFalha(real, **falha))
        assert jpc.preparar(janela) is False
        # Sem ter aplicado nada, a janela não ficou sem ativação.
        if "SetWindowLongPtrW" in falha:
            assert not jpc.estilos_de(janela) & jpc.WS_EX_NOACTIVATE
    finally:
        janela.destroy()


def _bombear(segundos=0.6):
    contexto = GLib.MainContext.default()
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        while contexto.iteration(False):
            pass
        time.sleep(0.01)


def test_cartao_mostrado_nao_tem_botao_na_barra_de_tarefas():
    """O GTK tira o WS_EX_TOOLWINDOW ao mostrar a janela; o que a tira da barra e
    do Alt+Tab é o dono (e o WS_EX_NOACTIVATE), sem tomar o foco."""
    u = jpc._api()
    primeiro_plano = u.GetForegroundWindow()
    janela = Gtk.Window(decorated=False, resizable=False, title="teste-cartao")
    janela.set_child(Gtk.Label(label="Conquista desbloqueada"))
    janela.realize()
    try:
        assert jpc.preparar(janela) is True
        janela.set_visible(True)
        assert jpc.por_no_canto(janela, "inferior-direito") is True
        _bombear()
        hwnd = jpc.handle(janela)
        estilos = jpc.estilos_de(janela)
        assert u.IsWindowVisible(hwnd)
        assert estilos & jpc.WS_EX_NOACTIVATE
        assert not estilos & jpc.WS_EX_APPWINDOW
        dono = jpc.dono_de(janela)
        assert estilos & jpc.WS_EX_TOOLWINDOW or (dono and not u.IsIconic(dono))
        assert dono and not u.IsIconic(dono)
        assert u.GetForegroundWindow() == primeiro_plano  # e sem pegar o foco
    finally:
        janela.destroy()


def test_por_no_canto_passa_por_notopmost_antes_de_topmost(monkeypatch):
    """Logo depois de o primeiro plano mudar, o Windows aceitava o HWND_TOPMOST
    sem aplicá-lo, e o cartão ficava atrás do jogo e da barra de tarefas. Pedir
    HWND_NOTOPMOST antes faz o HWND_TOPMOST valer (medido em 06/10/2026)."""
    janela = Gtk.Window(decorated=False, resizable=False)
    janela.realize()
    pedidos = []
    real = jpc._api()

    def set_window_pos(hwnd, depois_de, *resto):
        pedidos.append(depois_de)
        return real.SetWindowPos(hwnd, depois_de, *resto)

    try:
        monkeypatch.setattr(jpc, "_api", lambda: _Win32ComFalha(real, SetWindowPos=set_window_pos))
        assert jpc.por_no_canto(janela, "inferior-direito") is True
        assert pedidos == [jpc.HWND_NOTOPMOST, jpc.HWND_TOPMOST]
    finally:
        janela.destroy()


def test_todos_os_cartoes_compartilham_o_mesmo_dono():
    a, b = Gtk.Window(decorated=False), Gtk.Window(decorated=False)
    a.realize()
    b.realize()
    try:
        assert jpc.preparar(a) and jpc.preparar(b)
        assert jpc.dono_de(a) and jpc.dono_de(a) == jpc.dono_de(b)
        a.destroy()  # destruir um cartão não leva o dono embora
        assert jpc.dono_de(b) and jpc._api().IsWindow(jpc.dono_de(b))
    finally:
        a.destroy()
        b.destroy()


def test_sem_dono_o_cartao_ainda_e_preparado(monkeypatch, caplog):
    janela = Gtk.Window(decorated=False)
    janela.realize()
    try:
        def sem_dono():
            raise OSError("sem dono")

        monkeypatch.setattr(jpc, "_dono_oculto", sem_dono)
        with caplog.at_level("WARNING"):
            assert jpc.preparar(janela) is True
        assert "dono" in caplog.text
        assert jpc.dono_de(janela) == 0
    finally:
        janela.destroy()


def test_sem_typelib_do_gdkwin32_o_modulo_importa_e_nao_ha_handle(monkeypatch):
    import gi  # noqa: PLC0415

    real = gi.require_version

    def sem_gdkwin32(nome, versao):
        if nome == "GdkWin32":
            raise ValueError("Namespace GdkWin32 not available")
        return real(nome, versao)

    janela = Gtk.Window(decorated=False)
    janela.realize()
    try:
        with monkeypatch.context() as ctx:
            ctx.setattr(gi, "require_version", sem_gdkwin32)
            importlib.reload(jpc)  # o import do módulo não pode derrubar o app
            assert jpc.handle(janela) is None
            assert jpc.preparar(janela) is False
            assert jpc.por_no_canto(janela, "inferior-direito") is False
        importlib.reload(jpc)  # volta ao estado normal para os outros testes
        assert jpc.handle(janela) is not None
    finally:
        janela.destroy()


def test_declarar_os_tipos_aqui_nao_estraga_o_user32_do_window_geometry(monkeypatch):
    """``ctypes.windll.user32`` é compartilhado: declarar o ``GetMonitorInfoW`` com a
    estrutura simples deixava ``window_geometry.monitors()`` sem nenhum monitor."""
    from cartridges.utils import window_geometry  # noqa: PLC0415

    monkeypatch.setattr(jpc, "_user32", None)
    jpc._api()
    assert window_geometry.monitors()


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
