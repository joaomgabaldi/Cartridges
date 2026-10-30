# test_controle_sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox durante uma sessão de jogo: suspenso, a DLL solta e a volta.

O leitor e o relógio são falsos (não há controle físico neste PC); nenhum jogo é iniciado.
"""

from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from cartridges import jogo as modulo_jogo
from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.xinput import RUMBLE_LAUNCH
from tests.test_controle_grade import ATIVO, INATIVO, Montagem

CLASSICO = r'start "" "D:\Jogos\halo.exe"'


@pytest.fixture
def m():
    montagem = Montagem()
    montagem.tique()  # a primeira leitura só fixa a base
    montagem.eventos.clear()
    return montagem


def _lidos(montagem, sinal):
    achados = []
    getattr(montagem.controle, sinal).connect(lambda *a: achados.append(a))
    return achados


def _vencer_o_prazo(controle):
    """O prazo da soltura, disparado à mão: a vibração de abertura e 60 ms de folga."""
    soltura = controle._soltura  # noqa: SLF001
    assert soltura.isActive() and soltura.interval() == RUMBLE_LAUNCH[2] + 60
    soltura.stop()
    soltura.timeout.emit()


def test_suspender_para_de_ler_na_hora(m):
    m.controle.suspender()
    assert not m.controle.lendo
    assert not m.leitor.solto, "a DLL só sai depois do prazo"
    leituras = m.leitor.leituras
    m.controle.sincronizar()
    assert m.leitor.leituras == leituras


def test_solta_a_dll_so_depois_da_vibracao_de_abertura(m):
    shared.schema.set_boolean("gamepad-rumble", True)
    m.controle.vibrarAbertura()
    m.controle.suspender()
    assert m.leitor.vibracoes == [RUMBLE_LAUNCH[:2]] and not m.leitor.solto
    _vencer_o_prazo(m.controle)
    assert m.leitor.vibracoes[-1] == (0.0, 0.0), "os motores param antes de a DLL sair"
    assert m.leitor.solto and m.controle._leitor is None  # noqa: SLF001


def test_retomar_dentro_do_prazo_mantem_a_dll(m):
    m.controle.suspender()
    m.controle.retomar()
    assert not m.controle._soltura.isActive()  # noqa: SLF001
    assert m.controle.lendo and not m.leitor.solto and m.fabricados == 1


def test_retomar_recarrega_e_nao_avisa_conexao(m):
    conexoes, presentes = _lidos(m, "conectado"), _lidos(m, "presente")
    m.controle.suspender()
    _vencer_o_prazo(m.controle)
    m.controle.retomar()
    assert m.controle.lendo and m.fabricados == 2, "a DLL volta pela fábrica"
    m.leitor.botoes = 0x1000  # A segurado ao voltar: é a base, não um comando
    m.tique()
    assert presentes == [()] and conexoes == [], "o mesmo controle redescoberto não é uma conexão nova"
    assert m.comandos() == []


def test_desconectar_durante_a_sessao_avisa_ao_voltar(m):
    conexoes = _lidos(m, "conectado")
    m.controle.suspender()
    _vencer_o_prazo(m.controle)
    m.controle.retomar()
    ler = m.leitor.ler
    m.leitor.ler = lambda: None  # desligado durante a sessão: a primeira leitura volta sem controle
    m.tique()
    m.leitor.ler = ler
    m.tique()
    assert conexoes == [()], "religado depois da volta, é uma conexão"


def test_suspenso_ignora_foco_e_preferencia(m):
    m.controle.suspender()
    _vencer_o_prazo(m.controle)
    m.estado = INATIVO
    m.controle.sincronizar()
    m.estado = ATIVO
    m.controle.sincronizar()
    shared.schema.set_boolean("gamepad", False)
    shared.schema.set_boolean("gamepad", True)
    m.controle.sincronizar()
    assert not m.controle.lendo and m.fabricados == 1, "suspenso, nada religa a leitura nem a DLL"
    m.controle.retomar()
    assert m.controle.lendo


@pytest.mark.parametrize("vibrar", [False, True])
def test_vibrar_abertura_respeita_a_preferencia(m, vibrar):
    shared.schema.set_boolean("gamepad-rumble", vibrar)
    m.controle.vibrarAbertura()
    assert m.leitor.vibracoes == ([RUMBLE_LAUNCH[:2]] if vibrar else [])


class _ControleQueAnota:
    def __init__(self, passos):
        self.passos = passos

    def vibrarAbertura(self):  # noqa: N802
        self.passos.append("vibrar")

    def suspender(self):
        self.passos.append("suspender")

    def retomar(self):
        self.passos.append("retomar")


def test_abertura_vibra_antes_de_sair_da_frente(monkeypatch, schema):
    """A vibração sai antes de o controle ser suspenso: a DLL só é solta depois que ela acaba."""
    passos = []
    sessao = ModeloDaSessao(FilaDeAvisos(), controle=_ControleQueAnota(passos))
    monkeypatch.setattr(shared, "sessao", sessao, raising=False)
    monkeypatch.setattr(modulo_jogo, "run_executable", lambda *_a: passos.append("rodar"))
    schema.set_boolean("playtime-tracking", True)
    jogo = Jogo({"game_id": "shortcuts_1", "source": "shortcuts", "name": "Halo", "executable": CLASSICO, "added": 0})
    jogo.sair_da_frente.connect(lambda: passos.append("sair"), Qt.ConnectionType.DirectConnection)

    assert jogo.launch() is True

    assert passos == ["rodar", "vibrar", "suspender", "sair"]
    sessao.terminar()
    assert passos[-1] == "retomar"


def test_sessao_bloqueia_a_entrada_automatica(app_qt, monkeypatch):
    """Um controle conectado com a sessão à vista não abre o Big Picture por baixo dela, como na `main`."""
    from cartridges.modelos import big_picture as modulo_bp  # noqa: PLC0415
    from tests.test_qml_biblioteca import _App, _esperar, _jogos  # noqa: PLC0415

    monkeypatch.setattr(modulo_bp, "tem_3d", lambda _janela: True)
    app = _App(_jogos(*((n, f"Jogo {n}", {}) for n in range(3))))
    app.big_picture.definir_janela(app.janela)
    shared.schema.set_boolean("big-picture-ao-conectar", True)
    shared.schema.set_boolean("gamepad", True)
    jogo = SimpleNamespace(game_id="0", name="Jogo 0", notes="", zerado=False, status="")
    monkeypatch.setattr("cartridges.utils.game_logo.cached_logo_path", lambda _jogo: None)
    app.sessao.show_session_blocker(jogo)
    _esperar()
    app.controle.conectado.emit()
    assert not app.big_picture.ocupada and not app.big_picture.visivel
    app.sessao.hide_session_blocker()
    _esperar()
    app.controle.conectado.emit()  # sem sessão, a entrada automática volta a valer
    assert app.big_picture.ocupada
    assert _esperar(lambda: not app.big_picture.ocupada, limite=5)
    app.big_picture.encerrar()
    app.fechar()
