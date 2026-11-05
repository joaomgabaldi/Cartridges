"""A janela que fica por cima do jogo sem pegar o foco (sobre `QWindow`, com o user32 falso)."""

import pytest
from PySide6.QtGui import QWindow

from cartridges.utils import janela_por_cima as jpc

MONITOR = (0, 0, 1920, 1080)
_API_REAL = jpc._api  # guardado na importação, antes do guarda do conftest


@pytest.fixture
def janela(app_qt):  # noqa: ARG001
    """Uma `QWindow` criada (offscreen): tem `winId()`, nunca vai à tela de verdade."""
    janela = QWindow()
    janela.create()
    yield janela
    janela.destroy()


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


class _SemWinId:
    def winId(self):  # noqa: N802
        return 0


def test_sem_winid_nao_ha_handle(user32_falso):
    assert jpc.handle(_SemWinId()) is None
    assert jpc.preparar(_SemWinId()) is False
    assert not user32_falso.chamadas


def test_handle_e_o_winid_da_qwindow(janela):
    assert jpc.handle(janela) == int(janela.winId()) != 0


def test_preparar_aplica_os_estilos(janela, user32_falso):
    assert jpc.preparar(janela) is True
    estilos = jpc.estilos_de(janela)
    for bit in (jpc.WS_EX_NOACTIVATE, jpc.WS_EX_TOOLWINDOW, jpc.WS_EX_TOPMOST, jpc.WS_EX_TRANSPARENT):
        assert estilos & bit, hex(bit)
    assert bool(estilos & jpc.WS_EX_LAYERED) is jpc.USAR_CAMADAS


@pytest.mark.parametrize(
    "falha",
    [
        {"SetWindowLongPtrW": 0},  # o estilo não pega: o foco seria roubado
        {"SetWindowPos": 0},
        {"SetLayeredWindowAttributes": 0},
    ],
    ids=["estilo-nao-pega", "setwindowpos-falha", "camadas-falham"],
)
def test_preparar_so_devolve_true_com_os_estilos_aplicados(janela, user32_falso, falha):
    if "SetLayeredWindowAttributes" in falha and not jpc.USAR_CAMADAS:
        pytest.skip("sem camadas, o SetLayeredWindowAttributes não é chamado")
    user32_falso.falhas.update(falha)
    assert jpc.preparar(janela) is False
    # Sem ter aplicado nada, a janela não ficou sem ativação.
    if "SetWindowLongPtrW" in falha:
        assert not jpc.estilos_de(janela) & jpc.WS_EX_NOACTIVATE


def test_cartao_mostrado_nao_tem_botao_na_barra_de_tarefas(janela, user32_falso):
    """O que tira o cartão da barra e do Alt+Tab é o dono oculto (e o WS_EX_NOACTIVATE)."""
    assert jpc.preparar(janela) is True
    jpc.mostrar_sem_tomar_o_foco(janela)
    assert jpc.por_no_canto(janela, "inferior-direito") is True
    estilos = jpc.estilos_de(janela)
    assert janela.isVisible()
    assert estilos & jpc.WS_EX_NOACTIVATE
    assert not estilos & jpc.WS_EX_APPWINDOW
    assert jpc.dono_de(janela) == user32_falso.DONO
    hwnd = jpc.handle(janela)
    assert (hwnd, jpc.GWLP_HWNDPARENT, user32_falso.DONO) in user32_falso.pedidos("SetWindowLongPtrW")


def test_dono_volta_depois_que_o_qt_o_tira_ao_mostrar(janela, user32_falso):
    """O Qt refaz o dono da janela ao mostrá-la (o da `transientParent`: nenhum)."""
    assert jpc.preparar(janela) is True
    janela.visibleChanged.connect(lambda _v: user32_falso.donos.clear())
    jpc.mostrar_sem_tomar_o_foco(janela)
    assert jpc.dono_de(janela) == user32_falso.DONO


def test_cartao_mostrado_com_o_app_na_frente_nao_toma_o_foco(janela, user32_falso):
    """O app na frente: mostrar passa o primeiro plano ao cartão, que o devolve na hora."""
    assert jpc.preparar(janela) is True
    janela.visibleChanged.connect(lambda _v: setattr(user32_falso, "primeiro_plano", jpc.handle(janela)))
    jpc.mostrar_sem_tomar_o_foco(janela)
    assert user32_falso.pedidos("SetForegroundWindow") == [(50,)]


def test_por_no_canto_passa_por_notopmost_antes_de_topmost(janela, user32_falso):
    """Logo depois de o primeiro plano mudar, o Windows aceitava o HWND_TOPMOST sem aplicá-lo; pedir HWND_NOTOPMOST antes o faz valer."""
    assert jpc.por_no_canto(janela, "inferior-direito") is True
    assert [args[1] for args in user32_falso.pedidos("SetWindowPos")] == [jpc.HWND_NOTOPMOST, jpc.HWND_TOPMOST]


def test_todos_os_cartoes_compartilham_o_mesmo_dono(app_qt, user32_falso):  # noqa: ARG001
    a, b = QWindow(), QWindow()
    a.create()
    b.create()
    try:
        assert jpc.preparar(a) and jpc.preparar(b)
        assert jpc.dono_de(a) and jpc.dono_de(a) == jpc.dono_de(b)
        a.destroy()  # destruir um cartão não leva o dono embora
        assert jpc.dono_de(b) and user32_falso.IsWindow(jpc.dono_de(b))
        assert len(user32_falso.pedidos("CreateWindowExW")) == 1
    finally:
        a.destroy()
        b.destroy()


def test_sem_dono_o_cartao_ainda_e_preparado(janela, user32_falso, monkeypatch, caplog):  # noqa: ARG001
    def sem_dono():
        raise OSError("sem dono")

    monkeypatch.setattr(jpc, "_dono_oculto", sem_dono)
    with caplog.at_level("WARNING"):
        assert jpc.preparar(janela) is True
    assert "dono" in caplog.text
    assert jpc.dono_de(janela) == 0


def test_sem_user32_nao_ha_aviso_nem_excecao(janela, monkeypatch):
    """Um user32 que não carrega (ou o guarda dos testes) não derruba quem chama."""

    def sem_user32():
        raise OSError("user32 indisponível")

    monkeypatch.setattr(jpc, "_api", sem_user32)
    assert jpc.preparar(janela) is False
    assert jpc.estilos_de(janela) == 0
    assert jpc.dono_de(janela) == 0
    assert jpc.por_no_canto(janela, "inferior-direito") is False


def test_declarar_os_tipos_aqui_nao_estraga_o_user32_do_window_geometry(monkeypatch, monitors_de_verdade):  # noqa: ARG001
    """``ctypes.windll.user32`` é compartilhado: declarar o ``GetMonitorInfoW`` com a estrutura simples deixava ``window_geometry.monitors()`` sem nenhum monitor."""
    from cartridges.utils import window_geometry  # noqa: PLC0415

    monkeypatch.setattr(jpc, "_api", _API_REAL)  # aqui o de verdade: só declara os tipos
    monkeypatch.setattr(jpc, "_user32", None)
    jpc._api()
    assert window_geometry.monitors()


def test_falha_do_win32_nao_levanta(janela, user32_falso, monkeypatch):  # noqa: ARG001
    def explode(*_a):
        raise OSError("negado")

    monkeypatch.setattr(jpc, "_definir_estilos", explode)
    assert jpc.preparar(janela) is False
    monkeypatch.setattr(jpc, "_monitor_em_uso", explode)
    assert jpc.por_no_canto(janela, "inferior-direito") is False


def test_handle_e_estilos_nao_levantam_com_janela_estranha(user32_falso):  # noqa: ARG001
    class Estranha:
        def winId(self):  # noqa: N802
            raise RuntimeError("sem janela")

    assert jpc.handle(Estranha()) is None
    assert jpc.estilos_de(Estranha()) == 0
    assert jpc.preparar(Estranha()) is False
    assert jpc.por_no_canto(Estranha(), "inferior-direito") is False


class _JanelaFalsa:
    """Só o que `mostrar_sem_tomar_o_foco` usa; mostrar muda o primeiro plano."""

    def __init__(self, ao_mostrar):
        self._ao_mostrar = ao_mostrar

    def show(self):
        self._ao_mostrar()


def _mostrar_com(monkeypatch, user32, antes, depois, set_foreground=None, existe=True, retorno=1):
    """Mostra uma janela falsa (hwnd 100, dono 200) com o primeiro plano indo de
    ``antes`` a ``depois``. Devolve os pedidos de ``SetForegroundWindow``."""
    user32.primeiro_plano = antes
    pedidos = []

    def definir(hwnd):
        pedidos.append(hwnd)
        if set_foreground:
            set_foreground(hwnd)
        return retorno

    monkeypatch.setattr(user32, "_SetForegroundWindow", definir, raising=False)
    monkeypatch.setattr(user32, "_IsWindow", lambda hwnd: int(existe and hwnd != 0), raising=False)
    monkeypatch.setattr(jpc, "handle", lambda _janela: 100)
    monkeypatch.setattr(jpc, "dono_de", lambda _janela: 200)
    janela = _JanelaFalsa(lambda: setattr(user32, "primeiro_plano", depois))
    jpc.mostrar_sem_tomar_o_foco(janela)
    return pedidos


@pytest.mark.parametrize("depois", [100, 200], ids=["o-cartao", "o-dono"])
def test_mostrar_devolve_o_foco_a_quem_o_tinha(monkeypatch, user32_falso, depois):
    assert _mostrar_com(monkeypatch, user32_falso, antes=50, depois=depois) == [50]


def test_mostrar_nao_mexe_no_foco_se_o_cartao_nao_o_tomou(monkeypatch, user32_falso):
    assert _mostrar_com(monkeypatch, user32_falso, antes=50, depois=50) == []
    assert _mostrar_com(monkeypatch, user32_falso, antes=50, depois=77) == []


def test_mostrar_sem_janela_anterior_nao_devolve_foco(monkeypatch, user32_falso):
    assert _mostrar_com(monkeypatch, user32_falso, antes=0, depois=100) == []


def test_mostrar_nao_devolve_foco_a_janela_que_nao_existe_mais(monkeypatch, user32_falso):
    assert _mostrar_com(monkeypatch, user32_falso, antes=50, depois=100, existe=False) == []


def test_mostrar_avisa_se_o_windows_recusa_devolver_o_foco(monkeypatch, user32_falso, caplog):
    with caplog.at_level("WARNING"):
        assert _mostrar_com(monkeypatch, user32_falso, antes=50, depois=100, retorno=0) == [50]
    assert "recusou" in caplog.text


def test_mostrar_nao_levanta_se_o_win32_falhar(monkeypatch, user32_falso, caplog):
    def explode(_hwnd):
        raise OSError("negado")

    with caplog.at_level("WARNING"):
        assert _mostrar_com(monkeypatch, user32_falso, antes=50, depois=100, set_foreground=explode) == [50]
    assert "foco" in caplog.text
