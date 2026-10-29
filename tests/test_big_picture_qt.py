# test_big_picture_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A lista do Big Picture sobre o `ModeloDaBiblioteca`: centro, rótulos, tique e fundo."""

from dataclasses import replace

import pytest
from PySide6.QtCore import QEventLoop, QObject, QSize, QTimer, Signal
from PySide6.QtGui import QImage, QWindow
from PySide6.QtQuick import QSGRendererInterface

from cartridges.jogo import Jogo
from cartridges.modelos import big_picture as modulo
from cartridges.modelos import regras_do_big_picture as regras
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.utils import restauracao


def _esperar():
    laco = QEventLoop()
    QTimer.singleShot(20, laco.quit)
    laco.exec()


def _jogo(game_id, last_played=0, **extra):
    return Jogo({"game_id": game_id, "source": "imported", "name": game_id.upper(), "last_played": last_played, **extra})


@pytest.fixture
def tiques(monkeypatch):
    tocados = []
    monkeypatch.setattr(regras, "tocar_tique", lambda: tocados.append(1))
    return tocados


def _montar(*jogos):
    """O modelo e o Big Picture já aberto (a lista só acompanha a biblioteca visível), com a fila concluída."""
    modelo = ModeloDaBiblioteca()
    for jogo in jogos:
        modelo.atualizar(jogo)
    bp = BigPicture(modelo)
    bp.entrar()
    bp.filaTerminou()
    return modelo, bp


def _ids(bp):
    return [j["jogoId"] for j in bp.jogos]


@pytest.fixture
def tres(app_qt, tiques):
    """a (mais recente), b e c, nesta ordem."""
    return _montar(_jogo("a", 30), _jogo("b", 20), _jogo("c", 10))


def test_lista_do_mais_recente_ao_mais_antigo(tres):
    _, bp = tres
    assert _ids(bp) == ["a", "b", "c"]
    assert (bp.indice, bp.nome, bp.vazia) == (0, "A", False)
    assert set(bp.jogos[0]) == {"jogoId", "nome", "desenvolvedora", "capa", "capaAnimada"}


def test_pendente_de_restauracao_nao_entra(app_qt, tiques, monkeypatch):
    monkeypatch.setattr(restauracao, "e_pendente", lambda game_id: game_id == "p")
    modelo, bp = _montar(_jogo("a", 30), _jogo("p", 50))
    assert _ids(bp) == ["a"]
    assert modelo.rowCount() == 1


def test_desinstalado_nao_entra(app_qt, tiques):
    # Um zerado desinstalado fica no modelo (Jogos Zerados), mas não é da biblioteca.
    _, bp = _montar(_jogo("a", 30), _jogo("z", 50, removed=True, status="beaten"))
    assert _ids(bp) == ["a"]


def test_bloqueado_nao_entra(app_qt, tiques):
    _, bp = _montar(_jogo("a", 30), _jogo("x", 50, blacklisted=True))
    assert _ids(bp) == ["a"]


def test_mover_nao_notifica_a_lista(tres):
    modelo, bp = tres
    lista, geral = [], []
    bp.jogosMudaram.connect(lambda: lista.append(1))
    bp.alterado.connect(lambda: geral.append(1))
    assert bp.mover(1)
    assert lista == [] and geral == [1]
    bp.atualizar()
    assert lista == [1]
    modelo.soltar_copia("a")  # sem cópia animada: nada muda
    assert lista == [1]


def test_central_que_some_cai_no_vizinho(tres):
    modelo, bp = tres
    assert bp.irPara(1)
    modelo.retirar("b")
    _esperar()
    assert _ids(bp) == ["a", "c"]
    assert (bp.indice, bp.nome) == (1, "C")
    modelo.retirar("c")
    _esperar()
    assert (bp.indice, bp.nome) == (0, "A")
    modelo.retirar("a")
    _esperar()
    assert (bp.jogos, bp.indice, bp.nome, bp.vazia) == ([], 0, "", True)


def test_central_que_continua_la_mantem_o_centro(tres):
    modelo, bp = tres
    bp.irPara(1)
    modelo.atualizar(_jogo("n", 99))  # entra na frente
    _esperar()
    assert _ids(bp) == ["n", "a", "b", "c"]
    assert (bp.indice, bp.nome) == (2, "B")


def test_atualizar_com_centro_explicito(tres):
    _, bp = tres
    bp.atualizar("c")
    assert (bp.indice, bp.nome) == (2, "C")
    bp.atualizar("fantasma")  # desconhecido: fica no índice preso
    assert bp.indice == 2
    bp.atualizar()
    assert bp.indice == 2


def test_rotulos_seguem_o_central(app_qt, tiques):
    _, bp = _montar(_jogo("a", 30, developer="Estúdio A"), _jogo("b", 20))
    assert (bp.nome, bp.desenvolvedora) == ("A", "Estúdio A")
    bp.mover(1)
    assert (bp.nome, bp.desenvolvedora) == ("B", "")


def test_vazia_sem_jogos(app_qt, tiques):
    _, bp = _montar()
    assert (bp.vazia, bp.nome, bp.desenvolvedora, bp.jogos, bp.indice) == (True, "", "", [], 0)
    assert not (bp.mover(1) or bp.irPara(3) or bp.inicio() or bp.fim())


def test_mover_toca_o_tique_e_preso_nas_pontas(tres, tiques):
    _, bp = tres
    avisos = []
    bp.alterado.connect(lambda: avisos.append(1))
    assert not bp.mover(-1) and tiques == []
    assert bp.mover(1) and bp.indice == 1 and len(tiques) == 1 and avisos
    assert bp.mover(10) and bp.indice == 2
    assert not bp.mover(1)
    assert bp.inicio() and bp.indice == 0
    assert not bp.inicio()
    assert bp.fim() and bp.indice == 2
    assert bp.irPara(1) and bp.indice == 1
    assert not bp.irPara(1)
    assert len(tiques) == 5


def test_mudancas_da_biblioteca_viram_um_atualizar_por_ciclo(tres, monkeypatch):
    modelo, bp = tres
    chamadas = []
    original = bp.atualizar
    monkeypatch.setattr(bp, "atualizar", lambda *a: chamadas.append(1) or original(*a))
    modelo.atualizar(_jogo("x", 40))
    modelo.atualizar(_jogo("y", 50))
    modelo.retirar("c")
    modelo.atualizar(_jogo("a", 30, name="Outro nome"))  # dataChanged de nome
    assert chamadas == []
    _esperar()
    assert chamadas == [1]
    assert _ids(bp) == ["y", "x", "a", "b"]
    assert bp.jogos[2]["nome"] == "Outro nome"


def test_jogado_em_novo_reordena(tres):
    modelo, bp = tres
    modelo.atualizar(_jogo("c", 99))
    _esperar()
    assert _ids(bp) == ["c", "a", "b"]


def test_soltar_copia_esvazia_a_capa_animada_na_hora(app_qt, tiques):
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", 30))
    # shortcut: a cópia animada entra na linha à força; a real exige arquivo animado e a fila de cópias.
    modelo._linhas[0] = replace(modelo._linhas[0], capa_animada="file:///copia.webp")  # noqa: SLF001
    bp = BigPicture(modelo)
    bp.entrar()
    bp.filaTerminou()
    assert bp.jogos[0]["capaAnimada"] == "file:///copia.webp"
    avisos = []
    bp.jogosMudaram.connect(lambda: avisos.append(1))
    modelo.soltar_copia("a")
    assert bp.jogos[0]["capaAnimada"] == ""  # sem esperar o ciclo
    assert avisos == [1]


# --- fundo ---------------------------------------------------------------------------------------


def test_provedor_do_fundo_tamanho_e_falha(app_qt, monkeypatch):
    provedor = ProvedorDoFundo()
    tamanho = QSize()
    imagem = provedor.requestImage("64x32", tamanho, QSize())
    assert (imagem.width(), imagem.height()) == (64, 32)
    assert (tamanho.width(), tamanho.height()) == (64, 32)
    assert imagem.format() == QImage.Format.Format_RGB888
    assert imagem.pixelColor(0, 0).red() in (27, 28, 29)

    def quebra(_l, _a):
        raise MemoryError

    monkeypatch.setattr(modulo.regras, "bytes_do_fundo", quebra)
    imagem = provedor.requestImage("64x32", QSize(), QSize())
    assert (imagem.width(), imagem.height()) == (1, 1)
    assert imagem.pixelColor(0, 0).red() == 0
    assert provedor.requestImage("lixo", QSize(), QSize()).width() == 1


# --- entrar e sair --------------------------------------------------------------------------------


class _JanelaFalsa(QObject):
    """Registra as trocas de tela cheia; `rendererInterface` devolve o gráfico pedido."""

    sceneGraphInitialized = Signal()  # noqa: N815

    def __init__(self, maximizada=False, api=QSGRendererInterface.GraphicsApi.Direct3D11):
        super().__init__()
        self.chamadas = []
        self.maximizada = maximizada
        self.api = api

    def visibility(self):
        return QWindow.Visibility.Maximized if self.maximizada else QWindow.Visibility.Windowed

    def showFullScreen(self):  # noqa: N802
        self.chamadas.append("tela cheia")

    def showMaximized(self):  # noqa: N802
        self.chamadas.append("maximizada")

    def showNormal(self):  # noqa: N802
        self.chamadas.append("normal")

    def rendererInterface(self):  # noqa: N802
        api = self.api
        return None if api is None else type("Renderizador", (), {"graphicsApi": lambda _s: api})()


def _com_janela(*jogos, **kw):
    modelo = ModeloDaBiblioteca()
    for jogo in jogos:
        modelo.atualizar(jogo)
    bp = BigPicture(modelo)
    janela = _JanelaFalsa(**kw)
    bp.definir_janela(janela)
    pedidos = []
    bp.filaPedida.connect(pedidos.append)
    return modelo, bp, janela, pedidos


@pytest.fixture
def aberta(app_qt, tiques):
    return _com_janela(_jogo("a", 30), _jogo("b", 20), _jogo("c", 10))


def test_entrar_mostra_e_pede_tela_cheia(aberta):
    _, bp, janela, pedidos = aberta
    assert (bp.visivel, bp.ocupada) == (False, False)
    bp.entrar()
    assert (bp.visivel, bp.ocupada) == (True, True)
    assert janela.chamadas == ["tela cheia"]
    assert pedidos == [True]


def test_entrar_poe_o_ultimo_jogado_no_centro(aberta):
    _, bp, _, _ = aberta
    bp.atualizar("c")  # invisível: não vale
    bp.entrar()
    assert (bp.indice, bp.nome) == (0, "A")
    bp.filaTerminou()
    bp.irPara(2)
    bp.sair()
    bp.filaTerminou()
    bp.entrar()  # entra de novo: volta ao primeiro, não ao que estava
    assert bp.indice == 0


def test_sair_faz_a_fila_e_depois_desmostra(aberta):
    _, bp, janela, pedidos = aberta
    bp.entrar()
    bp.filaTerminou()
    saidas = []
    bp.saiu.connect(saidas.append)
    bp.irPara(1)
    assert bp.jaSaiu is False
    bp.sair()
    assert pedidos == [True, False]
    assert (bp.visivel, bp.ocupada) == (True, True)  # a fila de saída ainda corre
    assert janela.chamadas == ["tela cheia"]
    bp.filaTerminou()
    assert (bp.visivel, bp.ocupada, bp.jaSaiu) == (False, False, True)
    assert janela.chamadas[-1] == "normal"
    assert saidas == ["b"]  # o foco volta ao cartão do jogo central


def test_maximizada_volta_maximizada(app_qt, tiques):
    _, bp, janela, _ = _com_janela(_jogo("a", 30), maximizada=True)
    bp.entrar()
    bp.filaTerminou()
    bp.sair()
    bp.filaTerminou()
    assert janela.chamadas == ["tela cheia", "maximizada"]


def test_nao_maximizada_volta_normal(aberta):
    _, bp, janela, _ = aberta
    bp.entrar()
    bp.filaTerminou()
    bp.sair()
    bp.filaTerminou()
    assert janela.chamadas == ["tela cheia", "normal"]


def test_entrada_ignorada_enquanto_ocupada(aberta):
    _, bp, janela, pedidos = aberta
    bp.entrar()
    bp.entrar()  # visível e ocupada
    bp.sair()  # ocupada: não sai no meio da fila
    assert (janela.chamadas, pedidos, bp.visivel) == (["tela cheia"], [True], True)
    bp.filaTerminou()
    bp.entrar()  # visível
    assert pedidos == [True]
    bp.sair()
    bp.sair()  # ocupada pela saída
    assert pedidos == [True, False]


def test_sair_invisivel_nao_faz_nada(aberta):
    _, bp, janela, pedidos = aberta
    bp.sair()
    assert (janela.chamadas, pedidos, bp.jaSaiu) == ([], [], False)


def test_saida_parte_da_capa_atual(aberta):
    # A fila de saída não mexe no índice: o QML parte da posição visual do carrossel.
    _, bp, _, pedidos = aberta
    bp.entrar()
    bp.filaTerminou()
    bp.irPara(2)
    bp.sair()
    assert (bp.indice, pedidos[-1]) == (2, False)
    assert not bp.mover(-1)  # ocupada: o carrossel fica parado


def test_atualizar_durante_a_fila_fica_pendente(aberta):
    modelo, bp, _, _ = aberta
    bp.entrar()
    modelo.atualizar(_jogo("n", 99))  # entra na frente durante a fila
    _esperar()
    assert _ids(bp) == ["a", "b", "c"]  # nada mudou ainda
    assert bp.ocupada
    bp.filaTerminou()
    assert _ids(bp) == ["n", "a", "b", "c"]
    assert (bp.indice, bp.nome) == (1, "A")  # manteve o central


def test_atualizar_pendente_guarda_o_ultimo_centro(aberta):
    _, bp, _, _ = aberta
    bp.entrar()
    bp.atualizar("b")
    bp.atualizar("c")
    assert bp.indice == 0
    bp.filaTerminou()
    assert (bp.indice, bp.nome) == (2, "C")


def test_atualizar_pendente_some_se_saiu(aberta):
    modelo, bp, _, _ = aberta
    bp.entrar()
    bp.atualizar("c")  # pendente da fila de entrada
    bp.filaTerminou()
    assert bp.indice == 2
    bp.sair()  # saída em curso: atualizar não vale
    bp.atualizar("a")
    modelo.atualizar(_jogo("n", 99))
    _esperar()
    assert (_ids(bp), bp.indice) == (["a", "b", "c"], 2)
    bp.filaTerminou()
    assert _ids(bp) == []  # a saída esvazia a lista
    bp.entrar()  # o pendente não sobrevive: a entrada refaz a lista do zero
    assert (_ids(bp), bp.indice) == (["n", "a", "b", "c"], 0)
    bp.filaTerminou()
    assert bp.indice == 0


def test_atualizar_invisivel_nao_faz_nada(aberta):
    modelo, bp, _, _ = aberta
    modelo.atualizar(_jogo("n", 99))
    _esperar()
    bp.atualizar()
    assert _ids(bp) == []
    bp.entrar()  # a lista é refeita na entrada
    assert _ids(bp) == ["n", "a", "b", "c"]


def test_biblioteca_vazia_entra_sem_fila(app_qt, tiques):
    _, bp, janela, pedidos = _com_janela()
    bp.entrar()
    assert (bp.visivel, bp.ocupada, bp.vazia, pedidos) == (True, False, True, [])
    assert janela.chamadas == ["tela cheia"]
    bp.sair()  # sem fila: sai na hora
    assert (bp.visivel, bp.ocupada, bp.jaSaiu, pedidos) == (False, False, True, [])
    assert janela.chamadas == ["tela cheia", "normal"]


def test_sem_3d_indisponivel_e_nao_entra(app_qt, tiques):
    _, bp, janela, pedidos = _com_janela(_jogo("a", 30), api=QSGRendererInterface.GraphicsApi.Software)
    assert bp.disponivel is False
    bp.entrar()
    assert (bp.visivel, janela.chamadas, pedidos) == (False, [], [])


def test_renderizador_tardio_confere_ao_inicializar(app_qt, tiques):
    _, bp, _, _ = _com_janela(_jogo("a", 30))
    assert bp.disponivel is True
    # Sem renderizador ainda (antes do primeiro quadro): segue disponível; ao inicializar, confere.
    bp = BigPicture(ModeloDaBiblioteca())
    tardia = _JanelaFalsa(api=None)
    bp.definir_janela(tardia)
    assert bp.disponivel is True
    tardia.api = QSGRendererInterface.GraphicsApi.Software
    tardia.sceneGraphInitialized.emit()
    _esperar()
    assert bp.disponivel is False


def test_tem_3d_pela_api_grafica(app_qt):
    assert modulo.tem_3d(_JanelaFalsa()) is True
    assert modulo.tem_3d(_JanelaFalsa(api=QSGRendererInterface.GraphicsApi.Software)) is False
    assert modulo.tem_3d(_JanelaFalsa(api=None)) is False


def test_animacao_de_entrada_nao_toca(aberta, tiques):
    _, bp, _, _ = aberta
    bp.entrar()
    bp.filaTerminou()
    bp.sair()
    bp.filaTerminou()
    assert tiques == []


def test_lista_vazia_ate_entrar(app_qt):
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", 30))
    bp = BigPicture(modelo)
    assert bp.jogos == [] and bp.vazia is True  # a camada escondida não decodifica capas (D39)
    bp.entrar()
    assert _ids(bp) == ["a"]


def test_sair_esvazia_a_lista(tres):
    _, bp = tres
    saidos = []
    bp.saiu.connect(saidos.append)
    bp.sair()
    bp.filaTerminou()
    assert saidos == ["a"]  # o jogo central ainda é lido antes de esvaziar
    assert bp.jogos == [] and bp.vazia is True


def test_fila_do_qml_usa_a_constante_das_regras(app_qt):
    assert BigPicture(ModeloDaBiblioteca()).jogosNaFila == regras.JOGOS_NA_FILA
