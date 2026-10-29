# test_importacao_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A importação no app Qt: o botão, o resumo com "Desfazer", o diálogo de erros e os atalhos soltos."""

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QMetaObject, Qt, QTimer, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickWindow
from PySide6.QtQuickControls2 import QQuickStyle

from cartridges import aplicativo as modulo
from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.importer.source import SourceScanError
from cartridges.jogo import Jogo
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.modelos.controle import ControleDaGrade
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.modelos.sessao import ModeloDaSessao
from cartridges.ponte import Ponte
from cartridges.store.managers.exibicao_manager import ExibicaoManager
from cartridges.utils import restauracao, soltar_atalhos
from cartridges.utils.passada_agendada import PassadaAgendada

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
QQuickStyle.setStyle("Basic")


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


class FonteFalsa:
    """Uma fonte `shortcuts` cujo resultado cada teste dita."""

    source_id = "shortcuts"
    name = "shortcuts"
    is_available = True
    jogos: list = []
    erro: Exception | None = None

    def __iter__(self):
        for jogo in self.jogos:
            yield (jogo, {})
        if self.erro is not None:
            raise self.erro


@pytest.fixture
def fonte(monkeypatch):
    """Troca a fonte de atalhos pela falsa; o teste preenche `fonte.jogos`/`fonte.erro`."""
    classe = type("FonteDoTeste", (FonteFalsa,), {"jogos": [], "erro": None})
    monkeypatch.setattr(modulo, "ShortcutsSource", classe)
    return classe


class FilaRegistrada(FilaDeAvisos):
    """A fila real, anotando as chamadas que o teste confere."""

    def __init__(self):
        super().__init__()
        self.adicionados: list[tuple] = []
        self.dispensados: list = []
        self.depois: list = []

    def adicionar(self, texto, botao="", ao_clicar=None, segundos=5, chave=None):
        self.adicionados.append((texto, botao, segundos))
        return super().adicionar(texto, botao, ao_clicar, segundos, chave)

    def dispensar(self, id):  # noqa: A002
        self.dispensados.append(id)
        super().dispensar(id)

    def dispensar_depois(self, id, segundos):  # noqa: A002
        self.depois.append((id, segundos))
        super().dispensar_depois(id, segundos)


@pytest.fixture(autouse=True)
def importador_limpo(store):  # noqa: ARG001
    from cartridges.importer.importer import Importer  # noqa: PLC0415

    Importer.summary_toast = None
    yield
    Importer.summary_toast = None
    shared.importer = None
    shared.aplicativo = None


def _importar(app, **kwargs):
    """Dispara a importação e espera o fim dela (laço de eventos real, fontes no pool de rede)."""
    app.importar(**kwargs)
    assert _esperar(lambda: not app.importando), "a importação não terminou"
    _esperar()


def _jogos(*nomes):
    return [
        Jogo({"game_id": f"shortcuts_{n}", "source": "shortcuts", "name": n, "executable": "x", "added": 1})
        for n in nomes
    ]


def test_importar_desliga_o_botao_e_religa_no_fim(fonte, app_qt):
    fonte.jogos = _jogos("A")
    app = Aplicativo(FilaRegistrada())
    mudancas = []
    app.importandoChanged.connect(lambda: mudancas.append(app.importando))

    app.importar()
    assert app.importando is True
    assert _esperar(lambda: not app.importando)
    assert mudancas == [True, False]


def test_importacao_termina_com_varios_jogos_de_managers_assincronos(fonte, store, app_qt):
    """Cada pipeline conta o seu fim: uma conexão que enxerga só o último pipeline deixaria a importação pendurada."""
    from cartridges.store.managers.async_manager import AsyncManager  # noqa: PLC0415

    class Lento(AsyncManager):
        def main(self, game, additional_data):
            time.sleep(0.05)

    store.add_manager(Lento())
    fonte.jogos = _jogos("A", "B", "C", "D")
    fila = FilaRegistrada()

    _importar(Aplicativo(fila))

    assert fila.texto == "Importados: 4 jogos"
    assert shared.importer.n_pipelines_done == 4


def test_importar_com_importacao_em_andamento_nao_comeca_outra(fonte, app_qt):
    app = Aplicativo(FilaRegistrada())
    app.definir_importando(True)
    app.importar()
    assert shared.importer is None


def test_resumo_com_desfazer(fonte, store, app_qt):
    fonte.jogos = _jogos("B", "A")
    fila = FilaRegistrada()
    app = Aplicativo(fila)

    _importar(app)

    assert fila.texto == "Importados: A, B"
    assert fila.botao == "Desfazer"
    # Fica na tela até os avisos serem dispensados: sem diálogo, 5 segundos a partir daí.
    assert fila.adicionados == [("Importados: A, B", "Desfazer", 0)]
    assert fila.depois == [(1, 5)]
    assert all(not j.removed for j in store)

    fila.clicar()
    assert all(j.removed for j in store)


def test_resumo_de_um_jogo_so_usa_o_singular(fonte, app_qt):
    fonte.jogos = _jogos("A")
    fila = FilaRegistrada()
    _importar(Aplicativo(fila))
    assert fila.texto == "Importado: A"


def test_importacao_silenciosa_sem_novos_nao_avisa(fonte, app_qt):
    fila = FilaRegistrada()
    _importar(Aplicativo(fila), silenciosa=True)
    assert fila.adicionados == []
    assert fila.visivel is False


def test_importacao_pedida_sem_novos_avisa(fonte, app_qt):
    fila = FilaRegistrada()
    _importar(Aplicativo(fila))
    assert fila.texto == "Nenhum jogo novo encontrado"
    assert fila.botao == ""


def test_nova_importacao_tira_o_resumo_anterior_da_tela(fonte, app_qt):
    fonte.jogos = _jogos("A")
    fila = FilaRegistrada()
    app = Aplicativo(fila)
    _importar(app)
    anterior = fila.adicionados and 1
    fonte.jogos = _jogos("B")
    app.importar()
    assert anterior in fila.dispensados
    assert _esperar(lambda: not app.importando)


def test_erro_de_fonte_unico_vira_dialogo_com_titulo_e_corpo(fonte, app_qt):
    fonte.erro = SourceScanError("Pasta D:\\A & B <b>x</b>", "Não foi possível ler & <i>tudo</i>")
    fila = FilaRegistrada()
    app = Aplicativo(fila)
    pedidos = []
    app.dialogoPedido.connect(lambda *dados: pedidos.append(dados))

    _importar(app)

    assert pedidos == [("Pasta D:\\A & B <b>x</b>", "Não foi possível ler & <i>tudo</i>", [])]
    # Enquanto o diálogo está aberto, o resumo não conta tempo.
    assert fila.depois == []
    app.dialogoFechado()
    assert fila.depois == [(1, 5)]
    app.dialogoFechado()  # repetir não faz nada
    assert len(fila.depois) == 1


def test_erros_viram_dialogo_em_texto_puro(fonte, store, app_qt):
    from cartridges.store.managers.manager import Manager  # noqa: PLC0415

    class Gerente(Manager):
        blocking = True

        def main(self, game, additional_data):
            self.report_error(SourceScanError("Outro erro", "Detalhe"))

    fonte.jogos = _jogos("A")
    fonte.erro = SourceScanError("Erro & <b>negrito</b>", "Caminho C:\\Jogos & Cia <u>x</u>")
    store.add_manager(Gerente())
    app = Aplicativo(FilaRegistrada())
    pedidos = []
    app.dialogoPedido.connect(lambda *dados: pedidos.append(dados))

    _importar(app)

    (titulo, corpo, itens), = pedidos
    assert titulo == "Aviso"
    assert corpo == "Os seguintes erros ocorreram durante a importação:"
    assert itens == [
        {"titulo": "Erro & <b>negrito</b>", "subtitulo": "Caminho C:\\Jogos & Cia <u>x</u>"},
        {"titulo": "Outro erro", "subtitulo": "Detalhe"},
    ]


def test_soltar_urls_nao_locais_sao_ignoradas(tmp_path, schema, app_qt, monkeypatch):
    pasta = tmp_path / "Atalhos"
    pasta.mkdir()
    schema["shortcuts-location"] = str(pasta)
    fora = tmp_path / "Downloads"
    fora.mkdir()
    (fora / "Doom.lnk").write_bytes(b"x")
    chegaram = []
    original = soltar_atalhos.ao_soltar
    monkeypatch.setattr(soltar_atalhos, "ao_soltar", lambda c, i: (chegaram.append(c), original(c, i))[1])
    app = Aplicativo(FilaRegistrada())
    importacoes = []
    monkeypatch.setattr(app, "importar", lambda **kw: importacoes.append(kw))

    app.soltar([QUrl("https://exemplo.com/Falso.lnk"), "mtp://telefone/Foto.lnk", QUrl.fromLocalFile(str(fora / "Doom.lnk"))])

    assert chegaram == [[None, None, fora / "Doom.lnk"]]
    assert [p.name for p in pasta.iterdir()] == ["Doom.lnk"]
    assert len(importacoes) == 1 and importacoes[0]["varrer_atalhos"] is True


def test_soltar_avisa_ate_o_fim_da_importacao(tmp_path, schema, app_qt, monkeypatch):
    pasta = tmp_path / "Atalhos"
    pasta.mkdir()
    schema["shortcuts-location"] = str(pasta)
    (tmp_path / "Doom.lnk").write_bytes(b"x")
    (tmp_path / "Leia.txt").write_bytes(b"x")
    fila = FilaRegistrada()
    app = Aplicativo(fila)
    importacoes = []
    monkeypatch.setattr(app, "importar", lambda **kw: importacoes.append(kw))

    app.soltar([QUrl.fromLocalFile(str(tmp_path / "Doom.lnk")), QUrl.fromLocalFile(str(tmp_path / "Leia.txt"))])

    # O "Importando…" vem primeiro e fica; os demais avisos esperam atrás dele.
    assert fila.adicionados == [("Importando atalhos…", "", 0), ("1 arquivo foi ignorado.", "", 5)]
    assert fila.texto == "Importando atalhos…"
    importacoes[0]["ao_terminar"]()
    assert fila.texto == "1 arquivo foi ignorado."


def test_soltar_durante_importacao_nao_copia(tmp_path, schema, app_qt):
    pasta = tmp_path / "Atalhos"
    pasta.mkdir()
    schema["shortcuts-location"] = str(pasta)
    (tmp_path / "Doom.lnk").write_bytes(b"x")
    fila = FilaRegistrada()
    app = Aplicativo(fila)
    app.definir_importando(True)

    app.soltar([QUrl.fromLocalFile(str(tmp_path / "Doom.lnk"))])

    assert list(pasta.iterdir()) == []
    assert fila.texto == "Aguarde o fim da importação em andamento."


def test_importado_fica_ligado_a_ponte(fonte, store, app_qt):
    """Do fim da importação ao aviso de "iniciado": o jogo que a importação criou chega à Ponte."""
    modelo = ModeloDaBiblioteca()
    fila = FilaRegistrada()
    ponte = Ponte(fila)
    store.add_manager(ExibicaoManager(modelo, ao_ver=ponte.ligar))
    fonte.jogos = _jogos("A")
    _importar(Aplicativo(fila))

    assert modelo.contagem("biblioteca") == 1
    jogo = store.get("shortcuts_A")
    jogo.aviso.emit("{} iniciado".format(jogo.name), "")
    assert _esperar(lambda: any(a[0] == "A iniciado" for a in fila.adicionados))


def test_pendente_resolvido_volta_a_grade(store, app_qt):
    """D37: o modelo só avalia a pendência em `atualizar`; resolvê-la na importação reapresenta o jogo."""
    from cartridges.importer.importer import Importer  # noqa: PLC0415

    modelo = ModeloDaBiblioteca()
    store.add_manager(ExibicaoManager(modelo))
    jogo = _jogos("P")[0]
    restauracao.gravar([jogo.game_id], 1)
    store.add_game(jogo, {}, run_pipeline=False)
    jogo.update()
    _esperar()
    assert modelo.contagem("biblioteca") == 0

    importador = Importer(Aplicativo(FilaRegistrada()))
    importador.scanned_source_ids.add("shortcuts")
    store.duplicate_game_ids.add(jogo.game_id)  # a varredura o achou
    importador.resolver_pendencias()
    _esperar()

    assert restauracao.existe() is False
    assert modelo.contagem("biblioteca") == 1


def test_passada_agendada_espera_pela_importacao_do_aplicativo(app_qt):
    assert PassadaAgendada._importando() is False  # noqa: SLF001
    app = Aplicativo(FilaRegistrada())
    shared.aplicativo = app
    assert PassadaAgendada._importando() is False  # noqa: SLF001
    app.definir_importando(True)
    assert PassadaAgendada._importando() is True  # noqa: SLF001
    app.definir_importando(False)
    assert PassadaAgendada._importando() is False  # noqa: SLF001


# region A janela (QML offscreen, sem a ponte do QWindowKit)


def _achar(raiz, nome):
    pilha = [raiz]
    while pilha:
        atual = pilha.pop()
        if atual.objectName() == nome:
            return atual
        pilha.extend(atual.children())
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
        elif isinstance(atual, QQuickWindow):
            pilha.append(atual.contentItem())
    return None


class _Janela:
    def __init__(self):
        self.modelo = ModeloDaBiblioteca()
        self.filtros = FiltrosDaBiblioteca(self.modelo)
        self.ponte = Ponte()
        self.aplicativo = Aplicativo(self.ponte.fila)
        self.edicao = ModeloDaEdicao(self.aplicativo)
        self.big_picture = BigPicture(self.modelo)
        self.sessao = ModeloDaSessao(self.ponte.fila)
        self.motor = QQmlEngine()
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

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()


def test_dialogo_de_erros_mostra_texto_puro_e_so_fecha_pelo_botao(app_qt):
    janela = _Janela()
    fechados = []
    janela.aplicativo.pedir_dialogo(
        "Aviso", "Corpo & <b>x</b>", [{"titulo": "T & <i>a</i>", "subtitulo": "S & <u>b</u>"}], lambda: fechados.append(1)
    )
    _esperar()
    dialogo = janela.achar("dialogoDeErros")
    assert dialogo.property("visible") is True
    assert janela.achar("tituloDoDialogo").property("text") == "Aviso"
    assert janela.achar("corpoDoDialogo").property("text") == "Corpo & <b>x</b>"
    assert janela.achar("itemTitulo").property("text") == "T & <i>a</i>"
    assert janela.achar("itemSubtitulo").property("text") == "S & <u>b</u>"
    assert janela.achar("botaoDoDialogo").property("visible") is True
    # Com o diálogo aberto, a janela não aceita atalhos arrastados.
    assert janela.achar("alvoDeSoltar").property("enabled") is False

    QMetaObject.invokeMethod(dialogo, "fechar")
    _esperar()
    assert dialogo.property("visible") is False
    assert fechados == [1]
    assert janela.achar("alvoDeSoltar").property("enabled") is True
    janela.fechar()


def test_aviso_de_soltar_comeca_escondido(app_qt):
    janela = _Janela()
    aviso = janela.achar("avisoDeSoltar")
    assert aviso.property("visible") is False
    assert aviso.property("opacity") == 0
    janela.fechar()


# endregion


def test_todo_texto_do_dialogo_e_texto_puro():
    """Caminhos e mensagens de erro não são marcação: nenhum `Text` do diálogo fica no formato automático."""
    fonte_qml = (QML / "DialogoDeAviso.qml").read_text(encoding="utf-8")
    assert fonte_qml.count("Text {") == fonte_qml.count("textFormat: Text.PlainText") > 0
