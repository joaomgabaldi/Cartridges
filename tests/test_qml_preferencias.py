# test_qml_preferencias.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tela das Preferências: o modal com abas, as páginas Geral, Importação e SteamGridDB (QML offscreen)."""

from pathlib import Path

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, QPoint, Qt
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.utils import open_uri
from tests.test_qml_biblioteca import QML, _achar, _App, _esperar, _jogos
from tests.test_qml_detalhes import _abrir_pelo_cartao, _cartoes, _clicar, _foco_dentro_de


@pytest.fixture
def app(app_qt):
    janela = _App(_jogos((1, "Alfa", {}), (2, "Beta", {})))
    yield janela
    janela.fechar()


def _abrir(app, pagina=""):
    assert app.preferencias.abrir(pagina)
    assert _esperar(lambda: app.achar("dialogoDePreferencias").property("visible") is True)


def _avaliar(objeto, expressao):
    valor = QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]
    return valor.toVariant() if hasattr(valor, "toVariant") else valor


def _clique(app, nome):
    QMetaObject.invokeMethod(app.achar(nome), "click", Qt.ConnectionType.DirectConnection)


def _textos(raiz):
    """Todo `text` de todo item abaixo de `raiz`, visível ou não."""
    achados, pilha = [], [raiz]
    while pilha:
        atual = pilha.pop()
        texto = atual.property("text")
        if isinstance(texto, str) and texto:
            achados.append(texto)
        pilha.extend(atual.childItems() if isinstance(atual, QQuickItem) else [])
    return achados


def test_menu_principal_abre_as_preferencias(app):
    item = app.achar("itemPreferencias")
    assert item.property("text") == "Preferências"
    _clique(app, "itemPreferencias")
    assert app.preferencias.aberto is True
    assert _esperar(lambda: app.achar("dialogoDePreferencias").property("visible") is True)


def test_item_do_menu_apagado_durante_a_importacao(app):
    assert app.achar("itemPreferencias").property("enabled") is True
    app.aplicativo.definir_importando(True)
    assert app.achar("itemPreferencias").property("enabled") is False
    app.aplicativo.definir_importando(False)
    assert app.achar("itemPreferencias").property("enabled") is True


def test_abas_na_ordem_da_main(app):
    _abrir(app)
    rotulos = app.achar("dialogoDePreferencias").property("rotulosDasAbas").toVariant()
    # Personalização e Conquistas entram com as tasks delas (sem aba morta); a ordem é a da `main`.
    ordem = ["Geral", "Personalização", "Importação", "SteamGridDB", "Conquistas"]
    assert [r for r in ordem if r in rotulos] == rotulos
    assert rotulos[:1] == ["Geral"] and "Importação" in rotulos and "SteamGridDB" in rotulos
    assert rotulos.index("Importação") < rotulos.index("SteamGridDB")


def test_abre_na_pagina_pedida_e_a_aba_troca_de_pagina(app):
    _abrir(app, "sgdb")
    assert app.achar("paginaDoSteamGridDB").property("visible") is True
    assert app.achar("paginaGeral").property("visible") is False
    _clique(app, "aba-import")
    assert _esperar(lambda: app.achar("paginaDeImportacao").property("visible") is True)
    assert app.achar("paginaDoSteamGridDB").property("visible") is False


def test_esc_fecha_e_o_foco_volta_ao_botao_do_menu(app):
    app.achar("botaoMenu").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _foco_dentro_de(app, "botaoMenu")
    _clique(app, "itemPreferencias")
    assert _esperar(lambda: app.preferencias.aberto)
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDePreferencias"))
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.preferencias.aberto)
    assert app.achar("dialogoDePreferencias").property("visible") is False
    assert _esperar(lambda: _foco_dentro_de(app, "botaoMenu"))


def test_fundo_nao_recebe_tab_nem_clique(app):
    cartao = _cartoes(app)[0]
    _abrir(app)
    assert app.achar("pilha").property("enabled") is False
    assert app.achar("pagina").property("enabled") is False
    assert app.achar("botaoMenu").property("enabled") is False
    assert app.achar("alvoDeSoltar").property("enabled") is False
    dialogo = app.achar("dialogoDePreferencias")
    focados = set()
    for _ in range(40):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        atual = item = app.janela.property("activeFocusItem")
        focados.add(atual)
        dentro = False
        while item is not None:
            dentro = dentro or item is dialogo
            item = item.parentItem()
        assert dentro
    assert len(focados) >= 2  # o Tab circula de verdade, sem ficar parado
    # O clique por trás, num ponto fora do cartão do diálogo, não chega à grade.
    ponto = cartao.mapToScene(cartao.boundingRect().center()).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(ponto.x(), 60))
    _clicar(app, cartao)
    assert app.janela.property("paginaAtual") == "todos"


def test_historico_e_conquistas_apagados_com_as_preferencias(app):
    _abrir_pelo_cartao(app, 0)
    app.historico.abrir(app.jogos[0].game_id)
    assert _esperar(lambda: app.achar("dialogoDoHistorico").property("visible") is True)
    assert app.achar("cartaoDoHistorico").property("enabled") is True
    assert app.achar("caixaDeConquistas").property("enabled") is True
    _abrir(app)
    assert app.achar("cartaoDoHistorico").property("enabled") is False
    assert app.achar("caixaDeConquistas").property("enabled") is False


def test_controle_nao_passa_com_as_preferencias_abertas(app):
    _abrir(app)
    assert app.janela.property("popupAberto") is True


def test_interruptor_grava_no_schema(app):
    _abrir(app, "import")
    antes = shared.schema.get_boolean("auto-import")
    _clique(app, "interruptor-auto-importChave")
    assert shared.schema.get_boolean("auto-import") is (not antes)
    assert _esperar(lambda: app.achar("interruptor-auto-import").property("checked") is (not antes))


def test_minimizar_apagado_com_contar_horas(app):
    shared.schema.set_boolean("playtime-tracking", False)
    shared.schema.set_boolean("minimize-after-launch", False)
    _abrir(app)
    assert app.achar("interruptor-minimize-after-launch").property("enabled") is True
    _clique(app, "interruptor-playtime-trackingChave")
    assert _esperar(lambda: app.achar("interruptor-minimize-after-launch").property("enabled") is False)
    assert app.achar("interruptor-minimize-after-launch").property("checked") is True
    assert shared.schema.get_boolean("minimize-after-launch") is True


def test_tempo_de_espera_pelo_spinbox(app):
    shared.schema["process-tracking-grace"] = 10
    _abrir(app)
    caixa = app.achar("linhaDaEsperaCaixa")
    assert (caixa.property("from"), caixa.property("to"), caixa.property("stepSize")) == (0, 120, 1)
    assert caixa.property("value") == 10
    caixa.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Up)
    assert shared.schema.get_int("process-tracking-grace") == 11
    QTest.keyClick(app.janela, Qt.Key.Key_PageUp)  # a página é de 5
    assert shared.schema.get_int("process-tracking-grace") == 16
    assert _esperar(lambda: app.achar("linhaDaEsperaCaixa").property("value") == 16)


def test_b25_subtitulos_de_preferencias_descrevem_o_comportamento():
    texto = "".join((QML / n).read_text(encoding="utf-8") for n in ("PaginaGeral.qml", "PaginaDeImportacao.qml"))
    assert (
        '"Minimiza a janela ao iniciar um jogo quando a contagem de horas '
        'está desligada"'
    ) in texto
    assert (
        '"Registra o tempo de cada sessão; quando o jogo não pode ser '
        'acompanhado automaticamente, abre uma janela compacta para encerrar '
        'a sessão"'
    ) in texto
    assert (
        '"Busca na Steam título, desenvolvedora, publicadora, lançamento, '
        'gênero, descrição, avaliações e compatibilidade com controle"'
    ) in texto


def _linha(app, nome):
    linha = app.achar(nome)
    return linha.property("titulo"), linha.property("subtitulo")


def test_textos_da_pagina_geral_e_da_importacao(app):
    _abrir(app)
    assert app.achar("grupoComportamentoGeral").property("titulo") == "Comportamento"
    esperado = {
        "interruptor-minimize-after-launch": (
            "Minimizar ao iniciar um jogo",
            "Minimiza a janela ao iniciar um jogo quando a contagem de horas está desligada",
        ),
        "interruptor-playtime-tracking": (
            "Contar horas de jogo",
            "Registra o tempo de cada sessão; quando o jogo não pode ser acompanhado automaticamente, abre uma "
            "janela compacta para encerrar a sessão",
        ),
        "interruptor-gamepad": ("Usar controle Xbox", "Permite navegar no aplicativo com um controle"),
        "interruptor-gamepad-rumble": (
            "Vibração",
            "Vibra ao mover a seleção, ao chegar ao fim da lista e ao iniciar um jogo",
        ),
        "interruptor-big-picture-ao-conectar": (
            "Abrir o Big Picture ao usar um controle",
            "Abre o Big Picture ao iniciar o aplicativo com um controle conectado ou ao conectar um controle na "
            "biblioteca",
        ),
        "interruptor-big-picture-som": ("Som ao trocar de capa", "Toca um clique curto a cada capa no Big Picture"),
        "linhaDaEspera": (
            "Tempo de espera ao fechar o jogo",
            "Segundos de espera após o jogo fechar antes de encerrar a sessão, para que um reinício do jogo não "
            "divida a sessão",
        ),
        "interruptor-auto-import": ("Importar jogos automaticamente", ""),
        "interruptor-remove-missing": ("Remover jogos desinstalados", ""),
        "interruptor-steam-metadata": (
            "Buscar metadados da Steam",
            "Busca na Steam título, desenvolvedora, publicadora, lançamento, gênero, descrição, avaliações e "
            "compatibilidade com controle",
        ),
        "interruptor-hltb-metadata": (
            "Buscar tempos do HowLongToBeat",
            "Busca as estimativas de história principal, extras e completista",
        ),
        "interruptor-shortcuts": ("Atalhos", ""),
        "linhaDaPasta": ("Pasta", None),
        "interruptor-shortcuts-recursive": ("Buscar em subpastas", ""),
        "interruptor-sgdb": ("Usar o SteamGridDB", "Baixa imagens ao adicionar ou importar jogos"),
        "interruptor-sgdb-prefer": ("Priorizar o SteamGridDB às imagens oficiais", ""),
        "interruptor-sgdb-animated": ("Preferir imagens animadas", ""),
    }
    shared.schema.set_boolean("shortcuts", True)
    for nome, (titulo, subtitulo) in esperado.items():
        assert _esperar(lambda n=nome: _achar(app.janela, n) is not None)
        t, s = _linha(app, nome)
        assert t == titulo, nome
        if subtitulo is not None:
            assert s == subtitulo, nome
    assert app.achar("grupoAtalhos").property("titulo") == "Atalhos"
    assert app.achar("grupoAtalhos").property("descricao") == (
        "Importa atalhos de jogos (.lnk e .url) de uma pasta. Funciona com Steam, Epic, Ubisoft Connect, "
        "Xbox/Microsoft Store e outros."
    )
    assert app.achar("grupoComportamentoDaImportacao").property("titulo") == "Comportamento"


def test_big_picture_sem_3d_explica_na_linha(app):
    from cartridges.modelos.preferencias import SEM_3D  # noqa: PLC0415

    app.preferencias._tem_3d = lambda: False  # noqa: SLF001
    shared.schema.set_boolean("gamepad", True)
    _abrir(app)
    for nome in ("interruptor-big-picture-ao-conectar", "interruptor-big-picture-som"):
        assert _esperar(lambda n=nome: app.achar(n).property("enabled") is False)
        assert app.achar(nome).property("subtitulo") == SEM_3D == "Requer uma placa de vídeo com aceleração 3D."


def test_pasta_dos_atalhos_em_texto_puro_no_formato_do_windows(app):
    shared.schema["shortcuts-location"] = "D:/Games & Emulators"
    shared.schema.set_boolean("shortcuts", True)
    _abrir(app, "import")
    subtitulo = app.achar("linhaDaPastaSubtitulo")
    assert _esperar(lambda: subtitulo.property("text") == "D:\\Games & Emulators")
    assert _avaliar(subtitulo, "textFormat") == Qt.TextFormat.PlainText.value


def test_sem_pasta_mostra_nenhuma_pasta_selecionada(app):
    shared.schema["shortcuts-location"] = ""
    shared.schema.set_boolean("shortcuts", True)
    _abrir(app, "import")
    assert _esperar(lambda: app.achar("linhaDaPastaSubtitulo").property("text") == "Nenhuma pasta selecionada")


def test_escolher_pasta_grava_o_caminho_e_url_vazia_nao_grava(app, tmp_path):
    from PySide6.QtCore import QUrl  # noqa: PLC0415

    shared.schema["shortcuts-location"] = "C:/Antes"
    app.preferencias.escolherPastaDosAtalhos(QUrl())
    assert shared.schema.get_string("shortcuts-location") == "C:/Antes"
    app.preferencias.escolherPastaDosAtalhos(QUrl.fromLocalFile(str(tmp_path)))
    assert shared.schema.get_string("shortcuts-location") == str(Path(tmp_path))


def test_linhas_dos_atalhos_so_com_atalhos_ligado(app):
    shared.schema.set_boolean("shortcuts", False)
    _abrir(app, "import")
    assert app.achar("linhaDaPasta").property("visible") is False
    assert app.achar("interruptor-shortcuts-recursive").property("visible") is False
    _clique(app, "interruptor-shortcutsChave")
    assert _esperar(lambda: app.achar("linhaDaPasta").property("visible") is True)
    assert app.achar("interruptor-shortcuts-recursive").property("visible") is True
    assert app.achar("linhaDaPasta").property("dica") == "Selecionar pasta"


def test_chave_do_sgdb_digitada_e_o_interruptor_acende(app):
    shared.schema["sgdb-key"] = ""
    shared.schema.set_boolean("sgdb", False)
    _abrir(app, "sgdb")
    assert app.achar("interruptor-sgdb").property("enabled") is False
    app.achar("campoDaChaveDoSgdb").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    for letra in "abc":
        QTest.keyClick(app.janela, letra)
    assert shared.schema.get_string("sgdb-key") == "abc"
    assert _esperar(lambda: app.achar("interruptor-sgdb").property("enabled") is True)


def test_descricao_da_autenticacao_e_o_link_abre_o_navegador_falso(app, monkeypatch):
    urls = []
    monkeypatch.setattr(open_uri, "abrir_url", lambda url: urls.append(url) or True)
    _abrir(app, "sgdb")
    grupo = app.achar("grupoAutenticacao")
    assert grupo.property("titulo") == "Autenticação"
    assert grupo.property("descricao") == (
        'É necessária uma chave da API para usar o SteamGridDB. '
        '<a href="https://www.steamgriddb.com/profile/preferences/api">Obtenha aqui</a>.'
    )
    descricao = app.achar("grupoAutenticacaoDescricao")
    assert _avaliar(descricao, "textFormat") == 4  # Text.StyledText
    QMetaObject.invokeMethod(
        descricao, "linkActivated", Qt.ConnectionType.DirectConnection,
        Q_ARG("QString", "https://www.steamgriddb.com/profile/preferences/api"),
    )  # fmt: skip
    assert urls == ["https://www.steamgriddb.com/profile/preferences/api"]


def test_grupos_do_plano_8_nao_aparecem(app):
    _abrir(app)
    todos = "\n".join(_textos(app.achar("dialogoDePreferencias")))
    for texto in ("Backup da sua biblioteca", "Atualizações", "Zona de perigo", "Barra superior", "Redefinir"):
        assert texto not in todos
