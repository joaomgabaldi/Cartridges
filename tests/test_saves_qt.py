# test_saves_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Os saves na sessão e as versões ("Restaurar save"): o fim da sessão, o `launch`, o menu do jogo, o diálogo de versões
e a confirmação, no `Aplicativo.qml` inteiro. Os testes de `test_saves_ui.py` desta área vieram para cá com os mesmos nomes."""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEventLoop, QMetaObject, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from cartridges import app as app_modulo
from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.jogo import Jogo
from cartridges.modelos import seletores
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.modelos.preferencias import Preferencias
from cartridges.modelos.restauracao import ContinuacaoDaRestauracao
from cartridges.modelos.saves import SavesDoJogo, corpo_da_confirmacao, formatar, subtitulo
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.ponte import Ponte
from cartridges.saves import backup_de_saves
from cartridges.saves.ludusavi import Versao
from tests import apoio_aplicativo

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
QQuickStyle.setStyle("Basic")


def _versao(id_: str, quando: datetime, comentario: str = "") -> Versao:
    return Versao(id_, quando.replace(tzinfo=timezone.utc), comentario)


def _jogo(n=1, nome="Alfa", **extra) -> Jogo:
    return Jogo({"game_id": f"imported_{n}", "source": "imported", "name": nome, "executable": "x.exe", **extra})


# -- fim da sessão -------------------------------------------------------------


def _sessao_com_avisos():
    avisos = apoio_aplicativo.AvisosAnotados()
    return ModeloDaSessao(avisos), avisos


def test_fim_de_sessao_dispara_backup(monkeypatch, make_game):
    chamados = []
    monkeypatch.setattr(backup_de_saves, "no_fim_da_sessao", chamados.append)
    jogo = make_game()
    modelo, avisos = _sessao_com_avisos()
    modelo.session_toast(jogo, 60)
    assert chamados == [jogo]
    assert len(avisos.textos) == 1


def test_falha_ao_iniciar_o_backup_nao_perde_o_aviso(monkeypatch, make_game, caplog):
    def explode(_jogo):
        raise RuntimeError("falhou")

    monkeypatch.setattr(backup_de_saves, "no_fim_da_sessao", explode)
    modelo, avisos = _sessao_com_avisos()
    with caplog.at_level(logging.ERROR):
        modelo.session_toast(make_game(), 60)  # não levanta
    assert len(avisos.textos) == 1
    assert "não chegou a começar" in caplog.text


def test_falha_ao_iniciar_o_backup_nao_perde_o_aviso_com_anotar(monkeypatch, make_game):
    monkeypatch.setattr(backup_de_saves, "no_fim_da_sessao", lambda _j: 1 / 0)
    modelo, avisos = _sessao_com_avisos()
    modelo.session_toast(make_game(status="playing"), 60)
    assert avisos.ultima["botao"] == "Anotar"


# -- abrir o jogo --------------------------------------------------------------


def test_launch_durante_a_restauracao_avisa_e_nao_abre(monkeypatch):
    # O guarda `sem_jogo_de_verdade` faz o `run_executable` falhar alto se o jogo abrisse.
    jogo = _jogo(nome="Probe", comando_a_conferir=True)
    monkeypatch.setattr(backup_de_saves, "restaurando", lambda g: g is jogo)
    avisos, pedidos = [], []
    jogo.aviso.connect(lambda texto, acao: avisos.append((texto, acao)), Qt.ConnectionType.DirectConnection)
    jogo.confirmar_comando.connect(pedidos.append, Qt.ConnectionType.DirectConnection)

    assert jogo.launch() is False

    assert avisos == [("Aguarde o fim da restauração dos saves de Probe.", "")]
    assert pedidos == []  # antes do comando a conferir (a ordem da `main`)
    assert jogo.last_played == 0


# -- início do app -------------------------------------------------------------


def test_main_atualiza_o_cache_na_abertura(monkeypatch):
    ordem = []

    class Varredura:
        def __init__(self, nome):
            self.nome = nome

        def start(self):
            ordem.append(self.nome)

    monkeypatch.setattr(backup_de_saves, "atualizar_cache", lambda: ordem.append("cache"))
    monkeypatch.setattr(app_modulo, "_ligar_conquistas", lambda _aplicativo: ordem.append("conquistas"))

    class Novidades:
        def acompanhar_a_chave(self):
            pass

        def ligar(self):
            ordem.append("novidades")

    app_modulo._comecar_varreduras(  # noqa: SLF001
        object(), Varredura("atualizacoes"), Novidades(), Varredura("hltb"), Varredura("tamanho")
    )

    assert ordem == ["atualizacoes", "novidades", "hltb", "tamanho", "cache", "conquistas"]


def test_pasta_do_ludusavi_e_a_do_backup_de_saves():
    assert seletores.pasta_do_ludusavi() == backup_de_saves._pasta_config() == shared.app_dir / "ludusavi"  # noqa: SLF001


# -- as funções puras ----------------------------------------------------------


def test_subtitulos_das_versoes():
    quando = datetime(2026, 10, 9, 10, 0)
    assert [
        subtitulo(_versao("v", quando, comentario))
        for comentario in (
            backup_de_saves.INCOMPLETA,
            backup_de_saves.ANTES_DE_RESTAURAR,
            "",
            "comentario do usuario",  # um comentário qualquer nunca aparece na tela
        )
    ] == [
        "Incompleta: alguns arquivos não puderam ser copiados",
        "Guardada antes de uma restauração",
        "",
        "",
    ]


def test_data_local_no_formato_da_spec():
    quando = datetime(2026, 10, 9, 21, 14, tzinfo=timezone.utc)
    local = quando.astimezone()
    assert formatar(quando) == f"{local:%d/%m/%Y} às {local:%H:%M}"
    assert formatar(quando).count(" às ") == 1


def test_confirmacao_tem_o_texto_da_spec():
    versao = _versao("v1", datetime(2026, 10, 9, 21, 14))
    local = versao.quando.astimezone()
    assert corpo_da_confirmacao(versao) == (
        f"Tem certeza que deseja restaurar o save de {local:%d/%m/%Y} às {local:%H:%M}? "
        "Os saves atuais deste jogo serão guardados como uma nova versão antes da restauração."
    )


def test_confirmacao_de_versao_incompleta():
    quando = datetime(2026, 10, 9, 21, 14, tzinfo=timezone.utc)
    local = quando.astimezone()
    assert corpo_da_confirmacao(_versao("v1", quando, backup_de_saves.INCOMPLETA)) == (
        f"Tem certeza que deseja restaurar o save de {local:%d/%m/%Y} às {local:%H:%M}? "
        "Os saves atuais deste jogo serão guardados como uma nova versão antes da restauração. "
        "Esta versão está incompleta: alguns arquivos não foram copiados."
    )


# -- o modelo ------------------------------------------------------------------


class _Loja(QObject):
    jogo_excluido = Signal(str)

    def __init__(self, *jogos):
        super().__init__()
        self.por_id = {j.game_id: j for j in jogos}

    def get(self, game_id, default=None):
        return self.por_id.get(game_id, default)


@pytest.fixture
def aplicativo_anotado(monkeypatch):
    return apoio_aplicativo.instalar(monkeypatch)


def test_abrir_sem_versoes_ou_fora_da_store_nao_abre(monkeypatch, aplicativo_anotado):
    jogo = _jogo(ludusavi_nome="A")
    monkeypatch.setattr(shared, "store", _Loja(jogo), raising=False)
    monkeypatch.setattr(backup_de_saves, "versoes_do_jogo", lambda _j: [])
    saves = SavesDoJogo(aplicativo_anotado)
    assert saves.abrir(jogo.game_id) is False
    assert saves.abrir("imported_99") is False
    assert saves.aberto is False


def test_lista_do_modelo_mais_recente_primeiro(monkeypatch, aplicativo_anotado):
    jogo = _jogo(ludusavi_nome="A")
    monkeypatch.setattr(shared, "store", _Loja(jogo), raising=False)
    velha = _versao("v1", datetime(2026, 10, 8, 12, 0))
    nova = _versao("v2", datetime(2026, 10, 9, 21, 14), backup_de_saves.INCOMPLETA)
    monkeypatch.setattr(backup_de_saves, "versoes_do_jogo", lambda _j: [velha, nova])
    saves = SavesDoJogo(aplicativo_anotado)

    assert saves.abrir(jogo.game_id) is True
    assert saves.aberto is True
    assert saves.versoes == [
        {"id": "v2", "titulo": formatar(nova.quando), "subtitulo": subtitulo(nova)},
        {"id": "v1", "titulo": formatar(velha.quando), "subtitulo": ""},
    ]


# -- a tela --------------------------------------------------------------------


def _esperar(ate=None, limite=5.0):
    limite = 0.3 if ate is None else limite
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(20, laco.quit)
        laco.exec()
        if ate is not None and ate():
            return True
    return ate is None


def _achar(raiz, nome):
    pilha, vistos = [raiz], {}
    while pilha:
        atual = pilha.pop()
        if id(atual) in vistos:
            continue
        vistos[id(atual)] = atual
        try:
            if atual.objectName() == nome:
                return atual
            pilha.extend(atual.children())
            if isinstance(atual, QQuickItem):
                pilha.extend(atual.childItems())
            elif isinstance(atual, QQuickWindow) and atual is raiz:
                pilha.append(atual.contentItem())
        except RuntimeError:
            continue
    return None


def _avaliar(objeto, expressao):
    """Uma expressão QML no contexto do objeto (o que o Python não alcança: enums, `itemAtIndex`, anexos)."""
    return QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]


class _DetalhesFalsos(QObject):
    alterado = Signal()
    jogoId = ""  # noqa: N815
    loja = SimpleNamespace(get=lambda _id: None)


class _Janela:
    def __init__(self, jogos):
        self.jogos = jogos
        self.loja = _Loja(*jogos)
        shared.store = self.loja
        self.modelo = ModeloDaBiblioteca()
        for jogo in jogos:
            self.modelo.atualizar(jogo)
        self.filtros = FiltrosDaBiblioteca(self.modelo)
        self.ponte = Ponte()
        self.aplicativo = Aplicativo(self.ponte.fila)
        self.edicao = ModeloDaEdicao(self.aplicativo)
        self.historico = HistoricoDeSessoes(self.loja)
        self.saves = SavesDoJogo(self.aplicativo)
        self.preferencias = shared.preferencias = Preferencias(self.ponte.fila, lambda: True)
        self.painel_das_tarefas = PainelDasTarefas()
        self.restauracao = ContinuacaoDaRestauracao(self.aplicativo)
        self.big_picture = BigPicture(self.modelo)
        self.sessao = ModeloDaSessao(self.ponte.fila)
        self.conquistas = ConquistasDoJogo(_DetalhesFalsos(), self.sessao)
        self.motor = QQmlEngine()
        from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
        self.motor.addImageProvider("icone", ProvedorDeIcones())
        self.motor.addImageProvider("fundo", ProvedorDoFundo())
        contexto = self.motor.rootContext()
        for nome, valor in (
            ("filtros", self.filtros),
            ("paginaTodos", FiltroDaPagina(self.modelo, self.filtros, "biblioteca")),
            ("paginaZerados", FiltroDaPagina(self.modelo, self.filtros, "zerados")),
            ("aplicativo", self.aplicativo),
            ("ponte", self.ponte),
            ("controle", ControleDaGrade(estado_do_app=lambda: Qt.ApplicationState.ApplicationInactive)),
            ("edicao", self.edicao),
            ("bigPicture", self.big_picture),
            ("sessao", self.sessao),
            ("historico", self.historico),
            ("saves", self.saves),
            ("conquistasDoJogo", self.conquistas),
            ("preferencias", self.preferencias),
            ("painelDasTarefas", self.painel_das_tarefas),
            ("restauracao", self.restauracao),
        ):
            contexto.setContextProperty(nome, valor)
        componente = QQmlComponent(self.motor, QUrl.fromLocalFile(str(QML / "Aplicativo.qml")))
        self.janela = componente.createWithInitialProperties({"semAgente": True})
        assert self.janela is not None, componente.errorString()
        self.componente = componente
        _esperar()

    def achar(self, nome):
        objeto = _achar(self.janela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def fechar_das_versoes(self):
        """O X do cabeçalho do diálogo (o mesmo nome existe em outros diálogos)."""
        objeto = _achar(self.achar("dialogoDeVersoes"), "fecharDoCabecalho")
        assert objeto is not None, "sem o X do diálogo das versões"
        return objeto

    def dentro_da_confirmacao(self, nome):
        objeto = _achar(self.achar("confirmacaoDoApp"), nome)
        assert objeto is not None, f"sem objeto {nome!r} na confirmação"
        return objeto

    def linhas(self):
        lista = self.achar("listaDeVersoes")
        return [_avaliar(lista, f"itemAtIndex({i})") for i in range(_avaliar(lista, "count"))]

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()


@pytest.fixture
def versoes(monkeypatch):
    """Três versões falsas por jogo com `ludusavi_nome`; nenhum Ludusavi roda."""
    lista = [
        _versao("v1", datetime(2026, 10, 7, 9, 0)),
        _versao("v3", datetime(2026, 10, 9, 21, 14), backup_de_saves.ANTES_DE_RESTAURAR),
        _versao("v2", datetime(2026, 10, 8, 12, 0), backup_de_saves.INCOMPLETA),
    ]
    monkeypatch.setattr(backup_de_saves, "versoes_do_jogo", lambda j: list(lista) if j.ludusavi_nome else [])
    monkeypatch.setattr(backup_de_saves, "tem_backup", lambda j: bool(j.ludusavi_nome))
    return lista


@pytest.fixture
def janela_dos_saves(app_qt, versoes, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(shared, "store", None, raising=False)
    criadas = []

    def criar(*jogos):
        criadas.append(_Janela(list(jogos) or [_jogo(1, "Alfa", ludusavi_nome="A"), _jogo(2, "Beta")]))
        return criadas[-1]

    yield criar
    for j in criadas:
        j.fechar()
    shared.store = None


def _abrir_menu(janela, jogo_id):
    menu = janela.achar("menuDoJogo")
    menu.setProperty("jogoId", jogo_id)
    QMetaObject.invokeMethod(menu, "popup", Qt.ConnectionType.DirectConnection)
    _esperar(lambda: menu.property("visible") is True)
    return menu


def test_acao_some_sem_backup(janela_dos_saves):
    janela = janela_dos_saves()
    item = janela.achar("itemRestaurarSave")
    menu = _abrir_menu(janela, "imported_2")  # sem backup
    assert item.property("visible") is False and item.property("height") == 0
    menu.close()
    _esperar(lambda: menu.property("visible") is False)
    menu = _abrir_menu(janela, "imported_1")  # com backup
    assert item.property("visible") is True and item.property("height") > 0
    menu.close()


def test_restore_save_esta_registrada_e_no_menu(janela_dos_saves):
    """O item existe, numa seção própria (separador) depois de "Remover"."""
    janela = janela_dos_saves()
    menu = janela.achar("menuDoJogo")
    item = janela.achar("itemRestaurarSave")
    assert item.property("text") == "Restaurar save"
    ordem = _avaliar(menu, "[0, 1, 2, 3].map(function (i) { return itemAt(i) ? itemAt(i).objectName + '|' + itemAt(i).text : '' }).join('#')").split("#")
    assert ordem[0].startswith("itemEditar|") and ordem[1].startswith("itemRemover|")
    assert ordem[2].startswith("|")  # o separador (sem nome nem texto)
    assert ordem[3] == "itemRestaurarSave|Restaurar save"


def test_dialogo_lista_versoes_mais_recente_primeiro(janela_dos_saves, versoes):
    janela = janela_dos_saves()
    dialogo = janela.achar("dialogoDeVersoes")
    assert dialogo.property("visible") is False
    # Abaixo dos avisos e da confirmação (declarados depois, no mesmo nível): nenhum `z` o põe na frente deles.
    assert dialogo.property("z") <= janela.achar("camadaDeAvisos").property("z")
    assert janela.saves.abrir("imported_1") is True
    assert _esperar(lambda: dialogo.property("visible") is True)

    linhas = janela.linhas()
    titulos = [_avaliar(linha, "modelData.titulo") for linha in linhas]
    assert titulos == [formatar(v.quando) for v in sorted(versoes, key=lambda v: v.quando, reverse=True)]
    assert [_avaliar(linha, "modelData.id") for linha in linhas] == ["v3", "v2", "v1"]
    # Os cartões de trás e a soltura de atalhos ficam apagados.
    assert janela.achar("alvoDeSoltar").property("enabled") is False
    assert janela.achar("pagina").property("enabled") is False
    assert janela.achar("botaoBusca").property("enabled") is False
    assert _esperar(lambda: janela.fechar_das_versoes().property("activeFocus") is True)


def test_versao_incompleta_chega_ao_leitor_como_descricao(janela_dos_saves):
    """G-M9: o título é o nome da linha e o subtítulo (que diz se a versão é incompleta) é a descrição, como a `AdwActionRow`."""
    janela = janela_dos_saves()
    assert janela.saves.abrir("imported_1") is True
    assert _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is True)
    for linha in janela.linhas():
        botao = _achar(linha, linha.property("objectName") + "Botao")
        assert _avaliar(botao, "Accessible.name") == _avaliar(linha, "modelData.titulo")
        assert _avaliar(botao, "Accessible.description") == _avaliar(linha, "modelData.subtitulo")
    assert any(_avaliar(_achar(l, l.property("objectName") + "Botao"), "Accessible.description") for l in janela.linhas())


def test_versoes_e_confirmacao_em_texto_puro(janela_dos_saves, monkeypatch):
    janela = janela_dos_saves(_jogo(1, "Tom & <b>Jerry</b>", ludusavi_nome="A"))
    assert janela.saves.abrir("imported_1")
    _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is True)
    for linha in janela.linhas():
        for sufixo in ("Titulo", "Subtitulo"):
            assert _avaliar(_achar(linha, linha.objectName() + sufixo), "textFormat === Text.PlainText") is True
    # A segunda linha em ordem decrescente é a incompleta: o texto de fora (o nome do jogo) nunca é interpretado.
    QMetaObject.invokeMethod(janela.linhas()[1], "click", Qt.ConnectionType.DirectConnection)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    for nome in ("tituloDoDialogo", "corpoDoDialogo"):
        assert _avaliar(janela.dentro_da_confirmacao(nome), "textFormat === Text.PlainText") is True
    assert janela.dentro_da_confirmacao("tituloDoDialogo").property("text") == "Restaurar este save?"

    # O único texto desta área que leva o nome do jogo é o aviso do "Jogar" durante a restauração.
    jogo = janela.jogos[0]
    janela.ponte.ligar(jogo)
    monkeypatch.setattr(backup_de_saves, "restaurando", lambda g: g is jogo)
    assert jogo.launch() is False
    aviso = janela.achar("textoDoAviso")
    assert _esperar(lambda: aviso.property("text") == "Aguarde o fim da restauração dos saves de Tom & <b>Jerry</b>.")
    assert _avaliar(aviso, "textFormat === Text.PlainText") is True


def _escolher(janela, indice):
    QMetaObject.invokeMethod(janela.linhas()[indice], "click", Qt.ConnectionType.DirectConnection)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    return confirmacao


def _responder_pelo_botao(janela, nome):
    janela.dentro_da_confirmacao(nome).forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)


def test_confirmar_restaura_e_fecha_o_dialogo(janela_dos_saves, monkeypatch):
    restaurados = []
    monkeypatch.setattr(backup_de_saves, "restaurar", lambda jogo, versao: restaurados.append((jogo, versao)))
    janela = janela_dos_saves()
    janela.saves.abrir("imported_1")
    _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is True)

    confirmacao = _escolher(janela, 1)  # a "v2", incompleta
    assert janela.dentro_da_confirmacao("botaoConfirmarDoDialogo").property("text") == "Restaurar"
    assert janela.dentro_da_confirmacao("botaoCancelarDoDialogo").property("text") == "Cancelar"  # destrutivo
    assert "Esta versão está incompleta" in janela.dentro_da_confirmacao("corpoDoDialogo").property("text")
    assert restaurados == []
    _responder_pelo_botao(janela, "botaoConfirmarDoDialogo")

    assert _esperar(lambda: confirmacao.property("visible") is False)
    assert restaurados == [(janela.jogos[0], "v2")]
    assert janela.saves.aberto is False
    assert _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is False)


def test_cancelar_nao_restaura(janela_dos_saves, monkeypatch):
    restaurados = []
    monkeypatch.setattr(backup_de_saves, "restaurar", lambda jogo, versao: restaurados.append(versao))
    janela = janela_dos_saves()
    janela.saves.abrir("imported_1")
    _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is True)

    confirmacao = _escolher(janela, 0)
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)  # a confirmação responde "não"; o Esc não chega ao diálogo

    assert _esperar(lambda: confirmacao.property("visible") is False)
    assert restaurados == []
    assert janela.saves.aberto is True  # a lista continua: dá para escolher outra versão
    assert janela.achar("dialogoDeVersoes").property("visible") is True


def test_jogo_que_sai_da_store_fecha_o_dialogo(janela_dos_saves, monkeypatch):
    restaurados = []
    monkeypatch.setattr(backup_de_saves, "restaurar", lambda jogo, versao: restaurados.append(versao))
    janela = janela_dos_saves()
    janela.saves.abrir("imported_1")
    _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is True)

    janela.loja.por_id.pop("imported_1")
    janela.loja.jogo_excluido.emit("imported_2")  # outro jogo: o diálogo fica
    _esperar()
    assert janela.saves.aberto is True
    janela.loja.jogo_excluido.emit("imported_1")
    assert _esperar(lambda: janela.saves.aberto is False)
    assert _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is False)

    # Excluído com a confirmação na tela: confirmar depois não restaura nada.
    janela.loja.por_id["imported_1"] = janela.jogos[0]
    janela.saves.abrir("imported_1")
    _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is True)
    _escolher(janela, 0)
    janela.loja.por_id.pop("imported_1")
    janela.loja.jogo_excluido.emit("imported_1")
    _esperar(lambda: janela.saves.aberto is False)
    _responder_pelo_botao(janela, "botaoConfirmarDoDialogo")
    _esperar()
    assert restaurados == []


def test_esc_fecha_e_o_foco_volta_ao_cartao(janela_dos_saves):
    """Aberto pelo menu do jogo (o único caminho real): o item do menu some ao fechar, e o foco vai à grade."""
    janela = janela_dos_saves()
    grade = janela.achar("grade")
    grade.forceActiveFocus()
    _esperar()
    assert grade.property("activeFocus") is True

    _abrir_menu(janela, "imported_1")
    QMetaObject.invokeMethod(janela.achar("itemRestaurarSave"), "click", Qt.ConnectionType.DirectConnection)
    dialogo = janela.achar("dialogoDeVersoes")
    assert _esperar(lambda: dialogo.property("visible") is True)
    assert _esperar(lambda: janela.fechar_das_versoes().property("activeFocus") is True)

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)

    assert _esperar(lambda: dialogo.property("visible") is False)
    assert janela.saves.aberto is False
    assert _esperar(lambda: grade.property("activeFocus") is True)


def test_tab_circula_dentro_do_dialogo_das_versoes(janela_dos_saves):
    janela = janela_dos_saves()
    janela.saves.abrir("imported_1")
    _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is True)
    botao = janela.fechar_das_versoes()
    assert _esperar(lambda: botao.property("activeFocus") is True)
    linhas = janela.linhas()
    for esperado in (*linhas, botao):  # X -> v3 -> v2 -> v1 -> X
        QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
        assert _esperar(lambda esperado=esperado: esperado.property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Backtab)
    assert _esperar(lambda: linhas[-1].property("activeFocus") is True)


def test_setas_e_paginas_movem_o_foco_entre_as_versoes(janela_dos_saves):
    janela = janela_dos_saves()
    janela.saves.abrir("imported_1")
    _esperar(lambda: janela.achar("dialogoDeVersoes").property("visible") is True)
    linhas = janela.linhas()
    linhas[0].forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert _esperar(lambda: linhas[1].property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_PageDown)  # passa do fim: para na última
    assert _esperar(lambda: linhas[2].property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Up)
    assert _esperar(lambda: linhas[1].property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_PageUp)
    assert _esperar(lambda: linhas[0].property("activeFocus") is True)


def test_fechar_as_versoes_devolve_o_foco_a_grade(janela_dos_saves):
    """Aberto sem nenhum item com o foco (só o `contentItem` da janela): ao fechar, o foco vai à grade, não ao fundo."""
    janela = janela_dos_saves()
    grade = janela.achar("grade")
    grade.setProperty("focus", False)
    janela.janela.contentItem().forceActiveFocus()
    _esperar()
    assert janela.janela.activeFocusItem() is janela.janela.contentItem()

    assert janela.saves.abrir("imported_1") is True
    dialogo = janela.achar("dialogoDeVersoes")
    assert _esperar(lambda: janela.fechar_das_versoes().property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)

    assert _esperar(lambda: dialogo.property("visible") is False)
    assert _esperar(lambda: grade.property("activeFocus") is True)
