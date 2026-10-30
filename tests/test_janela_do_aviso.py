"""A janela do aviso de conquista: o cartão em QML, sem tomar o foco, fora da barra e por cima do jogo.

O user32 é sempre o `user32_falso` (nenhuma janela TOPMOST nem estilo Win32 de verdade); a
`QQuickView` é offscreen.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QWindow
from PySide6.QtQml import QQmlEngine, QQmlExpression

from cartridges import conquista_aviso
from cartridges.conquistas import icones
from cartridges.utils import janela_por_cima as jpc


@pytest.fixture
def entregas(monkeypatch):
    """`icones.carregar` sem rede nem thread: guarda (origem, entregar) para o teste entregar o arquivo."""
    pedidos = []
    monkeypatch.setattr(icones, "carregar", lambda origem, entregar: pedidos.append((origem, entregar)))
    return pedidos


@pytest.fixture
def abrir(user32_falso, entregas):  # noqa: ARG001
    """Cria uma `JanelaDoAviso`; todas são fechadas no fim do teste."""
    from cartridges.janela_do_aviso import JanelaDoAviso  # noqa: PLC0415

    abertas = []

    def criar(rotulo="Conquista desbloqueada", titulo="Mestre da Grama", descricao="Corte toda a grama.", icone=""):
        janela = JanelaDoAviso(conquista_aviso.Aviso(rotulo, titulo, descricao, icone))
        abertas.append(janela)
        return janela

    yield criar
    for janela in abertas:
        janela.fechar()


def _filho(janela, nome):
    achado = janela.rootObject().findChild(QObject, nome)
    assert achado is not None, nome
    return achado


def _textos_visiveis(janela):
    return [
        _filho(janela, nome).property("text")
        for nome in ("rotuloDoAviso", "tituloDoAviso", "descricaoDoAviso")
        if _filho(janela, nome).property("visible")
    ]


def _esperar(flush_idle, condicao, limite=3.0):
    passos = int(limite / 0.05)
    for _ in range(passos):
        if condicao():
            return True
        flush_idle(0.05)
    return condicao()


def test_cartao_tem_rotulo_titulo_e_descricao_em_texto_puro(abrir):
    janela = abrir("Conquista desbloqueada", "A & B <i>", "<b>negrito</b> & cia")
    assert _textos_visiveis(janela) == ["Conquista desbloqueada", "A & B <i>", "<b>negrito</b> & cia"]
    for nome in ("rotuloDoAviso", "tituloDoAviso", "descricaoDoAviso"):
        item = _filho(janela, nome)
        assert QQmlExpression(QQmlEngine.contextForObject(item), item, "textFormat === Text.PlainText").evaluate()[0]
    assert janela.titulo == "A & B <i>"


def test_texto_longo_quebra_em_36_caracteres(abrir):
    janela = abrir(descricao="Uma descrição muito comprida que não cabe numa linha só do cartão do aviso.")
    descricao = _filho(janela, "descricaoDoAviso")
    assert descricao.property("lineCount") > 1
    assert descricao.property("width") <= janela.rootObject().property("larguraMaxima") + 0.5


def test_sem_descricao_so_duas_linhas(abrir):
    janela = abrir(descricao="")
    assert _textos_visiveis(janela) == ["Conquista desbloqueada", "Mestre da Grama"]


def test_sem_icone_mostra_a_estrela(abrir, entregas):
    janela = abrir(icone="")
    assert _filho(janela, "estrelaDoAviso").property("visible") is True
    assert _filho(janela, "iconeDoAviso").property("visible") is False
    assert entregas == []  # nada a carregar


def test_icone_que_chega_aparece_no_lugar_da_estrela(abrir, entregas, tmp_path):
    janela = abrir(icone="https://exemplo.test/i.jpg")
    assert [origem for origem, _ in entregas] == ["https://exemplo.test/i.jpg"]
    arquivo = tmp_path / "i.png"
    entregas[0][1](arquivo)
    assert _filho(janela, "iconeDoAviso").property("visible") is True
    assert _filho(janela, "estrelaDoAviso").property("visible") is False
    assert Path(janela.rootObject().property("icone").removeprefix("file:///")) == arquivo


def test_icone_que_chega_depois_do_fechamento_nao_levanta(abrir, entregas, tmp_path):
    janela = abrir(icone="https://exemplo.test/i.jpg")
    janela.entrar("inferior-direito")
    janela.fechar()
    entregas[0][1](tmp_path / "i.png")  # o arquivo chega com a janela já fechada: nada acontece


def test_preparar_que_falha_nao_mostra_a_janela(abrir, user32_falso):
    user32_falso.falhas["SetWindowPos"] = 0
    janela = abrir()
    with pytest.raises(RuntimeError):
        janela.entrar("inferior-direito")
    assert not janela.isVisible()
    assert user32_falso.pedidos("SetForegroundWindow") == []


def test_mostrar_nao_toma_o_foco_e_devolve_quem_tinha(abrir, user32_falso):
    """Review Focus 1: o processo na frente, o Windows ativa o aviso ao mostrá-lo; o foco volta ao jogo."""
    janela = abrir()
    janela.visibleChanged.connect(lambda _v: setattr(user32_falso, "primeiro_plano", jpc.handle(janela)))
    janela.entrar("inferior-direito")
    assert janela.isVisible()
    assert user32_falso.pedidos("SetForegroundWindow") == [(50,)]


def test_janela_do_aviso_sai_da_barra_e_fica_por_cima(abrir, user32_falso):
    """Review Focus 1: sem moldura, sem foco, clique atravessa; estilos Win32, dono oculto e TOPMOST."""
    janela = abrir()
    janela.entrar("inferior-direito")
    flags = janela.flags()
    for flag in (
        Qt.WindowType.Tool,
        Qt.WindowType.FramelessWindowHint,
        Qt.WindowType.WindowStaysOnTopHint,
        Qt.WindowType.WindowDoesNotAcceptFocus,
        Qt.WindowType.WindowTransparentForInput,
    ):
        assert flags & flag == flag, flag
    hwnd = jpc.handle(janela)
    estilos = [valor for h, indice, valor in user32_falso.pedidos("SetWindowLongPtrW") if h == hwnd and indice == jpc.GWL_EXSTYLE]
    assert estilos and estilos[0] & jpc.ESTILOS == jpc.ESTILOS
    assert (hwnd, jpc.GWLP_HWNDPARENT, user32_falso.DONO) in user32_falso.pedidos("SetWindowLongPtrW")
    assert jpc.dono_de(janela) == user32_falso.DONO
    assert [args[1] for args in user32_falso.pedidos("SetWindowPos") if args[0] == hwnd][-1] == jpc.HWND_TOPMOST
    # Os estilos antes de a janela aparecer: o primeiro SetWindowPos de mostrar vem depois deles.
    nomes = [nome for nome, _ in user32_falso.chamadas]
    assert nomes.index("SetWindowLongPtrW") < nomes.index("GetForegroundWindow")


@pytest.mark.parametrize("canto", jpc.CANTOS)
def test_canto_da_preferencia(abrir, monkeypatch, canto):
    pedidos = []
    real = jpc.posicao
    monkeypatch.setattr(jpc, "posicao", lambda c, *resto: pedidos.append(c) or real(c, *resto))
    abrir().entrar(canto)
    assert pedidos == [canto]


def test_entrada_comeca_do_zero_e_chega_a_um(abrir, flush_idle):
    janela = abrir()
    janela.entrar("inferior-direito")
    cartao = janela.rootObject()
    assert cartao.property("opacidade") < 1
    assert _esperar(flush_idle, lambda: cartao.property("opacidade") == 1)


def test_saida_animada_chama_ao_terminar_uma_vez(abrir, flush_idle):
    janela = abrir()
    janela.entrar("inferior-direito")
    chamadas = []
    janela.sair(lambda: chamadas.append(1))
    assert chamadas == []  # animada: não termina na hora
    assert _esperar(flush_idle, lambda: chamadas == [1])
    assert janela.rootObject().property("opacidade") == 0
    flush_idle(0.4)
    assert chamadas == [1]


def test_fechar_durante_a_saida_nao_chama_ao_terminar(abrir, flush_idle):
    janela = abrir()
    janela.entrar("inferior-direito")
    chamadas = []
    janela.sair(lambda: chamadas.append(1))
    janela.fechar()
    assert not QWindow.isVisible(janela)  # saiu da tela na hora, no meio da saída
    flush_idle(0.5)
    assert chamadas == []
    janela.sair(lambda: chamadas.append(2))  # depois de fechar, nada
    flush_idle(0.1)
    assert chamadas == []


def test_fechar_tira_da_tela_na_hora(abrir):
    janela = abrir()
    janela.entrar("inferior-direito")
    janela.fechar()
    assert not QWindow.isVisible(janela)


def test_opaco_sem_fundo_transparente(abrir, monkeypatch):
    transparente = abrir()
    assert transparente.color().alpha() == 0
    assert transparente.rootObject().property("opaco") is False
    assert transparente.rootObject().property("raio") == 12
    monkeypatch.setattr(jpc, "FUNDO_TRANSPARENTE", False)
    opaca = abrir()
    assert opaca.color() == QColor("#1c1b22")
    assert opaca.rootObject().property("opaco") is True
    assert opaca.rootObject().property("raio") == 0
