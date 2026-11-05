# test_qml_conquistas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O cartão de conquistas da página do jogo e a lista completa na tela (QML offscreen)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.conquistas import catalogo, historico, icones
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.jogo import Jogo
from tests.apoio_conquistas import com_fonte
from tests.apoio_qml_biblioteca import _achar, _App, _assentar, _esperar, _jogos
from tests.apoio_qml_detalhes import _abrir_pelo_cartao, _clicar, _foco_dentro_de
from tests.apoio_qml_historico import _caixa, _expr, _todos

RAIZ = Path(__file__).resolve().parent.parent

CAT = Catalogo(
    (
        ConquistaInfo("A", "Primeira", "Faça algo.", "https://x/a.png", "", False, 55.0),
        ConquistaInfo("B", "Rara", "Difícil.", "https://x/b.png", "", False, 4.1),
        ConquistaInfo("C", "Segredo", "Spoiler.", "https://x/c.png", "", True, 20.0),
    ),
    0,
    True,
)


@pytest.fixture(autouse=True)
def _sem_jogo_de_verdade(monkeypatch):
    monkeypatch.setattr(Jogo, "launch", lambda self, *a, **k: True)


@pytest.fixture(autouse=True)
def pedidos(monkeypatch):
    """No lugar do `icones.carregar` de verdade: anota (origem, entregar); o teste entrega o arquivo quando quiser."""
    anotados = []
    monkeypatch.setattr(icones, "carregar", lambda origem, entregar: anotados.append((origem, entregar)))
    return anotados


def _app(cat=CAT, desbloqueadas=(("A", 100), ("B", 200)), **extra):
    """Dois jogos; o primeiro tem as conquistas (a fonte já gravada), o segundo não."""
    jogos = _jogos((1, "Alfa", extra), (2, "Beta", {}))
    catalogo.guardar("570", cat)
    historico.registrar(jogos[0].game_id, [Desbloqueio(nome, quando) for nome, quando in desbloqueadas])
    com_fonte(jogos[0], "steam:570")
    return _App(jogos)


def _png(caminho, largura=8, altura=8):
    imagem = QImage(largura, altura, QImage.Format.Format_ARGB32)
    imagem.fill(QColor("red"))
    assert imagem.save(str(caminho), "PNG")
    return caminho


def _abrir_lista(app):
    pagina = _abrir_pelo_cartao(app, 0)
    app.conquistas.abrir(app.jogos[0].game_id)
    assert _esperar(lambda: app.achar("dialogoDeConquistas").property("visible") is True)
    _assentar()
    return pagina, app.achar("dialogoDeConquistas")


def _icone_da_primeira(dialogo):
    """O ícone da fileira "Primeira", achado de novo a cada chamada (a lista é refeita quando um ícone chega)."""
    linha = next(f for f in _todos(dialogo, "fileiraDeConquista") if _achar(f, "tituloDaConquista").property("text") == "Primeira")
    return _achar(linha, "iconeDaConquista")


def _visiveis(raiz, nome):
    return [item for item in _todos(raiz, nome) if item.property("visible")]


# -- o cartão da página -----------------------------------------------------------------------


def test_cartao_abaixo_do_hltb_e_some_sem_conquistas(app_qt):
    app = _app(hltb_main=36000)
    pagina = _abrir_pelo_cartao(app, 0)
    bloco = app.achar("blocoDeConquistas")
    hltb = app.achar("blocoHltb")
    assert hltb.property("visible") is True
    assert bloco.property("visible") is True
    assert _caixa(bloco)[1] >= _caixa(hltb)[1] + hltb.height()
    assert app.achar("contagemDeConquistas").property("text") == "2 de 3"
    assert app.achar("porcentagemDeConquistas").property("text") == "66%"
    assert len(_visiveis(app.achar("iconesDeConquistas"), "iconeDaConquista")) == 2
    assert pagina.property("visible") is True

    # O outro jogo não tem conquistas: o cartão some.
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.janela.property("paginaAtual") == "todos")
    _abrir_pelo_cartao(app, 1)
    assert _esperar(lambda: app.achar("blocoDeConquistas").property("visible") is False)
    app.fechar()


def test_clicar_abre_o_dialogo(app_qt):
    app = _app()
    _abrir_pelo_cartao(app, 0)
    dialogo = app.achar("dialogoDeConquistas")
    assert dialogo.property("visible") is False
    assert app.conquistas.aberto is False

    _clicar(app, app.achar("cartaoDeConquistas"))

    assert _esperar(lambda: app.conquistas.aberto)
    assert app.conquistas.nome == "Alfa"
    assert _esperar(lambda: dialogo.property("visible") is True)
    # Como no histórico, o fundo fica desabilitado.
    assert app.achar("pilha").property("enabled") is False
    assert app.achar("botaoVoltar").property("enabled") is False
    app.fechar()


def test_enter_no_cartao_abre_o_dialogo(app_qt):
    app = _app()
    _abrir_pelo_cartao(app, 0)
    app.achar("cartaoDeConquistas").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: _foco_dentro_de(app, "cartaoDeConquistas"))

    QTest.keyClick(app.janela, Qt.Key.Key_Return)

    assert _esperar(lambda: app.conquistas.aberto)
    app.fechar()


def test_espaco_no_cartao_abre_o_dialogo(app_qt):
    app = _app()
    _abrir_pelo_cartao(app, 0)
    app.achar("cartaoDeConquistas").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: _foco_dentro_de(app, "cartaoDeConquistas"))

    QTest.keyClick(app.janela, Qt.Key.Key_Space)

    assert _esperar(lambda: app.conquistas.aberto)
    app.fechar()


def test_setas_da_pagina_alcancam_o_cartao(app_qt):
    app = _app()
    pagina = _abrir_pelo_cartao(app, 0)
    app.achar("botaoStatus").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: _foco_dentro_de(app, "botaoStatus"))
    QTest.keyClick(app.janela, Qt.Key.Key_Up)
    assert _esperar(lambda: _foco_dentro_de(app, "cartaoDeConquistas"))
    assert pagina.property("visible") is True
    app.fechar()


def test_esc_fecha_e_o_foco_volta_ao_cartao(app_qt):
    app = _app()
    _abrir_pelo_cartao(app, 0)
    cartao = app.achar("cartaoDeConquistas")
    cartao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _clicar(app, cartao)
    assert _esperar(lambda: app.conquistas.aberto)
    assert _esperar(lambda: _foco_dentro_de(app, "fecharDoCabecalho"))

    QTest.keyClick(app.janela, Qt.Key.Key_Escape)

    assert _esperar(lambda: app.conquistas.aberto is False)
    assert app.achar("dialogoDeConquistas").property("visible") is False
    assert _esperar(lambda: _foco_dentro_de(app, "cartaoDeConquistas"))
    # De volta aos detalhes, que seguem à vista.
    assert app.janela.property("paginaAtual") == "jogo"
    app.fechar()


def test_cartao_que_some_com_a_lista_aberta_nao_fecha_a_lista(app_qt):
    """A lista é o retrato de quando abriu; o jogo que perde o cartão não a fecha nem a esvazia (a página, sim)."""
    app = _app()
    _abrir_pelo_cartao(app, 0)
    cartao = app.achar("cartaoDeConquistas")
    cartao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _clicar(app, cartao)
    assert _esperar(lambda: app.conquistas.aberto)
    dialogo = app.achar("dialogoDeConquistas")
    antes = sorted(t.property("text") for t in _todos(dialogo, "tituloDaConquista"))
    assert antes == ["Conquista oculta", "Primeira", "Rara"]

    app.jogos[0].conquistas = False  # o cartão some: quem abriu a lista deixa de existir
    app.conquistas.mudou(None)

    assert _esperar(lambda: app.achar("blocoDeConquistas").property("visible") is False)
    _assentar()
    assert app.conquistas.aberto is True
    assert dialogo.property("visible") is True
    assert sorted(t.property("text") for t in _todos(dialogo, "tituloDaConquista")) == antes
    # Fechada pela pessoa, o foco volta à página à vista.
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.conquistas.aberto is False)
    assert _esperar(lambda: _foco_dentro_de(app, "paginaDoJogo"))
    app.fechar()


def test_lista_aberta_nao_muda_com_conquista_nova_nem_com_a_preferencia(app_qt):
    """Conquista nova e a troca de "mostrar ocultas" só valem na próxima abertura."""
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    titulos = lambda: sorted(t.property("text") for t in _todos(dialogo, "tituloDaConquista"))  # noqa: E731
    assert titulos() == ["Conquista oculta", "Primeira", "Rara"]

    historico.registrar(app.jogos[0].game_id, [Desbloqueio("A", 100), Desbloqueio("B", 200), Desbloqueio("C", 300)])
    app.conquistas.mudou(app.jogos[0].game_id)
    shared.schema.set_boolean("conquistas-mostrar-ocultas", True)
    _assentar()

    assert titulos() == ["Conquista oculta", "Primeira", "Rara"]  # a oculta segue sem nome, mesmo com a preferência
    assert app.conquistas.resumo == "2 de 3 conquistas desbloqueadas"
    # Na próxima abertura a lista é refeita.
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.conquistas.aberto is False)
    app.conquistas.abrir(app.jogos[0].game_id)
    assert _esperar(lambda: app.conquistas.resumo == "3 de 3 conquistas desbloqueadas")
    shared.schema.set_boolean("conquistas-mostrar-ocultas", False)
    app.fechar()


def test_botao_de_fechar_fecha(app_qt):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    _clicar(app, _achar(dialogo, "fecharDoCabecalho"))
    assert _esperar(lambda: app.conquistas.aberto is False)
    app.fechar()


def test_teclas_nao_passam_para_a_pagina_de_tras(app_qt):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    QTest.keyClick(app.janela, Qt.Key.Key_Left)
    _esperar()
    assert dialogo.property("visible") is True
    assert app.janela.property("paginaAtual") == "jogo"
    app.fechar()


def test_nome_acessivel_do_dialogo(app_qt):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    assert _expr(dialogo, "Accessible.name") == "Conquistas"
    assert _expr(dialogo, "Accessible.role") == _expr(dialogo, "Accessible.Dialog")
    # Sem título visível: o nome do jogo (ou o logo) é a manchete.
    assert [t.property("text") for t in _visiveis(dialogo, "nomeDasConquistas")] == ["Alfa"]
    assert app.achar("resumoDasConquistas").property("text") == "2 de 3 conquistas desbloqueadas"
    app.fechar()


# -- a lista ----------------------------------------------------------------------------------


def test_titulos_em_texto_puro(app_qt):
    cat = Catalogo((ConquistaInfo("A", "A & B <i>", "<b>x</b> & y", "", "", False, 50.0),), 0, True)
    app = _app(cat, (("A", 100),), name="Z & <u>W</u>")
    _pagina, dialogo = _abrir_lista(app)
    titulo = _visiveis(dialogo, "tituloDaConquista")[0]
    assert titulo.property("text") == "A & B <i>"
    assert _expr(titulo, "textFormat") == 0  # Text.PlainText
    for nome in ("subtituloDaConquista", "dataDaConquista", "porcentagemDaConquista", "nomeDasConquistas"):
        achados = _visiveis(dialogo, nome)
        assert achados, nome
        assert all(_expr(achado, "textFormat") == 0 for achado in achados), nome
    assert _visiveis(dialogo, "subtituloDaConquista")[0].property("text") == "<b>x</b> & y"
    app.fechar()


def test_rara_em_dourado(app_qt):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    por_titulo = {}
    for linha in _todos(dialogo, "fileiraDeConquista"):
        titulo = _achar(linha, "tituloDaConquista").property("text")
        por_titulo[titulo] = _achar(linha, "porcentagemDaConquista")
    rara, comum = por_titulo["Rara"], por_titulo["Primeira"]
    assert rara.property("text") == "★ 4,1%"
    assert _expr(rara, "color.toString()") == "#e5a50a"
    assert _expr(rara, "font.bold") is True
    assert comum.property("text") == "55,0%"
    assert _expr(comum, "color.toString()") != "#e5a50a"
    assert _expr(comum, "font.bold") is False
    app.fechar()


def test_bloqueada_fica_apagada(app_qt):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    opacidades = {}
    for linha in _todos(dialogo, "fileiraDeConquista"):
        opacidades[_achar(linha, "tituloDaConquista").property("text")] = linha.property("opacity")
    assert opacidades["Rara"] == 1
    assert opacidades["Conquista oculta"] == pytest.approx(0.55)
    app.fechar()


def test_grupo_vazio_nao_aparece(app_qt):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    assert app.achar("secaoDesbloqueadas").property("visible") is True
    assert app.achar("secaoBloqueadas").property("visible") is True
    app.fechar()

    # Tudo desbloqueado: só "Desbloqueadas".
    app = _app(desbloqueadas=(("A", 1), ("B", 2), ("C", 3)))
    _abrir_lista(app)
    assert app.achar("secaoDesbloqueadas").property("visible") is True
    assert app.achar("secaoBloqueadas").property("visible") is False
    app.fechar()


def test_ladrilho_ate_o_icone_chegar(app_qt, pedidos, tmp_path):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    fileira = next(f for f in _todos(dialogo, "fileiraDeConquista") if _achar(f, "tituloDaConquista").property("text") == "Rara")
    icone = _achar(fileira, "iconeDaConquista")
    assert _achar(icone, "ladrilhoDaConquista").property("visible") is True
    assert _achar(icone, "imagemDaConquista").property("visible") is False

    entregas = dict(pedidos)
    entregas["https://x/b.png"](_png(tmp_path / "b.png"))

    # A lista é refeita com a URL: o ícone é outro item, achado de novo.
    def _icone_de_rara():
        linha = next(f for f in _todos(dialogo, "fileiraDeConquista") if _achar(f, "tituloDaConquista").property("text") == "Rara")
        return _achar(linha, "iconeDaConquista")

    assert _esperar(lambda: _achar(_icone_de_rara(), "imagemDaConquista").property("visible") is True)
    assert _achar(_icone_de_rara(), "ladrilhoDaConquista").property("visible") is False
    # O cartão da página segue à vista (o ícone dele é outro pedido, não conferido aqui).
    assert app.achar("blocoDeConquistas").property("visible") is True
    app.fechar()


def test_lote_de_icones_nao_recria_as_fileiras(app_qt, pedidos, tmp_path):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    antes = next(f for f in _todos(dialogo, "fileiraDeConquista") if _achar(f, "tituloDaConquista").property("text") == "Rara")
    assert _achar(_achar(antes, "iconeDaConquista"), "imagemDaConquista").property("visible") is False

    dict(pedidos)["https://x/b.png"](_png(tmp_path / "b.png"))

    def _icone_trocou():
        try:  # a fileira antiga morreu (a lista foi refeita): o ícone dela não existe mais
            return _achar(_achar(antes, "iconeDaConquista"), "imagemDaConquista").property("visible") is True
        except (AttributeError, RuntimeError):
            return False

    assert _esperar(_icone_trocou)
    depois = next(f for f in _todos(dialogo, "fileiraDeConquista") if _achar(f, "tituloDaConquista").property("text") == "Rara")
    assert depois is antes  # a mesma fileira continua viva
    app.fechar()


def test_oculta_e_um_ladrilho_com_interrogacao(app_qt):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    fileira = next(f for f in _todos(dialogo, "fileiraDeConquista") if _achar(f, "tituloDaConquista").property("text") == "Conquista oculta")
    icone = _achar(fileira, "iconeDaConquista")
    assert icone.property("oculta") is True
    assert _achar(icone, "ladrilhoDaConquista").property("visible") is True
    assert _achar(icone, "imagemDaConquista").property("visible") is False
    app.fechar()


def test_icone_cortado_em_quadrado(app_qt, pedidos, tmp_path):
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    entregas = dict(pedidos)
    entregas["https://x/a.png"](_png(tmp_path / "a.png", 80, 40))  # larga: o quadrado central

    assert _esperar(lambda: _achar(_icone_da_primeira(dialogo), "imagemDaConquista").property("visible") is True)
    imagem = _achar(_icone_da_primeira(dialogo), "imagemDaConquista")
    assert imagem.width() == imagem.height() == 36
    assert _expr(imagem, "fillMode") == 2  # Image.PreserveAspectCrop
    app.fechar()


# O recorte arredondado é um `MultiEffect`, que o backend `software` da plataforma offscreen não desenha: a
# conferência dos pixels roda num processo à parte, na plataforma `windows` com Direct3D, e a janela nunca é mostrada
# (o `grabWindow` de uma janela escondida desenha fora da tela).
_RECORTE = r"""
import json, sys
from pathlib import Path
from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QColor, QGuiApplication, QImage
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickWindow

app = QGuiApplication([])
png = Path(sys.argv[1])
imagem = QImage(80, 80, QImage.Format.Format_ARGB32)
imagem.fill(QColor("red"))
assert imagem.save(str(png), "PNG")
url = QUrl.fromLocalFile(str(png)).toString()

motor = QQmlEngine()
from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
motor.addImageProvider("icone", ProvedorDeIcones())
janela = QQuickWindow()
janela.resize(400, 200)
janela.setColor(QColor("blue"))
itens = []


def montar(texto):
    componente = QQmlComponent(motor)
    componente.setData(texto.encode(), QUrl.fromLocalFile(str(Path("cartridges/qml/_recorte.qml").resolve())))
    item = componente.create()
    assert item is not None, componente.errorString()
    item.setParent(janela.contentItem())  # o dono em C++: sem ele o coletor do motor apaga o item
    item.setParentItem(janela.contentItem())
    itens.append(item)
    return item


icone = montar('IconeDaConquista { x: 10; y: 10; tamanho: 48; url: "%s" }' % url)
cartao = montar('CartaoDoAviso { x: 100; y: 10; opacidade: 1; icone: "%s" }' % url)
for _ in range(20):
    app.processEvents()
tela = janela.grabWindow()
escala = tela.width() / janela.width()


def pixels(item):
    canto = item.mapToScene(item.boundingRect().topLeft())
    x, y = round(canto.x() * escala), round(canto.y() * escala)
    meio = item.width() * escala / 2
    return [tela.pixelColor(x, y).name(), tela.pixelColor(round(x + meio), round(y + meio)).name()]


print(json.dumps({"api": str(janela.rendererInterface().graphicsApi()), "conquista": pixels(icone),
                  "aviso": pixels(cartao.findChild(QObject, "iconeDoAviso"))}))
"""


def test_icones_de_conquista_cortam_os_cantos(tmp_path):
    """O ícone vermelho cheio sai com o canto arredondado, no ícone das conquistas e no do aviso: no canto, o que está
    atrás (o azul da janela; o escuro do cartão do aviso); no meio, o vermelho."""
    ambiente = {**os.environ, "QT_QPA_PLATFORM": "windows", "CARTRIDGES_DADOS": str(tmp_path)}
    resultado = subprocess.run(
        [sys.executable, "-c", _RECORTE, str(tmp_path / "icone.png")],
        cwd=RAIZ, env=ambiente, capture_output=True, text=True, timeout=60, check=False,
    )  # fmt: skip
    assert resultado.returncode == 0, resultado.stderr
    medido = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert "Software" not in medido["api"], medido
    for onde in ("conquista", "aviso"):
        canto, meio = medido[onde]
        assert meio == "#ff0000", (onde, medido)
        assert canto != "#ff0000" and QColor(canto).red() < 128, (onde, medido)



def test_sem_avisos_do_qml_ao_abrir_e_fechar(app_qt):
    avisos = []
    anterior = qInstallMessageHandler(lambda tipo, _ctx, msg: avisos.append(msg) if tipo in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg) else None)
    try:
        app = _app()
        # A `PaginaDasConquistas` é a aba "conquistas" das Preferências; a lista de conquistas é outra tela.
        assert app.preferencias.abrir("conquistas")
        assert _esperar(lambda: app.achar("dialogoDePreferencias").property("visible") is True)
        assert _esperar(lambda: app.achar("paginaDasConquistas").property("visible") is True)
        QTest.keyClick(app.janela, Qt.Key.Key_Escape)
        assert _esperar(lambda: app.achar("dialogoDePreferencias").property("visible") is False)
        _abrir_lista(app)
        QTest.keyClick(app.janela, Qt.Key.Key_Escape)
        assert _esperar(lambda: app.achar("dialogoDeConquistas").property("visible") is False)
        app.fechar()
    finally:
        qInstallMessageHandler(anterior)
    assert [a for a in avisos if "PaginaDasConquistas" in a or "DialogoDeConquistas" in a] == []


# -- moldura e foco da lista --------------------------------------------------------------------


def test_dialogo_tem_as_medidas_da_main(app_qt):
    """Moldura de 520 por 640, raio 15, cabeçalho de 47, conteúdo 24 abaixo, fileiras de 55 de passo."""
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    cartao = _achar(dialogo, "cartaoDoDialogo")
    assert (cartao.width(), cartao.height()) == (520, 640)
    assert _expr(cartao, "radius") == 15
    assert _expr(dialogo, "Accessible.name") == "Conquistas"
    cabecalho = _achar(dialogo, "tituloDoCabecalho").parentItem()
    assert cabecalho.height() == 47
    rolagem = _achar(dialogo, "rolagemDeConquistas")
    assert rolagem.y() == 47  # logo abaixo do cabeçalho
    nome = _achar(dialogo, "nomeDasConquistas")
    assert nome.mapToItem(rolagem.property("contentItem"), 0, 0).y() == 24  # a margem da `PreferencesPage`
    assert _expr(nome, "font.pixelSize") == 22 and _expr(nome, "font.weight") == 800  # title-1
    resumo = _achar(dialogo, "resumoDasConquistas")
    assert _expr(resumo, "font.pixelSize") == 12 and _expr(resumo, "wrapMode") == 0  # Text.NoWrap
    assert resumo.property("lineCount") == 1
    barra = _achar(dialogo, "barraDasConquistas")
    assert barra.height() == 8
    # Os grupos: título de 12 em negrito sem recuo, a 12 da lista.
    secao = _achar(dialogo, "secaoDesbloqueadas")
    titulo = _expr(secao, "children[0]")
    assert _expr(titulo, "font.pixelSize") == 12 and _expr(titulo, "font.weight") == 700
    assert titulo.x() == 0
    assert _expr(secao, "spacing") == 12
    # As fileiras: 54 e 55 (o separador), título 12, subtítulo 10 com 3 de distância, data e porcentagem 12.
    fileiras = sorted(_todos(secao, "fileiraDeConquista"), key=lambda f: f.y())
    assert [f.height() for f in fileiras] == [54, 55]
    for f in fileiras:
        assert _expr(_achar(f, "tituloDaConquista"), "font.pixelSize") == 12
        assert _expr(_achar(f, "subtituloDaConquista"), "font.pixelSize") == 10
        assert _expr(_achar(f, "dataDaConquista"), "font.pixelSize") == 12
        assert _expr(_achar(f, "porcentagemDaConquista"), "font.pixelSize") == 12
        assert _expr(_achar(f, "subtituloDaConquista").parentItem(), "spacing") == 3
        assert _achar(f, "iconeDaConquista").mapToItem(f, 0, 0).x() == 14  # a margem lateral da fileira
    app.fechar()


def test_aberto_com_o_mouse_o_foco_vai_ao_fechar_sem_anel(app_qt):
    """O X recebe o foco ao abrir, mas o anel só aparece se o teclado já estava em uso."""
    app = _app()
    _abrir_pelo_cartao(app, 0)
    cartao = app.achar("cartaoDeConquistas")
    cartao.forceActiveFocus(Qt.FocusReason.MouseFocusReason)
    _clicar(app, cartao)
    assert _esperar(lambda: app.conquistas.aberto)
    assert _esperar(lambda: _foco_dentro_de(app, "fecharDoCabecalho"))
    fechar = _achar(app.achar("dialogoDeConquistas"), "fecharDoCabecalho")
    assert fechar.property("activeFocus") is True
    assert fechar.property("visualFocus") is False
    app.fechar()

    # Pelo teclado (Enter no cartão focado com Tab), o anel acende.
    app = _app()
    _abrir_pelo_cartao(app, 0)
    app.achar("cartaoDeConquistas").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: _foco_dentro_de(app, "cartaoDeConquistas"))
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.conquistas.aberto)
    fechar = _achar(app.achar("dialogoDeConquistas"), "fecharDoCabecalho")
    assert _esperar(lambda: fechar.property("visualFocus") is True)
    app.fechar()


def test_fileiras_recebem_foco_e_as_setas_andam_entre_elas(app_qt):
    """Tab alcança as fileiras, Cima e Baixo andam entre elas sem sair da lista, com o anel de foco."""
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    alvos = sorted(_todos(dialogo, "alvoDaFileiraDeConquista"), key=lambda a: a.mapToScene(QPointF(0, 0)).y())
    assert len(alvos) == 3
    fechar = _achar(dialogo, "fecharDoCabecalho")
    assert fechar.property("activeFocus") is True

    QTest.keyClick(app.janela, Qt.Key.Key_Tab)  # do X à primeira fileira
    assert _esperar(lambda: alvos[0].property("activeFocus") is True)
    assert alvos[0].property("visualFocus") is True
    primeira = alvos[0].parentItem()
    assert _expr(primeira, "foco") is True
    assert _expr(_achar(primeira, "anelDeFoco"), "ativo") is True

    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    assert _esperar(lambda: alvos[1].property("activeFocus") is True)
    assert _expr(primeira, "foco") is False
    QTest.keyClick(app.janela, Qt.Key.Key_Down)  # passa ao grupo "Bloqueadas"
    assert _esperar(lambda: alvos[2].property("activeFocus") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Down)  # na última, fica onde está (não volta ao X)
    _esperar()
    assert alvos[2].property("activeFocus") is True
    QTest.keyClick(app.janela, Qt.Key.Key_Up)
    assert _esperar(lambda: alvos[1].property("activeFocus") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Up)
    assert _esperar(lambda: alvos[0].property("activeFocus") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Up)  # na primeira, fica onde está (não sobe ao X)
    _esperar()
    assert alvos[0].property("activeFocus") is True
    assert dialogo.property("visible") is True
    app.fechar()


def test_foco_numa_fileira_de_baixo_rola_a_lista(app_qt):
    """A fileira focada fica à vista na rolagem do diálogo."""
    infos = tuple(ConquistaInfo(f"K{i}", f"Meta {i}", "Faça.", "", "", False, 50.0) for i in range(30))
    app = _app(Catalogo(infos, 0, True), tuple((f"K{i}", 100 + i) for i in range(5)))
    _pagina, dialogo = _abrir_lista(app)
    rolagem = _achar(dialogo, "rolagemDeConquistas")
    assert rolagem.property("contentY") == 0
    alvos = sorted(_todos(dialogo, "alvoDaFileiraDeConquista"), key=lambda a: a.mapToScene(QPointF(0, 0)).y())
    alvos[-1].forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: rolagem.property("contentY") > 0)
    topo = alvos[-1].mapToItem(rolagem, 0, 0).y()
    assert 0 <= topo and topo + alvos[-1].height() <= rolagem.height()
    app.fechar()


def test_abre_e_fecha_pela_moldura_com_o_esmaecimento_da_main(app_qt):
    """O fundo é o `Tema.esmaecido` (e não o #80000000 dos dois temas) e a janela estreita vira folha de baixo."""
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    esmaecimento = _achar(dialogo, "esmaecimentoDaMoldura")
    assert _expr(esmaecimento, "color.toString()") == _expr(dialogo, "Tema.esmaecido.toString()")
    assert _expr(dialogo, "cor.toString()") == _expr(dialogo, "Tema.fundo.toString()")
    assert dialogo.property("podeSerFolha") is True
    assert dialogo.property("emFolha") is False
    app.janela.resize(420, 700)
    assert _esperar(lambda: dialogo.property("emFolha") is True)
    cartao = _achar(dialogo, "cartaoDoDialogo")
    assert cartao.width() == 420
    app.fechar()


def test_cartao_da_pagina_segue_a_main(app_qt):
    """Contagem 14, porcentagem e `+N` 12, sem espaço entre elas; ícones sem ladrilho; foco a -1; hover a 200 ms."""
    app = _app()
    _abrir_pelo_cartao(app, 0)
    contagem = app.achar("contagemDeConquistas")
    porcentagem = app.achar("porcentagemDeConquistas")
    assert _expr(contagem, "font.pixelSize") == 14 and _expr(contagem, "font.weight") == 700  # title-4
    assert _expr(porcentagem, "font.pixelSize") == 12
    assert _expr(app.achar("restoDeConquistas"), "font.pixelSize") == 12
    assert porcentagem.x() == contagem.x() + contagem.width()  # sem espaçamento entre elas
    # Até o ícone chegar (ou se falhar) fica só o espaço de 32 px, sem ladrilho.
    icones_ = _visiveis(app.achar("iconesDeConquistas"), "iconeDaConquista")
    assert len(icones_) == 2
    for icone in icones_:
        assert icone.property("semLadrilho") is True
        assert (icone.width(), icone.height()) == (32, 32)
        assert _achar(icone, "ladrilhoDaConquista").property("visible") is False
    cartao = app.achar("cartaoDeConquistas")
    assert _expr(_achar(cartao, "anelDeFoco"), "afastamento") == -1
    # Ao apertar (o hover não existe no offscreen) soma 8% do texto, com a transição de 200 ms (não de uma vez).
    camada = _achar(cartao, "camadaDoCartaoDeConquistas")
    assert camada.property("opacity") == 0
    ponto = cartao.mapToScene(cartao.boundingRect().center()).toPoint()
    QTest.mousePress(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    vistos = []
    for _ in range(40):
        _assentar(1)
        vistos.append(camada.property("opacity"))
        if vistos[-1] == 1:
            break
    assert vistos[-1] == 1
    assert any(0 < v < 1 for v in vistos), vistos
    assert _expr(camada, "color") == _expr(camada, "Tema.linhaPressionada")
    QTest.mouseRelease(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(2, 2))  # solta fora: não abre
    assert app.conquistas.aberto is False
    app.fechar()


def test_icone_da_conquista_usa_o_fundo_de_7_2_por_cento(app_qt):
    """`alpha(currentColor, .12)` sobre `color: alpha(currentColor, .6)`: o fundo é 0,6 x 0,12 do texto (o claro leva o 0,8)."""
    app = _app()
    _pagina, dialogo = _abrir_lista(app)
    icone = _icone_da_primeira(dialogo)
    ladrilho = _achar(icone, "ladrilhoDaConquista")
    texto_a = _expr(icone, "Tema.texto.a")
    assert _expr(ladrilho, "color.a") == pytest.approx(texto_a * 0.072, abs=0.002)
    estrela = _achar(icone, "estrelaDaConquista")
    assert _expr(estrela, "cor.a") == pytest.approx(texto_a * 0.6, abs=0.01)
    app.fechar()
