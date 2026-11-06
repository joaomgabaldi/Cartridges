# test_qml_big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tela do cover flow do Big Picture: geometria, vagas, teclado, mouse e capas (QML offscreen)."""

import math
import os
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QObject, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QWheelEvent, QWindow
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.modelos import biblioteca as modulo_biblioteca
from cartridges.modelos import regras_do_big_picture as regras
from cartridges.modelos.big_picture import BigPicture
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.process_session import ProcessSession
from tests.apoio_qml_biblioteca import QML, _achar, _esperar, _LojaFalsa
from tests.apoio_qml_big_picture import (
    ALTURA,
    LARGURA,
    _abrir_jogo,
    _Tela,
    _aberto_com,
    _avaliar,
    _com_launch_falso,
    _entrar,
    _itens,
)


@pytest.fixture(autouse=True)
def _sem_som(monkeypatch):
    monkeypatch.setattr(regras, "tocar_tique", lambda: None)


def _produto(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


# A convenção do giro (sinal) e da perspectiva é a mesma do QML: a equivalência com o `rotate_3d` do
# Graphene vem das capturas do protótipo; aqui pega-se regressão e erro de encadeamento.
def _referencia_do_gtk(i, posicao, virada, largura_tela, altura_tela):
    """Os cantos projetados da capa `i`, pela cadeia de transformação e de arranjo."""
    altura = altura_tela * 0.60
    largura = altura * 2 / 3
    d = i - posicao
    a = min(abs(d), 1.0)
    lado = math.copysign(1, d)
    if abs(d) <= 1:
        x = d * largura * regras.ESPACO_CENTRAL
    else:
        x = lado * (largura * regras.ESPACO_CENTRAL + (abs(d) - 1) * largura * regras.ESPACO_LATERAL)
    angulo = -lado * a * regras.ANGULO_LATERAL
    prof = -a * regras.PROFUNDIDADE_LATERAL
    if virada != 1.0:
        x_fila = d * largura * regras.ESPACO_LATERAL * 1.6
        x, angulo, prof = (
            x_fila + (x - x_fila) * virada,
            -regras.ANGULO_LATERAL + (angulo + regras.ANGULO_LATERAL) * virada,
            -regras.PROFUNDIDADE_LATERAL + (prof + regras.PROFUNDIDADE_LATERAL) * virada,
        )

    def trans(tx, ty, tz):
        return [[1, 0, 0, tx], [0, 1, 0, ty], [0, 0, 1, tz], [0, 0, 0, 1]]

    r = math.radians(angulo)
    c, s = math.cos(r), math.sin(r)
    perspectiva = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, -1 / regras.PERSPECTIVA, 1]]
    giro = [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]
    m = trans(largura_tela / 2, altura_tela * 0.52, 0)
    for passo in (perspectiva, trans(x, 0, prof), giro, trans(-largura / 2, -altura / 2, 0)):
        m = _produto(m, passo)
    cantos = []
    for px, py in ((0, 0), (largura, 0), (largura, altura), (0, altura)):
        v = [sum(m[k][j] * (px, py, 0, 1)[j] for j in range(4)) for k in range(4)]
        cantos.append((v[0] / v[3], v[1] / v[3]))
    return cantos


def _cantos(tela, i):
    achados = tela.js(
        f"(function(){{const m=transformacao({i}); return [[0,0],[larguraCapa,0],[larguraCapa,alturaCapa],[0,alturaCapa]]"
        ".map(([x,y])=>{const v=m.times(Qt.vector4d(x,y,0,1)); return [v.x/v.w, v.y/v.w]})})()"
    )
    return [tuple(p) for p in achados]


def _dentro(cantos, px, py):
    lados = [
        (bx - ax) * (py - ay) - (by - ay) * (px - ax)
        for (ax, ay), (bx, by) in zip(cantos, cantos[1:] + cantos[:1], strict=True)
    ]
    return all(v >= 0 for v in lados) or all(v <= 0 for v in lados)


def _capa_em(tela, x, y):
    return tela.js(f"capaEm({x}, {y})")


def test_capa_em_acha_a_central_no_meio(app_qt):
    tela = _Tela()
    assert _capa_em(tela, LARGURA / 2, ALTURA * 0.52) == 0
    tela.bp.irPara(3)
    assert _capa_em(tela, LARGURA / 2, ALTURA * 0.52) == 3
    tela.fechar()


def test_capa_em_lateral_pela_caixa_alinhada(app_qt):
    # A caixa que contém a capa projetada acerta, mesmo nos cantos que o quadrilátero inclinado deixa de fora.
    tela = _Tela()
    tela.bp.irPara(2)
    cantos = _cantos(tela, 1)
    centro = (sum(x for x, _ in cantos) / 4, sum(y for _, y in cantos) / 4)
    assert _capa_em(tela, *centro) == 1
    xs, ys = [x for x, _ in cantos], [y for _, y in cantos]
    vizinha = _cantos(tela, 2)  # a central desenha por cima da que está ao lado
    vx, vy = [x for x, _ in vizinha], [y for _, y in vizinha]
    fora = [
        (x, y)
        for x in (min(xs) + 1, max(xs) - 1)
        for y in (min(ys) + 1, max(ys) - 1)
        if not _dentro(cantos, x, y) and not (min(vx) <= x <= max(vx) and min(vy) <= y <= max(vy))
    ]
    assert fora, "a capa lateral inclinada tem de deixar cantos da caixa fora do quadrilátero"
    for x, y in fora:
        assert _capa_em(tela, x, y) == 1
    # Fora da caixa, nada.
    assert _capa_em(tela, min(xs) - 5, max(ys) + 5) != 1
    tela.fechar()


def test_capa_em_fora_de_tudo(app_qt):
    tela = _Tela()
    assert _capa_em(tela, 1, 1) == -1
    assert _capa_em(tela, LARGURA - 1, ALTURA - 1) == -1
    tela.fechar()


@pytest.mark.parametrize(("posicao", "virada"), [(2.0, 1.0), (1.5, 1.0), (2.0, 0.6), (2.3, 0.4)])
def test_transformacao_igual_a_do_gtk(app_qt, posicao, virada):
    tela = _Tela()
    tela.tela.setProperty("virada", virada)
    tela.tela.setProperty("posicao", posicao)
    for i in (1, 2, 3):
        obtido = _cantos(tela, i)
        esperado = _referencia_do_gtk(i, posicao, virada, LARGURA, ALTURA)
        for (ox, oy), (ex, ey) in zip(obtido, esperado, strict=True):
            assert ox == pytest.approx(ex, abs=0.01)
            assert oy == pytest.approx(ey, abs=0.01)
    tela.fechar()


def test_constantes_iguais_as_das_regras(app_qt):
    tela = _Tela()
    for qml, valor in (
        ("perspectiva", regras.PERSPECTIVA), ("anguloLateral", regras.ANGULO_LATERAL),
        ("espacoCentral", regras.ESPACO_CENTRAL), ("espacoLateral", regras.ESPACO_LATERAL),
        ("profundidadeLateral", regras.PROFUNDIDADE_LATERAL), ("capasDeCadaLado", regras.CAPAS_DE_CADA_LADO),
        ("duracaoDoPasso", regras.DURACAO_PASSO_MS),
        ("reflexoAlcance", regras.REFLEXO_ALCANCE), ("reflexoOpacidade", regras.REFLEXO_OPACIDADE),
    ):  # fmt: skip
        assert tela.tela.property(qml) == pytest.approx(valor), qml
    tela.fechar()


def test_virada_0_todas_de_perfil(app_qt):
    tela = _Tela()
    tela.tela.setProperty("virada", 0)
    for i in range(5):
        assert tela.js(f"arranjo({i})[1]") == pytest.approx(-regras.ANGULO_LATERAL)
    tela.fechar()


@pytest.mark.parametrize("quantidade", [5, 1050])
def test_dezessete_vagas_qualquer_tamanho(app_qt, quantidade):
    tela = _Tela(quantidade)
    tela.bp.irPara(quantidade // 2)
    _esperar()
    # Só as vagas do carrossel: o `Botao` também tem um `Loader`, o da medida do rótulo.
    assert len([v for v in tela.itens("QQuickLoader") if v.property("i") is not None]) == 17
    capas = _itens(tela.tela, lambda i: i.objectName() == "capaDoBigPicture")
    assert len(capas) == min(quantidade, 15)
    tela.fechar()


def test_teclas_movem(app_qt):
    tela = _Tela()
    for tecla, esperado in (
        (Qt.Key.Key_Right, 1), (Qt.Key.Key_Right, 2), (Qt.Key.Key_Left, 1),
        (Qt.Key.Key_End, 4), (Qt.Key.Key_Home, 0), (Qt.Key.Key_PageDown, 4), (Qt.Key.Key_PageUp, 0),
    ):  # fmt: skip
        QTest.keyClick(tela.janela, tecla)
        assert tela.bp.indice == esperado, tecla
    tela.fechar()


def test_enter_ativa_e_esc_volta(app_qt):
    tela = _Tela()
    tela.bp.definir_animacoes_do_sistema(False)  # noqa: FBT003
    for tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
        QTest.keyClick(tela.janela, tecla)
        assert tela.bp.etapa == "detalhes", tecla
        QTest.keyClick(tela.janela, Qt.Key.Key_Escape)
        assert tela.bp.etapa == "carrossel", tecla
    QTest.keyClick(tela.janela, Qt.Key.Key_Escape)  # no carrossel, o Esc sai do Big Picture
    assert tela.bp.jaSaiu  # sem animações a saída termina na hora
    tela.fechar()


def test_sem_animacoes_troca_de_etapa_direto(app_qt):
    tela = _Tela()
    tela.bp.definir_animacoes_do_sistema(False)  # noqa: FBT003
    tela.bp.ativar()
    assert (tela.bp.etapa, tela.bp.ocupada) == ("detalhes", False)  # `etapaTerminou` no mesmo ciclo
    tela.fechar()


def _clicar(tela, x, y):
    QTest.mouseClick(tela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x), round(y)))


def test_toque_na_central_abre_e_na_lateral_vai(app_qt):
    tela = _Tela()
    tela.bp.irPara(2)
    tela.bp.definir_animacoes_do_sistema(False)  # noqa: FBT003
    _clicar(tela, LARGURA / 2, ALTURA * 0.52)
    assert tela.bp.etapa == "detalhes"
    tela.bp.voltar()
    cantos = _cantos(tela, 3)
    _clicar(tela, sum(x for x, _ in cantos) / 4, sum(y for _, y in cantos) / 4)
    assert tela.bp.indice == 3
    assert tela.bp.etapa == "carrossel"
    _clicar(tela, 1, 1)
    assert tela.bp.indice == 3
    tela.fechar()


def test_toque_depois_de_arrastar_nao_conta(app_qt):
    tela = _Tela()
    tela.bp.irPara(3)
    x0, y = LARGURA / 2, ALTURA * 0.52
    QTest.mousePress(tela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x0), round(y)))
    for dx in range(10, 211, 20):
        QTest.mouseMove(tela.janela, QPoint(round(x0 + dx), round(y)))
        _esperar()
    QTest.mouseRelease(
        tela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x0 + 210), round(y))
    )
    _esperar()
    assert tela.bp.etapa == "carrossel"
    # Arrastar para a direita traz as capas anteriores: dx / (0,45 · larguraCapa) passos.
    passos = int(210 / (regras.ESPACO_LATERAL * (ALTURA * 0.60 * 2 / 3)))
    assert passos >= 1
    assert tela.bp.indice == 3 - passos
    tela.fechar()


def test_roda_um_passo(app_qt):
    tela = _Tela()
    ponto = QPointF(LARGURA / 2, ALTURA / 2)
    for delta, esperado in ((-120, 1), (-120, 2), (120, 1)):
        evento = QWheelEvent(
            ponto, tela.janela.mapToGlobal(ponto), QPoint(0, 0), QPoint(0, delta),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
        )  # fmt: skip
        QCoreApplication.sendEvent(tela.janela, evento)
        assert tela.bp.indice == esperado
    tela.fechar()


def test_ocupada_ignora_entrada(app_qt):
    tela = _Tela()
    tela.bp._ocupada = True  # a fila de entrada liga isto
    tela.bp.alterado.emit()
    _esperar()
    for tecla in (Qt.Key.Key_Right, Qt.Key.Key_End, Qt.Key.Key_Return, Qt.Key.Key_Escape):
        QTest.keyClick(tela.janela, tecla)
    _clicar(tela, LARGURA / 2, ALTURA * 0.52)
    _clicar(tela, 1, 1)
    assert (tela.bp.indice, tela.bp.etapa) == (0, "carrossel")
    tela.fechar()


def _capa_de_teste(motor, pasta, *, central, animar=False, animada=False, escala=1.25):
    png = pasta / "capa.png"
    Image.new("RGB", (200, 300), "red").save(png)
    gif = pasta / "capa.gif"
    Image.new("P", (50, 75)).save(gif, save_all=True, append_images=[Image.new("P", (50, 75), 1)], duration=100, loop=0)
    componente = QQmlComponent(motor, QUrl.fromLocalFile(str(QML / "CapaDoBigPicture.qml")))
    capa = componente.createWithInitialProperties(
        {
            "jogo": {
                "nome": "A & <b>B</b>",
                "capa": QUrl.fromLocalFile(str(png)).toString(),
                "capaAnimada": QUrl.fromLocalFile(str(gif)).toString() if animada else "",
            },
            "indice": 0, "mascara": QQuickItem(), "largura": 100, "altura": 150,
            "escala": escala, "central": central, "animar": animar,
        }
    )  # fmt: skip
    assert capa is not None, componente.errorString()
    capa.componente = componente  # o componente mantém a criação viva
    return capa


def test_central_em_alta_so_estatica(app_qt, tmp_path):
    motor = QQmlEngine()
    from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    capa = _capa_de_teste(motor, tmp_path, central=True)
    lateral = _capa_de_teste(motor, tmp_path, central=False)
    animada = _capa_de_teste(motor, tmp_path, central=True, animada=True)
    _esperar()
    # As texturas em pixels reais: 300 · 1,25 nas laterais (a da grade); a central ganha por cima a de alta resolução, 900 · 1,25.
    assert _avaliar(_achar(capa, "capa"), "sourceSize.height") == round(300 * 1.25)
    em_alta = _achar(capa, "capaEmAlta")
    assert _avaliar(em_alta, "sourceSize.height") == round(900 * 1.25)
    assert _avaliar(_achar(capa, "capa"), "fillMode") == 0 == _avaliar(em_alta, "fillMode")  # Stretch: 2:3 sem corte
    assert em_alta.property("source").toString() != ""
    assert em_alta.property("visible") is True  # pronta: só então aparece
    assert _achar(lateral, "capaEmAlta").property("source").toString() == ""
    assert _achar(lateral, "capaEmAlta").property("visible") is False
    assert _achar(animada, "capaEmAlta").property("source").toString() == ""


def test_reflexo_com_mipmap(app_qt, tmp_path):
    motor = QQmlEngine()
    from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    capa = _capa_de_teste(motor, tmp_path, central=False)
    reflexo = _achar(capa, "reflexo")
    assert [_avaliar(reflexo, f"layer.{p}") for p in ("enabled", "mipmap", "smooth")] == [True, True, True]
    assert reflexo.property("opacity") == pytest.approx(regras.REFLEXO_OPACIDADE)


def test_animada_so_com_autoplay(app_qt, tmp_path):
    motor = QQmlEngine()
    from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    parada = _capa_de_teste(motor, tmp_path, central=True, animada=True, animar=False)
    tocando = _capa_de_teste(motor, tmp_path, central=True, animada=True, animar=True)
    lateral = _capa_de_teste(motor, tmp_path, central=False, animada=True, animar=True)
    _esperar()
    assert _achar(parada, "capaAnimada").property("source").toString() == ""
    assert _achar(tocando, "capaAnimada").property("source").toString() != ""
    assert _achar(tocando, "capaAnimada").property("playing") is True
    assert _achar(lateral, "capaAnimada").property("source").toString() == ""


def test_animar_central_segue_so_o_autoplay(app_qt):
    modelo = ModeloDaBiblioteca()
    antes = shared.schema.get_boolean("cover-autoplay")
    try:
        shared.schema.set_boolean("cover-autoplay", False)
        sem_sistema = BigPicture(modelo, animacoes_do_sistema=False)
        bp = BigPicture(modelo)
        assert (bp.animarCentral, sem_sistema.animarCentral) == (False, False)
        shared.schema.set_boolean("cover-autoplay", True)
        _esperar()
        assert (bp.animarCentral, sem_sistema.animarCentral) == (True, True)  # só a preferência
    finally:
        shared.schema.set_boolean("cover-autoplay", antes)


def test_fundo_em_pixels_reais(app_qt):
    tela = _Tela()
    fundo = tela.achar("fundo")
    assert tela.js("escala === Screen.devicePixelRatio")  # a escala vem do monitor da janela
    tela.tela.setProperty("escala", 1.0)
    assert fundo.property("source").toString() == f"image://fundo/{LARGURA}x{ALTURA}"
    tela.tela.setProperty("escala", 1.25)  # o `devicePixelRatio` de um monitor a 125%
    assert fundo.property("source").toString() == f"image://fundo/{round(LARGURA * 1.25)}x{round(ALTURA * 1.25)}"
    assert fundo.property("smooth") is False
    tela.fechar()


def test_fundo_na_thread_principal_e_so_com_o_big_picture_visivel(app_qt):
    # Provedor Python na thread de imagens trava: ela espera o GIL segurando o mutex do cache.
    tela = _Tela()
    fundo = tela.achar("fundo")
    assert fundo.property("asynchronous") is False
    assert fundo.property("source").toString().startswith("image://fundo/")
    tela.bp.sair()  # sem janela, sem HWND: troca sem fade
    tela.bp.filaTerminou()
    assert _esperar(lambda: not tela.bp.visivel)
    assert fundo.property("source").toString() == ""
    tela.fechar()


def test_vazio_mostra_o_aviso(app_qt):
    tela = _Tela(0)
    vazio = tela.achar("estadoVazioDoBigPicture")
    assert vazio.property("visible") is True
    assert vazio.property("titulo") == "Nenhum jogo"
    assert vazio.property("descricao") == "Pressione B ou Esc para voltar à biblioteca."
    QTest.keyClick(tela.janela, Qt.Key.Key_Right)  # sem jogos, nada quebra
    tela.fechar()
    cheia = _Tela()
    assert cheia.achar("estadoVazioDoBigPicture").property("visible") is False
    cheia.fechar()


def test_nome_em_texto_puro(app_qt, tmp_path):
    tela = _Tela(1, nome="A & <b>B</b>")
    nome = tela.achar("nomeDoLogoDoBigPicture")
    assert nome.property("text") == "A & <b>B</b>"
    textos = _itens(tela.tela, lambda i: i.metaObject().className().startswith("QQuickText"))
    assert len(textos) >= 3  # o nome no logo, as letras dos glifos e as dicas da barra
    for texto in textos:
        assert _avaliar(texto, "textFormat") == 0, texto.property("text")  # Text.PlainText
    tela.fechar()


def _roda(tela, x, y):
    ponto = QPointF(LARGURA / 2, ALTURA / 2)
    evento = QWheelEvent(
        ponto, tela.janela.mapToGlobal(ponto), QPoint(0, 0), QPoint(x, y),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )  # fmt: skip
    QCoreApplication.sendEvent(tela.janela, evento)


def test_roda_por_entalhe_e_sem_vertical_nao_move(app_qt):
    tela = _Tela()
    for _ in range(3):
        _roda(tela, 0, -30)
    assert tela.bp.indice == 0  # três quartos de entalhe ainda não são um passo
    _roda(tela, 0, -30)
    assert tela.bp.indice == 1
    _roda(tela, 120, 0)  # roda horizontal
    _roda(tela, -120, 0)
    assert tela.bp.indice == 1
    _roda(tela, 0, -240)  # dois entalhes de uma vez, dois passos
    assert tela.bp.indice == 3
    tela.fechar()


def test_lista_refeita_poe_a_posicao_direto(app_qt):
    tela = _Tela(animar_passo=True)
    tela.bp.irPara(3)
    _esperar(lambda: tela.tela.property("posicao") == 3)
    # O jogo 1 some: o centro continua o mesmo jogo, agora no índice 2. Sem deslizar.
    removido = tela.bp.jogos[1]["jogoId"]
    tela.modelo.retirar(removido)
    _esperar(lambda: tela.bp.indice == 2)
    assert tela.bp.indice == 2
    assert tela.tela.property("posicao") == 2  # na hora, sem os 350 ms do passo
    # Um passo de verdade continua deslizando.
    tela.bp.irPara(0)
    assert tela.tela.property("posicao") != 0
    tela.fechar()


def test_central_em_alta_so_no_fim_do_passo(app_qt):
    tela = _Tela(animar_passo=True)

    def centrais():
        capas = _itens(tela.tela, lambda i: i.objectName() == "capaDoBigPicture")
        return [i.property("indice") for i in capas if i.property("central")]

    assert centrais() == [0]
    tela.bp.irPara(3)
    assert centrais() == [0]  # durante o passo a antiga guarda a textura grande
    assert _esperar(lambda: centrais() == [3])
    tela.fechar()


def test_passo_nao_recria_as_vagas_do_meio(app_qt):
    tela = _Tela(1050, animar_passo=False)
    tela.bp.irPara(500)
    _esperar()
    antes = {id(i): i for i in _itens(tela.tela, lambda i: i.objectName() == "capaDoBigPicture")}
    tela.bp.mover(1)
    _esperar()
    depois = _itens(tela.tela, lambda i: i.objectName() == "capaDoBigPicture")
    assert sum(1 for i in depois if id(i) in antes) >= 14
    tela.fechar()


def test_roda_muda_de_sentido_sem_resto(app_qt):
    tela = _Tela()
    tela.bp.irPara(2)
    _roda(tela, 0, -90)
    _roda(tela, 0, 120)  # o resto de -90 não come o entalhe: um passo para trás
    assert tela.bp.indice == 1
    tela.fechar()


def test_lista_refeita_com_passo_em_curso_termina_no_indice_certo(app_qt):
    tela = _Tela(animar_passo=True)
    tela.bp.irPara(3)  # o passo até 3 começa e não termina
    tela.modelo.retirar(tela.bp.jogos[1]["jogoId"])
    assert _esperar(lambda: tela.bp.indice == 2)
    _esperar()
    assert tela.tela.property("posicao") == 2
    tela.fechar()


# --- entrar e sair (Aplicativo inteiro) ------------------------------------------------------------


def test_botao_abre_o_big_picture(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    botao = app.achar("botaoBigPicture")
    assert botao.property("dica") == "Big Picture"
    assert botao.property("enabled") is True and botao.property("visible") is True
    assert app.achar("bigPicture").property("visible") is False
    app.clicar("botaoBigPicture")
    assert app.big_picture.visivel and app.big_picture.ocupada
    assert app.achar("bigPicture").property("visible") is True
    assert _esperar(lambda: not app.big_picture.ocupada, limite=5)
    assert app.achar("bigPicture").property("activeFocus") is True
    assert app.janela.visibility() == QWindow.Visibility.FullScreen
    app.fechar()


def test_esc_sai_e_devolve_o_foco_ao_cartao_central(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    _entrar(app)
    app.big_picture.irPara(2)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    assert app.big_picture.jaSaiu
    grade = app.achar("grade")
    assert _esperar(lambda: grade.property("activeFocus") is True)
    assert grade.property("currentIndex") == 2
    assert app.achar("bigPicture").property("visible") is False
    app.fechar()


def test_botao_indisponivel_sem_3d(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    monkeypatch.setattr("cartridges.modelos.big_picture.tem_3d", lambda _janela: False)
    app.big_picture._rever_3d()  # noqa: SLF001
    botao = app.achar("botaoBigPicture")
    assert botao.property("indisponivel") is True
    assert botao.property("dica") == "Requer uma placa de vídeo com aceleração 3D."
    # Insensível: 50% de opacidade e sem o realce do ponteiro; a dica continua a abrir.
    assert botao.property("opacity") == 0.5 and botao.property("semRealce") is True
    # Nem o aperto muda a cor do fundo.
    fundo = _avaliar(botao, "background.color.a")
    ponto = botao.mapToScene(botao.boundingRect().center()).toPoint()
    QTest.mousePress(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    try:
        assert _esperar(lambda: _avaliar(botao, "down") is True)
        _esperar(lambda: False, 0.4)  # a transição de cor de 200 ms
        assert _avaliar(botao, "background.color.a") == fundo
    finally:
        QTest.mouseRelease(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    app.fechar()


def test_botao_some_fora_de_todos_e_com_a_edicao_aberta(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    app.clicar("botaoZerados")
    assert _esperar(lambda: app.achar("botaoBigPicture").property("visible") is False)
    app.clicar("botaoVoltar")
    assert _esperar(lambda: app.achar("botaoBigPicture").property("visible") is True)
    app.edicao.adicionar()
    _esperar()
    assert app.achar("botaoBigPicture").property("enabled") is False
    app.fechar()


def test_tela_cheia_esconde_a_barra(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    barra, pagina = app.achar("barraDeTitulo"), app.achar("pagina")
    assert barra.property("visible") is True and pagina.property("y") == barra.property("height") > 0
    _entrar(app)
    assert app.janela.property("telaCheia") is True
    assert barra.property("visible") is False
    assert pagina.property("y") == 0
    # Os botões da barra saem do foco: o Tab não os alcança, fica no Big Picture.
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert app.achar("bigPicture").property("activeFocus") is True
    assert not any(b.property("activeFocus") for b in app.janela.property("botoesDaBarra").toVariant())
    app.big_picture.sair()
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    assert barra.property("visible") is True and pagina.property("y") == barra.property("height")
    app.fechar()


def test_fila_termina_no_estado_normal(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    _entrar(app)
    tela = app.achar("bigPicture")
    assert (tela.property("posicao"), tela.property("virada")) == (0, 1)
    assert (tela.property("opacidadeCapas"), tela.property("opacidadeDosTextos")) == (1, 1)
    assert tela.property("naFila") is False
    app.big_picture.sair()
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    assert (tela.property("posicao"), tela.property("virada")) == (0, 1)
    assert (tela.property("opacidadeCapas"), tela.property("opacidadeDosTextos")) == (1, 1)
    app.fechar()


def test_fila_comeca_longe_e_corre(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch, quantidade=6)
    app.clicar("botaoBigPicture")
    tela = app.achar("bigPicture")
    assert tela.property("naFila") is True
    assert tela.property("posicao") == pytest.approx(5)  # n = jogos - 1: parte da cauda
    assert tela.property("opacidadeCapas") == 0 and tela.property("opacidadeDosTextos") == 0
    assert _esperar(lambda: tela.property("posicao") < 4.9, limite=2)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=5)
    app.fechar()


def test_saida_parte_da_posicao_visual(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch, quantidade=6)
    _entrar(app)
    tela = app.achar("bigPicture")
    app.big_picture.irPara(3)  # o passo desliza; a saída o interrompe onde está
    assert _esperar(lambda: 0.2 < tela.property("posicao") < 2.9, limite=1)
    visual = tela.property("posicao")
    app.big_picture.sair()
    assert tela.property("baseDaFila") == pytest.approx(visual)
    assert tela.property("naFila") is True
    assert tela.property("posicao") == pytest.approx(visual)  # o quadro 1 da saída é a capa onde estava
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    app.fechar()


def test_quadro_da_fila_em_js_igual_ao_python(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    _entrar(app)
    tela = app.achar("bigPicture")
    for t in (0, 0.3, 0.7, 0.9, 1):
        esperado = regras.quadro_da_fila(t, 7, 2.5)
        obtido = _avaliar(tela, f"quadroDaFila({t}, 7, 2.5)")
        assert obtido == pytest.approx(list(esperado)), t
    app.fechar()


def test_grade_para_de_animar_com_o_big_picture(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    pagina, grade = app.achar("pagina"), app.achar("grade")
    assert pagina.property("ativa") is True and grade.property("ativa") is True
    _entrar(app)
    assert pagina.property("ativa") is False and grade.property("ativa") is False
    assert pagina.property("enabled") is False  # nem mouse nem Tab chegam à grade
    app.big_picture.sair()
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    assert pagina.property("ativa") is True and pagina.property("enabled") is True
    app.fechar()


def test_avisos_ficam_na_frente(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    _entrar(app)
    tela, avisos = app.achar("bigPicture"), app.achar("camadaDeAvisos")
    irmaos = list(tela.parentItem().childItems())
    assert tela.parentItem() is avisos.parentItem()
    assert irmaos.index(avisos) > irmaos.index(tela)
    app.fechar()


def test_sem_animacoes_do_sistema_vai_direto_ao_fim(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch, animacoes=False)
    app.clicar("botaoBigPicture")
    # Sem animação, a fila acaba na própria chamada.
    assert (app.big_picture.visivel, app.big_picture.ocupada) == (True, False)
    tela = app.achar("bigPicture")
    assert (tela.property("posicao"), tela.property("virada"), tela.property("opacidadeCapas")) == (0, 1, 1)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert (app.big_picture.visivel, app.big_picture.jaSaiu) == (False, True)
    app.fechar()


def test_animada_nao_toca_escondida(app_qt, tmp_path):
    tela = _Tela(quantidade=3)
    gif = tmp_path / "capa.gif"
    Image.new("P", (50, 75)).save(gif, save_all=True, append_images=[Image.new("P", (50, 75), 1)], duration=100, loop=0)
    tela.bp._jogos[0]["capaAnimada"] = QUrl.fromLocalFile(str(gif)).toString()  # noqa: SLF001
    tela.bp._animar_central = True  # noqa: SLF001
    tela.bp.jogosMudaram.emit()
    tela.bp.animarCentralMudou.emit()
    assert _esperar(lambda: any(_achar(c, "capaAnimada").property("source").toString() for c in _itens(tela.tela, lambda i: i.objectName() == "capaDoBigPicture")))
    tela.bp._visivel = False  # noqa: SLF001
    tela.bp.alterado.emit()
    assert _esperar(lambda: not any(_achar(c, "capaAnimada").property("source").toString() for c in _itens(tela.tela, lambda i: i.objectName() == "capaDoBigPicture")))
    tela.fechar()


def test_dica_aparece_no_botao_indisponivel(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    monkeypatch.setattr("cartridges.modelos.big_picture.tem_3d", lambda _janela: False)
    app.big_picture._rever_3d()  # noqa: SLF001
    botao = app.achar("botaoBigPicture")
    assert botao.property("indisponivel") is True and botao.property("enabled") is True
    app.clicar("botaoBigPicture")
    assert not app.big_picture.visivel  # o clique é ignorado
    botao.setProperty("hoverEnabled", True)  # o offscreen não tem efeitos de hover; no Windows já vem ligado
    centro = botao.mapToScene(QPointF(botao.width() / 2, botao.height() / 2)).toPoint()
    QTest.mouseMove(app.janela, centro)
    QTest.mouseMove(app.janela, centro + QPoint(1, 0))
    dica = botao.findChild(QObject, "dica")
    assert _esperar(lambda: dica.property("visible") is True, limite=5)
    assert dica.property("text") == "Requer uma placa de vídeo com aceleração 3D."
    app.fechar()


# --- capas prontas antes da fila -------------------------------------------------------------


def _preparos(tela):
    return _itens(tela.tela, lambda i: i.objectName() in ("preparoDaCapa", "preparoDaCentral"))


_PREPARO_EM_125 = r"""
import builtins, json, sys, tempfile
from pathlib import Path
builtins._ = lambda m: m
sys.path.insert(0, sys.argv[1])
from PySide6.QtGui import QGuiApplication
app = QGuiApplication([])
from PIL import Image
from PySide6.QtCore import QUrl
from tests.apoio_qml_big_picture import _Tela, _avaliar, _itens
from tests.apoio_qml_biblioteca import _achar, _esperar
pasta = Path(tempfile.mkdtemp())
tela = _Tela(3)
for n, jogo in enumerate(tela.bp._jogos):
    png = pasta / f"{n}.png"
    Image.new("RGB", (200, 300), "red").save(png)
    jogo["capa"] = QUrl.fromLocalFile(str(png)).toString()
tela.bp.jogosMudaram.emit()
tela.janela.showFullScreen()
_esperar()
tela.tela.setProperty("width", tela.janela.width())
tela.tela.setProperty("height", tela.janela.height())  # em tela cheia, como no app
tela.bp.prepararCapas.emit()
_esperar()
def campos(i):
    return [_avaliar(i, "sourceSize.height"), _avaliar(i, "fillMode"), _avaliar(i, "autoTransform"), _avaliar(i, "cache")]
capas = _itens(tela.tela, lambda i: i.objectName() == "capaDoBigPicture")
print(json.dumps({
    "dpr": _avaliar(tela.tela, "Screen.devicePixelRatio"),
    "telaCheia": [tela.janela.height(), _avaliar(tela.tela, "Screen.height")],
    "vagas": sorted({json.dumps(campos(_achar(c, "capa"))) for c in capas}),
    "central": [campos(_achar(c, "capaEmAlta")) for c in capas if c.property("central")],
    "preparo": sorted({json.dumps(campos(i)) for i in _itens(tela.tela, lambda i: i.objectName() == "preparoDaCapa")}),
    "preparoCentral": [campos(i) for i in _itens(tela.tela, lambda i: i.objectName() == "preparoDaCentral")],
}))
"""


def test_preparo_usa_o_mesmo_tamanho_das_capas():
    # O cache do Qt Quick só acerta com a mesma URL, `sourceSize` e opções: senão a fila decodifica de novo.
    import json  # noqa: PLC0415
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    import sys  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    raiz = Path(__file__).resolve().parent.parent
    ambiente = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "QT_SCALE_FACTOR": "1.25"}
    saida = subprocess.run(
        [sys.executable, "-c", _PREPARO_EM_125, str(raiz)], cwd=raiz, env=ambiente,
        capture_output=True, text=True, check=False, timeout=120,
    )  # fmt: skip
    assert saida.returncode == 0, saida.stderr
    dados = json.loads(saida.stdout.strip().splitlines()[-1])
    assert dados["dpr"] == pytest.approx(1.25)
    assert dados["telaCheia"][0] == dados["telaCheia"][1]
    assert len(dados["vagas"]) == 1 and dados["vagas"] == dados["preparo"]
    altura = json.loads(dados["vagas"][0])[0]
    assert altura == round(300 * 1.25)  # a textura da grade
    assert len(dados["central"]) == 1 and dados["central"] == dados["preparoCentral"]
    assert dados["central"][0][0] == round(900 * 1.25)


def test_preparo_avisa_com_capa_ilegivel_e_sem_capa(app_qt, tmp_path):
    tela = _Tela(3)
    png, lixo = tmp_path / "boa.png", tmp_path / "ilegivel.png"
    Image.new("RGB", (200, 300), "red").save(png)
    lixo.write_bytes(b"isto nao e uma imagem")
    for jogo, capa in zip(tela.bp._jogos, (png, lixo, None), strict=True):  # noqa: SLF001
        jogo["capa"] = QUrl.fromLocalFile(str(capa)).toString() if capa else ""
    tela.bp.jogosMudaram.emit()
    tela.bp._capas_prontas = False  # noqa: SLF001
    tela.bp.prepararCapas.emit()
    assert _esperar(lambda: tela.bp._capas_prontas)  # noqa: SLF001
    assert len([i for i in _preparos(tela) if i.objectName() == "preparoDaCapa"]) == 3
    estados = [_avaliar(i, "status") for i in _preparos(tela) if i.objectName() == "preparoDaCapa"]
    assert sorted(estados) == [0, 1, 3]  # sem capa (Null), pronta (Ready) e ilegível (Error)
    tela.js("(entrando = true, terminarFila())")  # o fim da fila de entrada solta o preparo
    _esperar()
    assert _preparos(tela) == [] or all(i.property("source").toString() == "" for i in _preparos(tela))
    tela.fechar()


def test_preparo_so_das_primeiras_da_fila(app_qt):
    tela = _Tela(60)
    tela.bp.prepararCapas.emit()
    _esperar()
    prontos = [i for i in _preparos(tela) if i.objectName() == "preparoDaCapa"]
    assert len(prontos) == regras.JOGOS_NA_FILA + regras.CAPAS_DE_CADA_LADO + 1 == 39
    tela.fechar()


class _CortinaQueAnota:
    def __init__(self, hwnd):
        self.hwnd = hwnd

    def alfa(self, valor):
        pass

    def fechar(self):
        pass


def test_entrada_com_fade_no_app(app_qt, monkeypatch):
    # O caminho inteiro com a cortina falsa: o QML prepara as capas, a troca acontece no escuro e a fila corre.
    from PySide6.QtCore import QMetaObject  # noqa: PLC0415

    from cartridges.modelos import big_picture as modulo  # noqa: PLC0415
    from tests.apoio_qml_biblioteca import _App, _jogos  # noqa: PLC0415

    monkeypatch.setattr(modulo, "tem_3d", lambda _janela: True)
    app = _App(_jogos(*((n, f"Jogo {n}", {}) for n in range(4))), cortina=_CortinaQueAnota)
    app.big_picture.definir_janela(app.janela)
    QMetaObject.invokeMethod(app.achar("botaoBigPicture"), "click", Qt.ConnectionType.DirectConnection)
    assert not app.big_picture.visivel and app.big_picture._cortina is not None  # noqa: SLF001
    assert _esperar(lambda: app.big_picture.visivel, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=5)
    assert app.big_picture._cortina is None  # noqa: SLF001
    app.big_picture.sair()
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    tela = app.achar("bigPicture")
    assert (tela.property("posicao"), tela.property("virada"), tela.property("opacidadeCapas")) == (0, 1, 1)
    app.big_picture.encerrar()
    app.fechar()


# --- abrir o jogo (Aplicativo inteiro; nenhum jogo é iniciado: o `launch` é falso) ------------------


def _largura(tela, i):
    cantos = _cantos_de(tela, i)
    return max(x for x, _ in cantos) - min(x for x, _ in cantos)


def _cantos_de(tela, i):
    achados = _avaliar(
        tela,
        f"(function(){{const m=transformacao({i}); return [[0,0],[larguraCapa,0],[larguraCapa,alturaCapa],[0,alturaCapa]]"
        ".map(([x,y])=>{const v=m.times(Qt.vector4d(x,y,0,1)); return [v.x/v.w, v.y/v.w]})})()",
    )
    return [tuple(p) for p in achados]


def _clicar_no_texto(app, texto):
    alvo = next(
        i for i in _itens(app.janela.contentItem(), lambda i: i.metaObject().className().startswith("QQuickText"))
        if i.property("text") == texto and i.isVisible()
    )  # fmt: skip
    centro = alvo.mapToScene(QPointF(alvo.width() / 2, alvo.height() / 2))
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro.toPoint())


def test_confirmacao_do_comando_na_frente_e_cancelar_volta(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    jogo = _com_launch_falso(app, monkeypatch)
    jogo.executable, jogo.comando_a_conferir = "jogo.exe", True
    app.ponte.ligar(jogo)
    _entrar(app)
    tela, avisos = app.achar("bigPicture"), app.achar("camadaDeAvisos")
    _abrir_jogo(app)
    assert _esperar(lambda: avisos.property("dialogoAberto") is True, limite=3)
    # A camada do Big Picture volta à tela cheia e fica atrás do diálogo, sem receber teclas nem toques.
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    assert app.janela.visibility() == QWindow.Visibility.FullScreen
    irmaos = list(tela.parentItem().childItems())
    assert irmaos.index(avisos) > irmaos.index(tela)
    assert tela.property("enabled") is False and tela.property("activeFocus") is False
    QTest.keyClick(app.janela, Qt.Key.Key_Right)  # as teclas do carrossel não passam pela confirmação
    assert not app.big_picture.ocupada and jogo.launch.chamadas == 0 and app.big_picture.indice == 0
    # Dispensar: o carrossel segue em tela cheia, o jogo não é iniciado e o teclado volta a ele.
    _clicar_no_texto(app, "Dispensar")
    assert avisos.property("dialogoAberto") is False
    assert _esperar(lambda: tela.property("activeFocus") is True, limite=3)
    assert app.big_picture.visivel and not app.big_picture.ocupada and jogo.launch.chamadas == 0
    assert app.janela.visibility() == QWindow.Visibility.FullScreen
    # Iniciar: o mesmo caminho da abertura, e o jogo é iniciado uma única vez.
    jogo.comando_a_conferir = True
    _abrir_jogo(app)
    assert _esperar(lambda: avisos.property("dialogoAberto") is True, limite=3)
    _clicar_no_texto(app, "Iniciar")
    assert _esperar(lambda: jogo.launch.chamadas == 1, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    assert jogo.launch.chamadas == 1
    app.fechar()


def _com_confirmacao_aberta(monkeypatch, animacoes=False):
    # Sem animações do sistema: estes testes provam a camada de confirmação, não a animação (essa fica no teste acima).
    app = _aberto_com(monkeypatch, animacoes=animacoes)
    jogo = _com_launch_falso(app, monkeypatch)
    jogo.executable, jogo.comando_a_conferir = "jogo.exe", True
    app.ponte.ligar(jogo)
    _entrar(app)
    app.janela.requestActivate()
    _abrir_jogo(app)
    avisos = app.achar("camadaDeAvisos")
    assert _esperar(lambda: avisos.property("dialogoAberto") is True, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    return app, jogo, avisos


def test_confirmacao_pelo_teclado_cancela_com_esc_e_devolve_o_foco(app_qt, monkeypatch):
    app, jogo, avisos = _com_confirmacao_aberta(monkeypatch)
    tela = app.achar("bigPicture")
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert avisos.property("dialogoAberto") is False and jogo.launch.chamadas == 0
    assert _esperar(lambda: tela.property("activeFocus") is True, limite=3)
    assert app.big_picture.visivel and not app.big_picture.ocupada
    app.fechar()


@pytest.mark.parametrize("tecla", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_confirmacao_pelo_teclado_inicia_com_enter_ou_espaco_depois_de_escolher(app_qt, monkeypatch, tecla):
    app, jogo, avisos = _com_confirmacao_aberta(monkeypatch)
    QTest.keyClick(app.janela, Qt.Key.Key_Right)  # de "Dispensar" (o padrão) para "Iniciar"
    QTest.keyClick(app.janela, tecla)
    assert avisos.property("dialogoAberto") is False
    assert _esperar(lambda: jogo.launch.chamadas == 1, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    app.fechar()


@pytest.mark.parametrize("tecla", [Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space])
def test_confirmacao_enter_logo_ao_abrir_nao_inicia(app_qt, monkeypatch, tecla):
    app, jogo, avisos = _com_confirmacao_aberta(monkeypatch)
    QTest.keyClick(app.janela, tecla)
    assert avisos.property("dialogoAberto") is False and jogo.launch.chamadas == 0
    app.fechar()


def test_confirmacao_a_duas_vezes_logo_ao_abrir_nao_inicia(app_qt, monkeypatch):
    app, jogo, avisos = _com_confirmacao_aberta(monkeypatch, animacoes=True)  # a guarda é por tempo: o ritmo da animação conta
    app.controle.ativar.emit()
    app.controle.ativar.emit()
    assert avisos.property("dialogoAberto") is False and jogo.launch.chamadas == 0
    app.fechar()


def test_confirmacao_reaberta_ainda_devolve_o_foco_a_camada(app_qt, monkeypatch):
    app, jogo, avisos = _com_confirmacao_aberta(monkeypatch)
    tela = app.achar("bigPicture")
    app.ponte.confirmacaoPedida.emit("Iniciar Jogo?", "comando")  # com o diálogo já aberto
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert avisos.property("dialogoAberto") is False
    assert _esperar(lambda: tela.property("activeFocus") is True, limite=3)
    app.fechar()


def test_confirmacao_setas_trocam_o_botao_em_foco(app_qt, monkeypatch):
    app, jogo, avisos = _com_confirmacao_aberta(monkeypatch)
    QTest.keyClick(app.janela, Qt.Key.Key_Right)  # para "Iniciar"
    QTest.keyClick(app.janela, Qt.Key.Key_Left)  # e de volta a "Dispensar"
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert avisos.property("dialogoAberto") is False and jogo.launch.chamadas == 0
    app.fechar()


def test_confirmacao_pelo_controle_b_cancela_e_a_inicia(app_qt, monkeypatch):
    app, jogo, avisos = _com_confirmacao_aberta(monkeypatch)
    tela = app.achar("bigPicture")
    app.controle.voltar.emit()  # B
    assert avisos.property("dialogoAberto") is False and jogo.launch.chamadas == 0
    assert _esperar(lambda: tela.property("activeFocus") is True, limite=3)
    assert app.big_picture.visivel and app.big_picture.indice == 0
    jogo.comando_a_conferir = True
    _abrir_jogo(app)
    assert _esperar(lambda: avisos.property("dialogoAberto") is True, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    app.controle.mover.emit(1, 0)  # → vai a "Iniciar"
    app.controle.ativar.emit()  # A
    assert avisos.property("dialogoAberto") is False
    assert _esperar(lambda: jogo.launch.chamadas == 1, limite=3)
    assert _esperar(lambda: not app.big_picture.ocupada, limite=3)
    app.fechar()


def test_modo_big_picture_do_controle_so_sem_dialogo_na_frente(app_qt, monkeypatch):
    app, jogo, avisos = _com_confirmacao_aberta(monkeypatch)
    assert app.controle.modoBigPicture is False, "com o diálogo na frente vale a repetição da grade"
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert app.controle.modoBigPicture is True
    app.fechar()


def test_sem_capa_desenha_o_placeholder_da_biblioteca(app_qt, tmp_path):
    # Sem capa pronta aparece o placeholder, não um quadro cinza com o nome do jogo.
    motor = QQmlEngine()
    from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    placeholder = QUrl.fromLocalFile(str(modulo_biblioteca._PLACEHOLDER))  # noqa: SLF001
    sem = _capa_de_teste(motor, tmp_path, central=False)
    sem.setProperty("jogo", {"nome": "Sem capa", "capa": "", "capaAnimada": ""})
    sem.setProperty("placeholder", placeholder)
    com = _capa_de_teste(motor, tmp_path, central=False)
    com.setProperty("placeholder", placeholder)
    assert _esperar(lambda: _avaliar(_achar(com, "capa"), "status") == 1)  # Image.Ready
    quadro = _achar(sem, "placeholderDaCapa")
    assert quadro.property("visible") is True
    assert quadro.property("source") == placeholder
    assert _avaliar(quadro, "fillMode") == 0  # Stretch
    assert _achar(com, "placeholderDaCapa").property("visible") is False  # a capa pronta cobre o placeholder
    assert "Sem capa" not in _textos_de(sem), "o nome do jogo no quadro cinza saiu"


def test_tela_sem_capa_recebe_o_placeholder_do_modelo(app_qt):
    # O `BigPicture.qml` passa `bigPicture.placeholder` à capa; sem isso o jogo sem capa ficaria em branco.
    tela = _Tela(quantidade=1)
    try:
        quadros = _itens(tela.tela, lambda i: i.objectName() == "placeholderDaCapa")
        assert quadros, "o jogo sem capa desenha o placeholder"
        assert quadros[0].property("source").toLocalFile() != ""
        assert quadros[0].property("source").toString() == QUrl(tela.bp.placeholder).toString()
    finally:
        tela.fechar()


def _textos_de(raiz):
    return [i.property("text") for i in _itens(raiz, lambda i: i.metaObject().className().startswith("QQuickText"))]


def test_rodape_saiu_e_logo_no_alto(app_qt):
    tela = _Tela()
    assert _achar(tela.tela, "rodape") is None
    assert tela.achar("logoDoBigPicture").property("posicao") == "alto"
    tela.fechar()


def test_sem_logo_mostra_o_nome(app_qt):
    tela = _Tela(1, nome="Zelda")
    nome = tela.achar("nomeDoLogoDoBigPicture")
    assert nome.property("visible") is True and nome.property("text") == "Zelda"
    assert _avaliar(nome, "font.pixelSize") == _avaliar(nome, "Tema.titulo1")
    tela.fechar()


def test_dicas_do_carrossel(app_qt):
    tela = _Tela()
    assert tela.js("dicasDoBigPicture.textos") == ["Selecionar", "Voltar"]
    assert tela.achar("dicasDoBigPicture").property("visible") is True
    tela.fechar()


def test_glifos_com_as_cores_dos_botoes(app_qt):
    tela = _Tela()
    glifos = _itens(tela.tela, lambda i: i.objectName() == "glifoDoBotao")
    cores = {i.property("letra"): _avaliar(i, "color.toString()") for i in glifos}
    assert cores == {"A": "#5fbf3f", "B": "#e0453a"}
    assert _avaliar(glifos[0], "width") == 22
    tela.fechar()


def test_fundo_so_com_desfoque(app_qt):
    tela = _Tela()
    fundo = tela.achar("fundoDoBigPicture")
    fundo.setProperty("fonte", "file:///x.svg")
    _esperar()
    assert tela.js("fundoDoBigPicture.opacidadeVisivel") == 0
    fundo.setProperty("fonte", "image://desfoque/x?v=1")
    assert _esperar(lambda: abs(tela.js("fundoDoBigPicture.opacidadeVisivel") - 0.85) < 0.01, limite=3)
    fundo.setProperty("fonte", "")  # o desfoque do jogo seguinte ainda calcula: o fundo atual fica, sem esmaecer
    _esperar()
    assert tela.js("fundoDoBigPicture.opacidadeVisivel") == pytest.approx(0.85, abs=0.01)
    fundo.setProperty("visible", False)  # ao sair, as camadas largam a imagem
    _esperar()
    imagens = _itens(fundo, lambda i: i.objectName() == "imagemDoFundo")
    assert tela.js("fundoDoBigPicture.opacidadeVisivel") == 0
    assert [i.property("source").toString() for i in imagens] == ["", ""]
    tela.fechar()


def test_fundo_na_thread_principal(app_qt):
    tela = _Tela()
    fundo = tela.achar("fundoDoBigPicture")
    imagens = _itens(fundo, lambda i: i.objectName() == "imagemDoFundo")
    assert len(imagens) == 2
    assert all(i.property("asynchronous") is False for i in imagens)  # D45
    tela.fechar()


def _aguardar_etapa(tela):
    assert _esperar(lambda: not tela.bp.ocupada, limite=5)


def test_detalhes_aparecem_e_dicas_so_voltar(app_qt):
    tela = _Tela()
    tela.bp.ativar()
    _aguardar_etapa(tela)
    assert tela.achar("detalhesDoBigPicture").property("opacity") == 1
    assert tela.js("dicasDoBigPicture.textos") == ["Voltar"]
    assert tela.achar("logoDoBigPicture").property("posicao") == "coluna"
    tela.fechar()


def test_vizinhas_saem_da_tela_e_central_vai_a_esquerda(app_qt):
    tela = _Tela(9)
    tela.bp.irPara(4)
    _esperar(lambda: tela.js("posicao") == 4, limite=2)
    tela.bp.ativar()
    _aguardar_etapa(tela)
    for i in (0, 1, 2, 3, 5, 6, 7, 8):
        xs = [x for x, _ in _cantos(tela, i)]
        assert max(xs) <= 0 or min(xs) >= LARGURA, i
    cantos = _cantos(tela, 4)
    centro = sum(x for x, _ in cantos) / 4
    assert centro == pytest.approx(LARGURA / 2 - 0.28 * LARGURA, abs=2)
    tela.fechar()


def test_volta_dos_detalhes_restaura_o_carrossel(app_qt):
    tela = _Tela()
    antes = [_cantos(tela, i) for i in range(5)]
    tela.bp.ativar()
    _aguardar_etapa(tela)
    tela.bp.voltar()
    _aguardar_etapa(tela)
    assert tela.achar("detalhesDoBigPicture").property("opacity") == 0
    for i in range(5):
        for (ox, oy), (ex, ey) in zip(_cantos(tela, i), antes[i], strict=True):
            assert ox == pytest.approx(ex, abs=0.01)
            assert oy == pytest.approx(ey, abs=0.01)
    tela.fechar()


def test_iniciar_no_botao_chama_ativar(app_qt):
    tela = _Tela()
    tela.bp.ativar()
    _aguardar_etapa(tela)
    pedidos = []
    tela.bp.etapaPedida.connect(lambda de, para: pedidos.append((de, para)))  # o jogo de mentira não abre: a etapa volta
    botao = tela.achar("botaoIniciar")
    centro = botao.mapToScene(QPointF(botao.width() / 2, botao.height() / 2))
    _clicar(tela, centro.x(), centro.y())
    assert pedidos[0] == ("detalhes", "sessao")
    tela.fechar()


def test_toque_fora_do_botao_nos_detalhes_nao_faz_nada(app_qt):
    tela = _Tela()
    tela.bp.ativar()
    _aguardar_etapa(tela)
    _clicar(tela, LARGURA * 0.1, ALTURA * 0.52)  # onde a capa central estaria no carrossel
    _clicar(tela, 1, 1)
    assert tela.bp.etapa == "detalhes" and tela.bp.indice == 0
    tela.fechar()


def test_detalhes_somente_leitura(app_qt):
    tela = _Tela()
    tela.bp.ativar()
    _aguardar_etapa(tela)
    detalhes = tela.achar("detalhesDoBigPicture")
    nomes = ("TextEdit", "TextInput", "TextField", "Button", "MouseArea")
    for item in _itens(detalhes, lambda _: True):
        assert not item.metaObject().className().startswith(nomes), item.metaObject().className()
        nome = item.objectName().lower()
        assert not any(p in nome for p in ("menu", "excluir", "editar", "status", "anotacao", "atualizacao")), nome
    tela.fechar()


def test_um_pedido_novo_durante_a_animacao_termina_a_etapa_uma_vez(app_qt):
    tela = _Tela()
    chamadas = []
    original = tela.bp.etapaTerminou
    tela.bp.etapaTerminou = lambda: (chamadas.append(1), original())  # a chamada do QML passa pelo atributo da instância
    tela.bp.ativar()
    assert tela.bp.ocupada
    tela.bp.voltar()  # ocupada: ignorado
    assert tela.bp.etapa == "detalhes"
    _esperar(lambda: False, limite=0.3)  # no meio da animação
    assert chamadas == []
    # Sem as animações do Windows o pedido novo vai direto ao fim: a ida cancelada não pode terminar depois dele.
    tela.bp.definir_animacoes_do_sistema(False)  # noqa: FBT003
    tela.detalhes.sair.emit()
    assert tela.bp.etapa == "carrossel"
    assert len(chamadas) == 1
    _esperar(lambda: False, limite=1.5)  # além do fim da ida cancelada
    assert len(chamadas) == 1
    assert not tela.bp.ocupada
    tela.fechar()


class _ProcessoFalso:
    def __init__(self):
        self.parou = []

    def stop(self, record=False):
        self.parou.append(record)


def _ate_a_sessao(tela, monkeypatch):
    """Do carrossel à etapa da sessão, com um lançamento de mentira que inicia a sessão do primeiro jogo."""
    monkeypatch.setattr(shared, "store", _LojaFalsa(tela.jogos))
    monkeypatch.setattr(shared, "sessao", tela.sessao, raising=False)
    jogo = tela.jogos[0]
    jogo.launch = lambda **_: (tela.sessao.show_session_blocker(jogo), True)[1]
    tela.bp.ativar()
    _aguardar_etapa(tela)
    tela.bp.abrirJogo()
    assert _esperar(lambda: tela.sessao.emAndamento, limite=5)
    assert _esperar(lambda: tela.achar("sessaoDoBigPicture").property("opacity") == 1, limite=5)


def test_sessao_mostra_relogio_e_botao(app_qt, monkeypatch):
    tela = _Tela()
    _ate_a_sessao(tela, monkeypatch)
    assert tela.achar("logoDoBigPicture").property("posicao") == "relogio"
    assert tela.js("dicasDoBigPicture.textos") == []
    assert tela.achar("relogioDoBigPicture").property("text") == tela.sessao.relogio
    assert tela.achar("botaoJaTerminei") is not None
    assert tela.js("progressoSessao") == 1
    tela.sessao.hide_session_blocker()
    tela.fechar()


def test_central_sai_pela_esquerda(app_qt, monkeypatch):
    tela = _Tela()
    _ate_a_sessao(tela, monkeypatch)
    assert max(x for x, _ in _cantos(tela, 0)) < 0
    for i in range(1, 5):
        xs = [x for x, _ in _cantos(tela, i)]
        assert min(xs) >= LARGURA, i
    tela.sessao.hide_session_blocker()
    tela.fechar()


def test_ja_terminei_chama_terminar(app_qt, monkeypatch):
    tela = _Tela()
    _ate_a_sessao(tela, monkeypatch)
    processo = _ProcessoFalso()
    monkeypatch.setattr(ProcessSession, "active", processo)
    botao = tela.achar("botaoJaTerminei")
    centro = botao.mapToScene(QPointF(botao.width() / 2, botao.height() / 2))
    _clicar(tela, centro.x(), centro.y())
    assert processo.parou == [True]
    tela.sessao.hide_session_blocker()
    tela.fechar()


def test_sem_onde_eu_parei(app_qt, monkeypatch):
    tela = _Tela()
    _ate_a_sessao(tela, monkeypatch)
    assert _achar(tela.tela, "botaoAnotacaoDaSessao") is None
    tela.sessao.hide_session_blocker()
    tela.fechar()


def test_enter_na_sessao_nao_faz_nada(app_qt, monkeypatch):
    tela = _Tela()
    _ate_a_sessao(tela, monkeypatch)
    processo = _ProcessoFalso()
    monkeypatch.setattr(ProcessSession, "active", processo)
    QTest.keyClick(tela.janela, Qt.Key.Key_Return)
    QTest.keyClick(tela.janela, Qt.Key.Key_Escape)
    assert processo.parou == [] and tela.bp.etapa == "sessao"
    tela.sessao.hide_session_blocker()
    tela.fechar()


def test_volta_da_sessao_restaura_o_carrossel(app_qt, monkeypatch):
    tela = _Tela()
    antes = [_cantos(tela, i) for i in range(5)]
    _ate_a_sessao(tela, monkeypatch)
    tela.sessao.hide_session_blocker()
    tela.bp.voltouDoJogo()
    assert tela.achar("logoDoBigPicture").property("posicao") == "alto"
    _aguardar_etapa(tela)
    assert tela.bp.etapa == "carrossel" and tela.js("progressoSessao") == 0
    assert tela.achar("sessaoDoBigPicture").property("opacity") == 0
    for i in range(5):
        for (ox, oy), (ex, ey) in zip(_cantos(tela, i), antes[i], strict=True):
            assert ox == pytest.approx(ex, abs=0.01)
            assert oy == pytest.approx(ey, abs=0.01)
    tela.fechar()


def test_sessao_sem_animacoes_vai_direto_ao_fim(app_qt, monkeypatch):
    tela = _Tela()
    tela.bp.definir_animacoes_do_sistema(False)  # noqa: FBT003
    _ate_a_sessao(tela, monkeypatch)
    assert tela.js("progressoSessao") == 1
    assert max(x for x, _ in _cantos(tela, 0)) < 0
    tela.sessao.hide_session_blocker()
    tela.fechar()


def test_escondido_nao_decodifica_imagem(app_qt, monkeypatch, tmp_path):
    # D43: nada é decodificado escondido. A página de detalhes do modo normal segue o jogo com o Big Picture fora da tela.
    tela = _Tela()
    tela.bp.sair()
    tela.bp.filaTerminou()
    assert not tela.bp.visivel
    png = QUrl.fromLocalFile(str(_png(tmp_path))).toString()
    monkeypatch.setattr(ProcessSession, "active", SimpleNamespace(elapsed=60))
    tela.sessao.show_session_blocker(tela.jogos[0])
    tela.detalhes.mostrar("imported_1")
    tela.detalhes._mesclar({"logo": png, "larguraDoLogo": 64})  # noqa: SLF001
    tela.conquistas._guardar({"sessao": {"visivel": True, "contagem": "1/2", "porcentagem": "50%", "fracao": 0.5, "icones": [{"url": png}]}})  # noqa: SLF001
    tela.conquistas.alterado.emit()
    _esperar()
    imagens = tela.itens("QQuickImage") + tela.itens("QQuickAnimatedImage")
    assert [i.objectName() for i in imagens if i.property("source").toString() != ""] == []
    tela.sessao.hide_session_blocker()
    tela.fechar()


def _png(pasta):
    caminho = pasta / "x.png"
    Image.new("RGBA", (64, 32), (255, 0, 0, 255)).save(caminho)
    return caminho


def test_sessao_que_acaba_mantem_relogio_e_cartao_durante_o_fade(app_qt, monkeypatch):
    tela = _Tela()
    monkeypatch.setattr(ProcessSession, "active", SimpleNamespace(elapsed=3725))
    _ate_a_sessao(tela, monkeypatch)
    tela.conquistas._guardar({"sessao": {"visivel": True, "contagem": "1/2", "porcentagem": "50%", "fracao": 0.5, "icones": []}})  # noqa: SLF001
    tela.conquistas.alterado.emit()
    _esperar()
    assert tela.achar("relogioDoBigPicture").property("text") == "1:02:05"
    assert tela.achar("conquistasDaSessao").property("visible") is True
    monkeypatch.setattr(ProcessSession, "active", None)
    tela.sessao.hide_session_blocker()  # os rastreadores saem antes de o texto acabar de sumir
    tela.conquistas._guardar({"sessao": {"visivel": False, "contagem": "", "porcentagem": "", "fracao": 0.0, "icones": []}})  # noqa: SLF001
    tela.conquistas.alterado.emit()
    tela.bp.voltouDoJogo()
    _esperar(lambda: False, limite=0.08)  # no meio do fade de saída (300 ms)
    sessao = tela.achar("sessaoDoBigPicture")
    assert 0 < sessao.property("opacity") < 1
    assert tela.achar("relogioDoBigPicture").property("text") == "1:02:05"
    assert tela.achar("conquistasDaSessao").property("visible") is True
    tela.fechar()


def test_ponta_a_ponta_com_a_ligacao_real(app_qt, monkeypatch):
    """`BigPicture` com `detalhes` e `ModeloDaSessao` com `big_picture`, como no app: a sessão de verdade volta ao carrossel."""
    app = _aberto_com(monkeypatch, animacoes=False)
    _entrar(app)
    bp = app.big_picture
    assert app.detalhes.jogoId == bp.jogos[0]["jogoId"]  # os detalhes seguem o central da entrada
    bp.mover(1)
    assert _esperar(lambda: app.detalhes.jogoId == bp.jogos[1]["jogoId"], limite=3)
    monkeypatch.setattr(shared, "store", app.loja)
    monkeypatch.setattr(shared, "sessao", app.sessao, raising=False)
    monkeypatch.setattr(ProcessSession, "active", None)
    jogo = app.loja.get(bp.jogos[1]["jogoId"])
    jogo.launch = lambda **_: (app.sessao.show_session_blocker(jogo), True)[1]
    bp.ativar()  # detalhes
    bp.ativar()  # Iniciar
    assert bp.etapa == "sessao" and app.sessao.emAndamento
    app.sessao.hide_session_blocker()  # o fim da sessão chama `voltouDoJogo`
    assert _esperar(lambda: bp.etapa == "carrossel" and not bp.ocupada, limite=3)
    assert bp.jogos[bp.indice]["jogoId"] == jogo.game_id
    assert app.detalhes.jogoId == jogo.game_id



@pytest.mark.parametrize("altura", [480, 600, 720, 1080])
def test_logo_no_alto_cabe_acima_da_capa(app_qt, altura):
    """O logo cresce e encolhe com a faixa livre acima da capa central, sem encostar nela em nenhuma resolução."""
    tela = _Tela()
    tela.tela.setProperty("height", altura)
    tela.bp.definir_animacoes_do_sistema(False)
    _esperar()
    logo = tela.achar("logoDoBigPicture")
    topo_da_capa = altura * 0.52 - tela.tela.property("alturaCapa") / 2
    assert logo.property("y") > 0
    assert logo.property("y") + logo.property("height") < topo_da_capa
    tela.fechar()


def test_logo_cresce_com_a_tela(app_qt):
    tela = _Tela()
    tela.bp.definir_animacoes_do_sistema(False)
    logo = tela.achar("logoDoBigPicture")
    tela.tela.setProperty("height", 720)
    _esperar()
    menor = logo.property("height")
    tela.tela.setProperty("height", 2160)
    _esperar()
    assert logo.property("height") > 2 * menor
    tela.fechar()


def _vizinho(tela):
    return tela.achar("logoVizinhoDoBigPicture")


def test_capas_maiores_e_mais_baixas_com_o_logo_acima(app_qt):
    tela = _Tela()
    assert tela.tela.property("alturaCapa") == pytest.approx(ALTURA * 0.60)
    topo_da_capa = ALTURA * 0.52 - ALTURA * 0.30
    logo = tela.achar("logoDoBigPicture")
    assert logo.property("y") == pytest.approx(topo_da_capa * 0.25)
    assert logo.property("height") == pytest.approx(topo_da_capa * 0.6)
    tela.fechar()


def test_logo_acompanha_a_capa_com_fade_no_meio(app_qt):
    """No meio do passo os dois logos estão à vista: o que sai segue a capa dele e o que chega vem com a capa seguinte."""
    tela = _Tela()
    tela.js("irDireto(0.4)")
    _esperar()
    saindo, chegando = tela.achar("logoDoBigPicture"), _vizinho(tela)
    assert saindo.property("deslocamento") == pytest.approx(tela.js("arranjo(0)[0]"))
    assert chegando.property("deslocamento") == pytest.approx(tela.js("arranjo(1)[0]"))
    assert saindo.property("opacity") == pytest.approx(1 - 0.4 / 0.7)
    assert chegando.property("opacity") == pytest.approx(1 - 0.6 / 0.7)
    tela.fechar()


def test_logo_parado_so_o_central_a_vista(app_qt):
    tela = _Tela()
    logo = tela.achar("logoDoBigPicture")
    assert logo.property("deslocamento") == 0
    assert logo.property("opacity") == 1
    assert _vizinho(tela).property("opacity") == 0
    tela.fechar()


def test_cada_logo_mostra_o_seu_jogo(app_qt):
    tela = _Tela()
    tela.js("irDireto(0.4)")
    _esperar()
    assert tela.achar("nomeDoLogoDoBigPicture").property("text") == "Jogo 0"
    assert tela.achar("nomeDoLogoVizinhoDoBigPicture").property("text") == "Jogo 1"
    tela.fechar()


def test_logo_de_le_o_disco_uma_vez_por_jogo(app_qt, monkeypatch, tmp_path):
    arquivo = tmp_path / "logo.png"
    Image.new("RGBA", (40, 10)).save(arquivo)
    lidos = []
    jogos = {"com": object(), "sem": object()}
    monkeypatch.setattr(shared, "store", SimpleNamespace(get=jogos.get), raising=False)
    monkeypatch.setattr(
        "cartridges.utils.game_logo.cached_logo_path",
        lambda jogo: lidos.append(jogo) or (arquivo if jogo is jogos["com"] else None),
    )
    bp = BigPicture(ModeloDaBiblioteca())
    assert "logo.png" in bp.logoDe("com")
    assert bp.logoDe("com") == bp.logoDe("com")
    assert bp.logoDe("sem") == ""
    assert bp.logoDe("sumiu") == ""
    assert lidos == [jogos["com"], jogos["sem"]]



def test_logo_troca_de_largura_sem_andar(app_qt):
    """A largura de cada logo é diferente: recentrar não pode animar, senão o logo desliza sempre para o mesmo lado."""
    tela = _Tela()
    logo = tela.achar("logoDoBigPicture")
    logo.setProperty("jogo", {"jogoId": "x", "nome": "Um nome de jogo bem mais comprido que os outros"})
    assert logo.property("x") == pytest.approx((LARGURA - logo.property("width")) / 2)
    tela.fechar()


def test_logo_anda_ate_a_coluna_e_volta(app_qt):
    tela = _Tela()
    logo = tela.achar("logoDoBigPicture")
    logo.setProperty("animar", False)
    logo.setProperty("posicao", "coluna")
    _esperar()
    assert logo.property("x") == pytest.approx(LARGURA * 0.42)
    logo.setProperty("posicao", "alto")
    _esperar()
    assert logo.property("x") == pytest.approx((LARGURA - logo.property("width")) / 2)
    tela.fechar()


def test_vizinhos_do_logo_ja_carregam(app_qt):
    tela = _Tela()
    tela.bp._logos["imported_2"] = "file:///logo-do-vizinho.png"
    tela.bp.mover(1)
    _esperar()
    fontes = [i.property("source").toString() for i in _itens(tela.tela, lambda i: i.objectName() == "preparoDoLogo")]
    assert "file:///logo-do-vizinho.png" in fontes
    preparo = _itens(tela.tela, lambda i: i.objectName() == "preparoDoLogo")[0]
    logo = tela.achar("logoDoJogoNoBigPicture")
    assert _avaliar(preparo, "fillMode") == _avaliar(logo, "fillMode")
    assert _avaliar(preparo, "sourceSize.height") == _avaliar(logo, "sourceSize.height")
    tela.fechar()


def test_texto_dos_detalhes_para_antes_do_fim_da_tela(app_qt):
    tela = _Tela()
    coluna = tela.achar("detalhesDoBigPicture")
    assert coluna.property("x") + coluna.property("width") == pytest.approx(LARGURA * 0.75)
    tela.fechar()


def test_iniciar_logo_abaixo_do_texto_e_centrado_na_pilula(app_qt):
    tela = _Tela()
    tela.bp.ativar()
    _esperar()
    botao = tela.achar("botaoIniciar")
    dados = tela.achar("dadosDoJogoNoBigPicture")
    assert botao.property("y") == pytest.approx(dados.property("height") + 24)
    conteudo = _achar(botao, "conteudoDoBotao")
    assert conteudo.property("x") == pytest.approx((botao.property("width") - conteudo.property("width")) / 2, abs=1)  # o Qt alinha ao pixel
    tela.fechar()



def test_veu_dos_detalhes_so_na_tela_do_jogo(app_qt):
    tela = _Tela()
    veu = tela.achar("veuDosDetalhes")
    assert veu.property("opacity") == 0
    tela.js("progressoDetalhe = 1")
    assert veu.property("opacity") == 1
    tela.js("progressoSessao = 1")
    assert veu.property("opacity") == 0
    tela.fechar()


def test_laterais_escurecem_com_a_distancia(app_qt):
    tela = _Tela()
    assert tela.js("escurecimento(0)") == 0
    perto, longe = tela.js("escurecimento(1)"), tela.js("escurecimento(3)")
    assert 0 < perto < longe <= 0.7
    tela.fechar()


def test_partes_de_um_dado_separam_rotulo_e_valor(app_qt):
    tela = _Tela()
    coluna = tela.achar("detalhesDoBigPicture")
    assert _avaliar(coluna, "partes('Tempo de jogo: 12 h')") == ["Tempo de jogo", "12 h"]
    assert _avaliar(coluna, "partes('')") == ["", ""]
    assert _avaliar(coluna, "unir(['Respawn', '', 'Respawn', 'EA'])") == "Respawn  ·  EA"
    tela.fechar()


def test_texto_dos_detalhes_cresce_com_a_tela(app_qt):
    tela = _Tela()
    descricao = tela.achar("descricaoDoJogo")
    tela.tela.setProperty("height", 1080)
    _esperar()
    em_1080 = descricao.property("font").pixelSize()
    tela.tela.setProperty("height", 2160)
    _esperar()
    assert em_1080 == 20
    assert descricao.property("font").pixelSize() == 40
    tela.fechar()


def test_destaques_abaixo_do_iniciar(app_qt):
    tela = _Tela()
    tela.tela.setProperty("height", 1080)
    _esperar()
    botao, base = tela.achar("botaoIniciar"), tela.achar("destaquesDoJogo").parent()
    assert base.property("y") >= botao.property("y") + botao.property("height")
    tela.fechar()


def test_big_picture_usa_o_fundo_vivo(app_qt, monkeypatch, tmp_path):
    monkeypatch.setattr(shared, "covers_dir", tmp_path, raising=False)
    Image.new("RGB", (200, 300), (200, 40, 40)).save(tmp_path / "imported_0.tiff")
    tela = _Tela()
    fundo = tela.achar("fundoDoBigPicture")
    assert _esperar(lambda: "vivo" in fundo.property("fonte"), limite=3)
    assert fundo.property("fonte") == tela.detalhes.fundoVivo
    tela.fechar()


def test_jogo_sem_capa_nao_herda_o_fundo_vivo_do_anterior(app_qt, monkeypatch, tmp_path):
    monkeypatch.setattr(shared, "covers_dir", tmp_path, raising=False)
    Image.new("RGB", (200, 300), (200, 40, 40)).save(tmp_path / "imported_0.tiff")
    tela = _Tela()
    fundo = tela.achar("fundoDoBigPicture")
    assert _esperar(lambda: tela.js("fundoDoBigPicture.opacidadeVisivel") > 0, limite=3)
    tela.detalhes.mostrar("imported_1")
    assert _esperar(lambda: tela.js("fundoDoBigPicture.opacidadeVisivel") == 0, limite=3)
    assert not fundo.property("fonte").startswith("image://")
    tela.fechar()

def test_logo_com_arquivo_quebrado_mostra_o_nome(app_qt, tmp_path):
    tela = _Tela()
    quebrado = tmp_path / "quebrado.png"
    quebrado.write_bytes(b"nada")
    logo = tela.achar("logoDoBigPicture")
    tela.detalhes._v["logo"] = quebrado.as_uri()
    tela.detalhes.alterado.emit()
    assert _esperar(lambda: _avaliar(tela.achar("logoDoJogoNoBigPicture"), "status") == 3, limite=3)  # Image.Error
    assert logo.property("logoDoJogo").endswith("quebrado.png")
    assert tela.achar("nomeDoLogoDoBigPicture").property("visible") is True
    tela.fechar()


def test_logos_nas_pontas_da_lista(app_qt):
    tela = _Tela(2)
    logos = _itens(tela.tela, lambda i: i.objectName() in {"logoDoBigPicture", "logoVizinhoDoBigPicture"})
    assert len(logos) == 2
    for posicao in (-0.4, 1.4):  # além da primeira e da última capa: só um dos dois lados tem jogo
        tela.js(f"irDireto({posicao})")
        _esperar()
        assert sum(_avaliar(logo, "jogo !== null") for logo in logos) == 1
    tela.fechar()


def test_logo_invisivel_na_fila_nao_le_o_disco(app_qt):
    tela = _Tela()
    tela.tela.setProperty("opacidadeDosTextos", 0)
    _esperar()
    assert tela.achar("logoDoBigPicture").property("jogo") is None
    tela.fechar()
