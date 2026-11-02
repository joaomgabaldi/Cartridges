# test_qml_preferencias.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tela das Preferências: o modal com abas, as páginas Geral, Importação e SteamGridDB (QML offscreen)."""

from pathlib import Path

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, QPoint, QPointF, Qt, QtMsgType, qInstallMessageHandler
from PySide6.QtCore import QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.utils import open_uri, window_geometry
from tests.apoio_qml_biblioteca import QML, _achar, _App, _esperar, _jogos
from tests.apoio_qml_detalhes import _abrir_pelo_cartao, _cartoes, _clicar, _foco_dentro_de
from tests.apoio_qml_preferencias import (  # noqa: F401  (as fixtures vêm junto)
    _abrir,
    _avaliar,
    _clique,
    _enabled,
    _linha,
    _textos,
    app,
    fitas_espiadas,
)


@pytest.mark.parametrize(("tecla", "modificador"), [
    (Qt.Key.Key_Return, Qt.KeyboardModifier.NoModifier),
    (Qt.Key.Key_Enter, Qt.KeyboardModifier.KeypadModifier),
])
def test_enter_aciona_interruptor_aba_e_fechar(app, tecla, modificador):
    _abrir(app)
    # O interruptor alterna com o Enter, como com o Espaço.
    chave = app.achar("interruptor-auto-importChave")
    antes = chave.property("checked")
    chave.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, tecla, modificador)
    assert _esperar(lambda: chave.property("checked") is (not antes))
    # A aba abre a sua página.
    app.achar("aba-import").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, tecla, modificador)
    assert _esperar(lambda: app.achar("paginaDeImportacao").property("visible") is True)
    # O X fecha.
    app.achar("botaoFecharPreferencias").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, tecla, modificador)
    assert _esperar(lambda: not app.preferencias.aberto)


def test_setas_trocam_de_aba_e_levam_o_foco(app):
    _abrir(app)
    app.achar("aba-general").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Right)
    assert app.achar("dialogoDePreferencias").property("aba") == "session"
    assert _foco_dentro_de(app, "aba-session")
    QTest.keyClick(app.janela, Qt.Key.Key_Left)
    assert app.achar("dialogoDePreferencias").property("aba") == "general"
    assert _foco_dentro_de(app, "aba-general")
    QTest.keyClick(app.janela, Qt.Key.Key_Left)  # na ponta, nada acontece
    assert app.achar("dialogoDePreferencias").property("aba") == "general"


def test_caixa_de_numero_tem_uma_parada_de_tab_e_segue_as_setas(app):
    _abrir(app, "general")
    caixa = app.achar("linhaDaEsperaCaixa")
    caixa.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    valor = caixa.property("value")
    QTest.keyClick(app.janela, Qt.Key.Key_Up)
    assert _esperar(lambda: caixa.property("value") == valor + 1)
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    foco = app.janela.property("activeFocusItem")
    assert foco is not caixa and foco.parentItem() is not caixa  # o item interno não é uma segunda parada
    QTest.keyClick(app.janela, Qt.Key.Key_Backtab)
    foco = app.janela.property("activeFocusItem")
    assert foco is caixa or foco.parentItem() is caixa  # editável (P35): a caixa passa o foco ao seu campo


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
    assert rotulos[:2] == ["Geral", "Personalização"] and "Importação" in rotulos and "SteamGridDB" in rotulos
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
    assert _achar(app.achar("dialogoDoHistorico"), "rolagemDoHistorico").property("enabled") is True
    assert app.achar("caixaDeConquistas").property("enabled") is True
    _abrir(app)
    assert _achar(app.achar("dialogoDoHistorico"), "rolagemDoHistorico").property("enabled") is False
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


def test_grupos_do_plano_8b_aparecem(app):
    """O backup e a Zona de perigo entraram no 8a (Task 7); "Atualizações" na Task 1 do 8b e "Barra superior" na Task 2."""
    _abrir(app)
    todos = "\n".join(_textos(app.achar("dialogoDePreferencias")))
    for texto in ("Barra superior", "Atualizações", "Backup da sua biblioteca", "Zona de perigo", "Redefinir Cartridges"):
        assert texto in todos


# region Atualizar metadados e capas (Task 3)


def _com_refresh_falso(monkeypatch):
    from cartridges import metadata_refresh  # noqa: PLC0415

    chamadas = []

    class Falso(metadata_refresh.MetadataRefresh):
        def start(self, games, only_missing=False):
            chamadas.append((games, only_missing))
            return True

    refresh = Falso()
    monkeypatch.setattr(metadata_refresh, "get_metadata_refresh", lambda: refresh)
    return refresh, chamadas


def _clique_em(botao):
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)


def test_escopo_dos_metadados_tem_tres_botoes_e_comeca_no_que_falta(app, store, make_game, monkeypatch):
    _refresh, chamadas = _com_refresh_falso(monkeypatch)
    jogo = make_game(game_id="a", has_hltb_times=False)
    store.add_game(jogo, {})
    _abrir(app, "import")
    assert app.achar("linhaDosMetadados").property("titulo") == "Atualizar metadados"
    assert app.achar("linhaDosMetadados").property("subtitulo") == "Busca dados para jogos já na biblioteca"
    assert app.achar("linhaDosMetadadosBotao").property("text") == "Atualizar"

    _clique(app, "linhaDosMetadadosBotao")
    dialogo = app.achar("dialogoDosMetadados")
    assert _esperar(lambda: dialogo.property("visible") is True)
    assert dialogo.property("titulo") == "Atualizar metadados"
    assert dialogo.property("corpo").startswith("Buscar o que falta atualiza 1 de 1 jogos")
    nomes = ("botaoCancelarDoDialogo", "botaoConfirmarDoDialogo", "botaoAlternativoDoDialogo")
    botoes = [_achar(dialogo, n) for n in nomes]
    assert [b.property("text") for b in botoes] == ["Cancelar", "Buscar o que falta", "Buscar tudo"]
    xs = [b.mapToScene(b.boundingRect().topLeft()).x() for b in botoes]
    assert xs == sorted(xs)
    assert _esperar(lambda: _foco_dentro_de(app, "botaoConfirmarDoDialogo"))

    _clique_em(botoes[2])  # Buscar tudo
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert chamadas == [([jogo], False)]


def test_confirmar_o_escopo_busca_so_o_que_falta_e_cancelar_nao_busca(app, store, make_game, monkeypatch):
    _refresh, chamadas = _com_refresh_falso(monkeypatch)
    jogo = make_game(game_id="a", has_hltb_times=False)
    store.add_game(jogo, {})
    _abrir(app, "import")
    dialogo = app.achar("dialogoDosMetadados")
    _clique(app, "linhaDosMetadadosBotao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)  # Esc vale como cancelar e não fecha as preferências
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert app.preferencias.aberto is True and not chamadas

    _clique(app, "linhaDosMetadadosBotao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    _clique_em(_achar(dialogo, "botaoConfirmarDoDialogo"))
    assert _esperar(lambda: chamadas == [([jogo], True)])


def test_barra_de_progresso_so_durante_a_atualizacao(app, monkeypatch):
    refresh, _ = _com_refresh_falso(monkeypatch)
    _abrir(app, "import")
    assert app.achar("linhaDosMetadadosBotao").property("visible") is True
    assert app.achar("linhaDosMetadadosProgresso").property("visible") is False
    assert app.achar("linhaDosMetadadosParar").property("visible") is False

    refresh.running, refresh.done, refresh.total = True, 3, 12
    refresh.progress.emit()
    assert _esperar(lambda: app.achar("linhaDosMetadadosProgresso").property("visible") is True)
    assert app.achar("linhaDosMetadadosProgresso").property("value") == pytest.approx(0.25)
    assert app.achar("linhaDosMetadadosProgressoTexto").property("text") == "3 de 12"
    assert app.achar("linhaDosMetadadosBotao").property("visible") is False
    parar = app.achar("linhaDosMetadadosParar")
    assert parar.property("visible") is True and parar.property("enabled") is True

    _clique(app, "linhaDosMetadadosParar")
    assert refresh.cancelled is True
    assert _esperar(lambda: app.achar("linhaDosMetadadosParar").property("enabled") is False)

    refresh.running = False
    refresh.progress.emit()
    assert _esperar(lambda: app.achar("linhaDosMetadadosProgresso").property("visible") is False)
    assert app.achar("linhaDosMetadadosBotao").property("visible") is True


def test_linha_dos_metadados_apagada_sem_as_duas_fontes(app):
    shared.schema.set_boolean("steam-metadata", True)
    _abrir(app, "import")
    assert app.achar("linhaDosMetadados").property("enabled") is True
    shared.schema.set_boolean("steam-metadata", False)
    shared.schema.set_boolean("hltb-metadata", False)
    assert _esperar(lambda: app.achar("linhaDosMetadados").property("enabled") is False)
    shared.schema.set_boolean("hltb-metadata", True)
    assert _esperar(lambda: app.achar("linhaDosMetadados").property("enabled") is True)


def test_atualizar_capas_apagado_sem_sgdb(app, store, make_game):
    from cartridges.store.managers.sgdb_manager import SgdbManager  # noqa: PLC0415
    from tests.apoio_capas import _ManagerDeCapas  # noqa: PLC0415

    store.add_game(make_game(game_id="a"), {})
    store.managers[SgdbManager] = gerente = _ManagerDeCapas()
    shared.schema.set_boolean("sgdb", False)
    _abrir(app, "sgdb")
    linha = app.achar("linhaDasCapas")
    assert linha.property("titulo") == "Atualizar capas"
    assert linha.property("subtitulo") == "Busca capas para jogos já na biblioteca"
    assert linha.property("enabled") is False

    app.preferencias.definirTexto("sgdb-key", "abc")
    app.preferencias.definir("sgdb", True)
    assert _esperar(lambda: app.achar("linhaDasCapas").property("enabled") is True)
    assert app.achar("linhaDasCapasOcupado").property("visible") is False

    _clique(app, "linhaDasCapasBotao")
    assert _esperar(lambda: app.achar("linhaDasCapasOcupado").property("visible") is True)
    assert app.achar("linhaDasCapasBotao").property("visible") is False
    for callback in gerente.callbacks:
        callback(gerente)
    assert _esperar(lambda: app.achar("linhaDasCapasBotao").property("visible") is True)
    assert app.achar("linhaDasCapasOcupado").property("visible") is False


# endregion


def test_foco_acompanha_o_botao_dos_metadados(app, store, make_game, monkeypatch):
    refresh, _ = _com_refresh_falso(monkeypatch)
    store.add_game(make_game(game_id="a", has_hltb_times=False), {})
    _abrir(app, "import")
    app.achar("linhaDosMetadadosBotao").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    refresh.running, refresh.done, refresh.total = True, 0, 1
    refresh.progress.emit()
    assert _esperar(lambda: _foco_dentro_de(app, "linhaDosMetadadosParar"))
    refresh.running = False
    refresh.progress.emit()
    assert _esperar(lambda: _foco_dentro_de(app, "linhaDosMetadadosBotao"))


def test_foco_das_capas_fica_no_dialogo_e_esc_fecha(app, store, make_game):
    from cartridges.store.managers.sgdb_manager import SgdbManager  # noqa: PLC0415
    from tests.apoio_capas import _ManagerDeCapas  # noqa: PLC0415

    store.add_game(make_game(game_id="a"), {})
    store.managers[SgdbManager] = gerente = _ManagerDeCapas()
    app.preferencias.definirTexto("sgdb-key", "abc")
    app.preferencias.definir("sgdb", True)
    _abrir(app, "sgdb")
    app.achar("linhaDasCapasBotao").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.achar("linhaDasCapasOcupado").property("visible") is True)
    assert _esperar(lambda: _foco_dentro_de(app, "linhaDasCapas"))
    for callback in gerente.callbacks:
        callback(gerente)
    assert _esperar(lambda: _foco_dentro_de(app, "linhaDasCapasBotao"))
    app.achar("linhaDasCapasBotao").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.preferencias.aberto)


def test_foco_levado_para_outro_controle_nao_e_roubado_ao_terminar(app, store, make_game, monkeypatch):
    refresh, _ = _com_refresh_falso(monkeypatch)
    store.add_game(make_game(game_id="a", has_hltb_times=False), {})
    _abrir(app, "import")
    app.achar("linhaDosMetadadosBotao").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    refresh.running, refresh.done, refresh.total = True, 0, 1
    refresh.progress.emit()
    assert _esperar(lambda: _foco_dentro_de(app, "linhaDosMetadadosParar"))
    app.achar("aba-sgdb").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    refresh.running = False
    refresh.progress.emit()
    _esperar()
    assert _foco_dentro_de(app, "aba-sgdb")


# region Personalização (Task 4)


def test_textos_da_personalizacao(app):
    _abrir(app, "session")
    assert app.achar("paginaDePersonalizacao").property("visible") is True
    assert app.achar("grupoBiblioteca").property("titulo") == "Biblioteca"
    assert _linha(app, "interruptor-cover-autoplay") == (
        "Reproduzir capas animadas automaticamente",
        "As capas animadas são reproduzidas na biblioteca automaticamente e em loop.",
    )
    assert app.achar("grupoAoIniciarUmJogo").property("titulo") == "Ao iniciar um jogo"
    assert app.achar("grupoAoIniciarUmJogo").property("descricao") == (
        "Move o Cartridges para outro monitor (se disponível) em vez de minimizá-lo para a barra de tarefas."
    )
    assert _linha(app, "interruptor-session-move-window") == ("Mover para outro monitor", "")
    assert app.achar("linhaDoMonitor").property("titulo") == "Monitor"
    assert app.achar("linhaDoMonitor").property("model") == ["Monitor 2"]
    assert app.achar("linhaIdentificarMonitores").property("titulo") == "Identificar monitores"
    assert app.achar("grupoPapelDeParede").property("titulo") == "Papel de parede"
    assert app.achar("grupoPapelDeParede").property("descricao") == (
        "Durante a sessão, substitui temporariamente o papel de parede dos outros monitores por uma imagem "
        "relacionada ao jogo."
    )
    assert _linha(app, "interruptor-session-wallpaper") == ("Trocar o papel de parede dos outros monitores", "")
    assert app.achar("campoDaChaveDoWallhaven").property("titulo") == "Chave da API do wallhaven (opcional)"


def test_monitor_apagado_com_o_interruptor_desligado_e_identificar_sempre_ativo(app):
    shared.schema.set_boolean("playtime-tracking", True)
    shared.schema.set_boolean("session-move-window", False)
    _abrir(app, "session")
    assert not _enabled(app, "linhaDoMonitor")
    assert _enabled(app, "linhaIdentificarMonitores")
    app.preferencias.definir("session-move-window", True)
    assert _esperar(lambda: _enabled(app, "linhaDoMonitor"))
    # Sem contar horas o grupo inteiro apaga, menos o "Identificar".
    app.preferencias.definir("playtime-tracking", False)
    assert _esperar(lambda: not _enabled(app, "linhaDoMonitor"))
    assert not _enabled(app, "interruptor-session-move-window")
    assert _enabled(app, "linhaIdentificarMonitores")


def test_sem_segundo_monitor_o_grupo_apaga_e_explica(app, monkeypatch):
    from tests.apoio_preferencias_qt import PRINCIPAL  # noqa: PLC0415

    monkeypatch.setattr(window_geometry, "monitors", lambda: [PRINCIPAL])
    _abrir(app, "session")
    assert not _enabled(app, "linhaDoMonitor")
    assert not _enabled(app, "interruptor-session-move-window")
    assert not _enabled(app, "interruptor-session-wallpaper")
    assert _enabled(app, "linhaIdentificarMonitores")
    assert _linha(app, "interruptor-session-move-window")[1] == "Requer um segundo monitor"
    assert _linha(app, "interruptor-session-wallpaper")[1] == "Requer um segundo monitor"


def test_chave_do_wallhaven_apagada_sem_o_papel_de_parede(app):
    shared.schema.set_boolean("playtime-tracking", True)
    shared.schema.set_boolean("session-wallpaper", False)
    _abrir(app, "session")
    assert not _enabled(app, "campoDaChaveDoWallhaven")
    app.preferencias.definir("session-wallpaper", True)
    assert _esperar(lambda: _enabled(app, "campoDaChaveDoWallhaven"))
    app.achar("campoDaChaveDoWallhaven").setProperty("text", "  abc ")
    QMetaObject.invokeMethod(app.achar("campoDaChaveDoWallhaven"), "editado", Qt.ConnectionType.DirectConnection)
    assert shared.schema.get_string("wallhaven-key") == "abc"


def test_placa_mostra_o_numero(app_qt):
    motor = QQmlEngine()
    from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    componente = QQmlComponent(motor, QUrl.fromLocalFile(str(QML / "PlacaDoMonitor.qml")))
    placa = componente.createWithInitialProperties({"numero": "2"})
    assert placa is not None, componente.errorString()
    assert "2" in _textos(placa)
    # SES-40: fundo e texto do tema, sem borda, número em 96 pt (128 px).
    ex = lambda o, t: QQmlExpression(QQmlEngine.contextForObject(o), o, t).evaluate()[0]  # noqa: E731
    assert ex(placa, "color.toString() === Tema.fundo.toString() && border.width === 0") is True
    numero = next(t for t in placa.childItems() if t.property("text") == "2")
    assert ex(numero, "font.pixelSize === 128 && color.toString() === Tema.texto.toString()") is True


def test_m14_sem_contar_horas_o_papel_de_parede_fica_apagado(app):
    # A metade das fitas (seguem configuráveis sem contar horas) entra na Task 5.
    shared.schema.set_boolean("playtime-tracking", False)
    _abrir(app, "session")
    assert not _enabled(app, "grupoPapelDeParede")
    assert not _enabled(app, "interruptor-session-wallpaper")
    app.preferencias.definir("playtime-tracking", True)
    assert _esperar(lambda: _enabled(app, "grupoPapelDeParede") and _enabled(app, "interruptor-session-wallpaper"))


# region Iluminação inteligente


def test_linhas_da_iluminacao_apagadas_sem_o_interruptor(app, fitas_espiadas):
    shared.schema.set_boolean("session-fita", False)
    _abrir(app, "session")
    assert app.achar("grupoIluminacao").property("titulo") == "Iluminação inteligente"
    assert app.achar("grupoIluminacao").property("descricao") == (
        "Muda a cor da iluminação inteligente enquanto o Cartridges está aberto: a cor do aplicativo fora do jogo e "
        "a cor do jogo durante a sessão. Ao fechar o aplicativo, a iluminação inteligente volta ao estado anterior."
    )
    assert _linha(app, "interruptor-session-fita") == ("Mudar a cor da iluminação inteligente", "1 dispositivo configurado")
    assert _linha(app, "linhaDoBrilhoDasFitas") == ("Brilho (%)", "Aplicado aos jogos sem brilho próprio definido")
    assert _linha(app, "linhaDoBrilhoPorDispositivo") == (
        "Brilho máximo por dispositivo", "Define o brilho máximo de cada dispositivo"
    )
    assert app.achar("linhaDoBrilhoPorDispositivo").property("dica") == "Ajustar o brilho de cada dispositivo"
    assert _linha(app, "linhaDaCorDoApp") == (
        "Cor do app", "A cor da iluminação inteligente com o aplicativo aberto e nenhum jogo em execução"
    )
    assert _linha(app, "linhaTestarFitas") == ("Testar", "Acende cada dispositivo na cor do aplicativo")
    assert app.achar("linhaTestarFitas").property("dica") == "Ligar a iluminação inteligente"
    caixa = app.achar("linhaDoBrilhoDasFitasCaixa")
    assert (caixa.property("from"), caixa.property("to"), caixa.property("stepSize")) == (1, 100, 1)
    assert app.achar("linhaDoBrilhoDasFitas").property("pagina") == 10
    dependentes = (
        "linhaDoBrilhoDasFitas", "linhaDoBrilhoPorDispositivo", "interruptor-fita-acompanha-tela",
        "linhaDaCorDoApp", "linhaTestarFitas",
    )  # fmt: skip
    assert _enabled(app, "interruptor-session-fita")
    assert [_enabled(app, n) for n in dependentes] == [False] * 5
    assert app.achar("linhaDaCorDoApp").property("opacity") == 0.5  # P23: a linha travada aparece apagada
    _clique(app, "interruptor-session-fitaChave")
    assert shared.schema.get_boolean("session-fita") is True
    assert fitas_espiadas == ["reacender"]
    assert _esperar(lambda: [_enabled(app, n) for n in dependentes] == [True] * 5)
    assert app.achar("linhaDaCorDoApp").property("opacity") == 1


def test_interruptor_das_fitas_apagado_sem_fita(app):
    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    assert not _enabled(app, "interruptor-session-fita")
    assert _linha(app, "interruptor-session-fita")[1] == "Nenhum dispositivo configurado"
    assert app.achar("interruptor-session-fita").property("checked") is False


def test_amostra_abre_o_seletor_e_a_cor_vai_ao_modelo(app, fitas_espiadas):
    from cartridges.utils import session_fita  # noqa: PLC0415

    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    assert app.achar("linhaDaCorDoAppAmostra").property("dica") == "Escolher a cor da iluminação inteligente"
    _clique(app, "linhaDaCorDoAppAmostra")
    assert _esperar(lambda: app.achar("linhaDaCorDoAppBalao").property("opened") is True)
    seletor = app.achar("linhaDaCorDoAppSeletor")
    # O seletor parte da cor do app (o roxo).
    assert abs(seletor.property("matiz") - session_fita.ROXO_DO_APP[0]) <= 1
    QMetaObject.invokeMethod(seletor, "mover", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", 120), Q_ARG("QVariant", 900))
    matiz, saturacao = session_fita.tom_do_app()
    assert abs(matiz - 120) <= 1 and abs(saturacao - 900) <= 2
    assert fitas_espiadas[-1] == session_fita.cor_do_app()
    assert _esperar(lambda: abs(app.achar("linhaDaCorDoApp").property("cor").hsvHueF() * 360 - 120) <= 1)


def test_voltar_a_cor_padrao_so_fora_do_roxo(app, fitas_espiadas):
    from cartridges.utils import session_fita  # noqa: PLC0415

    shared.schema.set_boolean("session-fita", True)
    _abrir(app, "session")
    assert app.achar("linhaDaCorDoAppVoltar").property("visible") is False
    session_fita.salvar_tom_do_app(200, 800)
    assert _esperar(lambda: app.achar("linhaDaCorDoAppVoltar").property("visible") is True)
    assert app.achar("linhaDaCorDoAppVoltar").property("dica") == "Voltar à cor padrão"
    _clique(app, "linhaDaCorDoAppVoltar")
    assert session_fita.tom_do_app() == session_fita.ROXO_DO_APP
    assert _esperar(lambda: app.achar("linhaDaCorDoAppVoltar").property("visible") is False)


def test_testar_troca_o_glifo_e_mostra_o_resultado(app, fitas_espiadas, monkeypatch):
    from cartridges.utils import session_fita  # noqa: PLC0415

    shared.schema.set_boolean("session-fita", True)
    import threading  # noqa: PLC0415

    solta = threading.Event()
    monkeypatch.setattr(session_fita, "aplicar", lambda *_a: solta.wait(5) and False)
    _abrir(app, "session")
    assert app.achar("linhaTestarFitas").property("glifo") == "\ue768"
    _clique(app, "linhaTestarFitasBotao")
    # Durante o teste o bot\u00e3o \u00e9 o de parar.
    assert _esperar(lambda: app.achar("linhaTestarFitas").property("glifo") == "\ue71a")
    assert app.achar("linhaTestarFitas").property("subtitulo") == "Testando\u2026"
    solta.set()
    assert _esperar(lambda: app.achar("linhaTestarFitas").property("subtitulo").startswith("Sem resposta: Centro."))
    assert app.achar("linhaTestarFitas").property("glifo") == "\ue768"


# endregion


# region O assistente da iluminação inteligente


@pytest.fixture(autouse=True)
def conta_da_tuya(tmp_path, monkeypatch):
    """A conta salva da Tuya vai para a pasta do teste: o assistente a lê ao abrir."""
    monkeypatch.setattr(shared, "tuya_conta_arquivo", tmp_path / "tuya_conta.json")
    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")


def _abrir_o_assistente(app):
    _abrir(app, "session")
    assert app.achar("linhaConfigurarFitas").property("titulo") == "Configurar a iluminação inteligente"
    assert app.achar("linhaConfigurarFitas").property("subtitulo") == "Busca os dispositivos na sua conta da Tuya"
    assert _enabled(app, "linhaConfigurarFitas")
    botao = app.achar("linhaConfigurarFitasBotao")
    botao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    dialogo = app.achar("dialogoDaConfiguracaoDasFitas")
    assert _esperar(lambda: dialogo.property("visible") is True)
    return dialogo, botao


def test_configurar_abre_o_assistente_com_a_conta_salva(app):
    from cartridges.utils import tuya_conta  # noqa: PLC0415

    tuya_conta.salvar(tuya_conta.Conta("chave-salva", "segredo-salvo", "eu"))
    dialogo, _botao = _abrir_o_assistente(app)
    textos = _textos(dialogo)
    for esperado in (
        "Configurar a iluminação inteligente",
        "Conta de desenvolvedor da Tuya",
        "Abrir o painel da Tuya",
        "Access ID (Client ID)",
        "Access Secret (Client Secret)",
        "Região",
        "Buscar dispositivos",
    ):
        assert esperado in textos
    assert app.achar("campoDoAccessId").property("text") == "chave-salva"
    assert app.achar("campoDoAccessSecret").property("text") == "segredo-salvo"
    # O segredo vai mascarado (TextInput.Password = 2).
    assert _avaliar(app.achar("campoDoAccessSecret"), "echoMode") == 2
    assert app.achar("regiaoDasFitas").property("currentIndex") == 1
    assert app.achar("avisoSemResultado").property("visible") is False
    assert app.preferencias.configuracaoDasFitas.pagina == "credenciais"


def test_dispositivos_do_assistente_em_texto_puro(app):
    """Review Focus 3: o nome do dispositivo vem da conta da Tuya e aparece como está."""
    dialogo, _botao = _abrir_o_assistente(app)
    nome = "<b>Sala</b> & Cia"
    from cartridges.utils.session_fita import Fita  # noqa: PLC0415

    app.preferencias.configuracaoDasFitas._mostrar([Fita(nome, "eb0", "192.0.2.10", "k")])  # noqa: SLF001
    assert _esperar(lambda: app.achar("dispositivoDasFitas-eb0").property("visible") is True)
    achados, pilha = [], [dialogo]
    while pilha:
        atual = pilha.pop()
        texto = atual.property("text")
        if isinstance(texto, str) and texto:
            achados.append((texto, _avaliar(atual, "textFormat")))
        pilha.extend(atual.childItems() if isinstance(atual, QQuickItem) else [])
    assert (nome, 0) in achados  # 0 = Text.PlainText
    assert ("Selecione os dispositivos", 0) in achados
    assert ("192.0.2.10", 0) in achados
    assert "Aplicar" in [t for t, _f in achados]


def test_dispositivo_sem_endereco_apagado(app):
    from cartridges.utils.session_fita import Fita  # noqa: PLC0415

    _abrir_o_assistente(app)
    app.preferencias.configuracaoDasFitas._mostrar([Fita("Sem IP", "eb1", "", "k"), Fita("Com IP", "eb2", "192.0.2.11", "k")])  # noqa: SLF001
    assert _esperar(lambda: app.achar("dispositivoDasFitas-eb1").property("visible") is True)
    assert app.achar("dispositivoDasFitas-eb1").property("enabled") is False
    assert app.achar("dispositivoDasFitas-eb1").property("subtitulo") == (
        "Não encontrado na rede. Verifique se o dispositivo está ligado."
    )
    assert app.achar("dispositivoDasFitas-eb2").property("enabled") is True
    assert app.achar("dispositivoDasFitas-eb1Chave").property("checked") is False
    # Marcar pela tela chega ao modelo.
    QMetaObject.invokeMethod(app.achar("dispositivoDasFitas-eb2Chave"), "click", Qt.ConnectionType.DirectConnection)
    marcado = {d["id"]: d["marcado"] for d in app.preferencias.configuracaoDasFitas.dispositivos}
    assert marcado == {"eb1": False, "eb2": True}


def test_aviso_de_busca_sem_resultado(app):
    dialogo, _botao = _abrir_o_assistente(app)
    app.preferencias.configuracaoDasFitas._mostrar([])  # noqa: SLF001
    assert _esperar(lambda: app.achar("avisoSemResultado").property("visible") is True)
    assert app.achar("avisoSemResultado").property("text") == "Nenhum dispositivo encontrado. Confira as credenciais e a região."
    assert "Buscar dispositivos" in _textos(dialogo)


def test_esc_fecha_o_assistente_e_volta_as_preferencias(app, flush_idle):
    dialogo, botao = _abrir_o_assistente(app)
    # O foco começa no primeiro campo.
    assert _esperar(lambda: app.achar("campoDoAccessId").property("activeFocus") is True)
    # O cartão das Preferências fica apagado por trás.
    assert app.achar("cartaoDasPreferencias").property("enabled") is False
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert app.preferencias.configuracaoDasFitas is None
    assert app.preferencias.aberto is True
    assert app.achar("cartaoDasPreferencias").property("enabled") is True
    assert _esperar(lambda: botao.hasActiveFocus())


# endregion


# region O assistente de calibração


@pytest.fixture
def calibracao_aberta(app, fitas_espiadas, monkeypatch):
    """O assistente aberto sobre duas fitas, sem acender nada (a prévia de uma fita só também é espiada)."""
    from cartridges.utils import session_fita  # noqa: PLC0415

    session_fita.gravar_fitas(
        [session_fita.Fita("<b>Sala</b> & Cia", "eb0", "192.0.2.10", "k"), session_fita.Fita("Quarto", "eb1", "192.0.2.11", "k")]
    )
    monkeypatch.setattr(session_fita, "previa_calibracao", lambda *_a: fitas_espiadas.append("so"))
    _abrir(app, "session")
    app.preferencias.abrirCalibracao()
    dialogo = app.achar("assistenteDeCalibracao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    return app, dialogo


def _centro_da_amostra(app, nome):
    from PySide6.QtCore import QPointF  # noqa: PLC0415

    amostra = app.achar(nome)
    ponto = amostra.mapToScene(QPointF(amostra.width() / 2, amostra.height() / 2)).toPoint()
    return app.janela.grabWindow().pixelColor(ponto)


def _perto(a, b):
    return max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) < 8


def test_calibracao_mostra_a_amostra_na_cor_da_etapa(calibracao_aberta):
    app, _dialogo = calibracao_aberta
    assistente = app.preferencias.calibracao
    assistente.escolher("eb0")
    assert _esperar(lambda: app.achar("amostraDaCalibracao").property("visible") is True)
    assert _esperar(lambda: _perto(_centro_da_amostra(app, "amostraDaCalibracao"), assistente.corNaTela))
    assistente.proxima()  # amarelo
    assert _esperar(lambda: _perto(_centro_da_amostra(app, "amostraDaCalibracao"), assistente.corNaTela))
    assert app.achar("amostraDaCalibracao").property("height") == 240


def test_temperatura_so_no_branco(calibracao_aberta):
    app, _dialogo = calibracao_aberta
    assistente = app.preferencias.calibracao
    assistente.escolher("eb0")

    def visiveis():
        return [
            app.achar(n).property("visible") is True
            for n in ("tomDaCalibracao-eb0", "intensidadeDaCalibracao-eb0", "temperaturaDaCalibracao-eb0")
        ]

    assert _esperar(lambda: visiveis() == [True, True, False])
    for _ in range(6):
        assistente.proxima()
    assert _esperar(lambda: visiveis() == [False, False, True])
    textos = _textos(app.achar("assistenteDeCalibracao"))
    assert "Mais quente" in textos and "Mais frio" in textos
    assert assistente.titulo == "Branco (7 de 7)"


def test_sliders_seguem_as_constantes_da_calibracao(calibracao_aberta):
    from cartridges.utils import calibracao  # noqa: PLC0415

    app, _dialogo = calibracao_aberta
    app.preferencias.calibracao.escolher("eb0")
    assert _esperar(lambda: app.achar("tomDaCalibracao-eb0").property("visible") is True)
    tom, intensidade = app.achar("tomDaCalibracao-eb0"), app.achar("intensidadeDaCalibracao-eb0")
    assert (tom.property("from"), tom.property("to")) == (-calibracao.TOM_MAXIMO, calibracao.TOM_MAXIMO)
    assert (intensidade.property("from"), intensidade.property("to")) == (
        calibracao.FATOR_MINIMO * 100, calibracao.FATOR_MAXIMO * 100
    )


def test_nomes_dos_dispositivos_em_texto_puro(calibracao_aberta):
    app, dialogo = calibracao_aberta
    nome = "<b>Sala</b> & Cia"

    def formatos():
        achados, pilha = [], [dialogo]
        while pilha:
            atual = pilha.pop()
            texto = atual.property("text")
            if isinstance(texto, str) and texto:
                achados.append((texto, _avaliar(atual, "textFormat")))
            pilha.extend(atual.childItems() if isinstance(atual, QQuickItem) else [])
        return achados

    # Na lista do início.
    assert (nome, 0) in formatos()  # 0 = Text.PlainText
    assert ("Todos os dispositivos", 0) in formatos()
    # E nos grupos da etapa de todos.
    app.preferencias.calibracao.escolher("__todos__")
    assert _esperar(lambda: app.achar("tomDaCalibracao-eb0").property("visible") is True)
    assert all(f == 0 for t, f in formatos() if nome in t)
    assert sum(1 for t, _f in formatos() if t == nome) >= 2


def test_textos_do_assistente_de_calibracao(calibracao_aberta):
    app, dialogo = calibracao_aberta
    # Os controles só existem com uma etapa na tela.
    app.preferencias.calibracao.escolher("eb0")
    assert _esperar(lambda: app.achar("tomDaCalibracao-eb0").property("visible") is True)
    textos = _textos(dialogo)
    for esperado in (
        "Calibrar as cores",
        "Cancelar",
        "Escolha o dispositivo a calibrar. Em cada etapa, ajuste os controles até a cor do dispositivo ficar igual à da "
        "tela. Para um resultado melhor, deixe o ambiente com pouca luz.",
        "Todos os dispositivos",
        "Ajusta todos ao mesmo tempo, cada um com os seus controles",
        "Testar calibração",
        "Restaurar",
        "Voltar",
        "Próximo",
        "Voltar aos ajustes",
        "Pausar",
        "Avançar",
        "Concluir",
        "Tom",
        "Intensidade",
        "Temperatura",
    ):
        assert esperado in textos, esperado


@pytest.mark.parametrize("nome", ["dialogoDaConfiguracaoDasFitas", "assistenteDeCalibracao"])
def test_modal_por_cima_nao_aparece_com_assistente_indefinido(app, nome):
    _abrir(app)  # com o pai visível, o `visible` do modal depende só do `assistente`
    modal = app.achar(nome)
    assert modal.property("visible") is False
    _avaliar(modal, "assistente = undefined")
    assert modal.property("visible") is False


def _clicar_botao(app, nome):
    """Um clique de verdade (mouse) no botão, esperando ele aparecer.

    O clique vai perto da borda direita: no `offscreen` a fonte é larga, a fila de botões passa da borda esquerda do
    cartão e o centro do primeiro cai na parte cortada.
    """
    assert _esperar(lambda: app.achar(nome).property("visible") is True), nome
    botao = app.achar(nome)
    ponto = botao.mapToScene(QPointF(botao.width() - 12, botao.height() / 2)).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)


def test_calibracao_clique_nos_botoes_de_ponta_a_ponta(calibracao_aberta, fitas_espiadas):
    from cartridges.utils import session_fita  # noqa: PLC0415

    app, _dialogo = calibracao_aberta
    assistente = app.preferencias.calibracao
    # Lista -> etapa: o dispositivo escolhido.
    _clicar_botao(app, "dispositivoDaCalibracao-eb0")
    assert assistente.paginaAtual == "etapa"
    # Restaurar volta a etapa ao neutro; Voltar da primeira etapa leva à lista.
    assistente.mudar_tom(-8)
    _clicar_botao(app, "botaoRestaurarCalibracao")
    assert assistente.calibracoes["eb0"].cores[0] == (0, 1.0)
    _clicar_botao(app, "botaoVoltarCalibracao")
    assert assistente.paginaAtual == "inicio"
    # Testar -> teste; Pausar vira Continuar e de volta; Avançar muda a cor.
    _clicar_botao(app, "botaoTestarCalibracao")
    assert assistente.paginaAtual == "teste"
    titulo = assistente.titulo
    _clicar_botao(app, "botaoPausarCalibracao")
    assert assistente.pausado is True
    assert _esperar(lambda: app.achar("botaoPausarCalibracao").property("text") == "Continuar")
    _clicar_botao(app, "botaoPausarCalibracao")
    assert assistente.pausado is False
    assert app.achar("botaoPausarCalibracao").property("text") == "Pausar"
    _clicar_botao(app, "botaoAvancarTeste")
    assert assistente.titulo != titulo
    # Voltar aos ajustes devolve à lista; Testar de novo e Concluir grava e fecha.
    _clicar_botao(app, "botaoVoltarAosAjustes")
    assert assistente.paginaAtual == "inicio"
    _clicar_botao(app, "botaoTestarCalibracao")
    assistente.mudar_tom(5)
    _clicar_botao(app, "botaoConcluirCalibracao")
    assert _esperar(lambda: app.achar("assistenteDeCalibracao").property("visible") is False)
    assert app.preferencias.calibracao is None
    assert [f.id for f in session_fita.fitas()] == ["eb0", "eb1"]


# endregion



# --- A busca (D69) ---


def _buscar(app, texto):
    app.achar("dialogoDePreferencias").setProperty("filtro", texto)
    assert _esperar(lambda: app.achar("campoDeBuscaDasPreferencias").property("text") == texto)


def _visivel(app, nome):
    return app.achar(nome).property("visible") is True


def test_buscar_brilho_mostra_as_linhas_das_duas_paginas(app):
    _abrir(app)
    _buscar(app, "brilho")
    assert _esperar(lambda: _visivel(app, "linhaDoBrilhoDasFitas"))
    assert _visivel(app, "linhaDoBrilhoPorDispositivo")
    assert not _visivel(app, "interruptor-sgdb")
    assert not _visivel(app, "abas")  # a barra de abas some


def test_busca_sem_acento_acha_iluminacao(app):
    _abrir(app)
    _buscar(app, "ILUMINACAO")
    assert _esperar(lambda: _visivel(app, "interruptor-session-fita"))
    assert _visivel(app, "linhaConfigurarFitas")
    assert not _visivel(app, "interruptor-gamepad")


def test_busca_no_subtitulo(app):
    _abrir(app)
    _buscar(app, "segundos de espera")
    assert _esperar(lambda: _visivel(app, "linhaDaEspera"))
    assert not _visivel(app, "interruptor-gamepad")


def test_grupo_sem_linhas_some_na_busca(app):
    _abrir(app)
    _buscar(app, "brilho")
    assert _esperar(lambda: _visivel(app, "grupoIluminacao"))
    assert not _visivel(app, "grupoComportamentoGeral")
    assert not _visivel(app, "grupoBiblioteca")


def test_linha_escondida_por_regra_continua_escondida_na_busca(app):
    app.preferencias.definir("shortcuts", False)
    _abrir(app)
    _buscar(app, "pasta")
    assert _esperar(lambda: _visivel(app, "grupoAtalhos") is False)
    assert not _visivel(app, "linhaDaPasta")


def test_nenhum_resultado(app):
    _abrir(app)
    assert not _visivel(app, "estadoSemResultadoDasPreferencias")
    _buscar(app, "zzzzzz")
    assert _esperar(lambda: _visivel(app, "estadoSemResultadoDasPreferencias"))
    assert app.achar("estadoSemResultadoDasPreferencias").property("titulo") == "Nenhum resultado encontrado"
    _buscar(app, "brilho")
    assert _esperar(lambda: not _visivel(app, "estadoSemResultadoDasPreferencias"))


def test_esc_limpa_a_busca_e_depois_fecha(app):
    _abrir(app)
    campo = app.achar("campoDeBuscaDasPreferencias")
    campo.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    for tecla in (Qt.Key.Key_B, Qt.Key.Key_R, Qt.Key.Key_I):
        QTest.keyClick(app.janela, tecla)
    assert _esperar(lambda: campo.property("text") == "bri")
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: campo.property("text") == "")
    assert app.preferencias.aberto
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.preferencias.aberto)


def test_limpar_volta_a_aba_de_antes(app):
    _abrir(app, "import")
    _buscar(app, "brilho")
    assert _esperar(lambda: _visivel(app, "linhaDoBrilhoDasFitas"))
    _buscar(app, "")
    assert _esperar(lambda: not _visivel(app, "linhaDoBrilhoDasFitas"))
    assert _visivel(app, "paginaDeImportacao")
    assert app.achar("dialogoDePreferencias").property("aba") == "import"


def test_ctrl_f_leva_ao_campo(app):
    _abrir(app)
    campo = app.achar("campoDeBuscaDasPreferencias")
    app.achar("aba-general").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert campo.property("activeFocus") is not True
    QTest.keyClick(app.janela, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert _esperar(lambda: campo.property("activeFocus") is True)


def test_filtro_nao_esvazia_os_assistentes_abertos_por_cima(app, fitas_espiadas, monkeypatch):
    from cartridges.utils import session_fita  # noqa: PLC0415

    monkeypatch.setattr(session_fita, "previa_calibracao", lambda *_a: None)
    _abrir(app, "session")
    _buscar(app, "brilho")
    assert _esperar(lambda: _visivel(app, "linhaDoBrilhoDasFitas"))
    app.preferencias.abrirBrilhoPorDispositivo()
    assert _esperar(lambda: _visivel(app, "brilhoDoDispositivo-eb0"))
    app.preferencias.abrirCalibracao()
    assert _esperar(lambda: _visivel(app, "dispositivoDaCalibracao-eb0"))
    _buscar(app, "fitas")
    app.preferencias.abrirConfiguracaoDasFitas()
    assert _esperar(lambda: _visivel(app, "campoDoAccessId"))
    assert _visivel(app, "grupoDaContaDaTuya")


def test_buscar_epic_mostra_a_linha_da_conta(app):
    _abrir(app)
    _buscar(app, "epic")
    assert _esperar(lambda: _visivel(app, "botaoDaConta_epic"))
    assert not _visivel(app, "botaoDaConta_microsoft")
    assert not _visivel(app, "botaoDaConta_ea")


def test_fechar_com_texto_e_reabrir_volta_com_campo_vazio_e_abas(app):
    _abrir(app)
    _buscar(app, "brilho")
    assert not _visivel(app, "abas")
    app.preferencias.fechar()
    assert _esperar(lambda: not _visivel(app, "dialogoDePreferencias"))
    _abrir(app)
    assert app.achar("campoDeBuscaDasPreferencias").property("text") == ""
    assert _visivel(app, "abas")


def test_loader_das_contas_some_na_busca_sem_conta(app):
    _abrir(app)
    _buscar(app, "brilho")
    assert _esperar(lambda: _visivel(app, "linhaDoBrilhoDasFitas"))
    assert not _visivel(app, "carregadorDasContas")
    assert _esperar(lambda: app.achar("paginaDasConquistas").property("implicitHeight") == 0)


def test_sem_avisos_do_qml_ao_abrir_e_fechar(app_qt):
    avisos = []
    anterior = qInstallMessageHandler(lambda tipo, _ctx, msg: avisos.append(msg) if tipo in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg) else None)
    try:
        janela = _App(_jogos((1, "Alfa", {})))
        _abrir(janela)
        assert janela.preferencias.fechar() is not False
        assert _esperar(lambda: janela.achar("dialogoDePreferencias").property("visible") is False)
        janela.fechar()
    finally:
        qInstallMessageHandler(anterior)
    assert [a for a in avisos if "DialogoDePreferencias" in a] == []


def test_ctrl_f_leva_ao_campo_de_busca_e_com_aviso_aberto_nao_tira_o_foco_do_aviso(app):
    _abrir(app)
    app.achar("botaoFecharPreferencias").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    assert _esperar(lambda: app.achar("campoDeBuscaDasPreferencias").property("activeFocus") is True)

    # Um aviso por cima das Preferências (a fila de diálogos do app): o Ctrl+F é dele, o foco fica no aviso.
    app.achar("botaoFecharPreferencias").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    app.aplicativo.pedir_dialogo("Aviso", "Corpo", [], lambda: None)
    assert _esperar(lambda: app.achar("camadaDeAvisos").property("dialogoAberto") is True)
    assert _esperar(lambda: _foco_dentro_de(app, "camadaDeAvisos"))
    QTest.keyClick(app.janela, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    _esperar()
    assert app.achar("campoDeBuscaDasPreferencias").property("activeFocus") is False
    assert _foco_dentro_de(app, "camadaDeAvisos")


def _itens_com_nome(raiz, prefixo):
    achados, pilha = [], [raiz]
    while pilha:
        atual = pilha.pop()
        if atual.objectName().startswith(prefixo) and not atual.objectName().endswith("Chave"):
            achados.append(atual)
        pilha.extend(atual.childItems())
    return achados


def test_foco_num_campo_abaixo_da_dobra_rola_a_pagina(app):
    """O `dentro()`/`contem()` subiam por `parentItem` (inexistente no QML): a rolagem não seguia o foco."""
    _abrir(app, "session")
    assert app.achar("rolagemDasPreferencias").property("contentY") == 0
    interruptores = [i for i in _itens_com_nome(app.achar("rolagemDasPreferencias"), "interruptor-") if i.property("enabled")]
    ultimo = max(interruptores, key=lambda i: i.mapToScene(QPointF(0, 0)).y())  # o mais baixo da página
    assert ultimo.mapToScene(QPointF(0, 0)).y() > app.achar("rolagemDasPreferencias").mapToScene(QPointF(0, 0)).y() + app.achar("rolagemDasPreferencias").height()
    ultimo.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: app.achar("rolagemDasPreferencias").property("contentY") > 0)


def test_foco_que_passa_pela_propria_linha_ainda_volta_ao_botao_ao_terminar(app, store, make_game, monkeypatch):
    """O `_dentro()` subia por `parentItem` (inexistente no QML): qualquer foco num filho da linha contava como "saiu"."""
    refresh, _ = _com_refresh_falso(monkeypatch)
    store.add_game(make_game(game_id="a", has_hltb_times=False), {})
    _abrir(app, "import")
    app.achar("linhaDosMetadadosBotao").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    refresh.running, refresh.done, refresh.total = True, 0, 1
    refresh.progress.emit()
    assert _esperar(lambda: _foco_dentro_de(app, "linhaDosMetadadosParar"))
    assert _esperar(lambda: app.achar("linhaDosMetadados").property("_focoNaLinha") is True)
    # O foco passa pela linha e volta ao botão de parar (ambos dentro dela): nada disso é "a pessoa foi embora".
    app.achar("linhaDosMetadados").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    app.achar("linhaDosMetadadosParar").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _esperar()
    assert app.achar("linhaDosMetadados").property("_focoNaLinha") is True
    refresh.running = False
    refresh.progress.emit()
    assert _esperar(lambda: _foco_dentro_de(app, "linhaDosMetadadosBotao"))
