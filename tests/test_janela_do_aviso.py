"""A janela do aviso de conquista: o cartão em QML, sem tomar o foco, fora da barra e por cima do jogo.

O user32 é sempre o `user32_falso` (nenhuma janela TOPMOST nem estilo Win32 de verdade); a
`QQuickView` é offscreen.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QWindow
from PySide6.QtQml import QQmlEngine, QQmlExpression

from cartridges import conquista_aviso, shared
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


# -- Auditoria GTK x Qt, pacote E --------------------------------------------------------------------


def _expr(item, texto):
    return QQmlExpression(QQmlEngine.contextForObject(item), item, texto).evaluate()[0]


def test_cartao_tem_as_fontes_e_os_limites_da_main(abrir):
    """A3/A4: rótulo e descrição são caption (10, linha de 140%), o título é heading (12, 700); cada um quebra em 36
    caracteres medidos na própria fonte, então o caption quebra mais cedo que o título."""
    longo = "palavra " * 30
    janela = abrir(rotulo=longo, titulo=longo, descricao=longo)
    raiz = janela.rootObject()
    rotulo, titulo, descricao = (_filho(janela, n) for n in ("rotuloDoAviso", "tituloDoAviso", "descricaoDoAviso"))
    for caption in (rotulo, descricao):
        assert _expr(caption, "font.pixelSize") == 10 and _expr(caption, "lineHeight") == 1.4
    assert _expr(titulo, "font.pixelSize") == 12 and _expr(titulo, "font.weight") == 700
    limites = {
        rotulo: _expr(raiz, "medidaDoRotulo.averageCharacterWidth") * 36,
        titulo: _expr(raiz, "medidaDoTitulo.averageCharacterWidth") * 36,
        descricao: _expr(raiz, "medidaDaDescricao.averageCharacterWidth") * 36,
    }
    for texto, limite in limites.items():
        assert texto.property("width") == pytest.approx(limite, abs=0.5)
        assert texto.property("lineCount") > 1
    assert descricao.property("width") < titulo.property("width")


def test_estrela_so_no_aviso_sem_icone_nenhum(abrir, entregas):
    """A5: com o ícone a caminho (ou que falhou) fica o quadrado vazio de 48 px, sem a estrela."""
    sem = abrir()
    assert sem.rootObject().property("semIcone") is True
    assert _filho(sem, "estrelaDoAviso").property("visible") is True
    com = abrir(icone="https://exemplo.test/i.jpg")  # o ícone ainda não chegou
    assert com.rootObject().property("semIcone") is False
    assert _filho(com, "estrelaDoAviso").property("visible") is False
    assert [origem for origem, _ in entregas] == ["https://exemplo.test/i.jpg"]


def test_estrela_e_o_starred_da_main(abrir):
    """I2: o `starred-symbolic` da Adwaita, branco, de 48 px (e não o glifo da Segoe)."""
    estrela = _filho(abrir(), "estrelaDoAviso")
    assert estrela.property("nome") == "starred" and estrela.property("tamanho") == 48
    assert _expr(estrela, "cor.toString()") == "#ffffff"


def test_fade_em_ease_out_cubic_e_segue_as_animacoes_do_windows(abrir, monkeypatch, flush_idle):
    """A1/A7: a curva é a do `Adw.TimedAnimation`; com os efeitos do Windows desligados o fade pula ao fim."""
    janela = abrir()
    raiz = janela.rootObject()
    assert _expr(raiz, "animacao.easing.type === Easing.OutCubic") is True
    assert raiz.property("animar") is True and _expr(raiz, "animacao.duration") == 250

    monkeypatch.setattr(shared, "aplicativo", SimpleNamespace(animacoesDoSistema=False))
    sem = abrir()
    assert sem.rootObject().property("animar") is False
    assert _expr(sem.rootObject(), "animacao.duration") == 0
    sem.entrar("inferior-direito")
    assert _esperar(flush_idle, lambda: sem.rootObject().property("opacidade") == 1)
    chamadas = []
    sem.sair(lambda: chamadas.append(1))
    assert _esperar(flush_idle, lambda: chamadas == [1])  # o `terminou` sai mesmo sem animar


def test_borda_esquerda_acompanha_a_curva_e_a_reserva_opaca_tem_faixa_reta(abrir, monkeypatch):
    """A2: a borda de 3 px é a meia-lua do CSS (raio 12 fora, 9x12 dentro); sem transparência os cantos são retos."""
    transparente = abrir().rootObject()
    assert _expr(transparente, "children[1].objectName") == "bordaDoAviso"
    assert transparente.findChild(QObject, "bordaDoAviso").property("visible") is True
    assert transparente.findChild(QObject, "bordaRetaDoAviso").property("visible") is False
    monkeypatch.setattr(jpc, "FUNDO_TRANSPARENTE", False)
    opaca = abrir().rootObject()
    assert opaca.findChild(QObject, "bordaDoAviso").property("visible") is False
    reta = opaca.findChild(QObject, "bordaRetaDoAviso")
    assert reta.property("visible") is True and reta.property("width") == 3


def test_cartao_embutido_tem_contorno_e_sombra(abrir):
    """A6: no assistente o cartão leva `0 0 0 1px alpha(white,.14), 0 2px 8px rgba(0,0,0,.35)`."""
    raiz = abrir().rootObject()
    sombra = raiz.findChild(QObject, "sombraDoAviso")
    assert raiz.property("embutido") is False and sombra.property("visible") is False
    raiz.setProperty("embutido", True)
    assert sombra.property("visible") is True
    assert _expr(sombra, "camadas.length") == 2
