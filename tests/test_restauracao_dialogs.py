# test_restauracao_dialogs.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A continuação da restauração (D81): o modelo `ContinuacaoDaRestauracao` e os quatro modais do `Aplicativo.qml`
(pasta de atalhos, jogos sem atalho, escolha do atalho, dados do jogo). Os textos são os aprovados; o seletor de
arquivos nunca abre (o modelo só emite `procurarPedido`)."""

import time
from datetime import datetime
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
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.conquistas import ConquistasDoJogo
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.historico import HistoricoDeSessoes
from cartridges.modelos.preferencias import Preferencias
from cartridges.modelos.restauracao import ContinuacaoDaRestauracao
from cartridges.modelos.saves import SavesDoJogo
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.ponte import Ponte
from cartridges.utils import backup, restauracao, session_log
from tests import apoio_aplicativo

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
QQuickStyle.setStyle("Basic")

_RECOMENDACAO = (
    "Escolha o atalho de cada jogo por esta janela. Um atalho importado de outra forma pode entrar como um jogo "
    "novo, sem o tempo de jogo e o histórico de sessões do backup."
)


# -- o modelo, sem tela ---------------------------------------------------------------------------------------------


class _Importador:
    """O `importar` do `Aplicativo`, anotado: o que a restauração pede à importação."""

    def __init__(self) -> None:
        self.pedidos: list[dict] = []
        self.observado: list = []


@pytest.fixture
def aplicativo(monkeypatch):
    anotado = apoio_aplicativo.instalar(monkeypatch)
    anotado.importacoes = _Importador()
    anotado.importar = lambda **kw: anotado.importacoes.pedidos.append(kw)
    return anotado


@pytest.fixture
def modelo(aplicativo, store):  # noqa: ARG001
    return ContinuacaoDaRestauracao(aplicativo)


def _avisos(aplicativo):
    return aplicativo.avisos.textos


def _jogo(store, make_game, game_id="a", nome="Alan Wake", **extra):
    jogo = make_game(game_id=game_id, name=nome, **extra)
    store.add_game(jogo, {}, run_pipeline=False)
    return jogo


def test_pedir_pasta_nao_fecha_sem_escolher(modelo, schema):
    schema["shortcuts-location"] = "D:\\Atalhos-que-nao-existe"
    modelo.continuar()
    assert modelo.pedindoPasta is True
    assert modelo.aberta is True
    assert modelo.textoDaPasta == (
        "A pasta de atalhos usada anteriormente não foi encontrada. Selecione a pasta onde estão os atalhos dos jogos."
    )
    modelo.escolherPasta(QUrl())  # seletor cancelado: a janela continua
    assert modelo.pedindoPasta is True


def test_pedir_pasta_sem_pasta_anterior_so_pede_a_escolha(modelo, schema):
    schema["shortcuts-location"] = ""
    modelo.continuar()
    assert modelo.pedindoPasta is True
    assert modelo.textoDaPasta == "Selecione a pasta onde estão os atalhos dos jogos."


def test_pasta_escolhida_grava_fecha_e_continua(modelo, aplicativo, schema, tmp_path):
    schema["shortcuts-location"] = ""
    modelo.continuar()

    modelo.escolherPasta(QUrl.fromLocalFile(str(tmp_path)))

    assert Path(schema.get_string("shortcuts-location")) == tmp_path
    assert modelo.pedindoPasta is False
    (pedido,) = aplicativo.importacoes.pedidos
    assert pedido["varrer_atalhos"] is True
    assert pedido["silenciosa"] is True
    assert pedido["ao_terminar"] == modelo.mostrarPendentes


def test_aviso_da_pasta_dos_saves(aplicativo, monkeypatch):
    monkeypatch.setattr(backup, "pasta_dos_saves_desfeita", "D:/Saves")
    monkeypatch.setattr(app_modulo.redefinir, "falha", None)

    app_modulo._avisos_da_abertura(aplicativo, False)  # noqa: SLF001

    assert aplicativo.dialogos == [
        (
            "Cópias dos saves na pasta padrão",
            "As cópias dos saves do backup foram para a pasta padrão. "
            "Para voltar a usar D:\\Saves, escolha-a novamente em Preferências.",
        )
    ]


def test_escolher_atalho_sem_candidatos_abre_direto_o_seletor(modelo, store, make_game, monkeypatch):
    _jogo(store, make_game, "gt", "Gran Turismo 7")
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [])
    pedidos = []
    modelo.procurarPedido.connect(lambda: pedidos.append(1))

    modelo.escolherAtalho("gt")

    assert pedidos == [1]
    assert modelo.escolha == {}


def test_escolher_atalho_com_candidatos_abre_a_lista(modelo, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game, "gt", "Gran Turismo 7")
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [tmp_path / "GT7.lnk"])
    pedidos = []
    modelo.procurarPedido.connect(lambda: pedidos.append(1))

    modelo.escolherAtalho("gt")

    assert pedidos == []
    assert modelo.escolha == {
        "id": "gt",
        "nome": "Gran Turismo 7",
        "candidatos": [{"caminho": str(tmp_path / "GT7.lnk"), "titulo": "GT7", "subtitulo": "GT7.lnk"}],
    }


def test_janela_lista_os_pendentes(modelo, store, make_game):
    _jogo(store, make_game, "a", "Alan Wake", playtime=3600)
    restauracao.gravar(["a"], 1)

    modelo.mostrarPendentes()

    assert modelo.pendentesAbertos is True
    assert modelo.pendentes == [{"id": "a", "nome": "Alan Wake", "tempo": "1 hora", "capa": ""}]


def test_pendentes_e_candidatos_em_texto_puro(modelo, store, make_game, monkeypatch, tmp_path, aplicativo):
    """Review Focus 3: o texto de fora chega como está ao QML (que o mostra em `PlainText`)."""
    _jogo(store, make_game, "t", "Tom & <b>Jerry</b>")
    restauracao.gravar(["t"], 1)
    atalho = tmp_path / "<Jogo> & 2.lnk"
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [atalho])

    modelo.mostrarPendentes()
    modelo.escolherAtalho("t")
    modelo.excluir("t")

    assert modelo.pendentes[0]["nome"] == "Tom & <b>Jerry</b>"
    assert modelo.escolha["nome"] == "Tom & <b>Jerry</b>"
    assert modelo.escolha["candidatos"][0]["titulo"] == "<Jogo> & 2"
    assert modelo.escolha["candidatos"][0]["subtitulo"] == "<Jogo> & 2.lnk"
    assert aplicativo.confirmacoes[0]["titulo"] == "Excluir Tom & <b>Jerry</b>?"


def test_usar_atalho_fora_da_lista_e_ignorado(modelo, aplicativo, store, make_game, monkeypatch, tmp_path):
    """A fronteira do QML: só um caminho da lista de candidatos atual vale."""
    _jogo(store, make_game, "gt", "Gran Turismo 7")
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [tmp_path / "GT7.lnk"])
    decididos = []
    monkeypatch.setattr(restauracao, "decidir", lambda *a: decididos.append(a))
    modelo.escolherAtalho("gt")

    modelo.usarAtalho(str(tmp_path / "Outro.lnk"))
    modelo.usarAtalho("")

    assert decididos == []
    assert aplicativo.importacoes.pedidos == []
    assert modelo.escolha["id"] == "gt"  # a lista continua aberta


def test_usar_atalho_sem_escolha_aberta_e_ignorado(modelo, aplicativo, monkeypatch, tmp_path):
    decididos = []
    monkeypatch.setattr(restauracao, "decidir", lambda *a: decididos.append(a))
    modelo.usarAtalho(str(tmp_path / "GT7.lnk"))
    assert decididos == []
    assert aplicativo.importacoes.pedidos == []


def _com_conflito(modelo, store, make_game, monkeypatch, tmp_path):
    """Um jogo restaurado e um novo (criado pela importação) com histórico, ambos no atalho `GT7.lnk`."""
    _jogo(store, make_game, "gt", "Gran Turismo 7", playtime=36000, last_played=1_700_000_050, added=10)
    atalho = tmp_path / "GT7.lnk"
    _jogo(
        store, make_game, "n", "GT7", playtime=6000, last_played=1_700_000_090, added=200,
        shortcut_path=str(atalho),
    )  # fmt: skip
    session_log.record("gt", 36000, 1_700_000_050)
    session_log.record("n", 6000, 1_700_000_090)
    restauracao.gravar(["gt"], 100)
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [atalho])
    modelo.mostrarPendentes()
    modelo.escolherAtalho("gt")
    modelo.usarAtalho(str(atalho))
    return atalho


def test_conflito_textos_e_botoes(modelo, store, make_game, monkeypatch, tmp_path):
    _com_conflito(modelo, store, make_game, monkeypatch, tmp_path)

    assert modelo.escolha == {}
    conflito = modelo.conflito
    assert conflito["nome"] == "Gran Turismo 7"
    ultima = datetime.fromtimestamp(1_700_000_050).strftime("%d/%m/%Y")
    assert conflito["backup"] == {"tempo": "10 horas", "sessoes": "1 sessão", "ultima": f"Última: {ultima}"}
    assert conflito["estePc"]["tempo"] == "1,7 horas"
    assert conflito["dica"] == "Mesclar dados: 11,7 horas em 2 sessões"


def test_decisao_desconhecida_e_ignorada(modelo, aplicativo, store, make_game, monkeypatch, tmp_path):
    _com_conflito(modelo, store, make_game, monkeypatch, tmp_path)
    decididos = []
    monkeypatch.setattr(restauracao, "decidir", lambda *a: decididos.append(a))

    modelo.decidir("apagar_tudo")
    modelo.decidir("")

    assert decididos == []
    assert aplicativo.importacoes.pedidos == []
    assert modelo.conflito["nome"] == "Gran Turismo 7"


def test_decisao_valida_decide_e_importa(modelo, aplicativo, store, make_game, monkeypatch, tmp_path):
    atalho = _com_conflito(modelo, store, make_game, monkeypatch, tmp_path)
    decididos = []
    monkeypatch.setattr(restauracao, "decidir", lambda *a: decididos.append(a))

    modelo.decidir("mesclar")

    ((restaurado, caminho, novo, decisao),) = decididos
    assert (restaurado.game_id, caminho, novo.game_id, decisao) == ("gt", atalho, "n", "mesclar")
    assert modelo.conflito == {}
    assert len(aplicativo.importacoes.pedidos) == 1


def test_manter_este_pc_rele_sem_importar(modelo, aplicativo, store, make_game, monkeypatch, tmp_path):
    _com_conflito(modelo, store, make_game, monkeypatch, tmp_path)
    monkeypatch.setattr(restauracao, "decidir", lambda *a: restauracao.remover("gt"))

    modelo.decidir("este_pc")

    assert aplicativo.importacoes.pedidos == []
    assert _avisos(aplicativo) == ["Restauração concluída"]


def test_atalho_de_mesmo_nome_avisa_conforme_a_lista(modelo, aplicativo, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game, "gt", "Gran Turismo 7")

    def existe(_origem):
        raise restauracao.AtalhoJaExiste("GT7.lnk")

    monkeypatch.setattr(restauracao, "copiar_para_a_pasta", existe)
    arquivo = QUrl.fromLocalFile(str(tmp_path / "GT7.lnk"))

    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [tmp_path / "Outro.lnk"])
    modelo.escolherAtalho("gt")
    modelo.procurado(arquivo)
    assert aplicativo.dialogos == [("Já existe um atalho com este nome. Selecione-o na lista.", "")]

    modelo.fecharEscolha()
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [])
    modelo.escolherAtalho("gt")  # sem candidatos: só o seletor
    modelo.procurado(arquivo)
    assert aplicativo.dialogos[1:] == [("Já existe um atalho com este nome na pasta de atalhos.", "")]


def test_falha_ao_copiar_o_atalho_sobe_para_o_erro_inesperado(modelo, store, make_game, monkeypatch, tmp_path):
    """Como na `main`: a exceção sobe ao `sys.excepthook` (log e diálogo), sem engolir (D89)."""
    _jogo(store, make_game, "gt", "Gran Turismo 7")

    def falha(_origem):
        raise PermissionError("negado")

    monkeypatch.setattr(restauracao, "copiar_para_a_pasta", falha)
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [])
    modelo.escolherAtalho("gt")
    with pytest.raises(PermissionError):
        modelo.procurado(QUrl.fromLocalFile(str(tmp_path / "GT7.lnk")))


def test_procurado_sem_escolha_ou_vazio_e_ignorado(modelo, aplicativo, monkeypatch, tmp_path):
    copiados = []
    monkeypatch.setattr(restauracao, "copiar_para_a_pasta", lambda o: copiados.append(o) or o)
    modelo.procurado(QUrl.fromLocalFile(str(tmp_path / "GT7.lnk")))
    modelo.procurado(QUrl())
    assert copiados == []
    assert aplicativo.importacoes.pedidos == []


def test_escolher_atalho_trava_a_lista_enquanto_importa(modelo, aplicativo, store, make_game, monkeypatch, tmp_path):
    """Duas importações ao mesmo tempo zerariam as listas uma da outra."""
    _jogo(store, make_game, "gt", "Gran Turismo 7")
    atalho = tmp_path / "GT7.lnk"
    eventos = []
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [atalho])
    monkeypatch.setattr(restauracao, "decidir", lambda *_a: eventos.append("decidir"))
    aplicativo.importar = lambda **_kw: eventos.append(("importar", modelo.listaTravada))
    modelo.escolherAtalho("gt")

    modelo.usarAtalho(str(atalho))

    assert eventos == ["decidir", ("importar", True)]
    assert modelo.escolha == {}


def test_janela_destrava_a_lista_ao_atualizar(modelo, aplicativo, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game, "gt", "Gran Turismo 7")
    restauracao.gravar(["gt"], 1)
    atalho = tmp_path / "GT7.lnk"
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [atalho])
    monkeypatch.setattr(restauracao, "decidir", lambda *_a: None)
    modelo.mostrarPendentes()
    modelo.escolherAtalho("gt")
    modelo.usarAtalho(str(atalho))
    assert modelo.listaTravada is True

    aplicativo.importacoes.pedidos[0]["ao_terminar"]()  # o fim da importação

    assert modelo.listaTravada is False
    assert modelo.pendentesAbertos is True


def test_importacao_que_termina_com_a_lista_fechada_nao_a_reabre(modelo, aplicativo, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game, "gt", "Gran Turismo 7")
    restauracao.gravar(["gt"], 1)
    atalho = tmp_path / "GT7.lnk"
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [atalho])
    monkeypatch.setattr(restauracao, "decidir", lambda *_a: None)
    modelo.mostrarPendentes()
    modelo.escolherAtalho("gt")
    modelo.usarAtalho(str(atalho))
    modelo.lembrarDepois()

    aplicativo.importacoes.pedidos[0]["ao_terminar"]()

    assert modelo.pendentesAbertos is False
    assert modelo.listaTravada is False
    assert _avisos(aplicativo) == []


def test_importacao_que_esvazia_a_lista_fechada_avisa_restauracao_concluida(
    modelo, aplicativo, store, make_game, monkeypatch, tmp_path
):
    _jogo(store, make_game, "gt", "Gran Turismo 7")
    restauracao.gravar(["gt"], 1)
    atalho = tmp_path / "GT7.lnk"
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [atalho])
    monkeypatch.setattr(restauracao, "decidir", lambda *_a: None)
    modelo.mostrarPendentes()
    modelo.escolherAtalho("gt")
    modelo.usarAtalho(str(atalho))
    modelo.lembrarDepois()
    restauracao.remover("gt")

    aplicativo.importacoes.pedidos[0]["ao_terminar"]()

    assert _avisos(aplicativo) == ["Restauração concluída"]
    assert modelo.listaTravada is False


def test_janela_que_esvazia_avisa_restauracao_concluida(modelo, aplicativo, store, make_game):
    _jogo(store, make_game)
    restauracao.gravar(["a"], 1)
    modelo.mostrarPendentes()

    restauracao.remover("a")
    modelo.mostrarPendentes()

    assert _avisos(aplicativo) == ["Restauração concluída"]
    assert modelo.pendentesAbertos is False
    assert modelo.aberta is False


def test_lembrar_mais_tarde_nao_avisa(modelo, aplicativo, store, make_game):
    _jogo(store, make_game)
    restauracao.gravar(["a"], 1)
    modelo.mostrarPendentes()

    modelo.lembrarDepois()

    assert modelo.pendentesAbertos is False
    assert _avisos(aplicativo) == []
    assert restauracao.existe() is True


def test_importacao_que_resolve_tudo_avisa_sem_abrir_a_janela(modelo, aplicativo):
    modelo.mostrarPendentes()  # a importação já resolveu tudo: sem arquivo
    assert modelo.pendentesAbertos is False
    assert _avisos(aplicativo) == ["Restauração concluída"]


def test_importacao_com_pendencias_abre_a_janela_sem_avisar(modelo, aplicativo, store, make_game):
    _jogo(store, make_game)
    restauracao.gravar(["a"], 1)
    modelo.mostrarPendentes()
    assert modelo.pendentesAbertos is True
    assert _avisos(aplicativo) == []


def test_excluir_pede_confirmacao_com_o_nome(modelo, aplicativo, store, make_game):
    _jogo(store, make_game, "a", "Tom & <b>Jerry</b>")
    _jogo(store, make_game, "b", "Zelda")
    restauracao.gravar(["a", "b"], 1)
    modelo.mostrarPendentes()

    modelo.excluir("a")

    (pedido,) = aplicativo.confirmacoes
    assert pedido["titulo"] == "Excluir Tom & <b>Jerry</b>?"
    assert pedido["corpo"] == "Tem certeza que deseja excluir este jogo? Esta ação é irreversível."
    assert pedido["rotulo"] == "Excluir"
    assert pedido["destrutivo"] is True
    aplicativo.responder(0, False)
    assert store.get("a") is not None
    assert [p["id"] for p in modelo.pendentes] == ["a", "b"]

    aplicativo.responder(0, True)
    assert store.get("a") is None
    assert [p["id"] for p in modelo.pendentes] == ["b"]


def test_excluir_de_jogo_desconhecido_e_ignorado(modelo, aplicativo):
    modelo.excluir("nao-existe")
    assert aplicativo.confirmacoes == []


def test_abertura_com_restauracao_pendente_continua(app_qt, aplicativo, schema):  # noqa: ARG001
    """`_abrir` com restauração pendente chama o `continuar()`, e não a importação automática."""
    schema["auto-import"] = True
    restauracao.gravar(["a"], 1)
    continuacao = SimpleNamespace(continuar=lambda: aplicativo.importacoes.observado.append("continuar"))
    aplicativo.importar = lambda **_kw: aplicativo.importacoes.observado.append("importar")

    app_modulo._importar_na_abertura(aplicativo, continuacao)  # noqa: SLF001
    _esperar()

    assert aplicativo.importacoes.observado == ["continuar"]


def test_abertura_sem_restauracao_importa_se_automatica(app_qt, aplicativo, schema):  # noqa: ARG001
    schema["auto-import"] = True
    continuacao = SimpleNamespace(continuar=lambda: aplicativo.importacoes.observado.append("continuar"))
    aplicativo.importar = lambda **kw: aplicativo.importacoes.observado.append(("importar", kw))

    app_modulo._importar_na_abertura(aplicativo, continuacao)  # noqa: SLF001
    _esperar()

    assert aplicativo.importacoes.observado == [("importar", {"silenciosa": True})]


# -- a tela ---------------------------------------------------------------------------------------------------------


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
    return QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]


def _puro(objeto):
    return _avaliar(objeto, "textFormat === Text.PlainText") is True


class _DetalhesFalsos(QObject):
    alterado = Signal()
    jogoId = ""  # noqa: N815
    loja = SimpleNamespace(get=lambda _id: None)


class _Janela:
    def __init__(self, store):
        self.modelo_da_biblioteca = ModeloDaBiblioteca()
        self.filtros = FiltrosDaBiblioteca(self.modelo_da_biblioteca)
        self.ponte = Ponte()
        self.aplicativo = Aplicativo(self.ponte.fila)
        self.edicao = ModeloDaEdicao(self.aplicativo)
        self.historico = HistoricoDeSessoes(store)
        self.saves = SavesDoJogo(self.aplicativo)
        self.preferencias = shared.preferencias = Preferencias(self.ponte.fila, lambda: True)
        self.painel_das_tarefas = PainelDasTarefas()
        self.big_picture = BigPicture(self.modelo_da_biblioteca)
        self.sessao = ModeloDaSessao(self.ponte.fila)
        self.conquistas = ConquistasDoJogo(_DetalhesFalsos(), self.sessao)
        self.restauracao = ContinuacaoDaRestauracao(self.aplicativo)
        self.importacoes: list[dict] = []
        # A importação de verdade lê a pasta de atalhos; aqui só se anota o pedido.
        self.aplicativo.importar = lambda **kw: self.importacoes.append(kw)
        self.motor = QQmlEngine()
        self.motor.addImageProvider("fundo", ProvedorDoFundo())
        contexto = self.motor.rootContext()
        for nome, valor in (
            ("filtros", self.filtros),
            ("paginaTodos", FiltroDaPagina(self.modelo_da_biblioteca, self.filtros, "biblioteca")),
            ("paginaZerados", FiltroDaPagina(self.modelo_da_biblioteca, self.filtros, "zerados")),
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

    def achar(self, nome, dentro=None):
        objeto = _achar(dentro or self.janela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def visivel(self, nome):
        return self.achar(nome).property("visible") is True

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()


@pytest.fixture
def janela(app_qt, store, aplicativo, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(shared, "preferencias", None, raising=False)
    criadas = []

    def criar():
        criadas.append(_Janela(store))
        return criadas[-1]

    yield criar
    for j in criadas:
        j.fechar()


def _clicar(objeto):
    QMetaObject.invokeMethod(objeto, "click", Qt.ConnectionType.DirectConnection)


def test_pedir_pasta_esc_e_x_nao_fecham(janela, schema):
    schema["shortcuts-location"] = "D:\\Atalhos-que-nao-existe"
    j = janela()
    j.restauracao.continuar()
    dialogo = j.achar("dialogoDaPastaDeAtalhos")
    assert _esperar(lambda: dialogo.property("visible") is True)
    assert j.achar("textoDaPasta", dialogo).property("text") == (
        "A pasta de atalhos usada anteriormente não foi encontrada. Selecione a pasta onde estão os atalhos dos jogos."
    )
    botao = j.achar("botaoEscolherPasta", dialogo)
    assert botao.property("text") == "Escolher pasta…"
    assert _esperar(lambda: botao.property("activeFocus") is True)
    assert j.achar("botaoFecharDoModal", dialogo).property("visible") is False  # sem X
    assert j.achar("alvoDeSoltar").property("enabled") is False

    QTest.keyClick(j.janela, Qt.Key.Key_Escape)
    _esperar()

    assert dialogo.property("visible") is True
    assert j.restauracao.pedindoPasta is True


def test_pedir_pasta_sem_pasta_anterior_mostra_so_a_escolha(janela, schema):
    schema["shortcuts-location"] = ""
    j = janela()
    j.restauracao.continuar()
    assert _esperar(lambda: j.visivel("dialogoDaPastaDeAtalhos"))
    assert j.achar("textoDaPasta").property("text") == "Selecione a pasta onde estão os atalhos dos jogos."
    assert j.achar("dialogoDaPastaDeAtalhos").property("titulo") == "Pasta de atalhos"


def test_janela_dos_pendentes_em_texto_puro_e_botoes(janela, store, make_game):
    _jogo(store, make_game, "t", "Tom & <b>Jerry</b>", playtime=7200)
    restauracao.gravar(["t"], 1)
    j = janela()
    j.restauracao.mostrarPendentes()
    dialogo = j.achar("dialogoDosPendentes")
    assert _esperar(lambda: dialogo.property("visible") is True)

    assert dialogo.property("titulo") == "Jogos sem atalho"
    assert j.achar("textoDosPendentes").property("text") == "Os atalhos dos jogos abaixo não foram encontrados."
    recomendacao = j.achar("recomendacaoDosPendentes")
    assert recomendacao.property("text") == _RECOMENDACAO
    nome = j.achar("nomeDoPendente")
    assert nome.property("text") == "Tom & <b>Jerry</b>"
    assert j.achar("tempoDoPendente").property("text") == "2 horas"
    assert j.achar("botaoEscolherAtalho").property("text") == "Escolher atalho…"
    assert j.achar("botaoExcluirPendente").property("text") == "Excluir"
    assert j.achar("botaoLembrarDepois").property("text") == "Lembrar mais tarde"
    for objeto in (nome, recomendacao, j.achar("tempoDoPendente")):
        assert _puro(objeto)
    assert j.achar("botaoMenu").property("enabled") is False


def test_esc_nos_pendentes_lembra_depois(janela, store, make_game):
    _jogo(store, make_game)
    restauracao.gravar(["a"], 1)
    j = janela()
    j.restauracao.mostrarPendentes()
    assert _esperar(lambda: j.visivel("dialogoDosPendentes"))
    assert _esperar(lambda: j.achar("botaoLembrarDepois").property("activeFocus") is True)

    QTest.keyClick(j.janela, Qt.Key.Key_Escape)

    assert _esperar(lambda: not j.visivel("dialogoDosPendentes"))
    assert restauracao.existe() is True  # continua pendente, sem aviso de concluída
    assert _esperar(lambda: j.achar("grade").property("activeFocus") is True)


def test_botoes_dos_pendentes_chamam_o_modelo(janela, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game)
    restauracao.gravar(["a"], 1)
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [tmp_path / "AW.lnk"])
    j = janela()
    j.restauracao.mostrarPendentes()
    assert _esperar(lambda: j.visivel("dialogoDosPendentes"))

    _clicar(j.achar("botaoEscolherAtalho"))
    assert _esperar(lambda: j.visivel("dialogoDaEscolhaDoAtalho"))
    assert j.achar("dialogoDosPendentes").property("enabled") is False
    j.restauracao.fecharEscolha()
    assert _esperar(lambda: not j.visivel("dialogoDaEscolhaDoAtalho"))
    assert j.achar("dialogoDosPendentes").property("enabled") is True

    _clicar(j.achar("botaoExcluirPendente"))
    confirmacao = j.achar("confirmacaoDoApp")
    assert _esperar(lambda: confirmacao.property("visible") is True)
    assert j.achar("tituloDoDialogo", confirmacao).property("text") == "Excluir Alan Wake?"


def test_escolha_do_atalho_lista_candidatos_em_texto_puro(janela, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game, "t", "Tom & <b>Jerry</b>")
    restauracao.gravar(["t"], 1)
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [tmp_path / "<Jogo> & 2.lnk"])
    j = janela()
    j.restauracao.escolherAtalho("t")
    dialogo = j.achar("dialogoDaEscolhaDoAtalho")
    assert _esperar(lambda: dialogo.property("visible") is True)

    assert dialogo.property("titulo") == "Tom & <b>Jerry</b>"
    titulo = j.achar("tituloDoCandidato")
    subtitulo = j.achar("subtituloDoCandidato")
    assert titulo.property("text") == "<Jogo> & 2"
    assert subtitulo.property("text") == "<Jogo> & 2.lnk"
    assert _puro(titulo)
    assert _puro(subtitulo)
    assert _puro(j.achar("tituloDoModal", dialogo))
    assert j.achar("botaoProcurarOutro").property("text") == "Procurar outro atalho…"


def test_clicar_num_candidato_usa_o_atalho(janela, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game, "gt", "Gran Turismo 7")
    atalho = tmp_path / "GT7.lnk"
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [atalho])
    monkeypatch.setattr(restauracao, "decidir", lambda *_a: None)
    j = janela()
    j.restauracao.escolherAtalho("gt")
    assert _esperar(lambda: j.visivel("dialogoDaEscolhaDoAtalho"))

    _clicar(j.achar("candidato-0"))

    assert _esperar(lambda: not j.visivel("dialogoDaEscolhaDoAtalho"))
    assert len(j.importacoes) == 1


def test_esc_fecha_so_a_escolha_e_o_foco_volta(janela, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game)
    restauracao.gravar(["a"], 1)
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [tmp_path / "AW.lnk"])
    j = janela()
    j.restauracao.mostrarPendentes()
    assert _esperar(lambda: j.visivel("dialogoDosPendentes"))
    escolher = j.achar("botaoEscolherAtalho")
    escolher.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    _clicar(escolher)
    assert _esperar(lambda: j.visivel("dialogoDaEscolhaDoAtalho"))
    assert _esperar(lambda: j.achar("candidato-0").property("activeFocus") is True)

    QTest.keyClick(j.janela, Qt.Key.Key_Escape)

    assert _esperar(lambda: not j.visivel("dialogoDaEscolhaDoAtalho"))
    assert j.visivel("dialogoDosPendentes")
    assert _esperar(lambda: j.achar("botaoEscolherAtalho").property("activeFocus") is True)


def test_tab_circula_dentro_dos_pendentes(janela, store, make_game):
    _jogo(store, make_game)
    restauracao.gravar(["a"], 1)
    j = janela()
    j.restauracao.mostrarPendentes()
    assert _esperar(lambda: j.visivel("dialogoDosPendentes"))
    dialogo = j.achar("dialogoDosPendentes")
    nomes = ("botaoFecharDoModal", "botaoEscolherAtalho", "botaoExcluirPendente", "botaoLembrarDepois")
    sequencia = [j.achar(n, dialogo) for n in nomes]
    assert _esperar(lambda: sequencia[-1].property("activeFocus") is True)  # o foco inicial
    for esperado in sequencia:  # ... -> X -> Escolher -> Excluir -> Lembrar
        QTest.keyClick(j.janela, Qt.Key.Key_Tab)
        assert _esperar(lambda esperado=esperado: esperado.property("activeFocus") is True)


def test_lista_travada_enquanto_a_importacao_roda(janela, store, make_game, monkeypatch, tmp_path):
    _jogo(store, make_game)
    restauracao.gravar(["a"], 1)
    atalho = tmp_path / "AW.lnk"
    monkeypatch.setattr(restauracao, "candidatos", lambda _jogo: [atalho])
    monkeypatch.setattr(restauracao, "decidir", lambda *_a: None)
    j = janela()
    j.restauracao.mostrarPendentes()
    j.restauracao.escolherAtalho("a")
    j.restauracao.usarAtalho(str(atalho))
    _esperar()

    assert j.achar("listaDosPendentes").property("enabled") is False
    j.importacoes[0]["ao_terminar"]()
    assert _esperar(lambda: j.achar("listaDosPendentes").property("enabled") is True)


def test_conflito_textos_e_botoes_na_tela(janela, store, make_game, monkeypatch, tmp_path):
    j = janela()
    _com_conflito(j.restauracao, store, make_game, monkeypatch, tmp_path)
    dialogo = j.achar("dialogoDosDadosDoJogo")
    assert _esperar(lambda: dialogo.property("visible") is True)

    assert dialogo.property("titulo") == "Dados do jogo"
    assert j.achar("nomeDoConflito").property("text") == "Gran Turismo 7"
    assert j.achar("textoDoConflito").property("text") == (
        "Este jogo já possui dados locais. Escolha qual versão deseja manter ou mescle as duas fontes."
    )
    assert [j.achar(n).property("text") for n in ("botaoManterBackup", "botaoMesclar", "botaoManterEstePc")] == [
        "Manter backup", "Mesclar dados", "Manter este PC",
    ]  # fmt: skip
    assert j.achar("rotuloDoCartaoBackup").property("text") == "Backup"
    assert j.achar("rotuloDoCartaoEstePc").property("text") == "Este PC"
    assert j.achar("tempoDoCartaoBackup").property("text") == "10 horas"
    assert j.achar("sessoesDoCartaoBackup").property("text") == "1 sessão"
    assert j.achar("dicaDoConflito").property("text") == "Mesclar dados: 11,7 horas em 2 sessões"
    assert _puro(j.achar("nomeDoConflito"))

    _clicar(j.achar("botaoMesclar"))
    assert _esperar(lambda: not j.visivel("dialogoDosDadosDoJogo"))
    assert len(j.importacoes) == 1


def test_esc_no_conflito_fecha_sem_decidir(janela, store, make_game, monkeypatch, tmp_path):
    j = janela()
    _com_conflito(j.restauracao, store, make_game, monkeypatch, tmp_path)
    assert _esperar(lambda: j.visivel("dialogoDosDadosDoJogo"))
    assert _esperar(lambda: j.achar("botaoManterBackup").property("activeFocus") is True)

    QTest.keyClick(j.janela, Qt.Key.Key_Escape)

    assert _esperar(lambda: not j.visivel("dialogoDosDadosDoJogo"))
    assert j.importacoes == []
    assert j.visivel("dialogoDosPendentes")


def test_o_botao_das_tarefas_some_com_a_restauracao_aberta(janela, schema):
    schema["shortcuts-location"] = ""
    j = janela()
    assert j.janela.property("modalAberto") is False
    j.restauracao.continuar()
    assert _esperar(lambda: j.janela.property("modalAberto") is True)
