# test_qml_big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tela do cover flow do Big Picture: geometria, vagas, teclado, mouse e capas (QML offscreen)."""

import math

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QWheelEvent, QWindow
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos import regras_do_big_picture as regras
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from tests.test_qml_biblioteca import QML, _achar, _esperar

LARGURA, ALTURA = 800, 600


def _avaliar(objeto, expressao):
    valor = QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]
    return valor.toVariant() if hasattr(valor, "toVariant") else valor


@pytest.fixture(autouse=True)
def _sem_som(monkeypatch):
    monkeypatch.setattr(regras, "tocar_tique", lambda: None)


class _Tela:
    """O `BigPicture.qml` sozinho numa janela de teste, sobre um `BigPicture` de jogos de mentira."""

    def __init__(self, quantidade=5, nome=None, animar_passo=False):
        self.modelo = ModeloDaBiblioteca()
        for n in range(quantidade):
            self.modelo.atualizar(
                Jogo(
                    {
                        "game_id": f"imported_{n}", "source": "imported",
                        "name": nome or f"Jogo {n}", "last_played": quantidade - n,
                    }
                )
            )  # fmt: skip
        self.bp = BigPicture(self.modelo)
        self.bp.entrar()  # antes do QML existir: a lista só acompanha a biblioteca visível, e sem fila
        self.bp.filaTerminou()
        self.motor = QQmlEngine()
        self.motor.addImageProvider("fundo", ProvedorDoFundo())
        self.motor.rootContext().setContextProperty("bigPicture", self.bp)
        componente = QQmlComponent(self.motor, QUrl.fromLocalFile(str(QML / "BigPicture.qml")))
        self.janela = QQuickWindow()
        self.tela = componente.createWithInitialProperties({"width": LARGURA, "height": ALTURA, "animarPasso": animar_passo})
        assert self.tela is not None, componente.errorString()
        self.componente = componente
        self.tela.setParentItem(self.janela.contentItem())
        self.janela.resize(LARGURA, ALTURA)
        self.janela.show()
        self.eventos = []
        eventos = self.eventos  # sem `self` no lambda: nada de ciclo preso à árvore Qt
        self.tela.abrir.connect(lambda: eventos.append("abrir"))
        self.tela.sair.connect(lambda: eventos.append("sair"))
        self.tela.forceActiveFocus()
        _esperar()

    def achar(self, nome):
        objeto = _achar(self.tela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def js(self, expressao):
        return _avaliar(self.tela, expressao)

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()

    def itens(self, classe):
        return _itens(self.tela, lambda i: i.metaObject().className().startswith(classe))


def _itens(raiz, filtro):
    achados, pilha = [], [raiz]
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, QQuickItem):
            if filtro(atual):
                achados.append(atual)
            pilha.extend(atual.childItems())
        else:
            pilha.extend(atual.children())
    return achados


def _produto(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


# A convenção do giro (sinal) e da perspectiva é a mesma do QML: a equivalência com o `rotate_3d` do
# Graphene vem das capturas do protótipo (D6); aqui pega-se regressão e erro de encadeamento.
def _referencia_do_gtk(i, posicao, virada, abertura, largura_tela, altura_tela):
    """Os cantos projetados da capa `i`, pela cadeia do `_transformacao`/`_arranjo` da `main` (Gsk)."""
    altura = altura_tela * 0.55
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
    escala = 1 + (regras.ESCALA_NA_ABERTURA - 1) * abertura * (1 - a)

    def trans(tx, ty, tz):
        return [[1, 0, 0, tx], [0, 1, 0, ty], [0, 0, 1, tz], [0, 0, 0, 1]]

    r = math.radians(angulo)
    c, s = math.cos(r), math.sin(r)
    perspectiva = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, -1 / regras.PERSPECTIVA, 1]]
    giro = [[c, 0, s, 0], [0, 1, 0, 0], [-s, 0, c, 0], [0, 0, 0, 1]]
    tamanho = [[escala, 0, 0, 0], [0, escala, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    m = trans(largura_tela / 2, altura_tela * 0.40, 0)
    for passo in (perspectiva, trans(x, 0, prof), giro, tamanho, trans(-largura / 2, -altura / 2, 0)):
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
    assert _capa_em(tela, LARGURA / 2, ALTURA * 0.40) == 0
    tela.bp.irPara(3)
    assert _capa_em(tela, LARGURA / 2, ALTURA * 0.40) == 3
    tela.fechar()


def test_capa_em_lateral_pelo_quadrilatero(app_qt):
    tela = _Tela()
    tela.bp.irPara(2)
    cantos = _cantos(tela, 1)
    centro = (sum(x for x, _ in cantos) / 4, sum(y for _, y in cantos) / 4)
    assert _capa_em(tela, *centro) == 1
    # Dentro da caixa alinhada (a da `main`) e fora do quadrilátero: não é a capa 1 (D44).
    xs, ys = [x for x, _ in cantos], [y for _, y in cantos]
    fora = [(x, y) for x in (min(xs), max(xs)) for y in (min(ys), max(ys)) if not _dentro(cantos, x, y)]
    assert fora, "a capa lateral inclinada tem de deixar cantos da caixa de fora"
    for x, y in fora:
        assert _capa_em(tela, x, y) != 1
    tela.fechar()


def test_capa_em_fora_de_tudo(app_qt):
    tela = _Tela()
    assert _capa_em(tela, 1, 1) == -1
    assert _capa_em(tela, LARGURA - 1, ALTURA - 1) == -1
    tela.fechar()


@pytest.mark.parametrize(
    ("posicao", "virada", "abertura"),
    [(2.0, 1.0, 0.0), (1.5, 1.0, 0.0), (2.0, 0.6, 0.0), (2.3, 0.4, 0.5), (2.0, 1.0, 1.0)],
)
def test_transformacao_igual_a_do_gtk(app_qt, posicao, virada, abertura):
    tela = _Tela()
    tela.tela.setProperty("virada", virada)
    tela.tela.setProperty("progressoAbertura", abertura)
    tela.tela.setProperty("posicao", posicao)
    for i in (1, 2, 3):
        obtido = _cantos(tela, i)
        esperado = _referencia_do_gtk(i, posicao, virada, abertura, LARGURA, ALTURA)
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
        ("duracaoDoPasso", regras.DURACAO_PASSO_MS), ("escalaNaAbertura", regras.ESCALA_NA_ABERTURA),
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
    assert len(tela.itens("QQuickLoader")) == 17
    capas = _itens(tela.tela, lambda i: i.objectName() == "capaDoBigPicture")
    assert len(capas) == min(quantidade, 15)
    tela.fechar()


def test_teclas_movem_e_esc_sai(app_qt):
    tela = _Tela()
    for tecla, esperado in (
        (Qt.Key.Key_Right, 1), (Qt.Key.Key_Right, 2), (Qt.Key.Key_Left, 1),
        (Qt.Key.Key_End, 4), (Qt.Key.Key_Home, 0), (Qt.Key.Key_PageDown, 4), (Qt.Key.Key_PageUp, 0),
    ):  # fmt: skip
        QTest.keyClick(tela.janela, tecla)
        assert tela.bp.indice == esperado, tecla
    for tecla in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
        QTest.keyClick(tela.janela, tecla)
    assert tela.eventos == ["abrir"] * 3
    QTest.keyClick(tela.janela, Qt.Key.Key_Escape)
    assert tela.eventos[-1] == "sair"
    tela.fechar()


def _clicar(tela, x, y):
    QTest.mouseClick(tela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x), round(y)))


def test_toque_na_central_abre_e_na_lateral_vai(app_qt):
    tela = _Tela()
    tela.bp.irPara(2)
    _clicar(tela, LARGURA / 2, ALTURA * 0.40)
    assert tela.eventos == ["abrir"]
    cantos = _cantos(tela, 3)
    _clicar(tela, sum(x for x, _ in cantos) / 4, sum(y for _, y in cantos) / 4)
    assert tela.bp.indice == 3
    assert tela.eventos == ["abrir"]
    _clicar(tela, 1, 1)
    assert tela.bp.indice == 3
    tela.fechar()


def test_toque_depois_de_arrastar_nao_conta(app_qt):
    tela = _Tela()
    tela.bp.irPara(3)
    x0, y = LARGURA / 2, ALTURA * 0.40
    QTest.mousePress(tela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x0), round(y)))
    for dx in range(10, 211, 20):
        QTest.mouseMove(tela.janela, QPoint(round(x0 + dx), round(y)))
        _esperar()
    QTest.mouseRelease(
        tela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(round(x0 + 210), round(y))
    )
    _esperar()
    assert "abrir" not in tela.eventos
    # Arrastar para a direita traz as capas anteriores: dx / (0,45 · larguraCapa) passos.
    passos = int(210 / (regras.ESPACO_LATERAL * (ALTURA * 0.55 * 2 / 3)))
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
    tela.bp._ocupada = True  # a fila de entrada (Task 3) liga isto
    tela.bp.alterado.emit()
    _esperar()
    for tecla in (Qt.Key.Key_Right, Qt.Key.Key_End, Qt.Key.Key_Return, Qt.Key.Key_Escape):
        QTest.keyClick(tela.janela, tecla)
    _clicar(tela, LARGURA / 2, ALTURA * 0.40)
    _clicar(tela, 1, 1)
    assert (tela.bp.indice, tela.eventos) == (0, [])
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
    capa = _capa_de_teste(motor, tmp_path, central=True)
    lateral = _capa_de_teste(motor, tmp_path, central=False)
    animada = _capa_de_teste(motor, tmp_path, central=True, animada=True)
    _esperar()
    # Pixels reais: 150 · 1,25 nas laterais; a central ganha por cima 150 · 1,6 · 1,25.
    assert _avaliar(_achar(capa, "capa"), "sourceSize.height") == round(150 * 1.25)
    em_alta = _achar(capa, "capaEmAlta")
    assert _avaliar(em_alta, "sourceSize.height") == round(150 * 1.6 * 1.25)
    assert em_alta.property("source").toString() != ""
    assert em_alta.property("visible") is True  # pronta: só então aparece
    assert _achar(lateral, "capaEmAlta").property("source").toString() == ""
    assert _achar(lateral, "capaEmAlta").property("visible") is False
    assert _achar(animada, "capaEmAlta").property("source").toString() == ""


def test_reflexo_com_mipmap(app_qt, tmp_path):
    motor = QQmlEngine()
    capa = _capa_de_teste(motor, tmp_path, central=False)
    reflexo = _achar(capa, "reflexo")
    assert [_avaliar(reflexo, f"layer.{p}") for p in ("enabled", "mipmap", "smooth")] == [True, True, True]
    assert reflexo.property("opacity") == pytest.approx(regras.REFLEXO_OPACIDADE)


def test_animada_so_com_autoplay(app_qt, tmp_path):
    motor = QQmlEngine()
    parada = _capa_de_teste(motor, tmp_path, central=True, animada=True, animar=False)
    tocando = _capa_de_teste(motor, tmp_path, central=True, animada=True, animar=True)
    lateral = _capa_de_teste(motor, tmp_path, central=False, animada=True, animar=True)
    _esperar()
    assert _achar(parada, "capaAnimada").property("source").toString() == ""
    assert _achar(tocando, "capaAnimada").property("source").toString() != ""
    assert _achar(tocando, "capaAnimada").property("playing") is True
    assert _achar(lateral, "capaAnimada").property("source").toString() == ""


def test_animar_central_segue_o_autoplay_e_as_animacoes_do_sistema(app_qt):
    modelo = ModeloDaBiblioteca()
    antes = shared.schema.get_boolean("cover-autoplay")
    try:
        shared.schema.set_boolean("cover-autoplay", False)
        sem_sistema = BigPicture(modelo, animacoes_do_sistema=False)
        bp = BigPicture(modelo)
        assert (bp.animarCentral, sem_sistema.animarCentral) == (False, False)
        shared.schema.set_boolean("cover-autoplay", True)
        _esperar()
        assert (bp.animarCentral, sem_sistema.animarCentral) == (True, False)
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


def test_vazio_mostra_o_aviso(app_qt):
    tela = _Tela(0)
    vazio = tela.achar("estadoVazioDoBigPicture")
    assert vazio.property("visible") is True
    assert vazio.property("titulo") == "Nenhum jogo"
    assert vazio.property("descricao") == "Pressione B ou Esc para voltar à biblioteca."
    assert tela.achar("rodape").property("visible") is False
    QTest.keyClick(tela.janela, Qt.Key.Key_Right)  # sem jogos, nada quebra
    tela.fechar()
    cheia = _Tela()
    assert cheia.achar("estadoVazioDoBigPicture").property("visible") is False
    assert cheia.achar("rodape").property("visible") is True
    cheia.fechar()


def test_nome_em_texto_puro(app_qt, tmp_path):
    tela = _Tela(1, nome="A & <b>B</b>")
    nome = tela.achar("nomeDoRodape")
    assert nome.property("text") == "A & <b>B</b>"
    textos = _itens(tela.tela, lambda i: i.metaObject().className().startswith("QQuickText"))
    assert len(textos) >= 3  # nome, desenvolvedora e o do placeholder da capa
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
    assert centrais() == []  # durante o passo, nenhuma
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


def _aberto_com(monkeypatch, animacoes=True, quantidade=4):
    """O Aplicativo com o Big Picture disponível (o offscreen não tem renderizador 3D) e `quantidade` jogos."""
    from PySide6.QtCore import QMetaObject  # noqa: PLC0415

    from cartridges.modelos import big_picture as modulo  # noqa: PLC0415
    from tests.test_qml_biblioteca import _App, _jogos  # noqa: PLC0415

    monkeypatch.setattr(modulo, "tem_3d", lambda _janela: True)
    jogos = _jogos(*((n, f"Jogo {n}", {"last_played": 100 - n}) for n in range(quantidade)))
    app = _App(jogos, animacoes=animacoes)
    app.big_picture.definir_janela(app.janela)
    app.clicar = lambda nome: QMetaObject.invokeMethod(app.achar(nome), "click", Qt.ConnectionType.DirectConnection)
    return app


def _entrar(app):
    app.clicar("botaoBigPicture")
    assert app.big_picture.visivel
    assert _esperar(lambda: not app.big_picture.ocupada, limite=5)


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
    barra, area = app.achar("barraDeTitulo"), app.achar("areaDaJanela")
    assert barra.property("visible") is True and area.property("y") == barra.property("height") > 0
    _entrar(app)
    assert app.janela.property("telaCheia") is True
    assert barra.property("visible") is False
    assert area.property("y") == 0
    # Os botões da barra saem do foco: o Tab não os alcança, fica no Big Picture.
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert app.achar("bigPicture").property("activeFocus") is True
    assert not any(b.property("activeFocus") for b in app.janela.property("botoesDaBarra").toVariant())
    app.big_picture.sair()
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    assert barra.property("visible") is True and area.property("y") == barra.property("height")
    app.fechar()


def test_fila_termina_no_estado_normal(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch)
    _entrar(app)
    tela = app.achar("bigPicture")
    assert (tela.property("posicao"), tela.property("virada")) == (0, 1)
    assert (tela.property("opacidadeCapas"), tela.property("opacidadeDoRodape")) == (1, 1)
    assert tela.property("naFila") is False
    app.big_picture.sair()
    assert _esperar(lambda: not app.big_picture.visivel, limite=5)
    assert (tela.property("posicao"), tela.property("virada")) == (0, 1)
    assert (tela.property("opacidadeCapas"), tela.property("opacidadeDoRodape")) == (1, 1)
    app.fechar()


def test_fila_comeca_longe_e_corre(app_qt, monkeypatch):
    app = _aberto_com(monkeypatch, quantidade=6)
    app.clicar("botaoBigPicture")
    tela = app.achar("bigPicture")
    assert tela.property("naFila") is True
    assert tela.property("posicao") == pytest.approx(5)  # n = jogos - 1: parte da cauda
    assert tela.property("opacidadeCapas") == 0 and tela.property("opacidadeDoRodape") == 0
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
    assert _esperar(lambda: _avaliar(botao, "ToolTip.visible") is True, limite=5)
    assert _avaliar(botao, "ToolTip.text") == "Requer uma placa de vídeo com aceleração 3D."
    app.fechar()
