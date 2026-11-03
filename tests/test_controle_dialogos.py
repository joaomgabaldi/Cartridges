# test_controle_dialogos.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox nos diálogos e menus: o direcional anda por todos os controles (`scope.child_focus` da `main`).

O leitor é falso (não há controle físico neste PC): os testes entram pelo sinal `mover`/`ativar` do `ControleDaGrade`,
que é o que o `_ler` emite para o direcional e para o botão A. O hardware real não foi verificado.
"""

import pytest
from PySide6.QtCore import QMetaObject, Qt

from cartridges import shared
from cartridges.jogo import Jogo
from tests.apoio_edicao import jogo
from tests.apoio_fita import pastas  # noqa: F401  # a pasta descartável das fitas (autouse)
from tests.apoio_qml_biblioteca import _App, _esperar
from tests.apoio_qml_preferencias import _abrir, _avaliar

EDGE = (0.6, 0.2)  # RUMBLE_EDGE
MOVE = (0.0, 0.14)  # RUMBLE_MOVE


@pytest.fixture
def app(app_qt, store, monkeypatch):
    monkeypatch.setattr(Jogo, "launch", lambda self, *a: True)
    shared.schema.set_boolean("gamepad-rumble", True)
    jogos = [jogo(store, 1, name="Alfa", developer="Dev A"), jogo(store, 2, name="Beta")]
    janela = _App(jogos)
    monkeypatch.setattr(shared, "aplicativo", janela.aplicativo, raising=False)
    yield janela
    janela.fechar()


def _foco(app):
    return app.janela.property("activeFocusItem")


def _nome(app):
    foco = _foco(app)
    return foco.objectName() if foco is not None else ""


def _com_foco_em(app, nome):
    app.achar(nome).forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: _nome(app) == nome or app.achar(nome).property("activeFocus") is True)
    app.leitor.vibracoes.clear()


def test_alerta_o_direcional_chega_ao_botao_secundario(app):
    # C-08: o botão secundário só era alcançável pelo Tab.
    app.aplicativo.pedir_confirmacao("Excluir?", "Corpo", "Excluir", lambda _c: None, destrutivo=True)
    assert _esperar(lambda: app.achar("confirmacaoDoApp").property("visible") is True)
    cancelar = app.achar("botaoCancelarDoDialogo")
    assert _esperar(lambda: cancelar.property("activeFocus") is True)
    app.leitor.vibracoes.clear()
    app.controle.mover.emit(1, 0)
    assert app.achar("botaoConfirmarDoDialogo").property("activeFocus") is True
    assert app.leitor.vibracoes == [MOVE], "C-10: cada passo no diálogo vibra"
    app.controle.mover.emit(-1, 0)
    assert cancelar.property("activeFocus") is True


def test_editor_o_direcional_sai_do_campo_de_texto_e_vibra_na_parede(app):
    # C-01: a raiz do editor engolia as setas e, num campo, elas só moviam o cursor.
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("dialogoDeEdicao").property("visible") is True)
    _com_foco_em(app, "campoNome")
    texto = app.achar("campoNome").property("text")
    app.controle.mover.emit(0, 1)
    assert _nome(app) != "campoNome" and app.achar("campoNome").property("activeFocus") is False
    assert app.achar("campoNome").property("text") == texto
    assert app.leitor.vibracoes == [MOVE]
    # ↑ volta ao campo.
    app.controle.mover.emit(0, -1)
    assert app.achar("campoNome").property("activeFocus") is True


def test_editor_o_direcional_nao_muda_o_valor_de_uma_escolha(app):
    # C-02: ↑/↓ numa linha de escolha não alteram o valor; só movem o foco.
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("dialogoDeEdicao").property("visible") is True)
    escolha = app.achar("escolhaDeStatus")
    caixa = app.achar("escolhaDeStatusCaixa")
    caixa.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: caixa.property("activeFocus") is True)
    indice = escolha.property("currentIndex")
    for dy in (1, -1, 1):
        app.controle.mover.emit(0, dy)
    app.controle.mover.emit(1, 0)
    assert escolha.property("currentIndex") == indice


def test_a_abre_a_lista_de_escolha(app):
    # C-03: o `ComboBox` fechado não abre com o Return que o A envia.
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("dialogoDeEdicao").property("visible") is True)
    caixa = app.achar("escolhaDeStatusCaixa")
    caixa.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: caixa.property("activeFocus") is True)
    app.controle.ativar.emit()
    assert _esperar(lambda: _avaliar(caixa, "popup.visible") is True)


def test_sobre_o_direcional_alcanca_as_linhas(app):
    # C-06: da página principal só uma linha era alcançável; a raiz engolia as setas.
    app.sobre.abrir()
    assert _esperar(lambda: app.achar("dialogoSobre").property("visible") is True)
    _com_foco_em(app, "linhaProblemas")
    app.controle.mover.emit(0, 1)
    assert app.achar("linhaCreditos").property("activeFocus") is True
    app.controle.mover.emit(0, -1)
    assert app.achar("linhaProblemas").property("activeFocus") is True
    assert app.leitor.vibracoes == [MOVE, MOVE]


def test_preferencias_o_direcional_anda_entre_as_linhas_sem_mudar_valor(app):
    # C-02: em Preferências, o direcional anda entre as linhas e nunca muda valor (↑/↓ num `SpinBox` mudariam).
    _abrir(app, "general")
    caixa = app.achar("linhaDaEsperaCaixa")
    caixa.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: _foco(app) is not None and (_foco(app) is caixa or _foco(app).parentItem() is caixa))
    valor = caixa.property("value")
    app.leitor.vibracoes.clear()
    app.controle.mover.emit(0, 1)
    assert _foco(app) is not caixa and _foco(app).parentItem() is not caixa, "o foco saiu da linha para a seguinte"
    app.controle.mover.emit(0, -1)
    assert caixa.property("value") == valor
    assert app.leitor.vibracoes == [MOVE, MOVE]


def test_lista_de_escolha_aberta_o_direcional_e_o_a_escolhem(app):
    # C-03 até o fim: aberta pelo A, a lista anda com o direcional e o A escolhe o realçado.
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("dialogoDeEdicao").property("visible") is True)
    escolha = app.achar("escolhaDeStatus")
    caixa = app.achar("escolhaDeStatusCaixa")
    caixa.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    inicio = escolha.property("currentIndex")
    app.controle.ativar.emit()
    assert _esperar(lambda: _avaliar(caixa, "popup.visible") is True)
    app.controle.mover.emit(0, 1)
    assert _avaliar(caixa, "popup.visible") is True, "o direcional anda na lista, não sai dela"
    assert _avaliar(caixa, "highlightedIndex") == inicio + 1
    app.controle.ativar.emit()
    assert _esperar(lambda: _avaliar(caixa, "popup.visible") is False)
    assert escolha.property("currentIndex") == inicio + 1


def test_menu_cada_passo_vibra_e_a_ponta_vibra_o_toque(app):
    # C-10: em menus cada passo vibra, o tique se o realce andou e o toque firme se bateu.
    menu = app.achar("menuPrincipal")
    menu.open()
    assert _esperar(lambda: menu.property("opened") is True)
    app.leitor.vibracoes.clear()
    app.controle.mover.emit(0, 1)
    assert app.leitor.vibracoes == [MOVE]
    app.leitor.vibracoes.clear()
    for _ in range(20):  # além do último item
        app.controle.mover.emit(0, 1)
    assert app.leitor.vibracoes[-1] in (EDGE, MOVE)
    assert app.leitor.vibracoes.count(MOVE) < 20, "ao menos um passo bateu na ponta e vibrou o toque firme"


def test_balao_a_nao_quebra_linha_e_o_direcional_sai_do_texto(app):
    # C-09: o A num `TextView` não faz nada (o Return seria uma quebra de linha); o direcional não é do cursor.
    app.janela.abrirDetalhes("shortcuts_z1")
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    QMetaObject.invokeMethod(app.achar("botaoAnotacao"), "click", Qt.ConnectionType.DirectConnection)
    campo = app.achar("campoDaAnotacao")
    assert _esperar(lambda: campo.property("activeFocus") is True)
    campo.setProperty("text", "linha")
    campo.setProperty("cursorPosition", 2)
    app.leitor.vibracoes.clear()
    app.controle.ativar.emit()
    assert campo.property("text") == "linha", "o A não insere quebra de linha"
    app.controle.mover.emit(-1, 0)
    assert campo.property("cursorPosition") == 2, "o direcional não move o cursor"
    assert app.leitor.vibracoes == [EDGE], "sem vizinho no balão, o toque da parede"
