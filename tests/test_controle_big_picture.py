# test_controle_big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox no Big Picture: a repetição, a vibração, o aviso de conexão e o roteamento do QML.

O leitor é sempre falso (não há controle físico neste PC) e a cortina do fade também.
"""

import ctypes
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from cartridges import shared
from cartridges.modelos import big_picture as modulo_bp
from cartridges.modelos.controle import ControleDaGrade
from cartridges.xinput import (
    ACELERAR_APOS_US,
    INTERVALO_ACELERADO_US,
    INTERVALO_NORMAL_US,
    REPEAT_DELAY_US,
    REPEAT_INTERVAL_US,
    RUMBLE_CAPA,
    RUMBLE_EDGE,
    RUMBLE_PULO,
    XINPUT_DPAD_RIGHT,
    XINPUT_LEFT_SHOULDER,
    XINPUT_RIGHT_SHOULDER,
    LeitorXInput,
)
from tests.test_controle_grade import ATIVO, Montagem
from tests.test_qml_big_picture import _aberto_com, _entrar
from tests.test_qml_biblioteca import _esperar


@pytest.fixture(autouse=True)
def _sem_som(monkeypatch):
    from cartridges.modelos import regras_do_big_picture as regras  # noqa: PLC0415

    monkeypatch.setattr(regras, "tocar_tique", lambda: None)


# --- o controle em si (leitor e relógio falsos) -----------------------------------------------------


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


def test_segurar_acelera_depois_de_um_segundo(m):
    m.controle.modoBigPicture = True
    m.leitor.botoes = XINPUT_DPAD_RIGHT
    m.tique()
    assert len(m.comandos()) == 1
    m.tique(REPEAT_DELAY_US)  # a primeira repetição espera o atraso
    assert len(m.comandos()) == 2
    m.tique(INTERVALO_NORMAL_US - 1)
    assert len(m.comandos()) == 2
    m.tique(1)
    assert len(m.comandos()) == 3
    # Passado um segundo desde que apertou, o intervalo cai para 40 ms.
    m.tique(ACELERAR_APOS_US)
    assert len(m.comandos()) == 4
    antes = len(m.comandos())
    m.tique(INTERVALO_ACELERADO_US - 1)
    assert len(m.comandos()) == antes
    m.tique(1)
    assert len(m.comandos()) == antes + 1


def test_segurar_varios_segundos_nao_acumula(m):
    m.controle.modoBigPicture = True
    m.leitor.botoes = XINPUT_DPAD_RIGHT
    m.tique()
    m.tique(REPEAT_DELAY_US)
    m.eventos.clear()
    m.tique(5_000_000)  # a janela travou por cinco segundos: um tique, um passo
    assert m.comandos() == [("mover", 1, 0)]


def test_grade_mantem_a_repeticao_antiga(m):
    # Sem `modoBigPicture`: o atraso e depois 120 ms constantes, sem aceleração (a de 1 s e 1,5 s de contagem).
    m.leitor.botoes = XINPUT_DPAD_RIGHT
    m.tique()
    for _ in range(150):
        m.tique(10_000)
    esperado = 1 + 1 + (1_500_000 - REPEAT_DELAY_US) // REPEAT_INTERVAL_US
    assert len(m.comandos()) == esperado


@pytest.mark.parametrize(
    ("botao", "delta"), [(XINPUT_LEFT_SHOULDER, -10), (XINPUT_RIGHT_SHOULDER, 10)]
)
def test_lb_rb_emitem_pular(m, botao, delta):
    pulos = _lidos(m, "pular")
    m.leitor.botoes = botao
    m.tique()
    assert pulos == [(delta,)]
    assert m.comandos() == [] and "usado" in m.eventos
    m.tique(33_000)
    assert pulos == [(delta,)], "segurar não repete"


def test_toques_dentro_do_intervalo_vibram_uma_vez(m):
    shared.schema.set_boolean("gamepad-rumble", True)
    janela_us = (RUMBLE_CAPA[2] + 60) * 1000
    m.controle.trocarCapa()
    m.agora += janela_us - 1
    m.controle.trocarCapa()
    assert m.leitor.vibracoes == [RUMBLE_CAPA[:2]]
    m.agora += 1
    m.controle.trocarCapa()
    assert m.leitor.vibracoes == [RUMBLE_CAPA[:2]] * 2


def test_toque_sem_vibrar_nao_consome_a_vez(m):
    shared.schema.set_boolean("gamepad-rumble", False)
    m.controle.trocarCapa()
    shared.schema.set_boolean("gamepad-rumble", True)
    m.agora += 1
    m.controle.trocarCapa()
    assert m.leitor.vibracoes == [RUMBLE_CAPA[:2]], "só conta o intervalo de um toque que vibrou"


def test_saltar_vibra_o_pulo_e_respeita_a_preferencia(m):
    shared.schema.set_boolean("gamepad-rumble", True)
    m.controle.saltar()
    assert m.leitor.vibracoes == [RUMBLE_PULO[:2]]
    m.leitor.vibracoes.clear()
    shared.schema.set_boolean("gamepad-rumble", False)
    m.controle.saltar()
    m.controle.trocarCapa()
    assert m.leitor.vibracoes == []


def test_conectar_avisa_uma_vez():
    montagem = Montagem()
    avisos = _lidos(montagem, "conectado")
    montagem.tique()
    montagem.tique(33_000)
    assert len(avisos) == 1


def test_desconectar_e_conectar_avisa_de_novo():
    montagem = Montagem()
    avisos = _lidos(montagem, "conectado")
    montagem.tique()
    original = montagem.leitor.ler
    montagem.leitor.ler = lambda: None
    montagem.tique(33_000)
    montagem.leitor.ler = original
    montagem.tique(33_000)
    assert len(avisos) == 2


def test_foco_de_volta_nao_e_conexao():
    montagem = Montagem()
    avisos, presentes = _lidos(montagem, "conectado"), _lidos(montagem, "presente")
    montagem.tique()
    montagem.estado = Qt.ApplicationState.ApplicationInactive
    montagem.controle.sincronizar()
    montagem.estado = ATIVO
    montagem.controle.sincronizar()
    montagem.tique(33_000)
    assert len(presentes) == 2, "o foco de volta acende a seleção, como sempre"
    assert len(avisos) == 1, "mas o mesmo controle não é uma conexão nova"


# --- a entrada automática ---------------------------------------------------------------------------


def _entrada(monkeypatch, *, preferencia=True, controle=True, tem_3d=True, grade=True, ja_saiu=False, quantidade=3):
    from tests.test_qml_biblioteca import _App, _jogos  # noqa: PLC0415

    monkeypatch.setattr(modulo_bp, "tem_3d", lambda _janela: tem_3d)
    app = _App(_jogos(*((n, f"Jogo {n}", {}) for n in range(quantidade))))
    app.big_picture.definir_janela(app.janela)
    app.big_picture._ja_saiu = ja_saiu  # noqa: SLF001
    for chave, valor in (("big-picture-ao-conectar", preferencia), ("gamepad", controle)):
        shared.schema.set_boolean(chave, valor)
    app.big_picture.controleConectado(grade)
    return app


def test_entrada_automatica_so_com_tudo_permitindo(app_qt, monkeypatch):
    app = _entrada(monkeypatch)
    assert app.big_picture.ocupada, "com tudo permitido, entra (o fade começa)"
    assert _esperar(lambda: app.big_picture.visivel, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=5)
    app.big_picture.encerrar()
    app.fechar()
    for falta in ("preferencia", "controle", "tem_3d", "grade"):
        app = _entrada(monkeypatch, **{falta: False})
        assert not app.big_picture.ocupada and not app.big_picture.visivel, f"sem {falta} não entra"
        app.fechar()


def test_ja_ter_saido_bloqueia(app_qt, monkeypatch):
    app = _entrada(monkeypatch, ja_saiu=True)
    assert not app.big_picture.ocupada and not app.big_picture.visivel
    app.fechar()


def test_conectado_do_qml_so_com_a_grade_a_vista(app_qt, monkeypatch):
    app = _entrada(monkeypatch, grade=False)  # o slot não faz nada
    shared.schema.set_boolean("big-picture-ao-conectar", True)
    shared.schema.set_boolean("gamepad", True)
    app.controle.conectado.emit()  # o QML passa `paginaAtual === "todos" && !popupAberto`
    assert app.big_picture.ocupada
    assert _esperar(lambda: not app.big_picture.ocupada and app.big_picture.visivel, limite=5)
    app.big_picture.encerrar()
    app.fechar()


def test_conectado_com_menu_aberto_nao_entra(app_qt, monkeypatch):
    app = _entrada(monkeypatch, grade=False)
    shared.schema.set_boolean("big-picture-ao-conectar", True)
    shared.schema.set_boolean("gamepad", True)
    app.achar("menuPrincipal").open()
    app.controle.conectado.emit()
    assert not app.big_picture.ocupada
    app.fechar()


# --- o roteamento no Aplicativo.qml ------------------------------------------------------------------


def _com_big_picture(monkeypatch, quantidade=5):
    app = _aberto_com(monkeypatch, quantidade=quantidade)
    shared.schema.set_boolean("gamepad-rumble", True)
    _entrar(app)
    app.leitor.vibracoes.clear()
    return app


def _vibracoes(app):
    return list(app.leitor.vibracoes)


def test_seta_move_o_carrossel_e_vibra_a_capa(app_qt, monkeypatch):
    app = _com_big_picture(monkeypatch)
    app.controle.mover.emit(1, 0)
    assert app.big_picture.indice == 1
    assert _vibracoes(app)[0] == RUMBLE_CAPA[:2]
    app.controle.mover.emit(-1, 0)
    assert app.big_picture.indice == 0
    app.big_picture.encerrar()
    app.fechar()


def test_na_ponta_vibra_o_fim(app_qt, monkeypatch):
    app = _com_big_picture(monkeypatch)
    app.controle.mover.emit(-1, 0)  # já está no primeiro
    assert app.big_picture.indice == 0
    assert _vibracoes(app)[0] == RUMBLE_EDGE[:2]
    app.big_picture.encerrar()
    app.fechar()


def test_cima_e_baixo_nao_fazem_nada(app_qt, monkeypatch):
    app = _com_big_picture(monkeypatch)
    app.controle.mover.emit(0, -1)
    app.controle.mover.emit(0, 1)
    assert app.big_picture.indice == 0 and _vibracoes(app) == []
    assert app.achar("botaoBigPicture").property("activeFocus") is False
    app.big_picture.encerrar()
    app.fechar()


def test_lb_rb_pulam_dez(app_qt, monkeypatch):
    app = _com_big_picture(monkeypatch, quantidade=25)
    app.controle.pular.emit(10)
    assert app.big_picture.indice == 10
    assert _vibracoes(app)[0] == RUMBLE_PULO[:2]
    app.controle.pular.emit(-10)
    assert app.big_picture.indice == 0
    app.big_picture.encerrar()
    app.fechar()


def test_pulo_na_ponta_vibra_o_fim(app_qt, monkeypatch):
    app = _com_big_picture(monkeypatch)
    app.controle.pular.emit(-10)
    assert app.big_picture.indice == 0
    assert _vibracoes(app) == [RUMBLE_EDGE[:2]]
    app.controle.pular.emit(10)  # com 5 jogos, o pulo vai até o último e conta como andar
    assert app.big_picture.indice == 4
    assert _vibracoes(app)[-1] == RUMBLE_PULO[:2]
    app.controle.pular.emit(10)
    assert _vibracoes(app)[-1] == RUMBLE_EDGE[:2]
    app.big_picture.encerrar()
    app.fechar()


def test_a_abre_e_b_sai(app_qt, monkeypatch):
    from tests.test_qml_big_picture import _com_launch_falso  # noqa: PLC0415

    app = _aberto_com(monkeypatch)
    jogo = _com_launch_falso(app, monkeypatch)
    _entrar(app)
    app.controle.ativar.emit()
    assert app.big_picture.ocupada, "A abre o jogo do centro"
    assert _esperar(lambda: jogo.launch.chamadas == 1, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    app.controle.voltar.emit()
    assert app.big_picture.ocupada
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    app.big_picture.encerrar()
    app.fechar()


@pytest.mark.parametrize("sinal", ["menuPrincipal", "menuDoJogo", "buscar"])
def test_start_y_back_nada(app_qt, monkeypatch, sinal):
    app = _com_big_picture(monkeypatch)
    getattr(app.controle, sinal).emit()
    assert app.achar("menuPrincipal").property("opened") is False
    assert app.achar("pagina").property("buscaAberta") is False
    assert app.big_picture.visivel and not app.big_picture.ocupada and app.big_picture.indice == 0
    app.big_picture.encerrar()
    app.fechar()


def test_ocupada_ignora_tudo(app_qt, monkeypatch):
    from tests.test_qml_big_picture import _com_launch_falso  # noqa: PLC0415

    app = _aberto_com(monkeypatch)
    jogo = _com_launch_falso(app, monkeypatch)
    _entrar(app)
    app.big_picture.abrirJogo()
    assert app.big_picture.ocupada
    app.leitor.vibracoes.clear()
    shared.schema.set_boolean("gamepad-rumble", True)
    for sinal, args in (("mover", (1, 0)), ("pular", (10,)), ("ativar", ()), ("voltar", ())):
        getattr(app.controle, sinal).emit(*args)
    assert app.big_picture.indice == 0 and app.big_picture.visivel
    assert _vibracoes(app) == [], "ocupada não vibra nem o fim"
    assert _esperar(lambda: jogo.launch.chamadas == 1, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    assert jogo.launch.chamadas == 1
    app.big_picture.encerrar()
    app.fechar()


def test_ocupada_fora_da_vista_engole_o_comando(app_qt, monkeypatch):
    # No escuro da entrada a camada ainda não apareceu, mas a grade também não recebe o comando.
    app = _aberto_com(monkeypatch)
    app.big_picture.entrar()
    assert app.big_picture.ocupada
    app.achar("pagina").mostrarSelecao()
    app.controle.mover.emit(1, 0)
    app.controle.ativar.emit()
    app.controle.menuPrincipal.emit()
    app.controle.buscar.emit()
    assert app.achar("menuPrincipal").property("opened") is False
    assert app.achar("pagina").property("buscaAberta") is False
    assert app.janela.property("paginaAtual") == "todos", "A não abriu os detalhes"
    assert _esperar(lambda: not app.big_picture.ocupada, limite=5)
    assert app.big_picture.indice == 0
    app.big_picture.encerrar()
    app.fechar()


def test_dialogo_aberto_tira_a_entrada_do_big_picture(app_qt, monkeypatch):
    app = _com_big_picture(monkeypatch)
    app.aplicativo.dialogoPedido.emit("Aviso", "Corpo", [])
    avisos = app.achar("camadaDeAvisos")
    assert avisos.property("dialogoAberto") is True
    app.controle.mover.emit(1, 0)  # com diálogo na frente vale o caminho das teclas, não o carrossel
    assert app.big_picture.indice == 0
    app.controle.pular.emit(10)
    app.controle.menuPrincipal.emit()
    assert app.big_picture.indice == 0 and app.achar("menuPrincipal").property("opened") is False
    app.big_picture.encerrar()
    app.fechar()


# --- a reserva de DLL e os quatro slots (já existem no xinput.py; aqui só a prova) -------------------


def _dll_falsa(slot_ocupado=None):
    biblioteca = MagicMock()
    consultados = []

    def get_state(slot, _ref):
        consultados.append(slot)
        return 0 if slot == slot_ocupado else 1167  # ERROR_DEVICE_NOT_CONNECTED

    biblioteca.XInputGetState = get_state
    biblioteca.XInputSetState = MagicMock()
    return biblioteca, consultados


def test_leitor_tem_reserva_de_dll(monkeypatch):
    biblioteca, _ = _dll_falsa()
    carregadas = []

    def win_dll(nome):
        carregadas.append(nome)
        if nome == "xinput1_4.dll":
            raise OSError(nome)
        return biblioteca

    monkeypatch.setattr(ctypes, "WinDLL", win_dll, raising=False)
    leitor = LeitorXInput()
    assert leitor.disponivel and leitor.xinput is biblioteca
    assert carregadas == ["xinput1_4.dll", "xinput1_3.dll"]


def test_leitor_sem_nenhuma_dll_fica_indisponivel(monkeypatch):
    def win_dll(nome):
        raise OSError(nome)

    monkeypatch.setattr(ctypes, "WinDLL", win_dll, raising=False)
    leitor = LeitorXInput()
    assert not leitor.disponivel and leitor.ler() is None


def test_leitor_acha_o_controle_em_qualquer_slot(monkeypatch):
    biblioteca, consultados = _dll_falsa(slot_ocupado=3)
    monkeypatch.setattr(ctypes, "WinDLL", lambda _nome: biblioteca, raising=False)
    leitor = LeitorXInput()
    pad = leitor.ler()
    assert pad is not None and leitor.slot == 3
    assert consultados == [0, 1, 2, 3]
    consultados.clear()
    leitor.ler()
    assert consultados == [3], "com o controle achado, só o slot dele é lido"

