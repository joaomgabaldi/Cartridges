# test_qml_edicao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O diálogo de edição e o "Adicionar jogo" (QML offscreen, sem a ponte do QWindowKit)."""

import pytest
from PySide6.QtCore import Q_ARG, QCoreApplication, QMetaObject, QPoint, QPointF, Qt, QtMsgType, QUrl, qInstallMessageHandler
from PySide6.QtGui import QColor, QGuiApplication, QWheelEvent
from PySide6.QtQml import QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.utils import session_fita
from tests.apoio_edicao import jogo
from tests.apoio_fita import pastas  # noqa: F401  # a pasta descartável das fitas (autouse)
from tests.apoio_qml_biblioteca import _achar, _App, _esperar
from tests.apoio_qml_detalhes import _abrir_pelo_cartao, _cartoes, _foco_dentro_de


@pytest.fixture(autouse=True)
def _sem_jogo_de_verdade(monkeypatch):
    monkeypatch.setattr(Jogo, "launch", lambda self, *a: True)


@pytest.fixture
def app(app_qt, store, monkeypatch):
    """A janela com três jogos de verdade na store (a `edicao` grava nela)."""
    jogos = [
        jogo(store, 1, name="Alfa", developer="Dev A", genre="Ação", rating=3, executable='"C:\\Jogos\\alfa.exe"'),
        jogo(store, 2, name="Beta"),
        jogo(store, 3, name="Gama"),
    ]
    janela = _App(jogos)
    monkeypatch.setattr(shared, "aplicativo", janela.aplicativo, raising=False)
    yield janela
    janela.fechar()


def _avaliar(objeto, expressao):
    valor = QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]
    return valor.toVariant() if hasattr(valor, "toVariant") else valor


def _rotulos(menu):
    return _avaliar(menu, "(function(){var r=[];for(var i=0;i<count;i++)if(itemAt(i).height>0)r.push(itemAt(i).text);return r})()")


def _clique(app, nome):
    QMetaObject.invokeMethod(app.achar(nome), "click", Qt.ConnectionType.DirectConnection)


def test_fechar_as_preferencias_com_o_editor_aberto_devolve_o_foco_ao_editor(app):
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("dialogoDeEdicao").property("visible") is True)
    app.janela.contentItem().forceActiveFocus(Qt.FocusReason.OtherFocusReason)  # nada a que voltar
    assert app.preferencias.abrir()
    assert _esperar(lambda: app.achar("dialogoDePreferencias").property("visible") is True)
    app.preferencias.fechar()
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDeEdicao"))


def test_editar_preenche_os_campos(app):
    app.edicao.abrir("shortcuts_z1")
    modelo = app.edicao
    assert modelo.aberto is True
    assert modelo.titulo == "Detalhes do jogo"
    assert modelo.rotuloDoAplicar == "Aplicar"
    assert (modelo.nome, modelo.desenvolvedora, modelo.genero, modelo.nota) == ("Alfa", "Dev A", "Ação", 3)
    assert modelo.executavel == '"C:\\Jogos\\alfa.exe"'
    # O QML mostra o que o modelo guarda.
    assert _esperar(lambda: app.achar("campoNome").property("text") == "Alfa")
    assert app.achar("campoDesenvolvedora").property("text") == "Dev A"
    assert app.achar("dialogoDeEdicao").property("visible") is True


def test_adicionar_titulo_e_botao(app):
    app.edicao.adicionar()
    assert app.edicao.aberto is True
    assert app.edicao.titulo == "Adicionar novo jogo"
    assert app.edicao.rotuloDoAplicar == "Adicionar"
    assert app.edicao.nome == "" and app.edicao.conquistas is True
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("text") == "Adicionar")


def test_adicionar_com_dialogo_aberto_nao_abre_outro(app):
    app.edicao.adicionar()
    app.edicao.nome = "Digitado"
    app.edicao.adicionar()
    app.edicao.abrir("shortcuts_z2")
    assert app.edicao.nome == "Digitado" and app.edicao.titulo == "Adicionar novo jogo"


def test_erro_de_validacao_mostra_dialogo_e_nao_fecha(app):
    app.edicao.adicionar()
    app.edicao.aplicar()
    erros = app.achar("dialogoDeErros")
    assert _esperar(lambda: erros.property("visible") is True)
    assert erros.property("titulo") == "Não foi possível adicionar o jogo"
    assert erros.property("corpo") == "O título do jogo não pode ficar vazio."
    assert app.edicao.aberto is True
    # Fechado o erro, o diálogo de edição segue aberto e com o foco.
    QMetaObject.invokeMethod(erros, "fechar", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: erros.property("visible") is False)
    assert app.edicao.aberto is True
    assert _esperar(lambda: _foco_dentro_de(app, "dialogoDeEdicao"))


def _foco_dentro_de(app, nome):
    item = app.janela.property("activeFocusItem")
    while item is not None:
        if item.objectName() == nome:
            return True
        item = item.parentItem()
    return False


def test_aplicar_grava_e_volta_aos_detalhes(app):
    _abrir_pelo_cartao(app, 0)
    _clique(app, "botaoEditar")
    assert _esperar(lambda: app.edicao.aberto)
    assert app.edicao.nome == "Alfa"
    app.edicao.nome = "Alfa Novo"
    app.edicao.aplicar()
    assert app.edicao.aberto is False
    assert shared.store.get("shortcuts_z1").name == "Alfa Novo"
    assert app.janela.property("paginaAtual") == "jogo"
    assert _esperar(lambda: app.detalhes.nome == "Alfa Novo")
    assert app.janela.property("tituloDaBarra") == "Alfa Novo"


def test_adicionar_cria_o_jogo_na_store(app):
    app.edicao.adicionar()
    app.edicao.nome = "Jogo novo"
    app.edicao.executavel = "cmd /c exit"
    app.edicao.aplicar()
    assert app.edicao.aberto is False
    novo = shared.store.get("imported_1")
    assert novo is not None and novo.name == "Jogo novo"


def test_ocupado_bloqueia_aplicar_e_enter(app):
    app.edicao.abrir("shortcuts_z1")
    app.edicao.iniciar_operacao()
    assert app.edicao.ocupado is True
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is False)
    app.edicao.nome = "Mudou"
    app.edicao.aplicar()
    assert app.edicao.aberto is True and shared.store.get("shortcuts_z1").name == "Alfa"
    # Enter na linha do executável também é bloqueado.
    app.achar("campoExecutavel").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    _esperar()
    assert app.edicao.aberto is True and shared.store.get("shortcuts_z1").name == "Alfa"
    app.edicao.terminar_operacao()
    assert app.edicao.ocupado is False
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is True)
    app.achar("campoExecutavel").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.edicao.aberto is False)
    assert shared.store.get("shortcuts_z1").name == "Mudou"


def test_loading_operations_balance(app):
    """Duas operações sobrepostas: o Aplicar só volta quando a última termina."""
    app.edicao.abrir("shortcuts_z1")
    aplicar = app.achar("botaoAplicarDaEdicao")
    assert _esperar(lambda: aplicar.property("enabled") is True)
    app.edicao.iniciar_operacao()
    app.edicao.iniciar_operacao()
    assert _esperar(lambda: aplicar.property("enabled") is False)
    app.edicao.terminar_operacao()
    _esperar()
    assert app.edicao.ocupado is True and aplicar.property("enabled") is False, "uma ainda está em andamento"
    app.edicao.terminar_operacao()
    assert _esperar(lambda: aplicar.property("enabled") is True)


def test_an_extra_end_never_drives_the_counter_negative(app):
    """Uma thread que termina duas vezes não pode deixar o Aplicar impossível de bloquear."""
    app.edicao.abrir("shortcuts_z1")
    app.edicao.terminar_operacao()
    app.edicao.terminar_operacao()
    assert app.edicao.ocupado is False
    app.edicao.iniciar_operacao()
    assert app.edicao.ocupado is True
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is False)


@pytest.mark.parametrize(("gravado", "posicao"), [(None, 0), ("full", 1), ("partial", 2)])
def test_controller_support_round_trips(app, store, gravado, posicao):
    """A linha é o único lugar onde o valor se digita à mão: o mapa valor↔posição vale nos dois sentidos."""
    jogo(store, 9, controller_support=gravado)
    app.edicao.abrir("shortcuts_z9")
    assert app.edicao.controleIndice == posicao
    app.edicao.controleIndice = (posicao + 1) % 3
    app.edicao.controleIndice = posicao
    assert app.edicao._form.controle == gravado  # noqa: SLF001


def _pasta_de_jogo(tmp_path):
    """Pasta que o app reconhece como a de um jogo só: tem desinstalador."""
    pasta = tmp_path / "Jogo"
    pasta.mkdir()
    (pasta / "unins000.exe").write_bytes(b"")
    (pasta / "jogo.exe").write_bytes(b"")
    return f'"{pasta / "jogo.exe"}"'


def _aberto_e_visivel(app, nome):
    assert _esperar(lambda: app.achar("dialogoDeEdicao").property("visible") is True)
    _esperar()
    return app.achar(nome).property("visible") is True


def test_the_folder_button_follows_the_executable_field(app, tmp_path):
    """Segue o que se digita, não o que o diálogo abriu: trocar o .exe por um steam:// é uma edição comum."""
    (tmp_path / "halo.exe").write_bytes(b"")
    app.edicao.adicionar()
    app.edicao.executavel = f'start "" "{tmp_path}\\halo.exe"'
    assert _aberto_e_visivel(app, "botaoAbrirPasta") is True
    app.edicao.executavel = 'start "" "steam://rungameid/440"'
    assert _aberto_e_visivel(app, "botaoAbrirPasta") is False


def test_the_folder_button_is_hidden_on_an_empty_dialog(app):
    """O "Adicionar jogo" começa sem comando: não há pasta a abrir."""
    app.edicao.adicionar()
    assert _aberto_e_visivel(app, "botaoAbrirPasta") is False


def test_rastrear_processo_some_quando_a_pasta_do_jogo_e_reconhecida(app, tmp_path):
    """Com a pasta reconhecida o tempo já é contado por ela: a opção de rastrear pelo nome não aparece."""
    app.edicao.adicionar()
    app.edicao.executavel = _pasta_de_jogo(tmp_path)
    app.edicao.rastrearProcesso = True
    assert _aberto_e_visivel(app, "alternanciaDeRastreio") is False
    assert app.achar("campoProcesso").property("visible") is False


def test_rastrear_processo_aparece_para_jogo_lancado_pela_loja(app):
    """Um steam:// não diz onde o jogo mora: sem o nome do executável, a sessão seria manual."""
    app.edicao.adicionar()
    app.edicao.executavel = "steam://rungameid/620"
    assert _aberto_e_visivel(app, "alternanciaDeRastreio") is True


def test_rastrear_processo_ja_abre_escondido_para_jogo_com_pasta(app, store, tmp_path):
    """Ao abrir um jogo existente, a visibilidade vem do comando gravado, sem nada digitado."""
    jogo(store, 9, executable=_pasta_de_jogo(tmp_path), track_process=True, process_executable="jogo.exe")
    app.edicao.abrir("shortcuts_z9")
    assert _aberto_e_visivel(app, "alternanciaDeRastreio") is False
    assert app.achar("campoProcesso").property("visible") is False


def test_clicar_na_nota_atual_remove(app):
    app.edicao.adicionar()
    app.edicao.definirNota(3)
    assert app.edicao.nota == 3
    app.edicao.definirNota(3)
    assert app.edicao.nota == 0
    app.edicao.definirNota(2)
    app.edicao.definirNota(4)
    assert app.edicao.nota == 4


def test_menu_do_jogo_tem_editar_e_remover(app):
    menu = app.achar("menuDoJogo")
    assert _rotulos(menu) == ["Editar", "Remover"]
    menu.setProperty("jogoId", "shortcuts_z2")
    _clique(app, "itemEditar")
    assert _esperar(lambda: app.edicao.aberto)
    assert app.edicao.nome == "Beta"


def test_clique_direito_abre_editar(app):
    cartao = next(c for c in _cartoes(app) if c.property("nome") == "Gama")
    ponto = cartao.mapToScene(cartao.boundingRect().center()).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, ponto)
    assert _esperar(lambda: app.edicao.aberto)
    assert app.edicao.nome == "Gama"


def test_menu_mais_tem_adicionar_acima_de_importar(app):
    menu = app.achar("menuDeAdicionar")
    assert _rotulos(menu) == ["Adicionar jogo", None, "Importar"]
    _clique(app, "itemAdicionarJogo")
    assert _esperar(lambda: app.edicao.aberto)
    assert app.edicao.titulo == "Adicionar novo jogo"


def test_zerado_que_saiu_da_store_fecha_sem_erro_e_sem_gravar(app, store):
    zerado = jogo(store, 40, removed=True, status="beaten", playtime=120)
    app.edicao.abrir(zerado.game_id)
    assert app.edicao.aberto is True
    store.excluir(zerado, apagar_sessoes=False)
    app.edicao.nome = ""  # inválido, mas o guarda vem antes da validação
    pedidos = []
    app.aplicativo.dialogoPedido.connect(lambda *a: pedidos.append(a))
    salvou = []
    zerado.salvar.connect(lambda: salvou.append(1))
    app.edicao.aplicar()
    _esperar()
    assert app.edicao.aberto is False
    assert pedidos == [] and salvou == []
    assert store.get(zerado.game_id) is None and zerado.name == "Jogo 40"


def test_zerado_esconde_executavel_e_atualizacoes(app, store):
    zerado = jogo(store, 41, removed=True, status="beaten")
    app.edicao.abrir(zerado.game_id)
    assert app.edicao.zerado is True
    assert _esperar(lambda: app.achar("campoNome").property("visible") is True)
    assert app.achar("campoExecutavel").property("visible") is False
    assert app.achar("alternanciaDeAtualizacoes").property("visible") is False
    app.edicao.cancelar()
    app.edicao.abrir("shortcuts_z1")  # um jogo comum mostra os dois grupos
    assert _esperar(lambda: app.achar("campoExecutavel").property("visible") is True)
    assert app.achar("alternanciaDeAtualizacoes").property("visible") is True


def test_textos_de_terceiros_em_texto_puro(app, store):
    jogo(store, 50, name="A & <b>B</b>", developer="<i>Dev</i>", executable="<u>x</u>")
    app.edicao.abrir("shortcuts_z50")
    dialogo = app.achar("dialogoDeEdicao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    textos, pilha = [], [dialogo]
    while pilha:
        atual = pilha.pop()
        # O número da `LinhaDeNumero` é um TextInput (só dígitos): não tem `textFormat`.
        if isinstance(atual, QQuickItem) and atual.metaObject().className().startswith("QQuickText") and "Input" not in atual.metaObject().className():
            textos.append(atual)
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
        pilha.extend(atual.children())
    assert len(textos) > 20
    for texto in textos:
        assert _avaliar(texto, "textFormat") == 0, texto.property("text")  # Text.PlainText


def test_esc_cancela_sem_gravar_e_devolve_o_foco(app):
    _abrir_pelo_cartao(app, 0)
    _clique(app, "botaoEditar")
    assert _esperar(lambda: _foco_dentro_de(app, "campoNome"))
    app.edicao.nome = "Nao grava"
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.edicao.aberto)
    assert shared.store.get("shortcuts_z1").name == "Alfa"
    assert _esperar(lambda: _foco_dentro_de(app, "botaoEditar"))


def test_tab_gira_dentro_do_dialogo(app):
    app.edicao.adicionar()
    assert _esperar(lambda: _foco_dentro_de(app, "campoNome"))
    dialogo = app.achar("dialogoDeEdicao")
    for _ in range(40):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        item = app.janela.property("activeFocusItem")
        dentro = False
        while item is not None:
            dentro = dentro or item is dialogo
            item = item.parentItem()
        assert dentro
    # Shift+Tab a partir do primeiro item (o botão do SteamGridDB, na capa) cai no último botão, sem sair do diálogo.
    app.achar("botaoEscolherCapaSgdb").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    assert _esperar(lambda: _foco_dentro_de(app, "botaoAplicarDaEdicao"))


def _fora_do_dialogo(app):
    return not _foco_dentro_de(app, "dialogoDeEdicao")


def test_foco_volta_a_grade_depois_do_adicionar_pelo_menu(app):
    botao = app.achar("botaoAdicionar")
    botao.forceActiveFocus()
    _clique(app, "botaoAdicionar")
    menu = app.achar("menuDeAdicionar")
    assert _esperar(lambda: menu.property("opened") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.edicao.aberto)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.edicao.aberto)
    assert _esperar(lambda: _fora_do_dialogo(app) and app.janela.property("activeFocusItem") is not None)
    # Uma tecla chega à página: a grade passa a mostrar a seleção por teclado.
    QTest.keyClick(app.janela, Qt.Key.Key_Right)
    assert _esperar(lambda: app.achar("grade").property("porTeclado") is True)


def test_foco_volta_a_grade_depois_do_editar_pelo_menu_do_jogo(app):
    cartao = _cartoes(app)[0]
    cartao.forceActiveFocus()
    QMetaObject.invokeMethod(cartao, "abrirMenu", Qt.ConnectionType.DirectConnection)
    menu = app.achar("menuDoJogo")
    assert _esperar(lambda: menu.property("opened") is True)
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.edicao.aberto)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not app.edicao.aberto)
    assert _esperar(lambda: _fora_do_dialogo(app) and app.janela.property("activeFocusItem") is not None)
    QTest.keyClick(app.janela, Qt.Key.Key_Right)
    assert _esperar(lambda: app.achar("grade").property("porTeclado") is True)


def test_appid_invalido_fica_vermelho_e_bloqueia_o_aplicar(app):
    app.edicao.abrir("shortcuts_z1")
    assert app.edicao.appidValido is True
    app.edicao.appid = "12a"
    assert app.edicao.appidValido is False
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is False)
    assert app.achar("campoAppid").property("erro") is True
    app.edicao.aplicar()  # o Enter nas linhas ainda cai na validação: o erro é dito
    assert _esperar(lambda: app.achar("dialogoDeErros").property("visible") is True)
    assert app.achar("dialogoDeErros").property("corpo") == "O AppID da Steam deve conter apenas números."
    app.edicao.appid = "123"
    assert app.edicao.appidValido is True
    assert _esperar(lambda: app.achar("botaoAplicarDaEdicao").property("enabled") is True)
    assert app.achar("campoAppid").property("erro") is False


def test_zerado_virado_desinstalado_comum_sai_dos_detalhes(app, store):
    zerado = jogo(store, 60, removed=True, status="beaten")
    app.loja.por_id[zerado.game_id] = zerado
    QMetaObject.invokeMethod(app.janela, "abrirDetalhes", Qt.ConnectionType.DirectConnection, Q_ARG("QVariant", zerado.game_id))
    assert _esperar(lambda: app.janela.property("paginaAtual") == "jogo")
    _clique(app, "botaoEditar")
    assert _esperar(lambda: app.edicao.aberto)
    app.edicao.statusIndice = 0  # "Sem status": deixa de ser zerado
    app.edicao.aplicar()
    assert zerado.zerado is False
    assert _esperar(lambda: app.janela.property("paginaAtual") != "jogo")


# -- capa, logo e papel de parede (tarefa 7) -----------------------------------------------------


def _imagem(caminho, tamanho=(120, 180), cor="red"):
    from PIL import Image  # noqa: PLC0415

    Image.new("RGB", tamanho, cor).save(caminho)
    return caminho


def _url(caminho):
    from PySide6.QtCore import QUrl  # noqa: PLC0415

    return QUrl.fromLocalFile(str(caminho))


def _escolher_capa(app, caminho):
    app.edicao.escolherCapa(_url(caminho))
    assert _esperar(lambda: not app.edicao.ocupado, 10)


def _provisoria(app):
    return app.edicao._form.capa  # noqa: SLF001


def _papel_do_modelo(app, game_id, papel):
    modelo = app.modelo
    for i in range(modelo.rowCount()):
        if modelo.data(modelo.index(i, 0), modelo.Papel.JogoId) == game_id:
            return modelo.data(modelo.index(i, 0), papel)
    raise AssertionError(game_id)


def test_filtro_de_capa_sem_svg(app):
    filtro = app.edicao.filtroDaCapa
    assert filtro.startswith("Imagens e vídeos (")
    assert "*.svg" not in filtro
    assert "*.png" in filtro and "*.mp4" in filtro and "*.webm" in filtro
    assert app.edicao.filtroDoLogo.startswith("Imagens de logo (") and "*.png" in app.edicao.filtroDoLogo


def test_escolher_imagem_converte_por_temporario(app, tmp_path, monkeypatch):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    app.edicao.abrir("shortcuts_z2")
    _escolher_capa(app, _imagem(tmp_path / "escolhida.png"))
    provisoria = _provisoria(app)
    # Só a capa pronta (um TIFF do tamanho das capas) fica em %TEMP%: a intermediária foi apagada.
    assert provisoria is not None and provisoria.suffix == ".tiff" and provisoria.parent == temp
    assert list(temp.iterdir()) == [provisoria]
    assert app.edicao.temCapa is True and app.edicao.capa.startswith("file:")
    assert app.edicao.ocupado is False
    assert (tmp_path / "escolhida.png").exists(), "a imagem da pessoa não é apagada"


def test_cancelar_apaga_as_provisorias(app, tmp_path):
    app.edicao.abrir("shortcuts_z2")
    _escolher_capa(app, _imagem(tmp_path / "a.png"))
    provisoria = _provisoria(app)
    assert provisoria.is_file()
    app.edicao.cancelar()
    assert not provisoria.exists()
    assert app.edicao.capa == ""


def test_segunda_escolha_apaga_a_primeira(app, tmp_path):
    app.edicao.abrir("shortcuts_z2")
    _escolher_capa(app, _imagem(tmp_path / "a.png", cor="red"))
    primeira = _provisoria(app)
    _escolher_capa(app, _imagem(tmp_path / "b.png", cor="blue"))
    segunda = _provisoria(app)
    assert segunda != primeira and segunda.is_file()
    assert not primeira.exists()
    app.edicao.cancelar()
    assert not segunda.exists()


def test_capa_provisoria_descartada_abandona_as_copias(app, tmp_path, monkeypatch):
    """Trocar a provisória e fechar sem aplicar: a geração das cópias dela sai da fila junto com o arquivo."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    abandonadas = []
    monkeypatch.setattr(copias_animadas, "abandonar", abandonadas.append)
    app.edicao.abrir("shortcuts_z2")
    _escolher_capa(app, _imagem(tmp_path / "a.png", cor="red"))
    primeira = _provisoria(app)
    _escolher_capa(app, _imagem(tmp_path / "b.png", cor="blue"))
    segunda = _provisoria(app)
    assert abandonadas == [primeira]
    app.edicao.cancelar()
    assert abandonadas == [primeira, segunda]
    assert not segunda.exists()


def test_resultado_atrasado_de_um_dialogo_fechado_e_descartado(app, tmp_path, monkeypatch):
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    app.edicao.abrir("shortcuts_z2")
    app.edicao.escolherCapa(_url(_imagem(tmp_path / "a.png")))
    app.edicao.cancelar()
    app.edicao.abrir("shortcuts_z3")
    # A conversão do jogo anterior chega depois: não entra neste diálogo e não deixa temporário.
    assert _esperar(lambda: False, 1) is False
    assert app.edicao.temCapa is False and app.edicao.ocupado is False
    assert list(temp.iterdir()) == []


def test_aplicar_grava_a_capa_e_a_provisoria_sai_depois(app, tmp_path):
    app.edicao.abrir("shortcuts_z2")
    _escolher_capa(app, _imagem(tmp_path / "a.png"))
    provisoria = _provisoria(app)
    app.edicao.aplicar()
    assert app.edicao.aberto is False
    assert (shared.covers_dir / "shortcuts_z2.tiff").is_file()
    assert _esperar(lambda: not provisoria.exists())
    app.modelo.atualizar(shared.store.get("shortcuts_z2"))  # o que a ponte do app faz com o `atualizado`
    assert _papel_do_modelo(app, "shortcuts_z2", app.modelo.Papel.Capa) != ""


def test_capa_presa_nao_aborta_o_aplicar(app, tmp_path, monkeypatch):
    from cartridges import edicao as regra  # noqa: PLC0415

    def presa(*_args):
        raise PermissionError(5, "Acesso negado")

    monkeypatch.setattr(regra, "save_cover", presa)
    app.edicao.abrir("shortcuts_z2")
    _escolher_capa(app, _imagem(tmp_path / "a.png"))
    provisoria = _provisoria(app)
    app.edicao.nome = "Beta Novo"
    app.edicao.aplicar()
    jogo_ = shared.store.get("shortcuts_z2")
    assert app.edicao.aberto is False
    assert jogo_.name == "Beta Novo", "o resto da edição é gravado"
    # A provisória é a capa desta sessão: fica no disco e é a que a grade e a página mostram.
    assert _esperar(lambda: provisoria.is_file())
    assert jogo_.get_cover_path() == provisoria
    app.modelo.atualizar(jogo_)  # o que a ponte do app faz com o `atualizado`
    assert provisoria.name in _papel_do_modelo(app, "shortcuts_z2", app.modelo.Papel.Capa)
    app.detalhes.mostrar("shortcuts_z2")
    assert provisoria.name in app.detalhes.capa


def test_apagar_capa_volta_ao_placeholder(app, tmp_path):
    _imagem(shared.covers_dir / "shortcuts_z2.tiff")
    app.edicao.abrir("shortcuts_z2")
    assert app.edicao.temCapa is True
    assert _esperar(lambda: app.achar("botaoExcluirCapa").property("visible") is True)
    _clique(app, "botaoExcluirCapa")
    assert app.edicao.capa == "" and app.edicao.temCapa is False
    assert _esperar(lambda: app.achar("botaoExcluirCapa").property("visible") is False)
    # Sem capa, a prévia mostra o placeholder da biblioteca.
    assert _esperar(lambda: app.achar("previaDaCapa").property("source").toString().endswith("library_placeholder.svg"))
    app.edicao.aplicar()
    assert shared.store.get("shortcuts_z2").get_cover_path() is None


def test_capa_ilegivel_na_previa_mostra_a_capa_padrao(app):
    (shared.covers_dir / "shortcuts_z2.tiff").write_bytes(b"nao e uma imagem")
    app.edicao.abrir("shortcuts_z2")
    assert _esperar(lambda: app.achar("previaDaCapa").property("source").toString().endswith("library_placeholder.svg"))


def test_logo_titulo_e_restaurar(app):
    from cartridges.edicao import Escolha  # noqa: PLC0415

    app.edicao.abrir("shortcuts_z2")
    assert app.edicao.logoSubtitulo == "Automático (SteamGridDB)" and app.edicao.logoRestauravel is False
    assert _esperar(lambda: app.achar("botaoRestaurarLogo").property("visible") is False)
    app.edicao._form.logo = Escolha("title")  # noqa: SLF001  # o "título" vem do seletor do SteamGridDB (tarefa 8)
    app.edicao.imagensChanged.emit()
    assert app.edicao.logoSubtitulo == "Sem logo; o título é exibido"
    assert _esperar(lambda: app.achar("botaoRestaurarLogo").property("visible") is True)
    assert app.achar("botaoRestaurarLogo").property("dica") == "Voltar a escolher o logo automaticamente"
    app.edicao.escolherLogo(_url("C:/qualquer/logo.png"))
    assert app.edicao.logoSubtitulo == "Escolhido manualmente"
    _clique(app, "botaoRestaurarLogo")
    assert app.edicao.logoSubtitulo == "Automático (SteamGridDB)"
    assert app.edicao._form.logo.modo == "auto"  # noqa: SLF001
    assert app.achar("botaoEscolherLogo").property("dica") == "Escolher logo de um arquivo"


def test_logo_de_arquivo_e_gravado_no_aplicar(app, tmp_path):
    from cartridges.utils import game_logo  # noqa: PLC0415

    arquivo = _imagem(tmp_path / "logo.png")
    app.edicao.abrir("shortcuts_z2")
    app.edicao.escolherLogo(_url(arquivo))
    app.edicao.aplicar()
    assert game_logo.logo_choice(shared.store.get("shortcuts_z2")) == "manual"
    assert arquivo.exists(), "o arquivo da pessoa não é apagado"


def test_papel_de_parede_desabilitado_com_um_monitor(app, monkeypatch):
    from cartridges.modelos import edicao as modelo  # noqa: PLC0415

    monkeypatch.setattr(modelo, "_segundo_monitor", lambda: False)
    app.edicao.abrir("shortcuts_z2")
    assert app.edicao.papelSubtitulo == "Requer um segundo monitor"
    assert _esperar(lambda: app.achar("linhaDoPapel").property("enabled") is False)
    app.edicao.cancelar()
    monkeypatch.setattr(modelo, "_segundo_monitor", lambda: True)
    app.edicao.abrir("shortcuts_z2")
    assert app.edicao.papelSubtitulo == "Automático (wallhaven)"
    assert _esperar(lambda: app.achar("linhaDoPapel").property("enabled") is True)
    app.edicao.nao_trocar_papel()
    assert app.edicao.papelSubtitulo == "Não trocar o papel de parede" and app.edicao.papelRestauravel is True
    app.edicao.restaurarPapel()
    assert app.edicao.papelSubtitulo == "Automático (wallhaven)"


def test_video_sem_ffmpeg_mostra_o_erro(app, tmp_path, monkeypatch):
    from cartridges.utils import capa_video  # noqa: PLC0415

    monkeypatch.setattr(capa_video, "executavel", lambda: None)
    pedidos = []
    app.aplicativo.dialogoPedido.connect(lambda *a: pedidos.append(a))
    video = tmp_path / "clipe.mp4"
    video.write_bytes(b"nao e um video")
    app.edicao.abrir("shortcuts_z2")
    _escolher_capa(app, video)
    assert _esperar(lambda: bool(pedidos))
    assert tuple(pedidos[0][:2]) == ("Não foi possível usar o vídeo", "O arquivo não pôde ser lido como vídeo.")
    assert app.edicao.temCapa is False and app.edicao.ocupado is False


def test_a_grade_e_a_pagina_largam_a_copia_animada_antes_de_gravar_a_capa(app, tmp_path, monkeypatch):
    from cartridges import edicao as regra  # noqa: PLC0415
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    capa = shared.covers_dir / "shortcuts_z2.gif"
    _imagem(capa)
    copia = copias_animadas.caminho_para(capa, copias_animadas.tamanhos()[0])
    copia.parent.mkdir(parents=True, exist_ok=True)
    _imagem(copia)
    monkeypatch.setattr(copias_animadas, "soltar_do_jogo", app.modelo.soltar_copia)
    app.modelo.atualizar(shared.store.get("shortcuts_z2"))
    app.detalhes.mostrar("shortcuts_z2")
    assert _papel_do_modelo(app, "shortcuts_z2", app.modelo.Papel.CapaAnimada) != ""
    assert app.detalhes.capaAnimada != ""

    vistos = []
    real = regra.save_cover

    def espiao(game_id, caminho):
        vistos.append((_papel_do_modelo(app, game_id, app.modelo.Papel.CapaAnimada), app.detalhes.capaAnimada))
        real(game_id, caminho)

    monkeypatch.setattr(regra, "save_cover", espiao)
    app.edicao.abrir("shortcuts_z2")
    _escolher_capa(app, _imagem(tmp_path / "nova.png"))
    app.edicao.aplicar()
    assert vistos == [("", "")]


# -- seletores de capa e de logo do SteamGridDB (tarefa 8) ------------------------------------------


@pytest.fixture
def sgdb(app, tmp_path, monkeypatch, schema):
    """O SteamGridDB e o download falsos nos dois seletores; %TEMP% de mentira."""
    from cartridges.modelos import seletores  # noqa: PLC0415
    from tests.apoio_seletores import DownloadFalso, SgdbFalso  # noqa: PLC0415

    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    schema.set_string("sgdb-key", "chave-de-teste")
    monkeypatch.setattr(seletores, "download_bytes", DownloadFalso())
    falsos = SgdbFalso()
    app.edicao.seletorDeCapa.sgdb = app.edicao.seletorDeLogo.sgdb = falsos
    app.temp = temp
    return falsos


def _visivel(app, nome):
    return app.achar(nome).property("visible") is True


def _abrir_seletor(app, botao, seletor):
    app.achar(botao).forceActiveFocus()
    _clique(app, botao)
    assert _esperar(lambda: _visivel(app, seletor))
    assert _esperar(lambda: _foco_dentro_de(app, seletor))
    grade = app.achar(seletor + "Grade")
    assert _esperar(lambda: grade.property("count") == 3 and _visivel(app, seletor + "Miniatura2"))


def test_seletor_de_capa_modal_e_devolve_o_foco(app, sgdb):
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _foco_dentro_de(app, "campoNome"))
    _abrir_seletor(app, "botaoEscolherCapaSgdb", "seletorDeCapa")
    assert app.achar("seletorDeCapaTitulo").property("text") == "Escolher capa"
    assert app.achar("seletorDeCapaCampo").property("text") == "Alfa"
    assert app.achar("seletorDeCapaCampo").property("placeholderText") == "Buscar jogo…"
    assert app.achar("seletorDeCapaAtalho").property("text") == "Animadas"
    for _ in range(40):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        assert _foco_dentro_de(app, "seletorDeCapa")
    # Esc fecha só o seletor: o diálogo de edição segue aberto e o foco volta ao botão que o abriu.
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not _visivel(app, "seletorDeCapa"))
    assert app.edicao.aberto is True and app.edicao.seletorDeCapa.aberto is False
    assert _esperar(lambda: _foco_dentro_de(app, "botaoEscolherCapaSgdb"))
    assert list(app.temp.iterdir()) == []


def test_escolher_uma_capa_do_seletor_a_deixa_na_previa(app, sgdb):
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherCapaSgdb", "seletorDeCapa")
    app.achar("seletorDeCapaMiniatura1").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.edicao.temCapa and not app.edicao.ocupado, 10)
    assert _esperar(lambda: not _visivel(app, "seletorDeCapa"))
    assert _esperar(lambda: _foco_dentro_de(app, "botaoEscolherCapaSgdb"))
    provisoria = _provisoria(app)
    assert provisoria.suffix == ".tiff" and [p.name for p in app.temp.iterdir()] == [provisoria.name]
    app.edicao.cancelar()
    assert list(app.temp.iterdir()) == []


def test_pulsa_do_clique_ate_o_primeiro_dado(app, sgdb, monkeypatch):
    """Entre o clique e o primeiro dado (DNS, TLS, um servidor lento) a barra fica indeterminada."""
    import threading  # noqa: PLC0415

    from cartridges.modelos import seletores  # noqa: PLC0415
    from tests.apoio_seletores import png_bytes  # noqa: PLC0415

    liberar = threading.Event()
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherCapaSgdb", "seletorDeCapa")
    seletor = app.edicao.seletorDeCapa
    # Só depois das miniaturas: o download da imagem escolhida é que espera.
    monkeypatch.setattr(seletores, "download_bytes", lambda *_a, **_k: liberar.wait(5) and png_bytes())

    seletor.escolher(1)
    assert _esperar(lambda: _visivel(app, "seletorDeCapaBaixando"))
    barra = app.achar("seletorDeCapaBarra")
    assert seletor.textoDoProgresso == "" and barra.property("indeterminate") is True

    seletor._progresso_recebido(seletor._generation, 2 * 1024 * 1024, 8 * 1024 * 1024)  # noqa: SLF001  (o primeiro dado)
    assert _esperar(lambda: barra.property("indeterminate") is False)
    assert barra.property("value") == pytest.approx(0.25)
    liberar.set()
    assert _esperar(lambda: app.edicao.temCapa and not app.edicao.ocupado, 10)
    app.edicao.cancelar()


def test_animadas_pede_as_capas_animadas(app, sgdb):
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherCapaSgdb", "seletorDeCapa")
    _clique(app, "seletorDeCapaAtalho")
    assert _esperar(lambda: sgdb.grids_pedidas[-1][1] is True)
    assert app.achar("seletorDeCapaAtalho").property("checked") is True
    assert app.achar("seletorDeCapaAtalho").property("dica") == "Mostrar capas animadas"
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: app.edicao.seletorDeCapa.aberto is False)


def test_seletor_de_logo_usar_o_titulo(app, sgdb):
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherLogoSgdb", "seletorDeLogo")
    assert app.achar("seletorDeLogoTitulo").property("text") == "Escolher logo"
    assert app.achar("seletorDeLogoAtalho").property("text") == "Usar o título"
    assert app.achar("seletorDeLogoAtalho").property("dica") == "Não usar logo neste jogo"
    _clique(app, "seletorDeLogoAtalho")
    assert _esperar(lambda: not _visivel(app, "seletorDeLogo"))
    assert app.edicao.logoSubtitulo == "Sem logo; o título é exibido"
    assert _esperar(lambda: _foco_dentro_de(app, "botaoEscolherLogoSgdb"))


def test_seletor_de_logo_escolhe_e_o_aplicar_grava(app, sgdb):
    from cartridges.utils import game_logo  # noqa: PLC0415

    app.edicao.abrir("shortcuts_z2")
    _abrir_seletor(app, "botaoEscolherLogoSgdb", "seletorDeLogo")
    app.achar("seletorDeLogoMiniatura0").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.edicao.logoSubtitulo == "Escolhido manualmente")
    entregue = app.edicao._form.logo.arquivo  # noqa: SLF001
    app.edicao.aplicar()
    assert game_logo.logo_choice(shared.store.get("shortcuts_z2")) == "manual"
    assert _esperar(lambda: not entregue.exists()), "o temporário do seletor sai depois de gravado"


def test_aviso_de_busca_sem_resultado_no_seletor(app, sgdb):
    sgdb.grids = []
    app.edicao.abrir("shortcuts_z1")
    app.achar("botaoEscolherCapaSgdb").forceActiveFocus()
    _clique(app, "botaoEscolherCapaSgdb")
    vazio = app.achar("seletorDeCapaVazio")
    assert _esperar(lambda: vazio.property("visible") is True)
    assert vazio.property("titulo") == "Nenhuma capa encontrada"
    assert vazio.property("descricao") == "Tente buscar por outro nome."
    assert app.achar("seletorDeCapaGrade").property("visible") is False


def test_textos_do_seletor_em_texto_puro(app, sgdb):
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherCapaSgdb", "seletorDeCapa")
    textos, pilha = [], [app.achar("seletorDeCapa")]
    while pilha:
        atual = pilha.pop()
        if atual.metaObject().className().startswith("QQuickText"):
            textos.append(atual)
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
        pilha.extend(atual.children())
    assert len(textos) >= 5
    for texto in textos:
        assert _avaliar(texto, "textFormat") == 0, (texto.property("text"), texto.parentItem())  # Text.PlainText


def test_save_cover_fora_do_aplicar_limpa_a_capa_da_sessao(app, tmp_path):
    from cartridges.utils.save_cover import save_cover  # noqa: PLC0415

    jogo_ = shared.store.get("shortcuts_z2")
    provisoria = _imagem(tmp_path / "provisoria.png", (600, 900), "red")
    jogo_.capa_da_sessao = provisoria
    assert jogo_.get_cover_path() == provisoria
    # O caminho da importação e do SteamGridDB: grava a capa sem passar pelo Aplicar.
    nova = _imagem(tmp_path / "nova.png", (600, 900), "blue")
    save_cover("shortcuts_z2", nova)
    assert _esperar(lambda: jogo_.capa_da_sessao is None)
    assert jogo_.get_cover_path() == shared.covers_dir / "shortcuts_z2.tiff"
    app.modelo.atualizar(jogo_)  # o que a ponte do app faz com o `atualizado`
    assert "shortcuts_z2.tiff" in _papel_do_modelo(app, "shortcuts_z2", app.modelo.Papel.Capa)


# -- Steam, HowLongToBeat e Ludusavi (tarefa 9) -----------------------------------------------------


@pytest.fixture
def steam(app, monkeypatch):
    """A Steam e o HowLongToBeat falsos; nada fala com a rede."""
    from cartridges.modelos import edicao as modulo  # noqa: PLC0415
    from tests.apoio_seletores import HltbFalso, SteamFalsa  # noqa: PLC0415

    falsa = SteamFalsa()
    app.edicao.seletorDaSteam.helper = falsa
    app.edicao.seletorDaSteam.atraso_da_busca_ms = 40
    monkeypatch.setattr(modulo, "shared_hltb_helper", lambda: object())
    monkeypatch.setattr(modulo, "fetch_times", HltbFalso())
    return falsa


def _abrir_avancadas(app):
    _clique(app, "cabecalhoDasAvancadas")
    assert _esperar(lambda: _visivel(app, "campoAppid"))


def test_abrir_com_avancadas_mostra_as_opcoes_avancadas(app):
    # O "Editar jogo" do aviso "Saves sem backup": abre o editor já com a seção aberta.
    app.edicao.abrir("shortcuts_z1", avancadas=True)
    assert _esperar(lambda: _visivel(app, "campoAppid"))
    assert app.achar("dialogoDeEdicao").property("avancadasAbertas") is True


def test_abrir_sem_avancadas_deixa_a_secao_fechada(app):
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("dialogoDeEdicao").property("visible") is True)
    assert app.achar("dialogoDeEdicao").property("avancadasAbertas") is False


def test_seletor_da_steam_pelo_appid_e_modal_e_preenche_o_campo(app, steam):
    app.edicao.abrir("shortcuts_z1")
    _abrir_avancadas(app)
    app.achar("botaoBuscarAppid").forceActiveFocus()
    _clique(app, "botaoBuscarAppid")
    assert _esperar(lambda: _visivel(app, "seletorDaSteam") and _visivel(app, "seletorDaSteamLinha1"))
    assert app.achar("seletorDaSteamTitulo").property("text") == "Escolher jogo na Steam"
    assert app.achar("seletorDaSteamCampo").property("text") == "Alfa"
    assert app.achar("seletorDaSteamCampo").property("placeholderText") == "Buscar jogo…"
    assert app.achar("dialogoDeEdicao").property("visible") is True
    for _ in range(12):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        assert _foco_dentro_de(app, "seletorDaSteam")
    # Esc fecha só o seletor e o foco volta ao botão que o abriu.
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not _visivel(app, "seletorDaSteam"))
    assert app.edicao.aberto is True and _esperar(lambda: _foco_dentro_de(app, "botaoBuscarAppid"))
    _clique(app, "botaoBuscarAppid")
    assert _esperar(lambda: _visivel(app, "seletorDaSteamLinha0"))
    app.achar("seletorDaSteamLinha0Botao").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.achar("campoAppid").property("text") == "400")
    assert _esperar(lambda: not _visivel(app, "seletorDaSteam"))
    assert _esperar(lambda: _foco_dentro_de(app, "botaoBuscarAppid"))


def test_buscar_metadados_pelo_botao_do_titulo(app, steam):
    app.edicao.abrir("shortcuts_z1")
    app.edicao.nome = "Portal"
    botao = app.achar("botaoBuscarMetadados")
    assert botao.property("dica") == "Buscar dados na Steam pelo título"
    steam.soltar.clear()
    _clique(app, "botaoBuscarMetadados")
    assert _esperar(lambda: app.achar("carregandoMetadados").property("visible") is True)
    assert app.achar("botaoAplicarDaEdicao").property("enabled") is False
    steam.soltar.set()
    assert _esperar(lambda: not app.edicao.ocupado)
    assert app.achar("campoDesenvolvedora").property("text") == "Valve"
    assert app.achar("campoGenero").property("text") == "Puzzle"
    assert _visivel(app, "botaoBuscarMetadados")
    assert app.edicao.appid == "400"


def test_buscar_metadados_com_varios_candidatos_abre_o_seletor(app, steam):
    from cartridges.utils.steam import SteamGameNotFoundError  # noqa: PLC0415

    steam.erro_do_resolve = SteamGameNotFoundError()
    app.edicao.abrir("shortcuts_z1")
    app.edicao.nome = "Portal"
    app.achar("botaoBuscarMetadados").forceActiveFocus()
    _clique(app, "botaoBuscarMetadados")
    assert _esperar(lambda: _visivel(app, "seletorDaSteam") and _visivel(app, "seletorDaSteamLinha1"))
    app.achar("seletorDaSteamLinha1Botao").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: not app.edicao.ocupado and app.achar("campoDesenvolvedora").property("text") == "Valve")
    assert app.edicao.appid == "620"


def test_aviso_de_busca_sem_resultado_no_seletor_da_steam(app, steam):
    steam.candidatos = []
    app.edicao.abrir("shortcuts_z1")
    _abrir_avancadas(app)
    _clique(app, "botaoBuscarAppid")
    vazio = app.achar("seletorDaSteamVazio")
    assert _esperar(lambda: vazio.property("visible") is True)
    assert vazio.property("titulo") == "Nenhum jogo encontrado"
    assert vazio.property("descricao") == "Tente buscar por outro nome."


def test_botoes_da_steam_sem_titulo(app, steam):
    """DE-56: o botão dos dados da Steam fica ativo sem título e o clique não faz nada; o do AppID espera o título."""
    app.edicao.adicionar()
    _abrir_avancadas(app)
    assert app.achar("botaoBuscarMetadados").property("enabled") is True
    _clique(app, "botaoBuscarMetadados")
    _esperar(lambda: False, 0.2)
    assert app.edicao.buscandoMetadados is False and app.edicao.ocupado is False
    assert app.achar("botaoBuscarAppid").property("enabled") is False
    app.edicao.nome = "Portal"
    assert app.achar("botaoBuscarAppid").property("enabled") is True


def _manifesto():
    pasta = shared.app_dir / "ludusavi"
    pasta.mkdir(parents=True, exist_ok=True)
    texto = 'Zelda:\n  files: {}\n"Alien: Isolation":\n  files: {}\nPortal:\n  files: {}\n'
    (pasta / "manifest.yaml").write_text(texto, encoding="utf-8")


def test_linha_do_ludusavi_desligada_sem_a_lista_baixada(app):
    app.edicao.abrir("shortcuts_z1")
    _abrir_avancadas(app)
    assert app.achar("linhaDoLudusaviBotao").property("enabled") is False
    assert app.achar("linhaDoLudusaviSubtitulo").property("text") == "A lista de jogos do Ludusavi ainda não foi baixada."


def test_seletor_do_ludusavi_escolhe_e_o_subtitulo_muda(app):
    _manifesto()
    app.edicao.abrir("shortcuts_z1")
    _abrir_avancadas(app)
    assert app.achar("linhaDoLudusaviSubtitulo").property("text") == "Nenhum"
    app.achar("linhaDoLudusaviBotao").forceActiveFocus()
    _clique(app, "linhaDoLudusaviBotao")
    assert _esperar(lambda: _visivel(app, "seletorDoLudusavi") and _visivel(app, "seletorDoLudusaviLinha2"))
    assert app.achar("seletorDoLudusaviTitulo").property("text") == "Jogo no Ludusavi"
    assert app.achar("seletorDoLudusaviNenhumTitulo").property("text") == "Nenhum (desliga o backup)"
    assert app.achar("seletorDoLudusaviCampo").property("placeholderText") == "Buscar jogo"
    for _ in range(12):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        assert _foco_dentro_de(app, "seletorDoLudusavi")
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not _visivel(app, "seletorDoLudusavi"))
    assert _esperar(lambda: _foco_dentro_de(app, "linhaDoLudusaviBotao"))
    _clique(app, "linhaDoLudusaviBotao")
    assert _esperar(lambda: _visivel(app, "seletorDoLudusaviLinha1"))
    app.achar("seletorDoLudusaviLinha1").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: app.achar("linhaDoLudusaviSubtitulo").property("text") == "Portal")
    _clique(app, "linhaDoLudusaviBotao")
    assert _esperar(lambda: _visivel(app, "seletorDoLudusaviNenhum"))
    _clique(app, "seletorDoLudusaviNenhumBotao")
    assert _esperar(lambda: app.achar("linhaDoLudusaviSubtitulo").property("text") == "Backup desligado")


def test_textos_dos_seletores_novos_em_texto_puro(app, steam):
    _manifesto()
    app.edicao.abrir("shortcuts_z1")
    app.edicao.seletorDaSteam.abrir("Portal")
    assert _esperar(lambda: _visivel(app, "seletorDaSteamLinha0"))
    da_steam = _formatos(app.achar("seletorDaSteam"))
    app.edicao.seletorDaSteam.fechar()
    app.edicao.seletorDoLudusavi.abrir("")
    assert _esperar(lambda: _visivel(app, "seletorDoLudusaviLinha0"))
    do_ludusavi = _formatos(app.achar("seletorDoLudusavi"))
    app.edicao.seletorDoLudusavi.fechar()
    for formatos in (da_steam, do_ludusavi):
        assert len(formatos) >= 3
        assert all(formato == 0 for _texto, formato in formatos), formatos  # Text.PlainText


def _formatos(raiz):
    """O `(texto, textFormat)` de todo `Text` sob `raiz`, lido com a tela aberta (as linhas somem ao fechar)."""
    textos, pilha = [], [raiz]
    while pilha:
        atual = pilha.pop()
        if atual.metaObject().className().startswith("QQuickText"):
            textos.append((atual.property("text"), _avaliar(atual, "textFormat")))
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
        pilha.extend(atual.children())
    return textos


# -- seletor do papel de parede (tarefa 10) ----------------------------------------------------------


@pytest.fixture
def wallhaven(app, tmp_path, monkeypatch):
    """O wallhaven, o download e os monitores falsos; %TEMP% de mentira; a edição com um segundo monitor."""
    import io  # noqa: PLC0415

    from PIL import Image  # noqa: PLC0415

    from cartridges.modelos import edicao as modelo  # noqa: PLC0415
    from cartridges.modelos import seletores  # noqa: PLC0415
    from cartridges.utils.session_wallpaper import Monitor  # noqa: PLC0415
    from tests.apoio_seletores import DownloadFalso, WallhavenFalso  # noqa: PLC0415

    temp = tmp_path / "temp"
    temp.mkdir(exist_ok=True)  # o `sgdb` pode já ter criado
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    monkeypatch.setattr(modelo, "_segundo_monitor", lambda: True)
    imagem = Image.new("RGB", (160, 90), "red")
    imagem.paste("blue", (80, 0, 160, 90))
    saida = io.BytesIO()
    imagem.save(saida, "PNG")
    baixar = DownloadFalso()
    baixar.conteudo = saida.getvalue()
    monkeypatch.setattr(seletores, "download_bytes", baixar)
    falso = WallhavenFalso()
    monkeypatch.setattr(seletores, "buscar", falso)
    app.edicao.seletorDePapelDeParede.monitores = lambda: [Monitor("1", 0, 0, 1920, 1080), Monitor("2", 1920, 0, 1080, 1920)]
    app.temp = temp
    return falso


def test_seletor_de_papel_modal_esc_fecha_e_devolve_o_foco(app, wallhaven):
    app.edicao.abrir("shortcuts_z1")
    assert app.achar("botaoEscolherPapelWallhaven").property("icone") == "edit-find"  # o ícone de buscar, como o da capa e o do logo
    assert app.achar("botaoEscolherPapelWallhaven").property("dica") == "Escolher papel de parede no wallhaven"
    _abrir_seletor(app, "botaoEscolherPapelWallhaven", "seletorDePapel")
    assert app.achar("seletorDePapelTitulo").property("text") == "Escolher papel de parede"
    assert app.achar("seletorDePapelCampo").property("text") == "Alfa"
    assert app.achar("seletorDePapelCampo").property("placeholderText") == "Buscar no wallhaven…"
    naotrocar = app.achar("seletorDePapelNaoTrocar")
    assert naotrocar.property("text") == "Não trocar"
    assert naotrocar.property("dica") == "Não alterar o papel de parede quando este jogo rodar"
    for _ in range(40):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        assert _foco_dentro_de(app, "seletorDePapel")
    # Esc fecha o seletor inteiro (como na versão anterior); o diálogo de edição segue aberto.
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: not _visivel(app, "seletorDePapel"))
    assert app.edicao.aberto is True and app.edicao.seletorDePapelDeParede.aberto is False
    assert _esperar(lambda: _foco_dentro_de(app, "botaoEscolherPapelWallhaven"))
    assert list(app.temp.iterdir()) == []


def test_seletor_de_papel_escolhe_ajusta_e_o_aplicar_grava(app, wallhaven):
    from cartridges.utils import session_wallpaper  # noqa: PLC0415

    app.edicao.abrir("shortcuts_z2")
    _abrir_seletor(app, "botaoEscolherPapelWallhaven", "seletorDePapel")
    app.achar("seletorDePapelMiniatura1").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: _visivel(app, "seletorDePapelUsar"))
    assert app.achar("seletorDePapelNaoTrocar").property("enabled") is True  # M1: sem `set_sensitive` na `main`
    # Na etapa de ajuste o foco não é forçado a lugar nenhum (`DE-88`).
    assert app.achar("seletorDePapelUsar").property("activeFocus") is False
    # A barra desliza a faixa do monitor em pé.
    app.edicao.seletorDePapelDeParede.definirPosicao(0, 100)
    assert _esperar(lambda: app.achar("seletorDePapelBarra0").property("value") == 100)
    # "Voltar" volta à grade, e a escolha de novo leva ao ajuste.
    _clique(app, "seletorDePapelVoltar")
    assert _esperar(lambda: _visivel(app, "seletorDePapelMiniatura2") and not _visivel(app, "seletorDePapelUsar"))
    app.achar("seletorDePapelMiniatura0").forceActiveFocus()
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: _visivel(app, "seletorDePapelUsar"))
    app.edicao.seletorDePapelDeParede.definirPosicao(0, 25)
    _clique(app, "seletorDePapelUsar")
    assert _esperar(lambda: not _visivel(app, "seletorDePapel"))
    assert _esperar(lambda: _foco_dentro_de(app, "botaoEscolherPapelWallhaven"))
    assert app.edicao.papelSubtitulo == "Escolhido manualmente"
    entregue = app.edicao._form.papel_de_parede.arquivo  # noqa: SLF001
    app.edicao.aplicar()
    jogo_ = shared.store.get("shortcuts_z2")
    assert session_wallpaper.escolha(jogo_) == "manual"
    assert session_wallpaper.posicoes_escolhidas(jogo_.game_id).retrato == 0.25
    assert _esperar(lambda: not entregue.exists()), "o temporário do seletor sai depois de gravado"


def test_seletor_de_papel_nao_trocar(app, wallhaven):
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherPapelWallhaven", "seletorDePapel")
    _clique(app, "seletorDePapelNaoTrocar")
    assert _esperar(lambda: not _visivel(app, "seletorDePapel"))
    assert app.edicao.papelSubtitulo == "Não trocar o papel de parede"
    assert _esperar(lambda: _foco_dentro_de(app, "botaoEscolherPapelWallhaven"))


def test_arquivo_do_disco_vai_ao_ajuste_sem_busca_nem_nao_trocar(app, wallhaven, tmp_path):
    app.edicao.abrir("shortcuts_z1")
    arquivo = _imagem(tmp_path / "parede.png", (160, 90))
    app.edicao.escolherPapel(_url(arquivo))
    assert _esperar(lambda: _visivel(app, "seletorDePapelUsar"))
    assert not _visivel(app, "seletorDePapelCampo") and not _visivel(app, "seletorDePapelNaoTrocar")
    assert wallhaven.pedidos == []
    _clique(app, "seletorDePapelVoltar")  # desiste: não há grade para onde voltar
    assert _esperar(lambda: not _visivel(app, "seletorDePapel"))
    assert app.edicao.papelSubtitulo == "Automático (wallhaven)" and arquivo.exists()


def test_aviso_de_busca_sem_resultado_no_seletor_de_papel(app, wallhaven):
    wallhaven.achados = []
    app.edicao.abrir("shortcuts_z1")
    app.achar("botaoEscolherPapelWallhaven").forceActiveFocus()
    _clique(app, "botaoEscolherPapelWallhaven")
    vazio = app.achar("seletorDePapelVazio")
    assert _esperar(lambda: vazio.property("visible") is True)
    assert vazio.property("titulo") == "Nenhum papel de parede encontrado"
    assert vazio.property("descricao") == "Tente buscar por outro nome."


# -- Iluminação inteligente (fitas de LED, D51) -------------------------------------------------------


@pytest.fixture
def previas(monkeypatch):
    """As prévias pedidas às fitas. Nenhuma fita de verdade acende."""
    pedidas = []
    monkeypatch.setattr(session_fita, "previa", lambda cor, *a, **k: pedidas.append(cor))
    return pedidas


def _com_fita():
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "192.0.2.10", "chave")])


def _abrir_o_seletor_de_cor(app):
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    _clique(app, "botaoDaCorDaFita")
    assert _esperar(lambda: app.achar("balaoDaCorDaFita").property("opened") is True)
    return app.achar("seletorDeCor")


def _ponto(seletor, fx, fy):
    """O ponto da janela que fica na fração (fx, fy) do quadrado do seletor."""
    return seletor.mapToScene(QPointF(seletor.width() * fx, seletor.height() * fy)).toPoint()


def test_seletor_de_cor_matiz_e_saturacao(app, previas, schema):
    _com_fita()
    seletor = _abrir_o_seletor_de_cor(app)
    assert _esperar(lambda: _foco_dentro_de(app, "seletorDeCor") or seletor.property("activeFocus") is True)
    escolhidas = []
    seletor.escolhida.connect(lambda cor: escolhidas.append(cor))

    # O matiz vai na horizontal (um terço é o verde, 120 graus) e a saturação na vertical (cheia em cima).
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _ponto(seletor, 1 / 3, 0.001))
    assert abs(seletor.property("matiz") - 120) < 4
    assert seletor.property("saturacao") > 980
    assert escolhidas and abs(escolhidas[-1].hsvHueF() * 360 - 120) < 4
    assert abs(previas[-1].matiz - 120) <= 4 and previas[-1].saturacao > 980

    # Embaixo é branco: a saturação cai.
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _ponto(seletor, 1 / 3, 0.99))
    assert seletor.property("saturacao") < 20
    assert previas[-1].saturacao < 20

    # Arrastar acende a cada movimento, e sair do quadrado trava na borda.
    total = len(previas)
    QTest.mousePress(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _ponto(seletor, 0.1, 0.5))
    QTest.mouseMove(app.janela, _ponto(seletor, 0.5, 0.5))
    QTest.mouseMove(app.janela, _ponto(seletor, 0.9, 0.2))
    QTest.mouseRelease(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _ponto(seletor, 0.9, 0.2))
    assert len(previas) >= total + 3
    assert abs(seletor.property("matiz") - 324) < 6

    # Teclado: setas mexem no matiz e na saturação, em passos pequenos.
    antes = seletor.property("matiz")
    QTest.keyClick(app.janela, Qt.Key.Key_Right)
    assert seletor.property("matiz") == pytest.approx(antes + 5)
    saturacao = seletor.property("saturacao")
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    assert seletor.property("saturacao") == saturacao - 20
    assert not session_fita.escolhida("shortcuts_z1")  # prévia não é escolha


def test_o_seletor_parte_da_cor_da_linha(app, previas):
    _com_fita()
    session_fita.salvar_cor("shortcuts_z1", "Alfa", session_fita.Cor(200, 800, 500))
    seletor = _abrir_o_seletor_de_cor(app)

    assert abs(seletor.property("matiz") - 200) < 2
    assert abs(seletor.property("saturacao") - 800) < 10
    assert previas == []  # abrir o balão não acende nada


def test_amostra_em_roda_no_automatico(app, schema, previas):
    schema.set_boolean("fita-acompanha-tela", True)
    _com_fita()
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    roda, cor = app.achar("amostraEmRoda"), app.achar("amostraDaCor")
    assert _esperar(lambda: roda.property("visible") is True)
    assert cor.property("visible") is False
    assert app.achar("linhaDaFitaSubtitulo").property("text") == "Automático"

    # Mexeu na cor: a roda dá lugar à cor escolhida.
    app.edicao.escolherCorDaFita(QColor.fromHsvF(0.55, 1, 1))
    assert _esperar(lambda: roda.property("visible") is False)
    assert cor.property("visible") is True and cor.property("width") == 22 and cor.property("height") == 22

    # Sem acompanhar a tela, a amostra é sempre a cor.
    app.edicao.cancelar()
    schema.set_boolean("fita-acompanha-tela", False)
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("amostraEmRoda").property("visible") is False)


def test_voltar_so_aparece_com_a_cor_escolhida(app, previas):
    _com_fita()
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    assert not _visivel(app, "botaoRestaurarFita")
    app.edicao.cancelar()

    session_fita.salvar_cor("shortcuts_z1", "Alfa", session_fita.Cor(340, 1000, 150))
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "botaoRestaurarFita"))
    assert app.achar("botaoRestaurarFita").property("dica") == "Voltar a escolher a cor a partir da capa"
    _clique(app, "botaoRestaurarFita")
    assert _esperar(lambda: not _visivel(app, "botaoRestaurarFita"))
    assert previas  # voltar ao automático também mostra a cor nas fitas


def test_sem_fita_as_duas_linhas_ficam_apagadas_com_o_aviso(app):
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    for linha in ("linhaDaFita", "linhaDoBrilhoDaFita"):
        assert app.achar(linha).property("enabled") is False
        assert app.achar(linha + "Subtitulo").property("text") == "Nenhum dispositivo configurado"


def test_o_brilho_da_fita_vai_a_edicao(app, previas):
    _com_fita()
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    caixa = app.achar("linhaDoBrilhoDaFitaCaixa")
    assert caixa.property("from") == 1 and caixa.property("to") == 100
    assert caixa.property("value") == app.edicao.fitaBrilho
    assert app.achar("linhaDoBrilhoDaFitaSubtitulo").property("visible") is False
    app.edicao.definirBrilhoDaFita(35)
    assert _esperar(lambda: caixa.property("value") == 35)
    assert previas[-1].brilho == session_fita.de_por_cento(35)


def test_zerado_esconde_logo_papel_e_iluminacao(app, store, schema):
    """Um zerado não é mais lançado: sem sessão, as linhas do logo, do papel e da fita não têm o que vestir."""
    _com_fita()
    zerado = jogo(store, 70, removed=True, status="beaten")
    app.edicao.abrir(zerado.game_id)
    assert _esperar(lambda: app.achar("campoNome").property("visible") is True)
    for nome in ("linhaDoPapel", "linhaDaFita", "linhaDoBrilhoDaFita"):
        assert app.achar(nome).property("visible") is False, nome
    app.edicao.cancelar()
    app.edicao.abrir("shortcuts_z1")  # um jogo comum mostra as três
    assert _esperar(lambda: app.achar("linhaDaFita").property("visible") is True)
    for nome in ("linhaDoPapel", "linhaDaFita", "linhaDoBrilhoDaFita"):
        assert app.achar(nome).property("visible") is True, nome


def test_busca_das_preferencias_nao_mexe_nas_linhas_do_editor_por_baixo(app):
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("campoNome").property("visible") is True)
    assert app.preferencias.abrir()
    assert _esperar(lambda: app.achar("dialogoDePreferencias").property("visible") is True)
    app.achar("dialogoDePreferencias").setProperty("filtro", "zzzzzz")
    assert _esperar(lambda: app.achar("estadoSemResultadoDasPreferencias").property("visible") is True)
    assert app.achar("campoNome").property("visible") is True


def test_sem_avisos_do_qml_ao_abrir_e_fechar(app_qt, store, monkeypatch):
    jogos = [jogo(store, 1, name="Alfa", executable=r'"C:\Jogos\alfa.exe"')]
    avisos = []
    anterior = qInstallMessageHandler(lambda tipo, _ctx, msg: avisos.append(msg) if tipo in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg) else None)
    try:
        janela = _App(jogos)
        monkeypatch.setattr(shared, "aplicativo", janela.aplicativo, raising=False)
        janela.edicao.abrir("shortcuts_z1")
        assert _esperar(lambda: janela.achar("dialogoDeEdicao").property("visible") is True)
        QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
        assert _esperar(lambda: not janela.edicao.aberto)
        janela.fechar()
    finally:
        qInstallMessageHandler(anterior)
    assert [a for a in avisos if "DialogoDeEdicao" in a] == []


def test_sem_avisos_do_qml_na_pagina_nos_dialogos_e_nos_seletores(app_qt, store, monkeypatch):
    """Nada de laço de binding, nem propriedade indefinida, nos arquivos do pacote B (página, editor e seletores)."""
    jogos = [jogo(store, 1, name="Alfa", executable=r'"C:\Jogoslfa.exe"', developer="Dev A", description="Texto")]
    avisos = []
    anterior = qInstallMessageHandler(lambda tipo, _ctx, msg: avisos.append(msg) if tipo in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg) else None)
    try:
        janela = _App(jogos)
        monkeypatch.setattr(shared, "aplicativo", janela.aplicativo, raising=False)
        _abrir_pelo_cartao(janela, 0)
        janela.janela.resize(800, 700)  # o breakpoint de 850
        _esperar(lambda: False, 0.3)
        QMetaObject.invokeMethod(janela.achar("botaoEditar"), "click", Qt.ConnectionType.DirectConnection)
        assert _esperar(lambda: janela.achar("dialogoDeEdicao").property("visible") is True)
        janela.edicao.avancadasPedidas.emit()
        for seletor in (janela.edicao.seletorDeCapa, janela.edicao.seletorDeLogo, janela.edicao.seletorDaSteam):
            seletor.abrir("Alfa")
            _esperar(lambda: False, 0.3)
            seletor.fechar()
        janela.edicao.escolherJogoNoLudusavi()
        janela.edicao.seletorDoLudusavi.fechar()
        janela.edicao.seletorDePapelDeParede.abrir("Alfa")
        _esperar(lambda: False, 0.3)
        janela.edicao.seletorDePapelDeParede.fechar()
        janela.fechar()
    finally:
        qInstallMessageHandler(anterior)
    nossos = ("PaginaDoJogo", "DialogoDeEdicao", "Seletor", "LinhaDeCor", "AmostraDeCor", "BalaoDaAnotacao", "CampoDeBusca", "TelaDeDownload", "PaginaDoSeletor", "BotaoOsd")
    # O laço de `altura` do `DialogoDeAlerta` (da fundação, pendência do pacote F) aparece com as confirmações da página.
    assert [a for a in avisos if any(n in a for n in nossos) and "DialogoDeAlerta" not in a] == []


def test_abrir_pasta_que_falha_avisa_que_nao_foi_possivel(app, monkeypatch):
    from cartridges.modelos import edicao as modelo_da_edicao  # noqa: PLC0415

    abertas, dialogos = [], []
    monkeypatch.setattr(modelo_da_edicao, "game_folder", lambda _comando: r"C:\Jogos")
    monkeypatch.setattr(modelo_da_edicao, "open_folder", lambda pasta: abertas.append(pasta) or False)
    monkeypatch.setattr(app.aplicativo, "pedir_dialogo", lambda titulo, corpo, itens, ao_fechar: dialogos.append((titulo, corpo, itens, ao_fechar)))
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: app.achar("dialogoDeEdicao").property("visible") is True)
    foco = []
    app.edicao.focoDevolvido.connect(lambda: foco.append(1))
    app.edicao.abrirPasta()
    assert abertas == [r"C:\Jogos"]
    assert [d[:3] for d in dialogos] == [("Não foi possível abrir a pasta", "A pasta pode ter sido movida ou apagada.", [])]
    dialogos[0][3]()  # fechar o aviso devolve o foco ao editor
    assert foco == [1]


def test_abrir_pasta_que_funciona_nao_avisa(app, monkeypatch):
    from cartridges.modelos import edicao as modelo_da_edicao  # noqa: PLC0415

    dialogos = []
    monkeypatch.setattr(modelo_da_edicao, "game_folder", lambda _comando: r"C:\Jogos")
    monkeypatch.setattr(modelo_da_edicao, "open_folder", lambda _pasta: True)
    monkeypatch.setattr(app.aplicativo, "pedir_dialogo", lambda *a: dialogos.append(a))
    app.edicao.abrir("shortcuts_z1")
    app.edicao.abrirPasta()
    assert dialogos == []


def test_escolher_executavel_poe_o_caminho_entre_aspas_e_url_vazia_nao_muda(app):
    app.edicao.abrir("shortcuts_z2")
    app.edicao.escolherExecutavel(QUrl.fromLocalFile("C:/Meus Jogos/Beta/beta.exe"))
    assert app.edicao.executavel == r'"C:\Meus Jogos\Beta\beta.exe"'
    app.edicao.escolherExecutavel(QUrl())
    assert app.edicao.executavel == r'"C:\Meus Jogos\Beta\beta.exe"'


def test_tab_ate_um_campo_abaixo_da_dobra_rola_o_editor(app):
    """O `Connections` da Edição estava morto: a rolagem não seguia o foco (consertado com `dialogo.Window.window`)."""
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _foco_dentro_de(app, "campoNome"))
    antes = _avaliar(app.achar("campoNome"), "rolagem.contentY")  # o nome, ao abrir, já ficou à vista
    app.achar("alternanciaDeConquistas").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _esperar()
    assert _esperar(lambda: _avaliar(app.achar("campoNome"), "rolagem.contentY") > antes)


def test_aviso_fechado_devolve_o_foco_ao_ultimo_campo_e_nao_ao_nome(app, monkeypatch):
    from cartridges.modelos import edicao as modelo_da_edicao  # noqa: PLC0415

    dialogos = []
    monkeypatch.setattr(modelo_da_edicao, "game_folder", lambda _comando: r"C:\Jogos")
    monkeypatch.setattr(modelo_da_edicao, "open_folder", lambda _pasta: False)
    monkeypatch.setattr(app.aplicativo, "pedir_dialogo", lambda titulo, corpo, itens, ao_fechar: dialogos.append(ao_fechar))
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _foco_dentro_de(app, "campoNome"))
    app.achar("botaoAbrirPasta").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _esperar()
    assert _esperar(lambda: app.achar("botaoAbrirPasta").property("activeFocus") is True)
    app.edicao.abrirPasta()
    assert len(dialogos) == 1
    app.janela.contentItem().forceActiveFocus()  # o aviso levou o foco
    dialogos[0]()
    _esperar()
    assert _esperar(lambda: app.achar("botaoAbrirPasta").property("activeFocus") is True)
    assert app.achar("campoNome").property("activeFocus") is False


# -- Auditoria GTK x Qt, pacote B: o editor e os seletores como os da `main` ---------------------------------------


def _x_da_cena(item):
    return item.mapToScene(item.boundingRect().topLeft()).x()


def test_a_moldura_do_editor_tem_480_e_os_botoes_da_capa_ficam_parados(app):
    """DE-37, DE-43, DE-44: 480 de largura, sem teto de altura; Excluir, Buscar, Abrir arquivo, com posições fixas."""
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    cartao = _achar(app.achar("dialogoDeEdicao"), "cartaoDoDialogo")
    assert cartao.property("width") == 480
    excluir, buscar, abrir = (app.achar(n) for n in ("botaoExcluirCapa", "botaoEscolherCapaSgdb", "botaoEscolherCapa"))
    assert (excluir.property("width"), buscar.property("height")) == (34, 34)
    assert _x_da_cena(excluir) < _x_da_cena(buscar) < _x_da_cena(abrir)
    antes = (_x_da_cena(buscar), _x_da_cena(abrir))
    assert excluir.property("visible") is False  # sem capa, o botão só está transparente...
    assert excluir.property("opacity") == 0
    app.edicao.cancelar()
    assert _esperar(lambda: not app.edicao.aberto)
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    assert (_x_da_cena(app.achar("botaoEscolherCapaSgdb")), _x_da_cena(app.achar("botaoEscolherCapa"))) == antes  # ...e não muda os outros


def test_clicar_na_linha_do_logo_aciona_o_botao_de_busca(app, sgdb):
    """DE-52: as linhas Logo, Papel e Iluminação são ativáveis (`activatable-widget`)."""
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    linha = app.achar("linhaDoLogo")
    ponto = linha.mapToScene(QPointF(30, linha.height() / 2)).toPoint()
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    assert _esperar(lambda: _visivel(app, "seletorDeLogo"))


def test_enter_no_appid_nao_aplica(app):
    """DE-57: só o executável e o nome do processo chamam o Aplicar."""
    app.edicao.abrir("shortcuts_z1")
    app.edicao.nome = "Mudou"
    _abrir_avancadas(app)
    app.achar("campoAppid").forceActiveFocus()
    app.achar("campoAppid").confirmado.emit()
    _esperar(lambda: False, 0.2)
    assert app.edicao.aberto is True and shared.store.get("shortcuts_z1").name == "Alfa"


def test_o_foco_inicial_do_seletor_e_o_do_dialogo_da_main(app, sgdb):
    """DE-66, DE-68: sem botão "Fechar" (o X é do cabeçalho); o foco inicial é o botão do cabeçalho, ou o campo se não há."""
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherCapaSgdb", "seletorDeCapa")
    assert app.achar("seletorDeCapaAtalho").property("activeFocus") is True
    assert _achar(app.janela, "seletorDeCapaFechar") is None
    x = _achar(app.achar("seletorDeCapa"), "fecharDoCabecalho")
    assert x is not None and _x_da_cena(x) > _x_da_cena(app.achar("seletorDeCapaAtalho"))  # o X vem depois do botão extra


def test_o_campo_de_busca_tem_lupa_e_limpa_mantendo_o_foco(app, sgdb):
    """DE-67: `SearchEntry` de 34, com o botão de limpar quando há texto."""
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherCapaSgdb", "seletorDeCapa")
    campo = app.achar("seletorDeCapaCampo")
    assert campo.property("height") == 34 and campo.property("width") <= 450
    limpar = app.achar("seletorDeCapaCampoLimpar")
    assert limpar.property("visible") is True
    QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centro_na_janela(limpar))
    assert _esperar(lambda: campo.property("text") == "" and campo.property("activeFocus") is True)
    assert app.edicao.seletorDeCapa.busca == ""


def _centro_na_janela(item):
    ponto = item.mapToScene(item.boundingRect().center()).toPoint()
    return ponto


def test_as_linhas_do_ludusavi_e_o_selecionado_tem_fundo(app):
    """DE-91, DE-92: o jogo escolhido é a linha selecionada (fundo), e a linha tem 8 em cima e embaixo."""
    _manifesto()
    app.edicao.abrir("shortcuts_z1")
    app.edicao.ludusavi_escolhido("Portal")
    _abrir_avancadas(app)
    _clique(app, "linhaDoLudusaviBotao")
    assert _esperar(lambda: _visivel(app, "seletorDoLudusaviLinha0") and _visivel(app, "seletorDoLudusaviLinha1"))
    linha = app.achar("seletorDoLudusaviLinha1")  # Portal, em ordem alfabética: Alien, Portal, Zelda
    assert linha.property("height") == 33
    fundo = _avaliar(linha, "background.color")
    assert fundo.alpha() > 0 and _avaliar(app.achar("seletorDoLudusaviLinha0"), "background.color").alpha() == 0



def test_botoes_da_capa_nao_recebem_clique_convertendo_e_a_amostra_fecha_o_balao(app, previas):
    """M3 (convertendo, os botões não agem) e M8 (clicar de novo na amostra fecha o balão)."""
    _com_fita()
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    app.edicao._capas_em_voo = 1  # noqa: SLF001
    app.edicao.capaChanged.emit()
    assert _esperar(lambda: app.achar("botaoEscolherCapa").property("enabled") is False)
    app.edicao._capas_em_voo = 0  # noqa: SLF001
    app.edicao.capaChanged.emit()
    assert _esperar(lambda: app.achar("botaoEscolherCapa").property("enabled") is True)
    amostra = app.achar("botaoDaCorDaFita")
    for _ in range(2):
        QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, _centro_na_janela(amostra))
        _esperar(lambda: False, 0.15)
    assert app.achar("balaoDaCorDaFita").property("opened") is False


def test_a_grade_do_seletor_so_ocupa_as_colunas(app, sgdb):
    """M6 (revisto): a grade tem a largura das colunas e fica centrada; as laterais rolam pelo `WheelHandler`."""
    app.edicao.abrir("shortcuts_z1")
    _abrir_seletor(app, "botaoEscolherCapaSgdb", "seletorDeCapa")
    grade = app.achar("seletorDeCapaGrade")
    assert grade.property("width") == app.achar("seletorDeCapa").property("colunas") * grade.property("cellWidth")


@pytest.mark.parametrize("largura", [560, 620, 672, 690, 760, 790, 900])
def test_as_colunas_reais_da_grade_do_seletor_sao_as_de_colunas(app, sgdb, largura):
    """Q1: mede, na tela, o `x` de cada miniatura: as colunas reais são `colunas` e a grade fica centrada."""
    from tests.apoio_seletores import SgdbFalso, lista_de_grades  # noqa: PLC0415

    app.edicao.seletorDeCapa.sgdb = SgdbFalso(grids=lista_de_grades(9))
    app.janela.resize(largura, 795)
    _esperar(lambda: False, 0.3)
    app.edicao.abrir("shortcuts_z1")
    _clique(app, "botaoEscolherCapaSgdb")
    # A contagem, não a miniatura 8: `achar` levanta enquanto as linhas ainda chegam uma a uma.
    assert _esperar(lambda: _visivel(app, "seletorDeCapa") and app.achar("seletorDeCapaGrade").property("count") == 9, 6)
    _esperar(lambda: False, 0.4)
    seletor = app.achar("seletorDeCapa")
    colunas = seletor.property("colunas")
    xs = sorted({round(_x_da_cena(app.achar(f"seletorDeCapaMiniatura{i}"))) for i in range(9)})
    assert len(xs) == colunas, (largura, colunas, xs)
    pagina = app.achar("seletorDeCapaGrade").parentItem()  # as sobras contam a partir da página, não da própria grade
    esquerda = xs[0] - _x_da_cena(pagina)
    direita = _x_da_cena(pagina) + pagina.property("width") - (xs[-1] + 140)
    assert abs(esquerda - direita) <= 2, (largura, esquerda, direita)


def _grade_longa(app, wallhaven, nome):
    """Abre o seletor `nome` (capa ou papel) cheio de miniaturas, numa janela de 1200; devolve a grade e a página."""
    from tests.apoio_seletores import SgdbFalso, lista_de_grades, lista_do_wallhaven  # noqa: PLC0415

    app.edicao.seletorDeCapa.sgdb = SgdbFalso(grids=lista_de_grades(40))
    wallhaven.achados = lista_do_wallhaven(40)
    app.janela.resize(1200, 795)
    _esperar(lambda: False, 0.3)
    app.edicao.abrir("shortcuts_z1")
    _clique(app, "botaoEscolherCapaSgdb" if nome == "seletorDeCapa" else "botaoEscolherPapelWallhaven")
    grade = app.achar(nome + "Grade")
    total = 30 if nome == "seletorDeCapa" else 24  # os tetos de cada busca
    assert _esperar(lambda: _visivel(app, nome) and grade.property("count") == total, 6)
    _esperar(lambda: False, 0.4)
    return grade, grade.parentItem()


def _girar(app, grade, x, y, angulo=-120):
    """Um `QWheelEvent` de verdade, na janela: o mesmo caminho da roda do mouse. Sobre a grade o `GridView` anima; espera parar."""
    pos = QPointF(x, y)
    QCoreApplication.sendEvent(app.janela, QWheelEvent(pos, pos, QPoint(0, 0), QPoint(0, angulo), Qt.MouseButton.NoButton,
                                                       Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False))
    QTest.qWait(30)
    assert _esperar(lambda: not grade.property("moving"), 3)


@pytest.mark.parametrize("nome", ["seletorDeCapa", "seletorDePapel"])
def test_a_roda_rola_a_grade_um_passo_por_entalhe_em_toda_a_pagina(app, sgdb, wallhaven, nome):
    """M6: um entalhe rola o mesmo nas laterais, sobre a grade e na borda: o `GridView` e o `WheelHandler` não somam."""
    erros = []
    anterior = qInstallMessageHandler(lambda _tipo, _ctx, texto: erros.append(texto))
    try:
        grade, pagina = _grade_longa(app, wallhaven, nome)
        passo = QGuiApplication.styleHints().wheelScrollLines() * 24
        y = pagina.mapToScene(QPointF(0, pagina.height() / 2)).y()
        esquerda = pagina.mapToScene(QPointF(0, 0)).x()
        inicio_da_grade = grade.mapToScene(QPointF(0, 0)).x()
        assert inicio_da_grade - esquerda > 20  # as laterais existem
        lateral = esquerda + 5
        for onde, x in {
            "lateral esquerda": lateral,
            "sobre a grade": inicio_da_grade + grade.width() / 2,
            "lateral direita": esquerda + pagina.width() - 30,
            "borda, sobre a barra": esquerda + pagina.width() - 3,
        }.items():
            antes = grade.property("contentY")
            _girar(app, grade, x, y)
            assert grade.property("contentY") - antes == pytest.approx(passo), onde
            _girar(app, grade, x, y, 120)
            assert grade.property("contentY") == pytest.approx(antes), onde
        # A lateral para nas pontas, como a grade.
        fim = grade.property("contentHeight") - grade.height() + grade.property("bottomMargin")
        for _ in range(int(fim / passo) + 3):
            _girar(app, grade, lateral, y)
        assert grade.property("contentY") == pytest.approx(fim)
        _girar(app, grade, inicio_da_grade + grade.width() / 2, y)  # sobre a grade, na ponta: nada muda
        assert grade.property("contentY") == pytest.approx(fim)
        for _ in range(int(fim / passo) + 3):
            _girar(app, grade, lateral, y, 120)
        assert grade.property("contentY") == pytest.approx(-grade.property("topMargin"))
    finally:
        qInstallMessageHandler(anterior)
    assert not [e for e in erros if "TypeError" in e], erros


@pytest.mark.parametrize("nome", ["seletorDeCapa", "seletorDePapel"])
def test_a_barra_do_seletor_fica_na_borda_da_pagina_e_arrasta_a_grade(app, sgdb, wallhaven, nome):
    """M6: como o `ScrolledWindow` da `main`, a barra é da página inteira, não da grade; e continua arrastando a grade."""
    grade, pagina = _grade_longa(app, wallhaven, nome)
    barra = app.achar(nome + "Rolagem")
    direita = pagina.mapToScene(QPointF(pagina.width(), 0)).x()
    assert barra.mapToScene(QPointF(barra.width(), 0)).x() == pytest.approx(direita)
    assert barra.height() == pagina.height()
    assert barra.mapToScene(QPointF(0, 0)).x() >= grade.mapToScene(QPointF(grade.width(), 0)).x()  # não pisa na última coluna
    x = int(direita - barra.width() / 2)
    topo = int(pagina.mapToScene(QPointF(0, 0)).y())
    QTest.mouseMove(app.janela, QPoint(x, topo + 20))
    QTest.mousePress(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, topo + 20))
    assert barra.property("pressed") is True
    QTest.mouseMove(app.janela, QPoint(x, topo + 200))
    QTest.mouseRelease(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, topo + 200))
    assert grade.property("contentY") > 100


def _seletor_pelo_teclado(app, wallhaven, nome, botao, itens):
    """Abre o seletor com `itens` miniaturas, em 1200, e chega ao campo de busca só com Tab, sem forçar foco."""
    from tests.apoio_seletores import SgdbFalso, lista_de_grades, lista_de_logos, lista_do_wallhaven  # noqa: PLC0415

    app.edicao.seletorDeCapa.sgdb = app.edicao.seletorDeLogo.sgdb = SgdbFalso(grids=lista_de_grades(itens), logos=lista_de_logos(itens))
    wallhaven.achados = lista_do_wallhaven(itens)
    app.janela.resize(1200, 795)
    _esperar(lambda: False, 0.3)
    app.edicao.abrir("shortcuts_z1")
    _clique(app, botao)
    grade = app.achar(nome + "Grade")
    assert _esperar(lambda: _visivel(app, nome) and grade.property("count") == itens, 6)
    _esperar(lambda: False, 0.4)
    campo = app.achar(nome + "Campo")
    for _ in range(12):
        if campo.property("activeFocus"):
            break
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert campo.property("activeFocus") is True
    return grade


def _assert_foco_visivel(app, nome, indice):
    foco = app.janela.activeFocusItem()
    assert foco.objectName() == f"{nome}Miniatura{indice}", foco
    assert foco.property("visualFocus") is True, indice  # o anel de foco acende


SELETORES_DE_GRADE = [
    ("seletorDeCapa", "botaoEscolherCapaSgdb", 9, [4, 5, 6, 6, 5]),  # 4 colunas: 6 + 4 não existe, o foco fica
    ("seletorDeLogo", "botaoEscolherLogoSgdb", 6, [2, 3, 4, 4, 3]),  # 2 colunas
    ("seletorDePapel", "botaoEscolherPapelWallhaven", 9, [4, 5, 6, 6, 5]),
]


@pytest.mark.parametrize("pelo_controle", [False, True], ids=["teclado", "controle"])
@pytest.mark.parametrize(("nome", "botao", "itens", "esperado"), SELETORES_DE_GRADE, ids=[s[0] for s in SELETORES_DE_GRADE])
def test_as_setas_movem_o_foco_visivel_entre_as_miniaturas_e_enter_escolhe(app, sgdb, wallhaven, nome, botao, itens, esperado, pelo_controle):
    """Como a `FlowBox` da `main`: índice coerente em sequência, anel aceso, e Enter ativa a célula. O controle entra pelo `teclar`."""

    def tecla(codigo):
        if pelo_controle:
            app.controle.teclar(int(codigo))
        else:
            QTest.keyClick(app.janela, codigo)

    _seletor_pelo_teclado(app, wallhaven, nome, botao, itens)
    tecla(Qt.Key.Key_Down)
    _assert_foco_visivel(app, nome, 0)
    passos = [Qt.Key.Key_Down, Qt.Key.Key_Right, Qt.Key.Key_Right, Qt.Key.Key_Down, Qt.Key.Key_Left]
    for codigo, indice in zip(passos, esperado, strict=True):
        tecla(codigo)
        _assert_foco_visivel(app, nome, indice)
    tecla(Qt.Key.Key_Return)
    if nome == "seletorDePapel":
        assert _esperar(lambda: _visivel(app, "seletorDePapelUsar"), 6)
    else:
        assert _esperar(lambda: not _visivel(app, nome), 10)


@pytest.mark.parametrize(("nome", "botao", "itens", "_esperado"), SELETORES_DE_GRADE, ids=[s[0] for s in SELETORES_DE_GRADE])
def test_seta_no_campo_seguida_de_enter_escolhe_a_primeira_miniatura(app, sgdb, wallhaven, nome, botao, itens, _esperado):
    _seletor_pelo_teclado(app, wallhaven, nome, botao, itens)
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    if nome == "seletorDePapel":
        assert _esperar(lambda: _visivel(app, "seletorDePapelUsar"), 6)
    else:
        assert _esperar(lambda: not _visivel(app, nome), 10)


@pytest.mark.parametrize(("nome", "botao", "itens"), [("seletorDeCapa", "botaoEscolherCapaSgdb", 30), ("seletorDePapel", "botaoEscolherPapelWallhaven", 24)])
def test_a_seta_desce_a_grade_longa_e_volta_ao_campo(app, sgdb, wallhaven, nome, botao, itens):
    """Fora da tela: a seta rola até a célula e o foco visível continua nela; acima da primeira linha, volta ao campo."""
    grade = _seletor_pelo_teclado(app, wallhaven, nome, botao, itens)
    colunas = app.achar(nome).property("colunas")
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    linhas = (itens - 1) // colunas
    for linha in range(1, linhas + 1):
        QTest.keyClick(app.janela, Qt.Key.Key_Down)
        _assert_foco_visivel(app, nome, linha * colunas)
    assert grade.property("contentY") > 100
    for linha in range(linhas - 1, -1, -1):
        QTest.keyClick(app.janela, Qt.Key.Key_Up)
        _assert_foco_visivel(app, nome, linha * colunas)
    QTest.keyClick(app.janela, Qt.Key.Key_Up)
    assert app.achar(nome + "Campo").property("activeFocus") is True


def test_clicar_de_novo_na_linha_da_iluminacao_fecha_o_balao(app, previas):
    """M8: o aperto na linha fecha o balão e a soltura não o reabre, qualquer que seja a duração do aperto (pela ordem dos eventos)."""
    _com_fita()
    app.edicao.abrir("shortcuts_z1")
    assert _esperar(lambda: _visivel(app, "dialogoDeEdicao"))
    linha = app.achar("linhaDaFita")
    ponto = linha.mapToScene(QPointF(30, linha.height() / 2)).toPoint()
    balao = app.achar("balaoDaCorDaFita")
    for espera in (0, 0.7):  # clique instantâneo e aperto longo
        QTest.mouseClick(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
        assert _esperar(lambda: balao.property("opened") is True)
        QTest.mousePress(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
        _esperar(lambda: False, espera + 0.05)
        QTest.mouseRelease(app.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
        _esperar(lambda: False, 0.3)
        assert balao.property("opened") is False, espera
