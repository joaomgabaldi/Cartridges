"""Controle (XInput) no Big Picture: rotas, aceleração, vibração e aviso de conexão."""

from types import SimpleNamespace

import pytest
from gi.repository import Gtk

from cartridges import gamepad as gp
from cartridges import shared


class PaginaFalsa:
    def __init__(self):
        self.visivel = True
        self.ocupada = False
        self.devolve = True
        self.chamadas = []

    def mover(self, delta):
        self.chamadas.append(("mover", delta))
        return self.devolve

    def pular(self, delta):
        self.chamadas.append(("pular", delta))
        return self.devolve

    def abrir_jogo(self):
        self.chamadas.append(("abrir",))

    def sair(self):
        self.chamadas.append(("sair",))


def _base(monkeypatch):
    m = gp.GamepadManager.__new__(gp.GamepadManager)
    m._direction = None
    m._direction_since = 0
    m._ultimo_passo_us = 0
    m._repeats = 0
    m._direction_latched = False
    m._engaged = True
    m._buttons = 0
    m._resync = False
    m._slot = None
    m._last_scan = -10_000_000
    m._redescoberta = False
    m.ao_conectar = None
    m.ao_usar = None
    m._ultimo_toque_capa_us = 0
    m.window = None
    clock = {"now": 1_000_000}
    monkeypatch.setattr(gp.GLib, "get_monotonic_time", lambda: clock["now"])
    m.clock = clock
    return m


@pytest.fixture
def pad_manager_bp(monkeypatch):
    m = _base(monkeypatch)
    m.pagina = PaginaFalsa()
    m.rumbles = []
    monkeypatch.setattr(m, "_rumble", m.rumbles.append)
    monkeypatch.setattr(
        shared, "win", SimpleNamespace(pagina_big_picture=m.pagina), raising=False
    )
    return m


class XInputFalso:
    def __init__(self):
        self.presente = True

    def XInputGetState(self, slot, _state):  # noqa: N802
        return 0 if self.presente and slot == 1 else 1167


@pytest.fixture
def manager_com_xinput_falso(monkeypatch):
    m = _base(monkeypatch)
    m.xinput = XInputFalso()
    m.chamadas = 0

    def spy():
        m.chamadas += 1

    m.ao_conectar = spy
    return m


def test_primeira_deteccao_avisa_a_conexao(manager_com_xinput_falso):
    m = manager_com_xinput_falso
    m._read()
    assert m.chamadas == 1 and m._slot == 1


def test_redescoberta_depois_de_um_jogo_nao_avisa(manager_com_xinput_falso):
    m = manager_com_xinput_falso
    m._redescoberta = True
    m._read()
    assert m.chamadas == 0 and not m._redescoberta


def test_varredura_sem_controle_apos_o_jogo_desliga_a_redescoberta(
    manager_com_xinput_falso,
):
    m = manager_com_xinput_falso
    m._redescoberta = True
    m.xinput.presente = False
    assert m._read() is None
    assert not m._redescoberta
    # Controle ligado depois: é uma conexão de verdade e avisa.
    m.xinput.presente = True
    m.clock["now"] += 10_000_000
    m._read()
    assert m.chamadas == 1


def test_desconectar_e_conectar_avisa_de_novo(manager_com_xinput_falso):
    m = manager_com_xinput_falso
    m._read()
    m.xinput.presente = False
    m.clock["now"] += 10_000_000
    assert m._read() is None and m._slot is None
    m.xinput.presente = True
    m.clock["now"] += 10_000_000
    m._read()
    assert m.chamadas == 2


def test_excecao_no_aviso_nao_derruba_o_poll(manager_com_xinput_falso):
    m = manager_com_xinput_falso

    def falha():
        raise RuntimeError("x")

    m.ao_conectar = falha
    assert m._read() is not None and m._slot == 1


def test_release_marca_redescoberta(monkeypatch):
    m = _base(monkeypatch)
    m._suspended = True
    m._release_id = 0
    m.xinput = object()
    m._release()
    assert m._redescoberta is True


def test_seta_direita_move_o_carrossel_e_vibra(pad_manager_bp):
    m = pad_manager_bp
    m._move(Gtk.DirectionType.RIGHT)
    m._move(Gtk.DirectionType.LEFT)
    assert m.pagina.chamadas == [("mover", 1), ("mover", -1)]
    assert m.rumbles == [gp.RUMBLE_CAPA]  # o segundo passo veio cedo demais


def test_na_ponta_vibra_o_fim(pad_manager_bp):
    m = pad_manager_bp
    m.pagina.devolve = False
    m._move(Gtk.DirectionType.RIGHT)
    assert m.rumbles == [gp.RUMBLE_EDGE]


def test_cima_e_baixo_nao_fazem_nada(pad_manager_bp):
    m = pad_manager_bp
    m._move(Gtk.DirectionType.UP)
    m._move(Gtk.DirectionType.DOWN)
    assert m.pagina.chamadas == [] and m.rumbles == []


def test_lb_rb_pulam_dez(pad_manager_bp):
    m = pad_manager_bp
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_LEFT_SHOULDER))
    m._handle_buttons(SimpleNamespace(wButtons=0))
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_RIGHT_SHOULDER))
    assert m.pagina.chamadas == [("pular", -10), ("pular", 10)]
    assert m.rumbles == [gp.RUMBLE_PULO] * 2
    m.pagina.devolve = False
    m._handle_buttons(SimpleNamespace(wButtons=0))
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_RIGHT_SHOULDER))
    assert m.rumbles[-1] == gp.RUMBLE_EDGE


def test_a_abre_e_b_sai(pad_manager_bp):
    m = pad_manager_bp
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_A))
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_B))
    assert m.pagina.chamadas == [("abrir",), ("sair",)]


def test_dialogo_aberto_tira_a_entrada_do_big_picture(pad_manager_bp, monkeypatch):
    m = pad_manager_bp
    assert m._big_picture() is m.pagina
    monkeypatch.setattr(shared.win, "get_visible_dialog", lambda: object(), raising=False)
    assert m._big_picture() is None
    normais = []
    monkeypatch.setattr(m, "_activate", lambda: normais.append("a"))
    monkeypatch.setattr(m, "_back", lambda: normais.append("b"))
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_A))
    m._handle_buttons(SimpleNamespace(wButtons=0))
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_B))
    assert m.pagina.chamadas == [] and normais == ["a", "b"]


@pytest.mark.parametrize(
    "botao", [gp.XINPUT_START, gp.XINPUT_Y, gp.XINPUT_BACK]
)
def test_start_y_back_nada(pad_manager_bp, botao):
    m = pad_manager_bp
    m._handle_buttons(SimpleNamespace(wButtons=botao))
    assert m.pagina.chamadas == []


def test_ocupada_ignora_tudo(pad_manager_bp):
    m = pad_manager_bp
    m.pagina.ocupada = True
    m._move(Gtk.DirectionType.RIGHT)
    for botao in (gp.XINPUT_A, gp.XINPUT_B, gp.XINPUT_LEFT_SHOULDER):
        m._buttons = 0
        m._handle_buttons(SimpleNamespace(wButtons=botao))
    assert m.pagina.chamadas == [] and m.rumbles == []


def test_pagina_ocupada_fora_da_vista_engole_o_comando(pad_manager_bp):
    m = pad_manager_bp
    m.pagina.visivel = False  # o escuro da entrada: ainda não foi empilhada
    m.pagina.ocupada = True
    m.window = SimpleNamespace(
        get_focus=lambda: pytest.fail("não deve chegar à grade"),
        set_focus_visible=lambda *_: None,
    )
    m._move(Gtk.DirectionType.RIGHT)
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_A))
    assert m.pagina.chamadas == [] and m.rumbles == []


def _passos(m, pad, ate_us, passo_us=33_000):
    """Roda o relógio até `ate_us` desde o início e conta movimentos."""
    inicio = m._direction_since
    antes = len(m.pagina.chamadas)
    while m.clock["now"] - inicio < ate_us:
        m.clock["now"] += passo_us
        m._handle_direction(pad)
    return len(m.pagina.chamadas) - antes


def test_segurar_acelera_depois_de_um_segundo(pad_manager_bp):
    m = pad_manager_bp
    pad = SimpleNamespace(wButtons=gp.XINPUT_DPAD_RIGHT, sThumbLX=0, sThumbLY=0)
    m._handle_direction(pad)  # primeiro passo
    inicio = m.clock["now"]
    _passos(m, pad, 400_000)
    antes = _passos(m, pad, 1_000_000)  # 0,4 s .. 1 s
    depois = _passos(m, pad, 2_000_000)  # 1 s .. 2 s
    assert inicio == m._direction_since
    assert antes >= 3 and depois >= 3 * antes


def test_grade_mantem_a_repeticao_antiga(monkeypatch):
    """Sem página: mesma cadência de tests/test_ui_logic.py (400 ms + 120 ms * n)."""
    m = _base(monkeypatch)
    monkeypatch.setattr(m, "_move", lambda direcao: None)
    monkeypatch.setattr(shared, "win", None, raising=False)
    pad = SimpleNamespace(wButtons=gp.XINPUT_DPAD_RIGHT, sThumbLX=0, sThumbLY=0)
    m._handle_direction(pad)
    for atraso, repeticoes in (
        (gp.REPEAT_DELAY_US - 1, 0),
        (1, 1),
        (gp.REPEAT_INTERVAL_US - 1, 1),
        (1, 2),
    ):
        m.clock["now"] += atraso
        m._handle_direction(pad)
        assert m._repeats == repeticoes


def test_toque_de_capa_usa_rumble_capa(pad_manager_bp):
    m = pad_manager_bp
    assert gp.RUMBLE_CAPA == (0.5, 1.0, 90)
    m._move(Gtk.DirectionType.RIGHT)
    assert m.rumbles == [gp.RUMBLE_CAPA]


def test_toques_dentro_do_intervalo_vibram_uma_vez(pad_manager_bp):
    m = pad_manager_bp
    m._move(Gtk.DirectionType.RIGHT)
    m.clock["now"] += 100_000
    m._move(Gtk.DirectionType.RIGHT)
    assert m.rumbles == [gp.RUMBLE_CAPA]
    m.clock["now"] += 60_000  # 160 ms desde o primeiro toque
    m._move(Gtk.DirectionType.RIGHT)
    assert m.rumbles == [gp.RUMBLE_CAPA] * 2
    assert len(m.pagina.chamadas) == 3  # o carrossel anda mesmo sem vibrar


def test_segurar_varios_segundos_nao_acumula(pad_manager_bp):
    m = pad_manager_bp
    pad = SimpleNamespace(wButtons=gp.XINPUT_DPAD_RIGHT, sThumbLX=0, sThumbLY=0)
    m._handle_direction(pad)
    _passos(m, pad, 3_000_000)
    assert len(m.pagina.chamadas) > len(m.rumbles)
    assert len(m.rumbles) <= 3000 // 150 + 1


def test_grade_continua_com_rumble_move(pad_manager_bp, monkeypatch):
    m = pad_manager_bp
    monkeypatch.setattr(m, "_visible_viewport", lambda: None)
    monkeypatch.setattr(m, "_sync_active_game", lambda: None)
    monkeypatch.setattr(m, "_scroll_to_focus", lambda: None)
    monkeypatch.setattr(gp.Gtk.Settings, "get_default", staticmethod(lambda: None))
    m._focus_and_scroll(lambda: True)
    m._focus_and_scroll(lambda: False)
    assert m.rumbles == [gp.RUMBLE_MOVE, gp.RUMBLE_EDGE]


def test_comando_do_controle_avisa_ao_usar(pad_manager_bp):
    m = pad_manager_bp
    usos = []
    m.ao_usar = lambda: usos.append(1)
    m._move(Gtk.DirectionType.RIGHT)
    assert len(usos) == 1
    m.pagina.devolve = False
    m._move(Gtk.DirectionType.LEFT)  # bateu na ponta também conta
    assert len(usos) == 2
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_A))
    assert len(usos) == 3
    m._handle_buttons(SimpleNamespace(wButtons=gp.XINPUT_A))  # sem borda nova
    assert len(usos) == 3
