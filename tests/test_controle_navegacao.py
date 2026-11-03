# test_controle_navegacao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O controle do Xbox na biblioteca e na barra: grade, busca, página vazia, detalhes, Start e Y (pacote C da auditoria).

O leitor é falso (não há controle físico neste PC): os testes entram pelos sinais do `ControleDaGrade` (`mover`, `ativar`,
`menuPrincipal`, `menuDoJogo`, `presente`), que é o que o `_ler` emite para o direcional e para os botões. O hardware real
não foi verificado.
"""

import pytest
from PySide6.QtCore import Qt

from cartridges import shared
from tests.apoio_qml_biblioteca import _App, _esperar, _jogos
from tests.apoio_qml_preferencias import _avaliar

EDGE = (0.6, 0.2)  # RUMBLE_EDGE
MOVE = (0.0, 0.14)  # RUMBLE_MOVE


def _app(quantidade=3, colunas=0):
    shared.schema.set_boolean("gamepad-rumble", True)
    shared.schema._gravar("library-rows", "u", colunas)  # noqa: SLF001
    app = _App(_jogos(*((n, f"Jogo {n:02}", {}) for n in range(quantidade))))
    app.leitor.vibracoes.clear()
    return app


@pytest.fixture(autouse=True)
def _restaura_colunas():
    yield
    shared.schema.reset("library-rows")


def test_baixo_sem_cartao_na_coluna_fica_e_vibra_o_tique(app_qt):
    # C-23: o `GtkFlowBox` não anda quando não há cartão embaixo (medido: `child_focus` devolve True e o foco não sai).
    app = _app(7, colunas=3)
    grade = app.achar("grade")
    grade.setProperty("currentIndex", 5)  # segunda linha, última coluna; a terceira só tem a coluna 0
    app.controle.mover.emit(0, 1)
    assert grade.property("currentIndex") == 5
    assert app.leitor.vibracoes == [MOVE], "contra a parede o `FlowBox` responde que andou: o tique leve"
    grade.setProperty("currentIndex", 3)
    app.controle.mover.emit(0, 1)
    assert grade.property("currentIndex") == 6
    app.fechar()


def test_barra_e_grade_vibram_nos_dois_sentidos(app_qt):
    # C-11: ↑ da grade para a barra e ↓ da barra para a grade.
    app = _app()
    app.controle.mover.emit(0, -1)
    assert app.leitor.vibracoes == [MOVE]
    app.leitor.vibracoes.clear()
    app.controle.mover.emit(0, 1)
    assert app.achar("grade").property("activeFocus") is True
    assert app.leitor.vibracoes == [MOVE]
    app.fechar()


def test_presente_com_botao_da_barra_focado_vai_ao_primeiro_jogo(app_qt):
    # C-12: o controle detectado com o foco na barra leva ao primeiro jogo, com o tique e a seleção à mostra.
    app = _app()
    grade = app.achar("grade")
    grade.setProperty("currentIndex", 2)
    app.achar("botaoBusca").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    app.controle.presente.emit()
    assert grade.property("activeFocus") is True
    assert grade.property("currentIndex") == 0
    assert grade.property("porTeclado") is True
    assert app.leitor.vibracoes == [MOVE]
    # Já na grade: só acende a seleção, no cartão em que estava, sem vibrar.
    app.leitor.vibracoes.clear()
    grade.setProperty("currentIndex", 2)
    grade.setProperty("porTeclado", False)
    app.controle.presente.emit()
    assert grade.property("currentIndex") == 2 and grade.property("porTeclado") is True
    assert app.leitor.vibracoes == []
    app.fechar()


def test_sair_do_big_picture_acende_a_selecao_no_cartao(app_qt):
    # C-13: `_show_selection` liga o foco visível antes de checar o Big Picture.
    app = _app()
    grade = app.achar("grade")
    grade.setProperty("porTeclado", False)
    app.big_picture.saiu.emit("imported_1")
    assert grade.property("currentIndex") == 1
    assert grade.property("porTeclado") is True
    app.fechar()


def test_a_na_busca_abre_o_primeiro_resultado(app_qt):
    # C-14: o A com o foco na busca faz o que o Enter do campo faz.
    from PySide6.QtCore import QMetaObject  # noqa: PLC0415

    app = _app(3)
    QMetaObject.invokeMethod(app.achar("botaoBusca"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.achar("campoDeBusca").property("activeFocus") is True)
    app.achar("grade").setProperty("currentIndex", 2)  # o cartão atual não é o primeiro
    app.controle.ativar.emit()
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    assert app.detalhes.nome == "Jogo 00"
    app.fechar()


def test_baixo_na_busca_so_entra_na_grade(app_qt):
    # C-15: ↓ não anda uma linha; ←/→ não mexem na seleção; ↑ vai à barra.
    from PySide6.QtCore import QMetaObject  # noqa: PLC0415

    app = _app(7, colunas=3)
    QMetaObject.invokeMethod(app.achar("botaoBusca"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.achar("campoDeBusca").property("activeFocus") is True)
    grade = app.achar("grade")
    grade.setProperty("currentIndex", 1)
    app.controle.mover.emit(1, 0)
    app.controle.mover.emit(-1, 0)
    assert grade.property("currentIndex") == 1 and app.achar("campoDeBusca").property("activeFocus") is True
    app.controle.mover.emit(0, 1)
    assert grade.property("activeFocus") is True and grade.property("currentIndex") == 1
    app.fechar()


def test_y_so_age_com_foco_no_cartao(app_qt):
    # C-16: na barra ou na busca o Y não abre o menu do cartão (a `main` também não).
    app = _app()
    app.achar("botaoBusca").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    app.controle.menuDoJogo.emit()
    _esperar()
    assert app.achar("menuDoJogo").property("visible") is False
    app.achar("grade").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    app.controle.menuDoJogo.emit()
    assert _esperar(lambda: app.achar("menuDoJogo").property("visible") is True)
    app.fechar()


def test_start_so_abre_o_menu_em_todos_e_zerados(app_qt):
    # C-17: nos detalhes e nas Novidades o Start não abre o menu principal.
    app = _app()
    app.janela.abrirDetalhes("imported_1")
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    app.controle.menuPrincipal.emit()
    _esperar()
    assert app.achar("menuPrincipal").property("opened") is False
    app.janela.voltar()
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    app.controle.menuPrincipal.emit()
    assert _esperar(lambda: app.achar("menuPrincipal").property("opened") is True)
    app.fechar()


def test_rolagem_pelo_controle_segue_as_regras_da_main(app_qt):
    # C-20: primeira linha volta à margem, última vai ao fim, no meio só o bastante; 200 ms OutCubic.
    app = _app(40, colunas=3)
    grade = app.achar("grade")
    assert _esperar(lambda: grade.property("height") > 0)
    minimo = _avaliar(grade, "originY - topMargin")
    maximo = _avaliar(grade, "originY + contentHeight + bottomMargin - height")
    assert maximo > minimo, "a grade precisa rolar para o teste valer"
    animacao = app.achar("rolagemDoControle")
    assert (animacao.property("duration"), _avaliar(animacao, "easing.type == Easing.OutCubic")) == (200, True)
    for _ in range(4):
        app.controle.mover.emit(0, 1)
    assert grade.property("contentY") > minimo, "uma linha fora da vista rola o bastante para ela caber"
    for _ in range(20):
        app.controle.mover.emit(0, 1)
    assert grade.property("currentIndex") >= 37
    assert grade.property("contentY") == pytest.approx(maximo, abs=1), "a última linha vai ao fim"
    for _ in range(20):
        app.controle.mover.emit(0, -1)
    assert grade.property("currentIndex") <= 2
    assert grade.property("contentY") == pytest.approx(minimo, abs=1), "a primeira linha volta à margem"
    app.fechar()


def test_pagina_vazia_o_direcional_alcanca_o_botao_importar_e_o_a_aciona(app_qt):
    # C-21: sem jogos, ↓ foca o botão "Importar" e A o aciona.
    app = _app(0)
    chamadas = []
    app.aplicativo.importar = lambda: chamadas.append("importar")
    estado = app.achar("estadoVazio")
    assert _esperar(lambda: estado.property("visible") is True)
    app.controle.mover.emit(0, 1)
    assert estado.property("botaoFocado") is True
    assert app.leitor.vibracoes == [MOVE]
    app.controle.ativar.emit()
    assert chamadas == ["importar"]
    app.controle.mover.emit(0, -1)  # ↑ volta à barra
    assert estado.property("botaoFocado") is False
    app.fechar()


def test_detalhes_o_foco_rola_a_pagina(app_qt):
    # C-22: o botão fora da vista rola para dentro dela.
    app = _app()
    app.janela.abrirDetalhes("imported_1")
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    pagina = app.achar("paginaDoJogo")
    rolagem = app.achar("rolagemDaPagina")
    pagina.setProperty("height", 120)  # uma janela baixa: a página rola
    _esperar()
    assert _avaliar(rolagem, "contentHeight > height"), "a janela baixa deixa botões fora da vista"
    def na_vista():
        botao = app.janela.property("activeFocusItem")
        topo = botao.mapToItem(rolagem.property("contentItem"), 0, 0).y()
        y = rolagem.property("contentY")
        return y - 1 <= topo and topo + botao.height() <= y + rolagem.height() + 1

    linhas = _avaliar(pagina, "linhasDeBotoes().length")
    for _ in range(linhas - 1):  # o foco inicial está embaixo: sobe até a primeira linha e desce de novo
        app.controle.mover.emit(0, -1)
    assert na_vista()
    no_topo = rolagem.property("contentY")
    for _ in range(linhas - 1):
        app.controle.mover.emit(0, 1)
    assert app.janela.property("activeFocusItem").objectName() == "botaoJogarDaPagina"
    assert na_vista() and rolagem.property("contentY") > no_topo, "o botão de baixo rolou para dentro da vista"
    app.fechar()
