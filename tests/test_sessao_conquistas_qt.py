# test_sessao_conquistas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As conquistas na tela da sessão: o cartão (`conquistasDoJogo.sessao` e `ConquistasDaSessao.qml`), o vigia ligado à
sessão e a leitura final do fim da sessão.

Eram os testes de `real_window` de `test_conquistas_ui.py` e `test_conquistas_sessao.py`. Nenhum vigia, fita, papel
de parede ou ícone de verdade: o `comecar`/`parar` do vigia, a varredura e o `icones.carregar` são falsos.
"""

import logging
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QCoreApplication, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QWheelEvent
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.conquistas import catalogo, historico, icones
from cartridges.conquistas import sessao as sessao_conquistas
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.jogo import Jogo
from cartridges.modelos import conquistas as modulo_das_conquistas
from cartridges.modelos import sessao as modulo_da_sessao
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.utils import session_fita, session_wallpaper, window_geometry
from tests.apoio_conquistas import com_fonte
from tests.apoio_conquistas_qt import _Detalhes, _jogo
from tests.apoio_qml_biblioteca import _achar, _App, _esperar, _jogos
from tests.apoio_qml_detalhes import _foco_dentro_de
from tests.apoio_qml_historico import _caixa, _expr, _todos

_parar_de_verdade = sessao_conquistas.parar  # antes de qualquer troca dos testes

CAT = Catalogo(
    (
        ConquistaInfo("A", "Primeira", "Faça algo.", "https://x/a.png", "", False, 55.0),
        ConquistaInfo("B", "Rara", "Difícil.", "https://x/b.png", "", False, 4.1),
        ConquistaInfo("C", "Segredo", "Spoiler.", "https://x/c.png", "", True, 20.0),
    ),
    0,
    True,
)


def _catalogo_de(quantas):
    return Catalogo(tuple(ConquistaInfo(f"N{n}", f"N{n}", "", f"https://x/{n}.png", "", False) for n in range(quantas)), 0, True)


@pytest.fixture(autouse=True)
def pedidos(monkeypatch):
    """No lugar do `icones.carregar` de verdade: anota (origem, entregar); o teste entrega o arquivo quando quiser."""
    anotados = []
    monkeypatch.setattr(icones, "carregar", lambda origem, entregar: anotados.append((origem, entregar)))
    return anotados


@pytest.fixture
def chamadas(monkeypatch, schema):
    """O que o fim e o começo da sessão pedem a cada efeito, em ordem; nenhum efeito de verdade."""
    feitas = []
    monkeypatch.setattr(session_wallpaper, "comecar", lambda _jogo: None)
    monkeypatch.setattr(session_wallpaper, "restaurar", lambda: feitas.append("parede"))
    monkeypatch.setattr(window_geometry, "restore_from_monitor", lambda _janela: None)
    monkeypatch.setattr(window_geometry, "session_geometry", lambda: None)
    schema.set_boolean("session-wallpaper", False)
    monkeypatch.setattr(session_fita, "comecar", lambda jogo: feitas.append(("fitas", jogo)))
    monkeypatch.setattr(session_fita, "voltar", lambda: feitas.append("voltar"))
    monkeypatch.setattr(session_fita, "captura_bloqueada", lambda: False)
    monkeypatch.setattr(session_fita, "fitas_fora_do_ar", lambda: [])
    monkeypatch.setattr(session_fita, "fechar", lambda: feitas.append("fechar"))
    monkeypatch.setattr(sessao_conquistas, "comecar", lambda jogo: feitas.append(("vigia", jogo)))
    monkeypatch.setattr(sessao_conquistas, "parar", lambda: feitas.append("parar"))
    return feitas


class _Controle:
    def __init__(self, feitas):
        self._feitas = feitas

    def suspender(self):
        self._feitas.append("suspender")

    def retomar(self):
        self._feitas.append("retomar")


@pytest.fixture
def modelo(chamadas, monkeypatch):
    instancia = ModeloDaSessao(SimpleNamespace(adicionar=lambda *_a, **_k: None), controle=_Controle(chamadas))
    monkeypatch.setattr(shared, "sessao", instancia, raising=False)
    return instancia


def _varredura(monkeypatch, varrer):
    monkeypatch.setattr(
        shared, "aplicativo", SimpleNamespace(varredura_conquistas=SimpleNamespace(varrer_jogo=varrer)), raising=False
    )


# -- o vigia e a leitura final ----------------------------------------------------------------


def test_a_sessao_liga_e_desliga_o_vigia(modelo, chamadas, make_game):
    jogo = make_game(name="Hollow Knight")
    modelo.show_session_blocker(jogo)
    # Depois das fitas e antes do controle, como na `main`.
    assert chamadas == [("fitas", jogo), ("vigia", jogo), "suspender"]
    chamadas.clear()
    modelo.hide_session_blocker()
    assert chamadas.index("parede") < chamadas.index("parar") < chamadas.index("voltar")


def test_troca_de_rastreador_nao_reinicia_o_vigia(modelo, chamadas, make_game):
    """O `fall_back` do `ProcessSession` passa a mesma sessão à janela manual: o vigia de antes continua."""
    jogo = make_game(name="Hollow Knight")
    modelo.show_session_blocker(jogo)
    modelo.show_session_blocker(jogo)
    assert chamadas.count(("vigia", jogo)) == 1
    assert "parar" not in chamadas


def test_o_fim_da_sessao_pede_a_leitura_final_depois_de_parar_o_vigia(modelo, chamadas, make_game, monkeypatch):
    _varredura(monkeypatch, lambda jogo: chamadas.append(("varrer", jogo)))
    jogo = make_game(name="Hollow Knight", steam_appid="570")
    modelo.show_session_blocker(jogo)
    assert not any(isinstance(c, tuple) and c[0] == "varrer" for c in chamadas)  # o começo da sessão não varre
    chamadas.clear()
    modelo.hide_session_blocker()
    # Depois de o vigia parar (com ele ativo o histórico do jogo é dele) e antes de as fitas voltarem.
    assert chamadas[chamadas.index("parede") :] == ["parede", "parar", ("varrer", jogo), "voltar"]


def test_fim_de_sessao_sem_varredura_ou_sem_jogo_nao_levanta(modelo, chamadas, make_game, monkeypatch):
    monkeypatch.setattr(shared, "aplicativo", SimpleNamespace(varredura_conquistas=None), raising=False)
    modelo.show_session_blocker(make_game(name="X"))
    modelo.hide_session_blocker()  # varredura None: nada
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    modelo.show_session_blocker(make_game(name="Y"))
    modelo.hide_session_blocker()  # sem aplicativo: nada
    varridos = []
    _varredura(monkeypatch, varridos.append)
    modelo.hide_session_blocker()  # sem jogo de sessão: nada
    assert varridos == []
    assert chamadas.count("voltar") == 3


def test_varredura_que_estoura_no_fim_da_sessao_nao_derruba_o_resto(modelo, chamadas, make_game, monkeypatch, caplog):
    def estoura(_jogo):
        raise RuntimeError("falhou")

    _varredura(monkeypatch, estoura)
    modelo.show_session_blocker(make_game(name="X"))
    with caplog.at_level(logging.WARNING):
        modelo.hide_session_blocker()
    assert chamadas[-1] == "voltar"
    assert modelo.emAndamento is False
    assert "Falha ao ler as conquistas no fim da sessão" in caplog.text


def test_encerrar_para_o_vigia_fecha_o_aviso_e_nao_le_no_fim(modelo, chamadas, make_game, monkeypatch):
    """Review Focus 5 e R1: no `saindo` (as janelas ainda na tela) só se grava e se para o vigia, que tira o aviso da
    tela; a parede e as fitas, que podem demorar, vêm no `aboutToQuit`, nessa ordem. A leitura final não roda."""
    from cartridges import conquista_aviso  # noqa: PLC0415

    monkeypatch.setattr(sessao_conquistas, "comecar", lambda _jogo: None)
    # O `parar` de verdade, com um vigia falso: é ele quem tira o aviso da tela.
    vigia = SimpleNamespace(parar=lambda: chamadas.append("vigia.parar"), game=None, ativo=True)
    monkeypatch.setattr(sessao_conquistas, "parar", _parar_de_verdade)
    monkeypatch.setattr(sessao_conquistas, "_vigia", vigia)
    monkeypatch.setattr(conquista_aviso, "fechar", lambda: chamadas.append("aviso.fechar"))
    _varredura(monkeypatch, lambda jogo: chamadas.append(("varrer", jogo)))
    modelo.show_session_blocker(make_game(name="Hollow Knight"))
    chamadas.clear()

    modelo.encerrar()  # o `saindo` (QEvent.Quit)
    # O segundo `fechar` é o do `encerrar`, para o aviso fora de sessão (I1 da revisão final do plano 6); repetido,
    # não faz nada.
    assert chamadas == ["vigia.parar", "aviso.fechar", "aviso.fechar"]

    modelo.devolver()  # o `aboutToQuit`, depois do `big_picture.encerrar()`
    assert chamadas == ["vigia.parar", "aviso.fechar", "aviso.fechar", "parede", "fechar"]


def test_devolver_sem_o_saindo_tambem_grava_antes(modelo, chamadas, make_game):
    """O desligar do Windows emite o `aboutToQuit` antes do `quit()`: o `devolver` faz o `encerrar` primeiro."""
    modelo.show_session_blocker(make_game(name="Hollow Knight"))
    chamadas.clear()
    modelo.devolver()
    assert chamadas == ["parar", "parede", "fechar"]


# -- a vista da sessão, sem tela --------------------------------------------------------------


@pytest.fixture
def vista(modelo):
    """`ConquistasDoJogo` ligado à sessão; o jogo 1 tem 2 de 3 conquistas, o 2 não tem nenhuma."""
    jogo, outro = _jogo(1), _jogo(2)
    catalogo.guardar("570", CAT)
    historico.registrar(jogo.game_id, [Desbloqueio("A", 100), Desbloqueio("B", 200)])
    com_fonte(jogo, "steam:570")
    conquistas = ConquistasDoJogo(_Detalhes(jogo, outro), modelo)
    return SimpleNamespace(jogo=jogo, outro=outro, conquistas=conquistas, sessao=modelo)


def test_cartao_da_sessao_esvazia_no_fim(vista):
    vazia = vista.conquistas.sessao
    assert vazia["visivel"] is False and vazia["icones"] == []  # sem sessão
    vista.sessao.show_session_blocker(vista.jogo)
    assert vista.conquistas.sessao["visivel"] is True
    vista.sessao.hide_session_blocker()
    assert vista.conquistas.sessao == vazia


def test_atualizar_outro_jogo_nao_mexe_no_cartao(vista, monkeypatch):
    vista.sessao.show_session_blocker(vista.jogo)
    antes = vista.conquistas.sessao
    montagens = []
    original = ConquistasDoJogo._montar_sessao  # noqa: SLF001
    monkeypatch.setattr(ConquistasDoJogo, "_montar_sessao", lambda s, g: (montagens.append(g), original(s, g))[1])
    vista.conquistas.mudou(vista.outro.game_id)
    assert montagens == []
    assert vista.conquistas.sessao == antes
    assert antes["contagem"] == "2 de 3"


def test_relogio_da_sessao_nao_refaz_o_cartao(vista, monkeypatch):
    """O `alterado` da sessão vem a cada segundo com o relógio à vista: só um jogo novo refaz o cartão."""
    vista.sessao.show_session_blocker(vista.jogo)
    montagens = []
    monkeypatch.setattr(ConquistasDoJogo, "_montar_sessao", lambda _s, g: montagens.append(g) or False)
    vista.sessao.alterado.emit()
    vista.sessao.alterado.emit()
    assert montagens == []


# -- o cartão na tela ---------------------------------------------------------------------------


@pytest.fixture
def sem_vigia(monkeypatch):
    monkeypatch.setattr(sessao_conquistas, "comecar", lambda _jogo: None)
    monkeypatch.setattr(sessao_conquistas, "parar", lambda: None)


@pytest.fixture(autouse=True)
def _sem_jogo_de_verdade(monkeypatch):
    monkeypatch.setattr(Jogo, "launch", lambda self, *a, **k: True)


def _app(cat=CAT, desbloqueadas=(("A", 100), ("B", 200))):
    """Dois jogos; o primeiro tem as conquistas (a fonte já gravada), o segundo não."""
    jogos = _jogos((1, "Alfa", {"status": "playing"}), (2, "Beta", {"status": "playing"}))
    for jogo in jogos:
        jogo.save = lambda: None
    catalogo.guardar("570", cat)
    historico.registrar(jogos[0].game_id, [Desbloqueio(nome, quando) for nome, quando in desbloqueadas])
    com_fonte(jogos[0], "steam:570")
    return _App(jogos)


def _comecar(app, indice=0):
    app.sessao.show_session_blocker(app.jogos[indice])
    _esperar(lambda: app.achar("camadaDaSessao").property("visible"))
    _esperar()


def _cartao(app):
    return app.achar("conquistasDaSessao")


def _lista(app):
    return app.achar("iconesDaSessao")


def _icones(app):
    return [i for i in _todos(_lista(app), "iconeDaConquista") if i.property("visible")]


def _png(caminho):
    imagem = QImage(8, 8, QImage.Format.Format_ARGB32)
    imagem.fill(QColor("red"))
    assert imagem.save(str(caminho), "PNG")
    return caminho


def test_cartao_da_sessao_mostra_progresso_e_todos_os_icones(app_qt, sem_vigia):
    app = _app()
    _comecar(app)
    cartao = _cartao(app)
    assert cartao.property("visible") is True
    assert _achar(cartao, "tituloDaSessao").property("text") == "Conquistas"
    assert _achar(cartao, "contagemDaSessao").property("text") == "2 de 3"
    assert _achar(cartao, "porcentagemDaSessao").property("text") == "66%"
    assert _achar(cartao, "barraDaSessao").property("value") == pytest.approx(2 / 3)
    icones_ = app.conquistas.sessao["icones"]
    assert len(icones_) == 3  # B (a mais recente), A e a oculta C por último
    assert icones_[1]["dica"].startswith("<b>Primeira</b>")
    assert icones_[2]["dica"] == "<b>Conquista oculta</b><br>Os detalhes aparecem depois do desbloqueio."
    assert icones_[2]["oculta"] is True
    assert _esperar(lambda: len(_icones(app)) == 3)
    # A dica de cada ícone vai em StyledText (o texto já sai escapado por `progresso.dica`).
    dicas = _todos(_lista(app), "dicaDaSessao")
    assert len(dicas) == 3
    assert {_expr(dica.property("contentItem"), "textFormat") for dica in dicas} == {4}  # Text.StyledText
    assert sorted(dica.property("text") for dica in dicas) == sorted(i["dica"] for i in icones_)
    app.fechar()


def test_dica_aparece_ao_passar_o_mouse(app_qt, sem_vigia):
    app = _app()
    app.janela.show()
    _comecar(app)
    assert _esperar(lambda: len(_icones(app)) == 3)
    icone = _icones(app)[0]
    ponto = icone.mapToScene(icone.boundingRect().center()).toPoint()
    QTest.mouseMove(app.janela, QPoint(ponto.x(), ponto.y()))
    dica = next(d for d in _todos(_lista(app), "dicaDaSessao") if d.parent() is icone or d.parentItem() is icone)
    assert _esperar(lambda: dica.property("visible") is True, limite=3)
    app.fechar()


def test_cartao_da_sessao_some_sem_conquistas(app_qt, sem_vigia):
    app = _app()
    _comecar(app, 1)
    assert _cartao(app).property("visible") is False
    # Escondido não ocupa espaço: a coluna da tela é a mesma de sem cartão.
    assert app.achar("colunaDaSessao").property("implicitHeight") == app.achar("colunaDoJogo").property("implicitHeight")
    app.fechar()


def test_cartao_da_sessao_atualiza_ao_vivo(app_qt, sem_vigia):
    """Uma conquista nova no meio da partida: o cartão muda sem a lista voltar ao início."""
    nomes = [f"N{n}" for n in range(157)]
    app = _app(_catalogo_de(157), desbloqueadas=((nomes[0], 1),))
    _comecar(app)
    lista = _lista(app)
    assert _esperar(lambda: lista.property("contentWidth") > lista.property("width"))
    lista.setProperty("contentX", 400)
    _esperar()
    historico.registrar(app.jogos[0].game_id, [Desbloqueio(nomes[1], 2)])
    app.conquistas.mudou(app.jogos[0].game_id)
    assert _esperar(lambda: _achar(_cartao(app), "contagemDaSessao").property("text") == "2 de 157")
    assert lista.property("contentX") == 400
    app.fechar()


def test_rolagem_volta_ao_inicio_na_sessao_seguinte(app_qt, sem_vigia):
    app = _app(_catalogo_de(157), desbloqueadas=(("N0", 1),))
    _comecar(app)
    lista = _lista(app)
    assert _esperar(lambda: lista.property("contentWidth") > lista.property("width"))
    lista.setProperty("contentX", 400)
    _esperar()
    app.sessao.hide_session_blocker()
    _esperar()
    _comecar(app)
    assert _esperar(lambda: _cartao(app).property("visible") is True)
    assert lista.property("contentX") == 0
    app.fechar()


def test_muitas_conquistas_ficam_numa_linha_que_rola_para_os_lados(app_qt, sem_vigia):
    app = _app(_catalogo_de(157), desbloqueadas=())
    _comecar(app)
    lista = _lista(app)
    assert _expr(lista, "orientation === ListView.Horizontal") is True
    assert lista.property("count") == 157
    # Uma linha só: a altura é a de um ícone, mais a folga da barra de rolagem.
    assert lista.property("height") == 48 + 14
    assert _esperar(lambda: lista.property("contentWidth") > lista.property("width"))
    assert _cartao(app).property("width") == app.achar("camadaDaSessao").property("width") - 48
    app.fechar()


def test_poucos_icones_deixam_o_cartao_estreito(app_qt, sem_vigia):
    app = _app(_catalogo_de(12), desbloqueadas=())
    _comecar(app)
    cartao, lista = _cartao(app), _lista(app)
    assert cartao.property("width") < app.achar("camadaDaSessao").property("width") - 48
    assert lista.property("contentWidth") <= lista.property("width"), "12 ícones cabem sem rolar"
    # Centralizado na camada.
    x, _y, largura, _a = _caixa(cartao)
    assert abs((x + largura / 2) - app.achar("camadaDaSessao").property("width") / 2) <= 1
    app.fechar()


def _rodar(app, item, dy):
    """Um entalhe da roda vertical sobre ``item`` (negativo: para baixo, como a roda girada para o usuário)."""
    centro = item.mapToScene(item.boundingRect().center())
    evento = QWheelEvent(
        centro, QPointF(app.janela.mapToGlobal(centro.toPoint())), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )  # fmt: skip
    QCoreApplication.sendEvent(app.janela, evento)
    _esperar()


def test_roda_do_mouse_rola_para_os_lados(app_qt, sem_vigia):
    app = _app(_catalogo_de(157), desbloqueadas=())
    app.janela.show()
    _comecar(app)
    lista = _lista(app)
    assert _esperar(lambda: lista.property("contentWidth") > lista.property("width"))
    _rodar(app, lista, -120)
    andou = lista.property("contentX")
    assert andou > 0
    _rodar(app, lista, 120)
    assert lista.property("contentX") < andou
    _rodar(app, lista, 120)
    assert lista.property("contentX") == 0  # não passa do início
    app.fechar()


def test_com_157_conquistas_e_logo_alto_o_botao_continua_na_janela(app_qt, sem_vigia, monkeypatch, tmp_path):
    """Review Focus 4: o logo no teto de altura e o cartão cheio não empurram o botão para fora da janela."""
    Image.new("RGBA", (300, 400), (255, 0, 0, 255)).save(tmp_path / "logo.png")  # mais alto que largo
    monkeypatch.setattr(modulo_da_sessao.game_logo, "cached_logo_path", lambda _jogo: tmp_path / "logo.png")
    app = _app(_catalogo_de(157), desbloqueadas=())
    app.janela.setWidth(1100)
    app.janela.setHeight(700)
    _comecar(app)
    assert _esperar(lambda: app.achar("logoDaSessao").property("visible") is True)
    _esperar()
    _x, y, _l, altura = _caixa(app.achar("botaoJaTerminei"))
    assert y >= 0 and y + altura <= 700
    cx, cy, largura, altura_do_cartao = _caixa(_cartao(app))
    assert cy + altura_do_cartao <= 700
    assert cx >= 0 and cx + largura <= 1100
    assert largura == 1100 - 48
    app.fechar()


def test_falha_no_cartao_nao_derruba_a_camada(app_qt, sem_vigia, monkeypatch):
    def quebrar(_self, _game_id):
        raise RuntimeError("falha de teste")

    monkeypatch.setattr(ConquistasDoJogo, "_montar_sessao", quebrar)
    app = _app()
    _comecar(app)
    assert app.achar("camadaDaSessao").property("visible") is True
    assert app.achar("botaoJaTerminei").property("enabled") is True
    assert _cartao(app).property("visible") is False
    app.fechar()


def test_icones_do_cartao_sao_passivos(app_qt, sem_vigia):
    app = _app()
    _comecar(app)
    assert _esperar(lambda: len(_icones(app)) == 3)
    cartao = _cartao(app)
    # Ícones só com dica: nada no cartão entra na ordem do Tab nem recebe foco.
    itens = _todos(cartao, "") + [cartao, _lista(app), *_icones(app)]
    assert not [i for i in itens if hasattr(i, "activeFocusOnTab") and i.property("activeFocusOnTab")]
    assert _lista(app).property("activeFocusOnTab") is False
    assert _lista(app).property("keyNavigationEnabled") is False
    app.fechar()


@pytest.mark.parametrize(("origem", "tecla"), [("botaoAnotacaoDaSessao", Qt.Key.Key_Tab), ("botaoJaTerminei", Qt.Key.Key_Backtab)])
def test_tab_atravessa_o_cartao_sem_perder_o_foco(app_qt, sem_vigia, origem, tecla):
    app = _app(_catalogo_de(12), desbloqueadas=())
    _comecar(app)
    app.achar(origem).forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _esperar()
    assert _foco_dentro_de(app, origem)
    QTest.keyClick(app.janela, tecla)
    _esperar()
    assert app.janela.property("activeFocusItem") is not None
    assert not _foco_dentro_de(app, origem)
    assert not _foco_dentro_de(app, "conquistasDaSessao")
    assert _foco_dentro_de(app, "camadaDaSessao")
    app.fechar()


def test_icone_que_nao_chega_fica_com_o_generico(app_qt, sem_vigia, pedidos, tmp_path):
    """Sem imagem (falha ou demora), a estrela no ladrilho, e não um buraco na fileira; quando ela chega, toma o lugar."""
    app = _app()
    _comecar(app)
    assert _esperar(lambda: len(_icones(app)) == 3)
    primeira = next(i for i in _icones(app) if i.property("url") == "" and not i.property("oculta"))
    assert _achar(primeira, "ladrilhoDaConquista").property("visible") is True
    assert primeira.property("imagemPronta") is False
    origem, entregar = next(p for p in pedidos if p[0] == "https://x/a.png")
    entregar(_png(tmp_path / "a.png"))
    assert _esperar(lambda: any(i.property("imagemPronta") for i in _icones(app)))
    pronto = next(i for i in _icones(app) if i.property("imagemPronta"))
    assert _achar(pronto, "ladrilhoDaConquista").property("visible") is False
    assert origem == "https://x/a.png"
    app.fechar()


def test_oculta_e_um_quadrado_igual_aos_outros(app_qt, sem_vigia):
    app = _app()
    _comecar(app)
    assert _esperar(lambda: len(_icones(app)) == 3)
    oculta = next(i for i in _icones(app) if i.property("oculta"))
    outras = [i for i in _icones(app) if not i.property("oculta")]
    assert (oculta.property("width"), oculta.property("height")) == (48, 48)
    assert all((i.property("width"), i.property("height")) == (48, 48) for i in outras)
    assert oculta.property("interrogacao") == 24
    assert _achar(oculta, "ladrilhoDaConquista").property("visible") is True
    app.fechar()


def test_modulo_gtk_do_cartao_saiu():
    """D63: o `CartaoDaSessao` GTK foi substituído pelo `ConquistasDaSessao.qml`."""
    import importlib.util  # noqa: PLC0415

    assert importlib.util.find_spec("cartridges.conquistas_sessao") is None
    assert hasattr(modulo_das_conquistas, "cartao_da_sessao")


def test_cores_do_cartao_da_sessao_nao_seguem_o_tema(app_qt, sem_vigia):
    """A camada da sessão é sempre escura: a trilha da barra, a barra de rolagem e o ladrilho do ícone ficam com as
    cores do tema escuro, qualquer que seja o tema (a plataforma offscreen não troca de tema: a conferência é contra o
    `Tema` de agora, o claro, cujas cores seriam as erradas aqui)."""
    app = _app()
    _comecar(app)
    cartao = _cartao(app)
    barra = _achar(cartao, "barraDaSessao")
    rolagem = _achar(cartao, "rolagemDaSessao")
    assert _esperar(lambda: len(_icones(app)) == 3)
    ladrilho = _achar(_icones(app)[0], "ladrilhoDaConquista")

    assert _expr(barra, "Tema.escuro") is False
    assert _expr(barra, "background.color.toString()") == "#3d3d3d" != _expr(barra, "Tema.botaoSobre.toString()")
    tema = _expr(rolagem, "Tema.textoSecundario.toString()")
    assert _expr(rolagem, "contentItem.color.toString()") == "#9a9a9a" != tema
    assert _expr(ladrilho, "Qt.rgba(color.r, color.g, color.b, 1).toString()") == "#ffffff"
    app.fechar()
