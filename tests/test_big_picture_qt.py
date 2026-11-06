# test_big_picture_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A lista do Big Picture sobre o `ModeloDaBiblioteca`: centro, rótulos, tique e fundo."""

import sys
from dataclasses import replace
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEasingCurve, QEventLoop, QObject, QSize, QTimer, Signal
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
    activeChanged = Signal()  # noqa: N815

    def __init__(self, maximizada=False, api=QSGRendererInterface.GraphicsApi.Direct3D11, hwnd=0):
        super().__init__()
        self.minimizada = False
        self.chamadas = []
        self._ativa = True
        self.maximizada = maximizada
        self.api = api
        self.hwnd = hwnd  # 0: sem HWND, a troca é direta (sem fade)

    def winId(self):  # noqa: N802
        return self.hwnd

    def isActive(self):  # noqa: N802
        return self._ativa

    def ativar(self, ativa):
        self._ativa = ativa
        self.activeChanged.emit()

    def visibility(self):
        if self.minimizada:
            return QWindow.Visibility.Minimized
        return QWindow.Visibility.Maximized if self.maximizada else QWindow.Visibility.Windowed

    def showFullScreen(self):  # noqa: N802
        self.minimizada = False
        self.chamadas.append("tela cheia")

    def showMaximized(self):  # noqa: N802
        self.chamadas.append("maximizada")

    def showNormal(self):  # noqa: N802
        self.minimizada = False
        self.chamadas.append("normal")

    def rendererInterface(self):  # noqa: N802
        api = self.api
        return None if api is None else type("Renderizador", (), {"graphicsApi": lambda _s: api})()


def _com_janela(*jogos, detalhes=None, **kw):
    modelo = ModeloDaBiblioteca()
    for jogo in jogos:
        modelo.atualizar(jogo)
    bp = BigPicture(modelo, detalhes=detalhes)
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
    assert bp.jogos == [] and bp.vazia is True  # a camada escondida não decodifica capas
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


# --- fade do monitor (cortina) --------------------------------------------------------------------


class _CortinaFalsa:
    """Registra a sequência do fade numa lista compartilhada; nenhuma janela Win32 de verdade."""

    registro: list = []
    falha = False

    def __init__(self, hwnd):
        if _CortinaFalsa.falha:
            raise OSError("sem cortina")
        _CortinaFalsa.registro.append(f"abriu {hwnd}")

    def alfa(self, valor):
        texto = f"alfa {round(valor)}"
        if _CortinaFalsa.registro[-1:] != [texto]:  # os quadros do meio não importam aqui
            _CortinaFalsa.registro.append(texto)

    def fechar(self):
        _CortinaFalsa.registro.append("fechou")


def _com_fade(*jogos, fabrica=_CortinaFalsa):
    modelo = ModeloDaBiblioteca()
    for jogo in jogos:
        modelo.atualizar(jogo)
    bp = BigPicture(modelo, fabrica_da_cortina=fabrica)
    janela = _JanelaFalsa(hwnd=42)
    bp.definir_janela(janela)
    pedidos = []
    bp.filaPedida.connect(pedidos.append)
    return SimpleNamespace(modelo=modelo, bp=bp, janela=janela, pedidos=pedidos, registro=_CortinaFalsa.registro)


@pytest.fixture
def fade(app_qt, tiques):
    """Três jogos, a cortina falsa e um HWND falso; animações e pausas disparadas à mão."""
    _CortinaFalsa.registro = []
    _CortinaFalsa.falha = False
    f = _com_fade(_jogo("a", 30), _jogo("b", 20), _jogo("c", 10))
    yield f
    f.bp.encerrar()


def _animacao(bp):
    animacao = bp._animacao_cortina  # noqa: SLF001
    assert animacao is not None, "sem animação da cortina"
    return animacao


def concluir_cortina(bp, ms=None):
    animacao = _animacao(bp)
    if ms is not None:
        assert animacao.duration() == ms
    assert animacao.easingCurve().type() == QEasingCurve.Type.InOutCubic
    animacao.setCurrentTime(animacao.duration())  # chega ao fim: `finished`


def concluir_pausa(bp):
    pausa = bp._pausa  # noqa: SLF001
    assert pausa.isActive() and pausa.interval() == 120
    pausa.stop()
    pausa.timeout.emit()


def _erros_do_laco(monkeypatch):
    """A exceção de um slot chamado pelo Qt (o fim da animação) chega ao `sys.excepthook`, não a quem chamou."""
    erros = []
    monkeypatch.setattr(sys, "excepthook", lambda tipo, *_: erros.append(tipo))
    return erros


def _entrar_inteiro(f):
    f.bp.entrar()
    f.bp.capasProntas()
    concluir_cortina(f.bp)
    concluir_pausa(f.bp)
    concluir_cortina(f.bp)
    f.bp.filaTerminou()


def test_entrar_escurece_troca_e_clareia(fade):
    bp = fade.bp
    bp.entrar()
    assert fade.registro == ["abriu 42", "alfa 0"] and bp.ocupada
    assert not bp.visivel and fade.janela.chamadas == []
    bp.capasProntas()
    concluir_cortina(bp, 300)
    assert bp.visivel and fade.registro[-1] == "alfa 1" and fade.janela.chamadas == ["tela cheia"]
    assert fade.pedidos == [True]  # a fila corre no escuro e enquanto clareia
    concluir_pausa(bp)
    concluir_cortina(bp, 350)
    assert fade.registro[-2:] == ["alfa 0", "fechou"] and bp._cortina is None  # noqa: SLF001
    assert bp.ocupada  # a fila ainda corre
    bp.filaTerminou()
    assert not bp.ocupada


def test_entrar_fica_ocupada_ate_o_fim_do_fade_sem_fila(app_qt, tiques):
    _CortinaFalsa.registro = []
    f = _com_fade()
    f.bp.entrar()
    concluir_cortina(f.bp)  # sem jogos: nada a esperar
    assert f.bp.ocupada and f.bp.visivel
    concluir_pausa(f.bp)
    concluir_cortina(f.bp)
    assert not f.bp.ocupada and f.pedidos == []


def test_entrar_com_a_pagina_visivel_nao_faz_nada(fade):
    _entrar_inteiro(fade)
    antes = list(fade.registro)
    fade.bp.entrar()
    assert fade.registro == antes and fade.janela.chamadas == ["tela cheia"]


def test_sair_faz_a_fila_e_depois_o_fade(fade):
    bp = fade.bp
    _entrar_inteiro(fade)
    fade.registro.clear()
    saidas = []
    bp.saiu.connect(saidas.append)
    bp.sair()
    assert fade.registro == [] and bp.ocupada and fade.pedidos[-1] is False  # primeiro a fila
    bp.filaTerminou()
    assert fade.registro == ["abriu 42", "alfa 0"] and bp.visivel  # escurecendo: o QML só repõe o quadro ao esconder
    assert bp.ocupada and not bp.mover(1)
    concluir_cortina(bp, 250)  # a saída não espera capas
    assert not bp.visivel and fade.janela.chamadas[-1] == "normal" and bp.ocupada
    assert saidas == ["a"] and bp.jogos == []
    concluir_pausa(bp)
    concluir_cortina(bp, 350)
    assert fade.registro[-1] == "fechou" and not bp.ocupada and bp.jaSaiu


def test_sem_hwnd_troca_sem_fade(fade):
    fade.janela.hwnd = 0
    fade.bp.entrar()
    assert fade.bp.visivel and fade.registro == []
    fade.bp.filaTerminou()
    fade.bp.sair()
    fade.bp.filaTerminou()
    assert not fade.bp.visivel and not fade.bp.ocupada and fade.registro == []


def test_cortina_que_falha_troca_sem_fade(fade):
    _CortinaFalsa.falha = True
    fade.bp.entrar()
    assert fade.bp.visivel and fade.bp._cortina is None  # noqa: SLF001
    fade.bp.filaTerminou()
    fade.bp.sair()
    fade.bp.filaTerminou()
    assert not fade.bp.visivel and not fade.bp.ocupada


def test_cortina_que_levanta_qualquer_erro_troca_sem_fade(app_qt, tiques):
    def explode(_hwnd):
        raise RuntimeError("x")

    f = _com_fade(_jogo("a", 30), fabrica=explode)
    f.bp.entrar()
    assert f.bp.visivel and f.pedidos == [True]


def test_entrar_durante_a_pausa_da_saida_nao_cria_outra_cortina(fade):
    bp = fade.bp
    _entrar_inteiro(fade)
    bp.sair()
    bp.filaTerminou()
    concluir_cortina(bp)
    assert bp._pausa.isActive()  # noqa: SLF001  # na pausa de 120 ms, já fora do Big Picture
    abertas = fade.registro.count("abriu 42")
    bp.entrar()
    assert fade.registro.count("abriu 42") == abertas and not bp.visivel
    concluir_pausa(bp)
    concluir_cortina(bp)
    assert fade.registro[-1] == "fechou" and not bp.ocupada


def test_entrar_duas_vezes_no_escurecimento_cria_uma_cortina(fade):
    fade.bp.entrar()
    fade.bp.entrar()
    assert fade.registro.count("abriu 42") == 1


def test_nova_sequencia_fecha_a_cortina_anterior(fade):
    fade.bp.entrar()
    fade.bp._trocar_no_escuro(lambda: None, 100, None)  # noqa: SLF001
    assert fade.registro.count("fechou") == 1 and fade.registro.count("abriu 42") == 2


def test_sair_repoe_o_quadro_mesmo_se_a_troca_falhar(fade, monkeypatch):
    # O QML repõe o quadro quando a camada some: a troca que falha ainda esconde o Big Picture.
    bp = fade.bp
    _entrar_inteiro(fade)
    bp.sair()
    bp.filaTerminou()

    def quebra():
        raise RuntimeError("x")

    monkeypatch.setattr(fade.janela, "showNormal", quebra)
    erros = _erros_do_laco(monkeypatch)
    concluir_cortina(bp)
    assert erros == [RuntimeError]  # propagada até o laço de eventos (o log de exceções do app)
    assert not bp.visivel and bp.jogos == [] and bp.jaSaiu


def test_sair_emite_saiu_mesmo_se_a_troca_falhar(fade, monkeypatch):
    # O foco volta à grade mesmo com a janela falhando ao sair da tela cheia.
    bp = fade.bp
    _entrar_inteiro(fade)
    emitidos = []
    bp.saiu.connect(emitidos.append)
    bp.sair()
    bp.filaTerminou()

    def quebra():
        raise RuntimeError("x")

    monkeypatch.setattr(fade.janela, "showNormal", quebra)
    monkeypatch.setattr(fade.janela, "showMaximized", quebra)
    erros = _erros_do_laco(monkeypatch)
    concluir_cortina(bp)
    assert erros == [RuntimeError] and len(emitidos) == 1


def test_encerrar_no_meio_do_fade_fecha_a_cortina(fade):
    bp = fade.bp
    bp.entrar()
    bp.encerrar()  # escurecendo
    assert fade.registro[-1] == "fechou" and bp._cortina is None and bp._animacao_cortina is None  # noqa: SLF001
    bp2 = _com_fade(_jogo("a", 30)).bp
    bp2.entrar()
    concluir_cortina(bp2)  # escuro, esperando as capas
    assert bp2._espera_das_capas.isActive()  # noqa: SLF001
    bp2.encerrar()
    assert fade.registro[-1] == "fechou" and not bp2._espera_das_capas.isActive()  # noqa: SLF001
    bp2.capasProntas()  # a resposta tardia do QML não troca nada
    assert not bp2.visivel
    bp3 = _com_fade(_jogo("a", 30)).bp
    bp3.entrar()
    bp3.capasProntas()
    concluir_cortina(bp3)
    assert bp3._pausa.isActive()  # noqa: SLF001  # na pausa
    bp3.encerrar()
    assert fade.registro[-1] == "fechou" and not bp3._pausa.isActive()  # noqa: SLF001
    assert fade.registro.count("abriu 42") == fade.registro.count("fechou") == 3


def test_troca_que_levanta_fecha_a_cortina_e_destrava(fade, monkeypatch):
    bp = fade.bp

    def quebra():
        raise RuntimeError("x")

    monkeypatch.setattr(fade.janela, "showFullScreen", quebra)
    bp.entrar()
    bp.capasProntas()
    erros = _erros_do_laco(monkeypatch)
    concluir_cortina(bp)
    assert erros == [RuntimeError]
    assert fade.registro[-1] == "fechou" and bp._cortina is None  # noqa: SLF001
    assert not bp.ocupada and not bp._em_fade  # noqa: SLF001
    assert not bp._pausa.isActive()  # noqa: SLF001
    bp.sair()  # destravada: a saída anda
    bp.filaTerminou()
    concluir_cortina(bp)
    concluir_pausa(bp)
    concluir_cortina(bp)
    assert not bp.visivel and not bp.ocupada


def test_troca_que_levanta_sem_cortina_destrava(fade):
    fade.janela.hwnd = 0
    depois = []

    def quebra():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        fade.bp._trocar_no_escuro(quebra, 300, lambda: depois.append(1))  # noqa: SLF001
    assert depois == [1]


def test_troca_espera_as_capas(fade):
    bp = fade.bp
    preparos = []
    bp.prepararCapas.connect(lambda: preparos.append(list(bp.jogos)))
    bp.entrar()
    assert [j["jogoId"] for j in preparos[0]] == ["a", "b", "c"]  # a lista já existe antes de escurecer
    concluir_cortina(bp)
    assert not bp.visivel and fade.registro[-1] == "alfa 1"  # escuro, esperando as capas
    espera = bp._espera_das_capas  # noqa: SLF001
    assert espera.isActive() and espera.interval() == modulo.ESPERA_MAXIMA_DAS_CAPAS_MS == 700
    bp.capasProntas()
    assert bp.visivel and not espera.isActive() and bp._pausa.isActive()  # noqa: SLF001


def test_troca_nao_espera_mais_que_o_limite(fade):
    bp = fade.bp
    bp.entrar()
    concluir_cortina(bp)
    espera = bp._espera_das_capas  # noqa: SLF001
    espera.stop()
    espera.timeout.emit()  # 700 ms sem resposta do QML
    assert bp.visivel and fade.pedidos == [True]
    bp.capasProntas()  # tardia: não troca de novo
    assert fade.janela.chamadas == ["tela cheia"]


def test_capas_prontas_antes_do_escuro_nao_atrasam(fade):
    bp = fade.bp
    bp.entrar()
    bp.capasProntas()  # o QML terminou durante o escurecimento
    concluir_cortina(bp)
    assert bp.visivel and not bp._espera_das_capas.isActive()  # noqa: SLF001


def test_sem_animacoes_do_sistema_o_fade_vai_direto_ao_fim(app_qt, tiques):
    _CortinaFalsa.registro = []
    bp = BigPicture(ModeloDaBiblioteca(), fabrica_da_cortina=_CortinaFalsa, animacoes_do_sistema=False)
    bp.definir_janela(_JanelaFalsa(hwnd=42))
    bp.entrar()  # sem jogos: nada a esperar
    assert bp.visivel and _CortinaFalsa.registro == ["abriu 42", "alfa 1"]
    concluir_pausa(bp)
    assert _CortinaFalsa.registro[-1] == "fechou" and not bp.ocupada


def test_mudanca_da_biblioteca_no_escuro_fica_pendente(fade):
    bp = fade.bp
    bp.entrar()
    fade.modelo.atualizar(_jogo("n", 99))
    _esperar()
    assert _ids(bp) == ["a", "b", "c"]  # a lista da entrada não muda no meio da troca
    bp.capasProntas()
    concluir_cortina(bp)
    concluir_pausa(bp)
    concluir_cortina(bp)
    bp.filaTerminou()
    assert _ids(bp) == ["n", "a", "b", "c"] and bp.nome == "A"


# --- abrir o jogo ---------------------------------------------------------------------------------


class _Launch:
    """O `launch` de mentira: nenhum jogo é iniciado. Como o de verdade, `last_played` sobe e o modelo é avisado."""

    def __init__(self, modelo, jogo, devolve=True, efeito=None):
        self.modelo, self.jogo, self.devolve, self.efeito = modelo, jogo, devolve, efeito
        self.chamadas = 0
        self.ao_confirmar = None

    def __call__(self, ao_confirmar=None, inis_conferidos=False, em_tela_cheia=False):
        self.chamadas += 1
        self.em_tela_cheia = em_tela_cheia
        self.inis_conferidos = inis_conferidos
        self.ao_confirmar = ao_confirmar
        if self.efeito is not None:
            self.efeito()
        if self.devolve:
            self.jogo.last_played = 99
            self.modelo.atualizar(self.jogo)
        return self.devolve


@pytest.fixture
def abrivel(app_qt, tiques, monkeypatch):
    """a, b e c com o Big Picture aberto e o `launch` falso; `shared.store` os acha pelo id."""
    jogos = {j.game_id: j for j in (_jogo("a", 30), _jogo("b", 20), _jogo("c", 10))}
    modelo, bp, janela, pedidos = _com_janela(*jogos.values(), detalhes=_DetalhesFalsos())
    monkeypatch.setattr(modulo.shared, "store", SimpleNamespace(get=jogos.get))
    for jogo in jogos.values():
        jogo.launch = _Launch(modelo, jogo)
    aberturas, focos = [], []
    bp.etapaPedida.connect(lambda de, para: aberturas.append((de, para)))
    bp.focoPedido.connect(lambda: focos.append(1))
    bp.entrar()
    bp.filaTerminou()
    bp.ativar()  # o jogo central, nos detalhes: de onde o Iniciar parte
    bp.etapaTerminou()
    aberturas.clear()
    return SimpleNamespace(jogos=jogos, modelo=modelo, bp=bp, janela=janela, aberturas=aberturas, focos=focos)


def _ida(a, jogo_id="b"):
    a.bp.atualizar(jogo_id)
    a.bp.abrirJogo()
    a.bp.etapaTerminou()


def test_abrir_jogo_pede_a_abertura_e_so_lanca_no_fim_dela(abrivel):
    a = abrivel
    a.bp.atualizar("b")
    a.bp.abrirJogo()
    assert a.bp.ocupada and a.aberturas == [("detalhes", "sessao")]
    assert a.jogos["b"].launch.chamadas == 0 and a.janela.chamadas == ["tela cheia"]
    a.bp.etapaTerminou()
    assert a.jogos["b"].launch.chamadas == 1
    assert a.janela.chamadas == ["tela cheia"]


def test_abertura_nao_sai_da_tela_cheia(abrivel):
    a = abrivel
    a.bp.atualizar("b")
    a.bp.abrirJogo()
    a.bp.etapaTerminou()
    assert a.janela.chamadas.count("normal") == 0
    assert a.jogos["b"].launch.em_tela_cheia is True


def test_dois_a_seguidos_abrem_o_jogo_uma_vez(abrivel):
    a = abrivel
    a.bp.atualizar("b")
    a.bp.abrirJogo()
    a.bp.abrirJogo()
    a.bp.etapaTerminou()
    a.bp.etapaTerminou()  # o fim da volta (ou um segundo aviso) não lança de novo
    assert a.jogos["b"].launch.chamadas == 1 and a.aberturas[0] == ("detalhes", "sessao")


def test_abrir_sem_jogos_nao_faz_nada(app_qt, tiques):
    _, bp, _, _ = _com_janela()
    avisos = []
    bp.etapaPedida.connect(lambda *_: avisos.append(1))
    bp.entrar()
    bp.abrirJogo()
    assert (bp.ocupada, avisos) == (False, [])


def test_launch_recusado_volta_ao_normal(abrivel):
    a = abrivel
    a.jogos["b"].launch.devolve = False
    _ida(a)
    assert a.aberturas == [("detalhes", "sessao"), ("sessao", "detalhes")] and a.bp.ocupada
    a.bp.etapaTerminou()
    assert not a.bp.ocupada and a.bp.etapa == "detalhes"
    assert a.janela.chamadas == ["tela cheia", "tela cheia"]
    assert a.bp.indice == 1


def test_confirmar_o_comando_abre_pelo_mesmo_caminho(abrivel):
    a = abrivel
    launch = a.jogos["b"].launch
    launch.devolve = False
    _ida(a)
    a.bp.etapaTerminou()  # a capa voltou aos detalhes
    confirmar, launch.devolve = launch.ao_confirmar, True  # o jogo restaurado teve o comando confirmado
    confirmar()
    assert a.bp.ocupada and a.aberturas[-1] == ("detalhes", "sessao")
    a.bp.etapaTerminou()
    assert launch.chamadas == 2


def test_conferencia_rapida_dos_inis_anima_uma_vez(abrivel):
    a = abrivel
    jogo = a.jogos["b"]
    launch = jogo.launch
    launch.devolve, launch.efeito = False, lambda: jogo.__dict__.update(_conferindo=True, _launch_iniciou=True)
    _ida(a)
    assert a.bp.ocupada and a.aberturas == [("detalhes", "sessao")]  # a capa fica aberta esperando a conferência
    launch.devolve, launch.efeito = True, None
    jogo._conferindo, jogo._inis_conferidos = False, True  # o fim da conferência relança
    launch.ao_confirmar()
    assert launch.chamadas == 2 and launch.inis_conferidos
    assert a.aberturas.count(("detalhes", "sessao")) == 1


def test_launch_ignorado_durante_outra_conferencia_nao_deixa_esperando(abrivel):
    """A conferência começou por outro clique: o launch da Big Picture é ignorado e a capa volta."""
    a = abrivel
    jogo = a.jogos["b"]
    launch = jogo.launch
    launch.devolve, launch.efeito = False, lambda: jogo.__dict__.update(_conferindo=True, _launch_iniciou=False)
    _ida(a)
    a.bp.etapaTerminou()
    assert not a.bp.ocupada and a.aberturas == [("detalhes", "sessao"), ("sessao", "detalhes")]


def test_conferencia_com_dialogo_devolve_a_capa(abrivel):
    a = abrivel
    jogo = a.jogos["b"]
    launch = jogo.launch
    launch.devolve, launch.efeito = False, lambda: jogo.__dict__.update(_conferindo=True, _launch_iniciou=True)
    _ida(a)
    jogo.procurando_inis.emit(lambda: None, lambda: None)
    a.bp.etapaTerminou()
    assert not a.bp.ocupada and a.aberturas == [("detalhes", "sessao"), ("sessao", "detalhes")]
    launch.devolve, launch.efeito = True, None
    jogo._inis_conferidos = True  # "Jogar mesmo assim"
    launch.ao_confirmar()
    jogo._inis_conferidos = False
    assert a.aberturas[-1] == ("detalhes", "sessao")
    a.bp.etapaTerminou()
    assert launch.chamadas == 2 and launch.inis_conferidos


def test_confirmar_depois_de_sair_nao_abre(abrivel):
    a = abrivel
    a.jogos["b"].launch.devolve = False
    _ida(a)
    confirmar = a.jogos["b"].launch.ao_confirmar
    a.bp.etapaTerminou()
    a.bp.sair()
    a.bp.filaTerminou()
    confirmar()
    assert not a.bp.ocupada and len(a.aberturas) == 2


def test_launch_que_levanta_volta_ao_normal_e_propaga(abrivel):
    a = abrivel

    def estoura():
        raise RuntimeError("falhou")

    a.jogos["b"].launch.efeito = estoura
    a.bp.atualizar("b")
    a.bp.abrirJogo()
    with pytest.raises(RuntimeError):
        a.bp.etapaTerminou()
    a.bp.etapaTerminou()
    assert not a.bp.ocupada and a.aberturas[-1] == ("sessao", "detalhes")
    assert a.janela.chamadas == ["tela cheia", "tela cheia"]


def test_jogo_que_sumiu_da_loja_volta_ao_normal(abrivel, monkeypatch):
    a = abrivel
    a.bp.abrirJogo()
    monkeypatch.setattr(modulo.shared, "store", SimpleNamespace(get=lambda _id: None))
    a.bp.etapaTerminou()
    a.bp.etapaTerminou()
    assert not a.bp.ocupada and a.janela.chamadas[-1] == "tela cheia"


def test_sem_sessao_volta_sozinho(abrivel, schema):
    a = abrivel
    schema.set_boolean("minimize-after-launch", False)
    _ida(a)
    a.bp.etapaTerminou()
    assert not a.bp.ocupada and a.janela.chamadas.count("tela cheia") == 1
    assert a.aberturas == [("detalhes", "sessao"), ("sessao", "detalhes")] and a.focos == [1]


def test_sem_sessao_sem_minimizar_poe_tela_cheia_na_hora(abrivel, schema):
    a = abrivel
    schema.set_boolean("minimize-after-launch", False)
    _ida(a)
    assert a.janela.chamadas == ["tela cheia"]










def test_maximizada_so_volta_maximizada_na_saida_do_big_picture(app_qt, tiques, monkeypatch):
    jogos = {"a": _jogo("a", 30)}
    modelo, bp, janela, _ = _com_janela(*jogos.values(), maximizada=True)
    monkeypatch.setattr(modulo.shared, "store", SimpleNamespace(get=jogos.get))
    jogos["a"].launch = _Launch(modelo, jogos["a"])
    bp.entrar()
    bp.filaTerminou()
    janela.maximizada = False  # em tela cheia a janela não conta como maximizada
    bp.abrirJogo()
    bp.etapaTerminou()
    bp.sair()
    bp.filaTerminou()
    # Abrir o jogo não mexe na janela; a maximização volta só na saída.
    assert janela.chamadas.count("maximizada") == 1 and "normal" not in janela.chamadas


def test_voltou_do_jogo_sem_estar_ocupada_nao_faz_nada(abrivel):
    a = abrivel
    a.bp.voltouDoJogo()
    assert a.janela.chamadas == ["tela cheia"] and a.aberturas == [] and a.focos == []


def test_voltou_do_jogo_com_a_janela_minimizada_restaura_antes_da_tela_cheia(abrivel):
    # O "Jogar" minimiza a janela e, sem restaurá-la antes, o Windows a devolvia em modo janela com o Big Picture aberto.
    a = abrivel
    a.bp.abrirJogo()
    a.janela.minimizada = True
    a.janela.chamadas.clear()
    a.bp.voltouDoJogo()
    assert a.janela.chamadas == ["normal", "tela cheia"]


def test_voltou_do_jogo_reabre_com_o_jogo_no_centro(abrivel):
    a = abrivel
    a.bp.atualizar("b")
    a.bp.abrirJogo()  # ocupada, como com uma sessão em curso
    a.bp.voltouDoJogo()
    a.bp.etapaTerminou()
    assert not a.bp.ocupada and a.aberturas[-1] == ("sessao", "carrossel")
    assert a.janela.chamadas[-1] == "tela cheia" and a.focos == [1]
    assert (a.bp.indice, a.bp.nome) == (1, "B")


def test_abrir_volta_com_o_jogo_aberto_no_centro(abrivel, schema):
    # O `launch` falso muda `last_played`: o jogo aberto passa ao índice 0 e fica no centro.
    a = abrivel
    schema.set_boolean("minimize-after-launch", False)
    _ida(a, "c")
    a.bp.etapaTerminou()
    assert _ids(a.bp)[0] == "c" and (a.bp.indice, a.bp.nome) == (0, "C")


def test_lista_refeita_durante_a_abertura_fica_para_a_volta(abrivel):
    a = abrivel
    a.bp.atualizar("b")
    a.bp.abrirJogo()
    a.modelo.atualizar(_jogo("n", 99))
    _esperar()
    assert _ids(a.bp) == ["a", "b", "c"]  # ocupada: pendente
    a.bp.voltouDoJogo()
    a.bp.etapaTerminou()
    assert _ids(a.bp) == ["n", "a", "b", "c"] and a.bp.nome == "B"


# --- a sessão de jogo ---------------------------------------------------


@pytest.fixture
def com_sessao(abrivel, monkeypatch, schema):
    """O `abrivel` com o `ModeloDaSessao` de verdade: o `launch` falso começa o rastreio por processo."""
    from cartridges.modelos.avisos import FilaDeAvisos  # noqa: PLC0415
    from cartridges.modelos.sessao import ModeloDaSessao  # noqa: PLC0415
    from cartridges.process_session import ProcessSession  # noqa: PLC0415

    a = abrivel
    a.sessao = ModeloDaSessao(FilaDeAvisos(), big_picture=a.bp)
    monkeypatch.setattr(modulo.shared, "sessao", a.sessao, raising=False)
    schema.set_boolean("minimize-after-launch", False)
    for jogo in a.jogos.values():
        jogo.executable, jogo.track_process, jogo.process_executable = r'start "" "D:\Jogos\x.exe"', False, ""
        jogo.launch.efeito = lambda jogo=jogo: ProcessSession(jogo).start()
    yield a
    a.sessao.encerrar()


def test_abrir_com_sessao_espera_o_fim(com_sessao):
    a = com_sessao
    _ida(a)
    assert a.sessao.emAndamento and a.bp.ocupada
    assert a.aberturas == [("detalhes", "sessao")] and a.focos == []
    assert a.janela.chamadas == ["tela cheia"]


def test_fim_da_sessao_reabre_com_o_jogo_no_centro(com_sessao):
    a = com_sessao
    _ida(a, "c")
    a.sessao.terminar()
    a.bp.etapaTerminou()
    assert not a.sessao.emAndamento and not a.bp.ocupada
    assert a.aberturas == [("detalhes", "sessao"), ("sessao", "carrossel")] and a.focos == [1]
    assert a.janela.chamadas == ["tela cheia", "tela cheia"]
    assert (a.bp.indice, a.bp.nome) == (0, "C")  # o jogado agora vem à frente e fica no centro


def test_fim_da_sessao_com_queda_para_a_manual_reabre_o_big_picture(com_sessao):
    from cartridges.process_session import ProcessSession  # noqa: PLC0415
    from cartridges.session_window import SessionWindow  # noqa: PLC0415

    a = com_sessao
    _ida(a)
    ProcessSession.active.stop(record=False, fall_back=True)  # o jogo nunca apareceu: passa à janela manual
    assert a.sessao.emAndamento and a.bp.ocupada and a.aberturas == [("detalhes", "sessao")], "a queda não reabre"
    SessionWindow.active.close()
    a.bp.etapaTerminou()
    assert not a.bp.ocupada and a.aberturas == [("detalhes", "sessao"), ("sessao", "carrossel")] and a.focos == [1]
    assert a.janela.chamadas.count("tela cheia") == 2  # a entrada e uma volta só
    a.sessao.hide_session_blocker()  # um fim repetido não reabre de novo
    assert len(a.aberturas) == 2 and a.janela.chamadas.count("tela cheia") == 2


@pytest.mark.parametrize("visivel", [False, True])
def test_fim_da_sessao_com_o_big_picture_escondido_nao_chama(app_qt, visivel):
    from cartridges.modelos.avisos import FilaDeAvisos  # noqa: PLC0415
    from cartridges.modelos.sessao import ModeloDaSessao  # noqa: PLC0415

    chamadas = []
    bp = SimpleNamespace(visivel=visivel, voltouDoJogo=lambda: chamadas.append(1))
    ModeloDaSessao(FilaDeAvisos(), big_picture=bp).hide_session_blocker()
    assert chamadas == ([1] if visivel else [])


def test_fim_da_sessao_no_meio_de_um_fade_nao_cria_outra_cortina(fade):
    from cartridges.modelos.avisos import FilaDeAvisos  # noqa: PLC0415
    from cartridges.modelos.sessao import ModeloDaSessao  # noqa: PLC0415

    bp = fade.bp
    aberturas = []
    bp.etapaPedida.connect(lambda de, para: aberturas.append((de, para)))
    bp.entrar()
    bp.capasProntas()
    concluir_cortina(bp)  # no escuro, já trocada: visível, ocupada e com a pausa correndo
    assert bp.visivel and bp.ocupada
    registro, chamadas = list(fade.registro), list(fade.janela.chamadas)

    ModeloDaSessao(FilaDeAvisos(), big_picture=bp).hide_session_blocker()

    assert fade.registro == registro and fade.janela.chamadas == chamadas and aberturas == []
    concluir_pausa(bp)  # a sequência em curso segue até o fim, com o próprio `depois`
    concluir_cortina(bp)
    bp.filaTerminou()
    assert not bp.ocupada and fade.registro.count("abriu 42") == 1 and fade.registro[-1] == "fechou"


# --- as etapas: carrossel, detalhes e sessão ------------------------------------------------------


class _DetalhesFalsos(QObject):
    """Grava as chamadas a `mostrar` e `esquecer`; `sair` é o sinal do jogo excluído."""

    sair = Signal()

    def __init__(self):
        super().__init__()
        self.mostrados, self.esquecidos, self.aceita = [], 0, True

    def mostrar(self, jogo_id):
        self.mostrados.append(jogo_id)
        return self.aceita

    def esquecer(self):
        self.esquecidos += 1


@pytest.fixture
def etapas(app_qt, tiques, monkeypatch):
    """a, b e c com o Big Picture aberto (carrossel), `detalhes` e `launch` falsos e uma sessão falsa."""
    jogos = {j.game_id: j for j in (_jogo("a", 30), _jogo("b", 20), _jogo("c", 10))}
    detalhes = _DetalhesFalsos()
    modelo, bp, janela, _ = _com_janela(*jogos.values(), detalhes=detalhes)
    sessao = SimpleNamespace(jogoId="", emAndamento=False, terminadas=0)
    sessao.terminar = lambda: setattr(sessao, "terminadas", sessao.terminadas + 1)
    monkeypatch.setattr(modulo.shared, "store", SimpleNamespace(get=jogos.get))
    monkeypatch.setattr(modulo.shared, "sessao", sessao, raising=False)
    for jogo in jogos.values():
        jogo.launch = _Launch(modelo, jogo)
    pedidas, saidas = [], []
    bp.etapaPedida.connect(lambda de, para: pedidas.append((de, para)))
    bp.saiu.connect(saidas.append)
    bp.entrar()
    bp.filaTerminou()
    return SimpleNamespace(
        jogos=jogos, modelo=modelo, bp=bp, janela=janela, detalhes=detalhes, sessao=sessao, pedidas=pedidas, saidas=saidas,
    )


def _nos_detalhes(e):
    e.bp.ativar()
    e.bp.etapaTerminou()


def test_comeca_no_carrossel(etapas):
    assert etapas.bp.etapa == "carrossel"


def test_ativar_no_carrossel_vai_aos_detalhes(etapas):
    e = etapas
    e.bp.ativar()
    assert e.pedidas == [("carrossel", "detalhes")] and e.bp.etapa == "detalhes" and e.bp.ocupada
    e.bp.etapaTerminou()
    assert not e.bp.ocupada and e.detalhes.mostrados[-1] == "a"


def test_ativar_ocupada_e_ignorado(etapas):
    e = etapas
    e.bp.ativar()
    e.bp.ativar()  # ainda na transição
    assert e.pedidas == [("carrossel", "detalhes")]


def test_ativar_com_detalhes_recusando_fica_no_carrossel(etapas):
    e = etapas
    e.detalhes.aceita = False
    e.bp.ativar()
    assert e.pedidas == [] and e.bp.etapa == "carrossel" and not e.bp.ocupada


def test_voltar_por_etapa(etapas):
    e = etapas
    _nos_detalhes(e)
    e.bp.voltar()
    assert e.pedidas[-1] == ("detalhes", "carrossel") and e.bp.etapa == "carrossel"
    e.bp.etapaTerminou()
    e.bp.voltar()  # do carrossel: sai
    assert e.bp.ocupada and e.bp._saindo  # noqa: SLF001
    e.bp.filaTerminou()


def test_voltar_na_sessao_nao_faz_nada(etapas):
    e = etapas
    e.sessao.jogoId = "a"
    _nos_detalhes(e)
    e.bp.ativar()
    e.bp.etapaTerminou()
    antes = list(e.pedidas)
    e.bp.voltar()
    assert e.pedidas == antes and e.bp.etapa == "sessao"


def test_iniciar_vai_a_sessao_e_lanca_no_fim_da_animacao(etapas):
    e = etapas
    e.sessao.jogoId = "a"
    _nos_detalhes(e)
    e.bp.ativar()  # Iniciar
    assert e.pedidas[-1] == ("detalhes", "sessao") and e.jogos["a"].launch.chamadas == 0
    e.bp.etapaTerminou()
    assert e.jogos["a"].launch.chamadas == 1 and e.jogos["a"].launch.em_tela_cheia is True
    assert e.bp.ocupada  # a sessão em curso segura a página


def test_abrir_jogo_fora_dos_detalhes_nao_faz_nada(etapas):
    etapas.bp.abrirJogo()
    assert etapas.pedidas == []


@pytest.mark.parametrize("devolve", [True, False])
def test_iniciar_sem_sessao_volta_aos_detalhes(etapas, devolve):
    e = etapas
    e.jogos["a"].launch.devolve = devolve
    _nos_detalhes(e)
    e.bp.ativar()
    e.bp.etapaTerminou()
    assert e.pedidas[-1] == ("sessao", "detalhes")
    e.bp.etapaTerminou()
    assert e.bp.etapa == "detalhes" and not e.bp.ocupada


def test_fim_da_sessao_volta_ao_carrossel_com_o_mesmo_central(etapas):
    e = etapas
    e.sessao.jogoId = "b"
    e.bp.atualizar("b")
    _nos_detalhes(e)
    e.bp.ativar()
    e.bp.etapaTerminou()
    e.bp.voltouDoJogo()
    assert e.pedidas[-1] == ("sessao", "carrossel") and e.bp.jogos[e.bp.indice]["jogoId"] == "b"
    e.bp.etapaTerminou()
    assert e.bp.etapa == "carrossel" and not e.bp.ocupada


def test_ativar_na_sessao_termina(etapas):
    e = etapas
    e.sessao.jogoId, e.sessao.emAndamento = "a", True
    _nos_detalhes(e)
    e.bp.ativar()
    e.bp.etapaTerminou()
    e.bp.ativar()
    assert e.sessao.terminadas == 1


def test_seguir_central_so_depois_de_parar(etapas):
    e = etapas
    assert e.detalhes.mostrados == ["a"]  # o central da entrada, na hora
    for _ in range(2):
        e.bp.mover(1)
    assert e.detalhes.mostrados == ["a"]
    for _ in range(15):  # 300 ms > ESPERA_DO_CENTRAL_MS
        _esperar()
    assert e.detalhes.mostrados == ["a", "c"]


def test_jogo_excluido_nos_detalhes_volta_ao_carrossel(etapas):
    e = etapas
    _nos_detalhes(e)
    e.detalhes.sair.emit()
    assert e.pedidas[-1] == ("detalhes", "carrossel")


def test_jogo_excluido_na_sessao_e_ignorado(etapas):
    e = etapas
    e.sessao.jogoId = "a"
    _nos_detalhes(e)
    e.bp.ativar()
    e.bp.etapaTerminou()
    antes = list(e.pedidas)
    e.detalhes.sair.emit()
    assert e.pedidas == antes


def test_sair_esquece_os_detalhes(etapas):
    e = etapas
    e.bp.sair()
    e.bp.filaTerminou()
    assert e.detalhes.esquecidos == 1


def test_entrar_de_novo_volta_ao_carrossel(etapas):
    e = etapas
    _nos_detalhes(e)
    e.bp.etapaTerminou()
    e.bp._etapa_bp = "detalhes"  # noqa: SLF001
    e.bp.sair()
    e.bp.filaTerminou()
    e.bp.entrar()
    assert e.bp.etapa == "carrossel"
