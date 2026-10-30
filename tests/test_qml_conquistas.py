# test_qml_conquistas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O cartão de conquistas da página do jogo e a lista completa na tela (QML offscreen, D58, D62)."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from cartridges.conquistas import catalogo, historico, icones
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.jogo import Jogo
from tests.apoio_conquistas import com_fonte
from tests.test_qml_biblioteca import _achar, _App, _esperar, _jogos
from tests.test_qml_detalhes import _abrir_pelo_cartao, _clicar, _foco_dentro_de
from tests.test_qml_historico import _caixa, _expr, _todos

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
    _esperar()
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
    assert _esperar(lambda: _foco_dentro_de(app, "botaoFecharConquistas"))

    QTest.keyClick(app.janela, Qt.Key.Key_Escape)

    assert _esperar(lambda: app.conquistas.aberto is False)
    assert app.achar("dialogoDeConquistas").property("visible") is False
    assert _esperar(lambda: _foco_dentro_de(app, "cartaoDeConquistas"))
    # De volta aos detalhes, que seguem à vista.
    assert app.janela.property("paginaAtual") == "jogo"
    app.fechar()


def test_cartao_que_some_com_a_lista_aberta_devolve_o_foco_a_pagina(app_qt):
    app = _app()
    _abrir_pelo_cartao(app, 0)
    cartao = app.achar("cartaoDeConquistas")
    cartao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _clicar(app, cartao)
    assert _esperar(lambda: app.conquistas.aberto)

    app.jogos[0].conquistas = False  # o cartão some: quem abriu a lista deixa de existir
    app.conquistas.mudou(None)

    assert _esperar(lambda: app.conquistas.aberto is False)
    assert app.achar("blocoDeConquistas").property("visible") is False
    assert _esperar(lambda: _foco_dentro_de(app, "paginaDoJogo"))
    app.fechar()


def test_botao_de_fechar_fecha(app_qt):
    app = _app()
    _abrir_lista(app)
    _clicar(app, app.achar("botaoFecharConquistas"))
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


# O recorte arredondado é um `MultiEffect` (D60), que o backend `software` da plataforma offscreen não desenha: a
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

