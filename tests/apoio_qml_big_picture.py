# apoio_qml_big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Ajudantes dos testes que antes viviam em `test_qml_big_picture.py` e eram importados por outros arquivos de teste.

Um teste nunca importa outro `test_*.py`: importar um arquivo de teste de outro roda a coleta de novo.
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem, QQuickWindow

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos.big_picture import BigPicture, ProvedorDoFundo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from tests.apoio_qml_biblioteca import QML, _achar, _esperar


LARGURA, ALTURA = 800, 600


def _avaliar(objeto, expressao):
    valor = QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]
    return valor.toVariant() if hasattr(valor, "toVariant") else valor


class _Tela:
    """O `BigPicture.qml` sozinho numa janela de teste, sobre um `BigPicture` de jogos de mentira."""

    def __init__(self, quantidade=5, nome=None, animar_passo=False):
        self.modelo = ModeloDaBiblioteca()
        for n in range(quantidade):
            self.modelo.atualizar(
                Jogo(
                    {
                        "game_id": f"imported_{n}", "source": "imported",
                        "name": nome or f"Jogo {n}", "last_played": quantidade - n,
                    }
                )
            )  # fmt: skip
        self.bp = BigPicture(self.modelo)
        self.bp.entrar()  # antes do QML existir: a lista só acompanha a biblioteca visível, e sem fila
        self.bp.filaTerminou()
        self.motor = QQmlEngine()
        self.motor.addImageProvider("fundo", ProvedorDoFundo())
        self.motor.rootContext().setContextProperty("bigPicture", self.bp)
        componente = QQmlComponent(self.motor, QUrl.fromLocalFile(str(QML / "BigPicture.qml")))
        self.janela = QQuickWindow()
        self.tela = componente.createWithInitialProperties({"width": LARGURA, "height": ALTURA, "animarPasso": animar_passo})
        assert self.tela is not None, componente.errorString()
        self.componente = componente
        self.tela.setParentItem(self.janela.contentItem())
        self.janela.resize(LARGURA, ALTURA)
        self.janela.show()
        self.eventos = []
        eventos = self.eventos  # sem `self` no lambda: nada de ciclo preso à árvore Qt
        self.tela.abrir.connect(lambda: eventos.append("abrir"))
        self.tela.sair.connect(lambda: eventos.append("sair"))
        self.tela.forceActiveFocus()
        _esperar()

    def achar(self, nome):
        objeto = _achar(self.tela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def js(self, expressao):
        return _avaliar(self.tela, expressao)

    def fechar(self):
        self.janela.close()
        self.janela.deleteLater()

    def itens(self, classe):
        return _itens(self.tela, lambda i: i.metaObject().className().startswith(classe))


def _itens(raiz, filtro):
    achados, pilha = [], [raiz]
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, QQuickItem):
            if filtro(atual):
                achados.append(atual)
            pilha.extend(atual.childItems())
        else:
            pilha.extend(atual.children())
    return achados


def _aberto_com(monkeypatch, animacoes=True, quantidade=4):
    """O Aplicativo com o Big Picture disponível (o offscreen não tem renderizador 3D) e `quantidade` jogos."""
    from PySide6.QtCore import QMetaObject  # noqa: PLC0415

    from cartridges.modelos import big_picture as modulo  # noqa: PLC0415
    from tests.apoio_qml_biblioteca import _App, _jogos  # noqa: PLC0415

    monkeypatch.setattr(modulo, "tem_3d", lambda _janela: True)
    jogos = _jogos(*((n, f"Jogo {n}", {"last_played": 100 - n}) for n in range(quantidade)))
    app = _App(jogos, animacoes=animacoes)
    app.big_picture.definir_janela(app.janela)
    app.clicar = lambda nome: QMetaObject.invokeMethod(app.achar(nome), "click", Qt.ConnectionType.DirectConnection)
    return app


def _entrar(app):
    app.clicar("botaoBigPicture")
    assert app.big_picture.visivel
    assert _esperar(lambda: not app.big_picture.ocupada, limite=5)


class _LaunchQueAnota:
    """Conta as chamadas e guarda o estado da tela no instante em que o jogo seria iniciado."""

    def __init__(self, app, jogo):
        self.app, self.jogo = app, jogo
        self.chamadas = 0
        self.no_instante = None

    def __call__(self, ao_confirmar=None):
        if self.jogo.comando_a_conferir:
            self.jogo._conferir_comando(ao_confirmar or self)  # noqa: SLF001  # o pedido de confirmação de verdade
            return False
        self.chamadas += 1
        self.no_instante = (self.app.achar("bigPicture").property("progressoAbertura"), self.app.janela.visibility())
        return True


def _com_launch_falso(app, monkeypatch, indice=0):
    monkeypatch.setattr(shared, "store", app.loja)
    monkeypatch.setattr(shared.schema, "get_boolean", lambda chave: False if chave == "minimize-after-launch" else True)  # noqa: FBT003
    jogo = app.jogos[indice]
    jogo.launch = _LaunchQueAnota(app, jogo)
    return jogo
