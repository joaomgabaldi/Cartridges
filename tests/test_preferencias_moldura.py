# test_preferencias_moldura.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As Preferências como diálogo: moldura, cabeçalho, barra das abas, paleta de cores, o progresso fora do cartão e os diálogos internos."""

import re

import pytest
from PySide6.QtCore import QMetaObject, QPointF, Qt
from PySide6.QtTest import QTest

from cartridges import shared
from tests.apoio_qml_biblioteca import QML, _achar, _esperar
from tests.apoio_qml_detalhes import _clicar
from tests.apoio_qml_preferencias import (  # noqa: F401  (as fixtures vêm junto)
    _abrir,
    _avaliar,
    _clique,
    _enabled,
    app,
    fitas_espiadas,
)


def _com_refresh_falso(monkeypatch):
    from cartridges import metadata_refresh  # noqa: PLC0415

    class Falso(metadata_refresh.MetadataRefresh):
        def start(self, games, only_missing=False):
            return True

    refresh = Falso()
    monkeypatch.setattr(metadata_refresh, "get_metadata_refresh", lambda: refresh)
    return refresh


@pytest.fixture
def calibracao_aberta(app, fitas_espiadas, monkeypatch):
    """O assistente aberto sobre duas fitas, sem acender nada."""
    from cartridges.utils import session_fita  # noqa: PLC0415

    session_fita.gravar_fitas(
        [session_fita.Fita("Sala", "eb0", "192.0.2.10", "k"), session_fita.Fita("Quarto", "eb1", "192.0.2.11", "k")]
    )
    monkeypatch.setattr(session_fita, "previa_calibracao", lambda *_a: fitas_espiadas.append("so"))
    _abrir(app, "session")
    app.preferencias.abrirCalibracao()
    dialogo = app.achar("assistenteDeCalibracao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    return app, dialogo


def _dialogo(app):
    return app.achar("dialogoDePreferencias")


def _cabecalho(app):
    """O cabeçalho do diálogo (o pai do título, dentro do cartão das Preferências e não dos diálogos internos)."""
    titulo = _achar(app.achar("cartaoDasPreferencias"), "tituloDoCabecalho")
    return titulo, titulo.parentItem()


def test_o_dialogo_e_uma_moldura_de_640_com_raio_15_e_altura_maxima(app):
    _abrir(app)
    dialogo = _dialogo(app)
    assert _avaliar(dialogo, "cartao.width") == 640
    assert _avaliar(dialogo, "cartao.radius") == 15
    # `content-height` sem teto: a janela limita, com a margem vertical da moldura.
    assert _avaliar(dialogo, "cartao.height") == _avaliar(dialogo, "height") - 2 * _avaliar(dialogo, "margemV")


def test_cartoes_das_paginas_tem_532_em_640(app):
    """Cartões de x=54 a x=586 no diálogo de 640."""
    _abrir(app, "general")
    grupo = app.achar("grupoComportamentoGeral")
    assert grupo.property("width") == 532
    # A margem de cima da página é 24: o título do primeiro grupo começa a 24 do cabeçalho.
    rolagem = app.achar("rolagemDasPreferencias")
    pagina = app.achar("paginaGeral")
    assert pagina.mapToItem(rolagem.property("contentItem"), QPointF(0, 0)).y() == 24


def test_cabecalho_de_47_com_o_titulo_e_a_lupa_e_sem_linha_no_topo(app):
    _abrir(app)
    titulo, cabecalho = _cabecalho(app)
    assert titulo.property("text") == "Preferências"
    assert cabecalho.property("height") == 47  # uma faixa só
    assert cabecalho.property("sombra") is False  # sem linha com a rolagem no topo
    lupa = app.achar("botaoDeBuscaDasPreferencias")
    assert lupa.property("icone") == "system-search"
    # Rolada, a linha aparece.
    rolagem = app.achar("rolagemDasPreferencias")
    rolagem.setProperty("contentY", 80)
    assert _esperar(lambda: cabecalho.property("sombra") is True)


def test_barra_das_abas_no_pe_com_icone_sobre_o_rotulo(app):
    _abrir(app)
    barra = app.achar("abas")
    assert barra.property("height") == 47
    cartao = app.achar("cartaoDasPreferencias")
    # No pé do cartão.
    assert barra.mapToItem(cartao, QPointF(0, 0)).y() + barra.property("height") == pytest.approx(cartao.property("height"))
    icones = []
    for aba in ("general", "session", "import", "sgdb", "conquistas"):
        botao = app.achar(f"aba-{aba}")
        assert (botao.property("width"), botao.property("height")) == (100, 40)
        icones.append(_avaliar(botao, "modelData.icone"))  # os ícones simbólicos
    assert icones == ["user-home", "video-joined-displays", "document-save", "image-x-generic", "starred"]
    # Ficam centralizadas, com 3 de vão (5 x 100 + 4 x 3 = 512 em 640).
    primeira, ultima = app.achar("aba-general"), app.achar("aba-conquistas")
    x0 = primeira.mapToItem(cartao, QPointF(0, 0)).x()
    x1 = ultima.mapToItem(cartao, QPointF(ultima.property("width"), 0)).x()
    assert x0 == pytest.approx(64) and x1 == pytest.approx(576)


def test_a_linha_da_barra_so_aparece_com_mais_conteudo_por_rolar(app):
    _abrir(app, "import")  # a página curta cabe: sem linha
    barra = app.achar("abas")
    linha = barra.childItems()[0]
    assert linha.property("visible") is False
    _abrir_geral = app.achar("aba-general")
    _clique(app, "aba-general")
    assert _esperar(lambda: app.achar("dialogoDePreferencias").property("aba") == "general")
    assert _esperar(lambda: linha.property("visible") is True)  # a página Geral é longa
    app.achar("rolagemDasPreferencias").setProperty("contentY", 100000)
    assert _esperar(lambda: linha.property("visible") is False)


def test_clicar_fora_do_cartao_nao_fecha(app):
    """O toque fora do diálogo flutuante é retido: nem fecha nem arrasta."""
    _abrir(app)
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, app.achar("botaoMenu").mapToScene(QPointF(-100, 200)).toPoint())
    _esperar()
    assert app.preferencias.aberto


def test_o_aviso_das_preferencias_fica_no_cartao_delas(app):
    """O aviso nasce dentro do cartão."""
    _abrir(app)
    app.aplicativo.avisar("Olá")
    aviso = app.achar("aviso")
    assert _esperar(lambda: aviso.property("visible") is True)
    pai = aviso.parentItem()
    assert pai.objectName() == "cartaoDoDialogo"
    ancora = pai
    while ancora is not None and ancora.objectName() != "dialogoDePreferencias":
        ancora = ancora.parentItem()
    assert ancora is not None


def test_abre_com_o_foco_no_x_e_a_aba_da_pagina_a_vista(app):
    # O primeiro Tab vai à primeira linha da página; a aba à vista é a pedida, mas não leva o foco.
    _abrir(app, "sgdb")
    assert _esperar(lambda: app.janela.activeFocusItem() is app.achar("dialogoDePreferencias").property("botaoFechar"))
    assert app.achar("dialogoDePreferencias").property("aba") == "sgdb"


def test_os_diretorios_de_arquivo_nao_tem_titulo_proprio():
    """O Windows mostra o título padrão (nenhum título é passado)."""
    for nome in ("PaginaGeral.qml", "PaginaDeImportacao.qml"):
        texto = (QML / nome).read_text(encoding="utf-8")
        for bloco in re.findall(r"(?:FileDialog|FolderDialog) \{.*?\n        \}", texto, flags=re.S):
            assert "title:" not in bloco, nome


# region Linhas com botão


def _rolar_ate(app, item):
    rolagem = app.achar("rolagemDasPreferencias")
    y = item.mapToItem(rolagem.property("contentItem"), QPointF(0, 0)).y()
    rolagem.setProperty("contentY", max(0, y - 100))
    assert _esperar(lambda: rolagem.property("contentY") == max(0, y - 100))


def test_linhas_das_fitas_acionam_pela_linha_inteira(app, fitas_espiadas):  # noqa: ARG001
    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    linha = app.achar("linhaDoBrilhoPorDispositivo")
    assert linha.property("ativavel").objectName() == "linhaDoBrilhoPorDispositivoBotao"
    _rolar_ate(app, linha)
    # Um clique longe do botão, no texto da linha.
    ponto = linha.mapToScene(QPointF(60, linha.property("height") / 2)).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    assert _esperar(lambda: app.preferencias.brilhoPorDispositivo is not None)


def test_pasta_dos_saves_e_buscar_atualizacoes_nao_sao_ativaveis(app):
    _abrir(app, "general")
    assert app.achar("linhaBuscarAtualizacoes").property("ativavel") is None
    assert app.achar("linhaPastaDosSaves").property("ativavel") is None
    assert app.achar("linhaBuscarAtualizacoesBotao").property("text") == "Buscar"


# endregion
# region O progresso fora do cartão


def test_progresso_dos_metadados_fica_abaixo_do_cartao(app, monkeypatch):
    refresh = _com_refresh_falso(monkeypatch)
    _abrir(app, "import")
    linha = app.achar("linhaDosMetadados")
    barra = app.achar("linhaDosMetadadosProgresso")
    assert barra.property("visible") is False
    refresh.running, refresh.done, refresh.total = True, 3, 12
    refresh.progress.emit()
    assert _esperar(lambda: barra.property("visible") is True)
    assert app.achar("linhaDosMetadadosProgressoTexto").property("text") == "3 de 12"
    cartao = app.achar("grupoAtualizarMetadados")
    texto = app.achar("linhaDosMetadadosProgressoTexto")
    # O texto fica acima da trilha, com a margem de 12 sob o cartão; a trilha tem 8.
    assert texto.mapToItem(cartao, QPointF(0, 0)).y() == pytest.approx(cartao.property("height") + 12)
    assert barra.mapToItem(cartao, QPointF(0, 0)).y() >= texto.mapToItem(cartao, QPointF(0, 0)).y() + texto.property("height")
    assert barra.property("height") == 8
    assert _avaliar(texto, "color.a") < 1 or _avaliar(texto, "color.toString() !== Tema.texto.toString()")  # esmaecido
    assert linha.property("height") == 54  # o cartão não cresceu


# endregion
# region A paleta de cores


def test_balao_da_cor_abre_na_paleta_e_o_mais_leva_ao_seletor(app, fitas_espiadas):
    from cartridges.utils import session_fita  # noqa: PLC0415

    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    linha = app.achar("linhaDaCorDoApp")
    _rolar_ate(app, linha)
    _clique(app, "linhaDaCorDoAppAmostra")
    balao = app.achar("linhaDaCorDoAppBalao")
    assert _esperar(lambda: balao.property("opened") is True)
    seletor = app.achar("linhaDaCorDoAppSeletor")
    assert seletor.property("visible") is False  # abre na paleta
    amostra = app.achar("linhaDaCorDoAppAmostra")
    assert _avaliar(amostra, "editando") is False
    # Os 45 tons da paleta; clicar num grava a cor e acende as fitas.
    tons = _avaliar(amostra, "paleta")
    assert len(tons) == 9 and all(len(coluna) == 5 for coluna in tons)
    # Cada tom tem o nome da paleta (em português), sem repetir.
    nomes = _avaliar(amostra, "nomesDosTons")
    assert [len(coluna) for coluna in nomes] == [5] * 9
    assert len({n for coluna in nomes for n in coluna}) == 45
    assert (nomes[0][0], nomes[0][2], nomes[6][4], nomes[7][0], nomes[8][4]) == (
        "Azul muito claro", "Azul", "Marrom muito escuro", "Branco", "Preto"
    )
    amostra.setProperty("editando", False)
    QMetaObject.invokeMethod(app.achar("linhaDaCorDoAppAmostraMais"), "forceActiveFocus")
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: seletor.property("visible") is True)
    QMetaObject.invokeMethod(seletor, "mover", Qt.ConnectionType.DirectConnection, _arg(120), _arg(900))
    matiz, _saturacao = session_fita.tom_do_app()
    assert abs(matiz - 120) <= 1
    assert fitas_espiadas[-1] == session_fita.cor_do_app()


def _arg(valor):
    from PySide6.QtCore import Q_ARG  # noqa: PLC0415

    return Q_ARG("QVariant", valor)


def test_clicar_num_tom_da_paleta_escolhe_a_cor(app, fitas_espiadas):
    from cartridges.utils import session_fita  # noqa: PLC0415

    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    _rolar_ate(app, app.achar("linhaDaCorDoApp"))
    _clique(app, "linhaDaCorDoAppAmostra")
    assert _esperar(lambda: app.achar("linhaDaCorDoAppBalao").property("opened") is True)
    balao = app.achar("linhaDaCorDoAppBalao")
    # O vermelho (`#e01b24`, quinta coluna, terceiro tom): o primeiro `Tom` com essa cor.
    alvo = None
    pilha = [balao.property("contentItem")]
    while pilha:
        atual = pilha.pop()
        if atual.property("cor") is not None and str(atual.property("cor").name()) == "#e01b24":
            alvo = atual
            break
        pilha.extend(atual.childItems())
    assert alvo is not None
    _clicar(app, alvo)
    assert _esperar(lambda: abs(session_fita.tom_do_app()[0] - 358) <= 3 or session_fita.tom_do_app()[0] >= 355 or session_fita.tom_do_app()[0] <= 3)
    assert fitas_espiadas[-1] == session_fita.cor_do_app()


# endregion
# region Os diálogos internos


def test_assistente_das_fitas_enter_nao_busca_e_o_segredo_tem_botao_de_mostrar(app):
    _abrir(app, "session")
    app.preferencias.abrirConfiguracaoDasFitas()
    dialogo = app.achar("dialogoDaConfiguracaoDasFitas")
    assert _esperar(lambda: dialogo.property("visible") is True)
    campo = app.achar("campoDoAccessId")
    assert _esperar(lambda: app.janela.activeFocusItem() is not None and campo.property("activeFocus") is not False)
    app.achar("campoDoAccessId").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    _esperar()
    assert app.preferencias.configuracaoDasFitas.pagina == "credenciais"  # Enter não faz nada
    # O segredo vai mascarado e o botão o mostra.
    segredo = app.achar("campoDoAccessSecret")
    assert _avaliar(segredo, "echoMode") == 2
    _clique(app, "botaoMostrarOSegredo")
    assert _esperar(lambda: _avaliar(segredo, "echoMode") == 0)
    _clique(app, "botaoMostrarOSegredo")
    assert _esperar(lambda: _avaliar(segredo, "echoMode") == 2)


def test_cabecalho_dos_dialogos_internos_tem_47_e_o_titulo_centralizado(app, fitas_espiadas):  # noqa: ARG001
    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    app.preferencias.abrirConfiguracaoDasFitas()
    dialogo = app.achar("dialogoDaConfiguracaoDasFitas")
    assert _esperar(lambda: dialogo.property("visible") is True)
    titulo = _achar(dialogo, "tituloDoCabecalho")
    cabecalho = titulo.parentItem()
    assert cabecalho.property("height") == 47
    centro = titulo.mapToItem(cabecalho, QPointF(titulo.property("width") / 2, 0)).x()
    assert centro == pytest.approx(cabecalho.property("width") / 2, abs=1)  # centralizado
    assert titulo.property("text") == "Configurar a iluminação inteligente"
    assert _achar(dialogo, "fecharDoCabecalho").property("visible") is True  # o X redondo da base


def test_brilho_por_dispositivo_cabecalho_47_com_cancelar_e_salvar(app, fitas_espiadas):  # noqa: ARG001
    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    app.preferencias.abrirBrilhoPorDispositivo()
    dialogo = app.achar("dialogoDoBrilhoPorDispositivo")
    assert _esperar(lambda: dialogo.property("visible") is True)
    titulo = _achar(dialogo, "tituloDoCabecalho")
    assert titulo.parentItem().property("height") == 47
    assert _avaliar(app.achar("botaoCancelarDoBrilho"), "estilo") == "plano"
    assert _avaliar(app.achar("botaoSalvarDoBrilho"), "estilo") == "sugestao"
    assert _avaliar(dialogo, "cartao.radius") == 15


def test_calibracao_botoes_na_base_e_amostra_sem_borda(calibracao_aberta):
    app, dialogo = calibracao_aberta
    assistente = app.preferencias.calibracao
    assistente.escolher("eb0")
    assert _esperar(lambda: app.achar("amostraDaCalibracao").property("visible") is True)
    cartao = _avaliar(dialogo, "cartao.height")
    amostra = app.achar("amostraDaCalibracao")
    assert amostra.property("height") > 240  # ocupa o que sobra
    botao = app.achar("botaoProximaCalibracao")
    # Os botões ficam na base, a 24 do fundo do cartão.
    raiz = _achar(dialogo, "cartaoDoDialogo")
    base = botao.mapToItem(raiz, QPointF(0, botao.property("height"))).y()
    assert base == pytest.approx(cartao - 24, abs=1)
    # A amostra não tem borda (só a cor de referência, raio 12).
    fonte = (QML / "AssistenteDeCalibracao.qml").read_text(encoding="utf-8")
    assert "border" not in fonte[fonte.index("component Amostra"):fonte.index("component Titulo")]
    assert _avaliar(amostra, "radius") == 12
    # O botão padrão da fundação; o texto da tela inicial na cor do texto.
    assert _avaliar(botao, "estilo") == "sugestao"


def test_calibracao_todos_os_dispositivos_sem_cartao(app, fitas_espiadas, monkeypatch):  # noqa: ARG001
    from cartridges.utils import session_fita  # noqa: PLC0415

    session_fita.gravar_fitas(
        [session_fita.Fita("Sala", "eb0", "192.0.2.10", "k"), session_fita.Fita("Quarto", "eb1", "192.0.2.11", "k")]
    )
    monkeypatch.setattr(session_fita, "previa_calibracao", lambda *_a: None)
    _abrir(app, "session")
    app.preferencias.abrirCalibracao()
    dialogo = app.achar("assistenteDeCalibracao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    app.preferencias.calibracao.escolher("__todos__")
    assert _esperar(lambda: app.achar("amostraDeTodosDaCalibracao").property("visible") is True)
    # Título e controles soltos, sem `GrupoDeLinhas` (o cartão) em volta.
    rolagem = _achar(dialogo, "tomDaCalibracao-eb0")
    pai = rolagem
    cartoes = 0
    while pai is not None and pai.objectName() != "assistenteDeCalibracao":
        if pai.property("itens") is not None and pai.property("separada") is not None:
            cartoes += 1
        pai = pai.parentItem()
    assert cartoes == 0


# endregion


# region Diálogo interno e camada dos avisos


def test_dialogo_interno_acompanha_o_redimensionamento_da_janela(app, fitas_espiadas):  # noqa: ARG001
    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    app.preferencias.abrirBrilhoPorDispositivo()
    dialogo = app.achar("dialogoDoBrilhoPorDispositivo")
    assert _esperar(lambda: dialogo.property("visible") is True)
    janela = app.janela

    def origem():
        return dialogo.mapToScene(QPointF(0, 0)).toPoint()

    assert (origem().x(), origem().y()) == (0, 0)
    janela.resize(janela.width() + 300, janela.height() + 200)
    assert _esperar(lambda: (origem().x(), origem().y()) == (0, 0))
    assert dialogo.property("width") == janela.width()


def test_aviso_e_contorno_ficam_abaixo_do_dialogo_interno(app, fitas_espiadas):  # noqa: ARG001
    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    app.preferencias.abrirBrilhoPorDispositivo()
    dialogo = app.achar("dialogoDoBrilhoPorDispositivo")
    assert _esperar(lambda: dialogo.property("visible") is True)
    app.aplicativo.avisar("Olá")
    aviso = app.achar("aviso")
    assert _esperar(lambda: aviso.property("visible") is True)
    cartao = aviso.parentItem()
    ponto = aviso.mapToItem(cartao, QPointF(aviso.property("width") / 2, aviso.property("height") / 2))
    # O que o cartão das Preferências tem de mais alto naquele ponto é o diálogo interno (via o `Item` de `z: 200`), não o aviso.
    topo = max(cartao.childItems(), key=lambda c: c.property("z") or 0)
    assert topo is not aviso and (topo.property("z") or 0) > aviso.property("z")
    assert dialogo.parentItem() is topo


# endregion


def test_alerta_do_app_fica_na_frente_das_preferencias_e_responde_ao_clique(app, fitas_espiadas):  # noqa: ARG001
    """A camada dos avisos (z 20) fica acima das molduras (z 10): com as Preferências abertas, o clique real no botão do alerta o alcança e o fecha."""
    _abrir(app, "session")
    fechados = []
    app.aplicativo.pedir_dialogo("Aviso", "Corpo", [], lambda: fechados.append(1))
    dialogo = app.achar("dialogoDeErros")
    assert _esperar(lambda: dialogo.property("visible") is True)
    botao = _achar(dialogo, "botaoDoDialogo")
    assert app.achar("camadaDeAvisos").property("z") > app.achar("dialogoDePreferencias").property("z")
    _clicar(app, botao)
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert fechados == [1]
