# test_monitor_da_sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O monitor da sessão e o papel de parede (Task 4 do plano 5).

Tudo com falsos: HWND falso, `user32` falso e área de trabalho falsa. Nenhuma janela é movida e o papel
de parede de verdade nunca é tocado (o `conftest.py` faz `_AreaDeTrabalho` levantar).
"""

import inspect
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QWindow

from cartridges import app, shared
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.utils import session_wallpaper, window_geometry

RAIZ = Path(__file__).resolve().parent.parent
PRINCIPAL = window_geometry.Monitor("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, True)
SEGUNDO = window_geometry.Monitor("\\\\.\\DISPLAY2", -1080, -512, 1080, 1920, False)


class _FakePlacementUser32:
    """O bastante do user32 para o vaivém da janela entre monitores.

    Guarda cada `SetWindowPlacement` recebido, que é o que o teste tem para olhar: é a única coisa que
    a mudança de monitor faz com a janela. `zoomed` e `visible` respondem `IsZoomed` e `IsWindowVisible`.
    """

    def __init__(self, rect=(100, 50, 900, 650), show=1, visible=True):
        self.rect = rect
        self.show = show  # SW_SHOWNORMAL, ou 3 para uma janela maximizada
        self.visible = visible
        self.written: list = []

    @staticmethod
    def IsIconic(_hwnd):  # noqa: N802
        return 0

    def IsZoomed(self, _hwnd):  # noqa: N802
        return int(self.show == 3)

    def IsWindowVisible(self, _hwnd):  # noqa: N802
        return int(self.visible)

    def GetWindowRect(self, _hwnd, ref):  # noqa: N802
        ref._obj.left, ref._obj.top, ref._obj.right, ref._obj.bottom = self.rect
        return 1

    def GetWindowPlacement(self, _hwnd, ref):  # noqa: N802
        ref._obj.showCmd = self.show
        posicao = ref._obj.rcNormalPosition
        posicao.left, posicao.top, posicao.right, posicao.bottom = self.rect
        return 1

    def SetWindowPlacement(self, _hwnd, ref):  # noqa: N802
        retangulo = ref._obj.rcNormalPosition
        self.written.append((ref._obj.showCmd, (retangulo.left, retangulo.top, retangulo.right, retangulo.bottom)))
        return 1


def _janela_falsa():
    return object()


@pytest.fixture
def sem_sessao(monkeypatch):
    """Zera o estado de módulo, e devolve-o intacto ao fim do teste."""
    monkeypatch.setattr(window_geometry, "_before_session", None)
    monkeypatch.setattr(window_geometry, "_before_placement", None)


@pytest.fixture
def monitores(monkeypatch):
    def trocar(*ligados):
        monkeypatch.setattr(window_geometry, "monitors", lambda: list(ligados))

    return trocar


@pytest.fixture
def user32(monkeypatch, sem_sessao):  # noqa: ARG001
    def montar(**kwargs):
        falso = _FakePlacementUser32(**kwargs)
        monkeypatch.setattr(window_geometry, "_user32", falso)
        monkeypatch.setattr(window_geometry, "_hwnd", lambda _janela: 42)
        return falso

    return montar


# -- Portados de `test_ui_logic.py`: a regra do `window_geometry` --------------------------------------


def test_the_window_never_moves_to_a_monitor_that_is_not_there(monkeypatch, sem_sessao, monitores):  # noqa: ARG001
    """O monitor escolhido foi desligado: a janela fica onde está (e quem chamou minimiza)."""
    monitores()
    monkeypatch.setattr(window_geometry, "_hwnd", lambda _janela: 42)

    assert window_geometry.move_to_monitor(_janela_falsa(), "\\\\.\\DISPLAY2") is False
    assert window_geometry.session_geometry() is None


def test_the_window_never_moves_onto_the_primary_monitor(user32, monitores):
    """O principal é onde o jogo roda: maximizada ali, a janela o cobriria."""
    falso = user32()
    monitores(PRINCIPAL)

    assert window_geometry.move_to_monitor(_janela_falsa(), "\\\\.\\DISPLAY1") is False
    assert falso.written == []
    assert window_geometry.session_geometry() is None


def test_a_secondary_monitor_is_any_monitor_but_the_primary(monitores):
    monitores(PRINCIPAL)
    assert window_geometry.has_secondary_monitor() is False

    monitores(PRINCIPAL, SEGUNDO)
    assert window_geometry.has_secondary_monitor() is True

    monitores()  # enumeração que falhou: o lado seguro é "não há"
    assert window_geometry.has_secondary_monitor() is False


def test_the_session_move_puts_the_window_back_exactly(user32, monitores):
    """Ida e volta: maximiza no monitor escolhido, volta ao estado de origem."""
    falso = user32()
    monitores(PRINCIPAL, SEGUNDO)
    janela = _janela_falsa()

    assert window_geometry.move_to_monitor(janela, "\\\\.\\DISPLAY2") is True
    # Primeiro pousa no monitor escolhido (SW_SHOWNORMAL) e só então maximiza (SW_SHOWMAXIMIZED).
    estacionada = (-1080, -512, 0, 1408)
    assert falso.written == [(1, estacionada), (3, estacionada)]
    assert window_geometry.session_geometry() == window_geometry.Geometry(100, 50, 800, 600, False)

    window_geometry.restore_from_monitor(janela)
    assert falso.written[-1] == (1, (100, 50, 900, 650))
    assert window_geometry.session_geometry() is None

    window_geometry.restore_from_monitor(janela)  # a sessão já acabou: não mexe em janela nenhuma
    assert len(falso.written) == 3


def test_a_window_hidden_at_the_end_of_the_session_is_written_hidden(user32, monitores):
    """Principal escondida no fim da sessão: placement gravado com SW_HIDE, a janela segue escondida."""
    falso = user32()
    monitores(SEGUNDO)
    janela = _janela_falsa()
    assert window_geometry.move_to_monitor(janela, "\\\\.\\DISPLAY2") is True
    falso.written.clear()

    falso.visible = False
    window_geometry.restore_from_monitor(janela)

    assert falso.written == [(0, (100, 50, 900, 650))]
    assert window_geometry.session_geometry() is None
    assert window_geometry._before_placement is None  # noqa: SLF001

    # A sessão seguinte estaciona de novo, sem herdar nada.
    falso.visible = True
    assert window_geometry.move_to_monitor(janela, "\\\\.\\DISPLAY2") is True
    window_geometry.restore_from_monitor(janela)
    assert falso.written[-1] == (1, (100, 50, 900, 650))


def test_a_maximized_window_hidden_at_the_end_keeps_its_restore_rectangle(user32, monitores):
    """Maximizada antes do jogo e escondida no fim: o retângulo de restauração é o de antes (não o do
    monitor do jogo), gravado numa escrita só, escondida."""
    falso = user32(show=3)
    monitores(SEGUNDO)
    janela = _janela_falsa()
    assert window_geometry.move_to_monitor(janela, "\\\\.\\DISPLAY2") is True
    falso.written.clear()

    falso.visible = False
    window_geometry.restore_from_monitor(janela)

    assert falso.written == [(0, (100, 50, 900, 650))]
    assert window_geometry.session_geometry() is None


def test_a_maximized_window_comes_back_maximized_where_it_was(user32, monitores):
    """Maximizada antes do jogo, maximizada depois, no monitor de origem (D: a janela volta como estava)."""
    falso = user32(show=3)
    monitores(SEGUNDO)
    janela = _janela_falsa()

    assert window_geometry.move_to_monitor(janela, "\\\\.\\DISPLAY2") is True
    window_geometry.restore_from_monitor(janela)

    casa, estacionada = (100, 50, 900, 650), (-1080, -512, 0, 1408)
    assert falso.written == [(1, estacionada), (3, estacionada), (1, casa), (3, casa)]


# -- Novos ---------------------------------------------------------------------------------------------


def test_hwnd_da_qwindow():
    janela = QWindow()
    hwnd = window_geometry._hwnd(janela)  # noqa: SLF001
    assert hwnd is not None and hwnd == int(janela.winId())
    assert window_geometry._hwnd(None) is None  # noqa: SLF001


def test_window_geometry_importa_sem_gi():
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; sys.path.insert(0, sys.argv[1]);"
        "import cartridges.utils.window_geometry, cartridges.utils.session_wallpaper, cartridges.modelos.sessao;"
        "sys.exit(1 if 'gi' in sys.modules else 0)"
    )
    resultado = subprocess.run([sys.executable, "-c", codigo, str(RAIZ)], capture_output=True, text=True, check=False)
    assert resultado.returncode == 0, resultado.stderr


class _JanelaQt:
    """O bastante de uma `QWindow` para o `present()`; anota a ordem do que acontece com ela."""

    def __init__(self, chamadas):
        self.chamadas = chamadas
        self.estados = Qt.WindowState.WindowMinimized

    def windowStates(self):  # noqa: N802
        return self.estados

    def setWindowStates(self, estados):  # noqa: N802
        self.estados = estados
        self.chamadas.append("present")

    def isVisible(self):  # noqa: N802
        return True

    def raise_(self):
        pass

    def requestActivate(self):  # noqa: N802
        pass


@pytest.fixture
def modelo(monkeypatch):
    """O modelo, com a parede e o monitor registrando em vez de agir."""
    instancia = ModeloDaSessao(FilaDeAvisos())
    instancia.chamadas = []
    instancia.comecou = []
    monkeypatch.setattr(session_wallpaper, "comecar", instancia.comecou.append)
    monkeypatch.setattr(session_wallpaper, "restaurar", lambda: instancia.chamadas.append("parede"))
    monkeypatch.setattr(
        window_geometry, "restore_from_monitor", lambda _janela: instancia.chamadas.append("monitor")
    )
    return instancia


def test_sem_segundo_monitor_desliga_a_opcao(modelo, schema, monitores, monkeypatch):
    schema["session-move-window"] = True
    schema["session-monitor"] = PRINCIPAL.device
    monitores(PRINCIPAL)
    modelo.definir_janela(QWindow())

    def nao_move(*_args):
        raise AssertionError("sem segundo monitor não há para onde levar a janela")

    monkeypatch.setattr(window_geometry, "move_to_monitor", nao_move)

    assert modelo.move_to_session_monitor() is False
    assert schema.get_boolean("session-move-window") is False


def test_opcao_desligada_nao_move_nem_pergunta_pelos_monitores(modelo, schema, monkeypatch):
    schema["session-move-window"] = False
    modelo.definir_janela(QWindow())

    def nao_pergunta(*_args):
        raise AssertionError("a opção está desligada")

    monkeypatch.setattr(window_geometry, "monitors", nao_pergunta)
    monkeypatch.setattr(window_geometry, "move_to_monitor", nao_pergunta)

    assert modelo.move_to_session_monitor() is False


def test_move_leva_a_janela_ao_monitor_escolhido(modelo, schema, monitores, monkeypatch):
    schema["session-move-window"] = True
    schema["session-monitor"] = SEGUNDO.key
    monitores(PRINCIPAL, SEGUNDO)
    janela = QWindow()
    modelo.definir_janela(janela)
    pedidos = []
    monkeypatch.setattr(window_geometry, "move_to_monitor", lambda j, escolhido: pedidos.append((j, escolhido)) or True)

    assert modelo.move_to_session_monitor() is True
    assert pedidos == [(janela, SEGUNDO.key)]


def test_relogio_so_com_a_janela_movida(modelo, schema, monkeypatch, make_game):
    schema["session-wallpaper"] = False
    jogo = make_game(name="Halo")
    avisos = []
    modelo.alterado.connect(lambda: avisos.append(1))

    monkeypatch.setattr(window_geometry, "session_geometry", lambda: None)
    modelo.show_session_blocker(jogo)
    assert modelo.relogioVisivel is False
    assert not modelo._tique.isActive()  # noqa: SLF001
    modelo.hide_session_blocker()

    monkeypatch.setattr(window_geometry, "session_geometry", lambda: window_geometry.Geometry(1, 2, 3, 4, False))
    modelo.show_session_blocker(jogo)
    assert modelo.relogioVisivel is True
    assert modelo._tique.isActive() and modelo._tique.interval() == 1000  # noqa: SLF001
    avisos.clear()
    relogios = []
    modelo.relogioMudou.connect(lambda: relogios.append(1))
    modelo._tique.timeout.emit()  # noqa: SLF001
    assert relogios == [1] and avisos == []  # cada tique avisa só o relógio, que o QML lê de novo

    modelo.hide_session_blocker()
    assert modelo.relogioVisivel is False
    assert not modelo._tique.isActive()  # noqa: SLF001


def test_volta_ao_monitor_antes_de_trazer_de_volta(modelo, make_game):
    modelo.definir_janela(_JanelaQt(modelo.chamadas))
    modelo.show_session_blocker(make_game(name="Halo"))

    # É a ordem dos rastreadores ao fim da sessão: esconder a camada e só então trazer a janela.
    modelo.hide_session_blocker()
    modelo.present()

    assert modelo.chamadas == ["monitor", "parede", "present"]


def test_parede_so_com_a_opcao_ligada(modelo, schema, make_game):
    jogo = make_game(name="Halo")
    schema["session-wallpaper"] = False
    modelo.show_session_blocker(jogo)
    assert modelo.comecou == []

    modelo.hide_session_blocker()
    schema["session-wallpaper"] = True
    modelo.show_session_blocker(jogo)
    assert modelo.comecou == [jogo]


def test_encerrar_devolve_a_parede(modelo):
    modelo.encerrar()  # o `saindo`: as janelas ainda na tela, nada que espere (R1)
    assert modelo.chamadas == []
    modelo.devolver()  # o `aboutToQuit`
    assert modelo.chamadas == ["parede"]  # sem tocar na janela (D: nada de interface no encerramento)


# -- Papel de parede: a volta para a thread principal ---------------------------------------------------


class _AreaComMonitores:
    def __init__(self, ligados):
        self.ligados_ = ligados

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    @staticmethod
    def em_apresentacao():
        return False

    def ligados(self):
        return list(self.ligados_)


class _AreaFalsa:
    def __init__(self, papeis):
        self.papeis = dict(papeis)
        self.vestidos = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def papel(self, monitor):
        return self.papeis.get(monitor)

    def vestir(self, monitor, caminho):
        self.vestidos.append((monitor, caminho))
        return True


@pytest.fixture
def preparada(monkeypatch, tmp_path):
    """`aplicar` pronto para rodar com um monitor-alvo e uma arte de verdade em disco."""
    arte = tmp_path / "arte.jpg"
    Image.new("RGB", (64, 36), (10, 10, 10)).save(arte)
    ligados = [session_wallpaper.Monitor("M1", 0, 0, 1920, 1080), session_wallpaper.Monitor("M2", 1920, 0, 640, 360)]
    monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", lambda: _AreaComMonitores(ligados))
    monkeypatch.setattr(session_wallpaper, "_fonte", lambda *_a, **_k: (arte, session_wallpaper.Posicoes()))


def _esperar(condicao, prazo=5.0):
    import time  # noqa: PLC0415

    fim = time.monotonic() + prazo
    while not condicao() and time.monotonic() < fim:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return condicao()


def test_vestir_chega_na_thread_principal(preparada, monkeypatch):  # noqa: ARG001
    chegou = []
    monkeypatch.setattr(
        session_wallpaper, "_vestir", lambda sessao, quadros: chegou.append((threading.current_thread(), sessao, quadros))
    )
    trabalho = threading.Thread(target=session_wallpaper.aplicar, args=(type("J", (), {"game_id": "jogo"})(), 7))
    trabalho.start()
    trabalho.join(10)

    assert _esperar(lambda: bool(chegou))
    [(thread, sessao, quadros)] = chegou
    assert thread is threading.main_thread()  # nunca a thread que preparou a arte
    assert sessao == 7 and [monitor for monitor, _ in quadros] == ["M2"]


def test_sessao_que_acaba_antes_da_arte_nao_veste(preparada, monkeypatch):  # noqa: ARG001
    area = _AreaFalsa({"M2": "c:/original.jpg"})
    sessao = session_wallpaper._sessao  # noqa: SLF001
    trabalho = threading.Thread(target=session_wallpaper.aplicar, args=(type("J", (), {"game_id": "jogo"})(), sessao))
    trabalho.start()
    trabalho.join(10)
    # A arte já está pronta e a entrega à thread principal enfileirada; a sessão acaba antes de ela rodar.
    session_wallpaper.restaurar()
    monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", lambda: area)
    cache = session_wallpaper._cache()  # noqa: SLF001
    assert list(cache.glob("*.jpg"))  # a arte foi preparada

    _esperar(lambda: not list(cache.glob("*.jpg")))

    assert area.vestidos == []
    assert shared.schema.get_string("session-wallpaper-saved") == ""
    assert not list(cache.glob("*.jpg"))  # o temporário foi apagado


def test_abertura_desfaz_orfaos(monkeypatch):
    # O comportamento: a marca de uma sessão que não voltou é desfeita.
    shared.schema.set_string("session-wallpaper-saved", json.dumps({"M1": "c:/a.jpg"}))
    area = _AreaFalsa({})
    monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", lambda: area)
    session_wallpaper.restaurar_orfaos()
    assert area.vestidos == [("M1", "c:/a.jpg")]
    assert shared.schema.get_string("session-wallpaper-saved") == ""

    # E o app a chama antes de carregar o QML (a janela já nasce sobre a parede de volta).
    fonte = inspect.getsource(app._abrir)  # noqa: SLF001
    assert 0 <= fonte.index("session_wallpaper.restaurar_orfaos()") < fonte.index("motor.load(")
