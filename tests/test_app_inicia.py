# test_app_inicia.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O ponto de entrada `python -m cartridges` e o que ele monta."""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEventLoop, QObject, QTimer, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca

RAIZ = Path(__file__).resolve().parent.parent
QML = RAIZ / "cartridges" / "qml"


def _ficha(pasta, game_id, nome):
    dados = {"game_id": game_id, "source": "imported", "name": nome, "executable": "start game.exe"}
    (pasta / f"{game_id}.json").write_text(json.dumps(dados), encoding="utf-8")


def test_app_carrega_e_sai(tmp_path):
    games = tmp_path / "games"
    games.mkdir(exist_ok=True)
    _ficha(games, "imported_1", "Alfa")
    _ficha(games, "imported_2", "Beta")
    (games / "quebrada.json").write_text("{ isto nao e json", encoding="utf-8")
    ambiente = {
        **os.environ,
        "CARTRIDGES_DADOS": str(tmp_path),
        "CARTRIDGES_REGISTRO": rf"Software\CartridgesTestes\app-{uuid.uuid4()}",
        "QT_QPA_PLATFORM": "offscreen",
    }
    resultado = subprocess.run(
        [sys.executable, "-m", "cartridges", "--sair-apos-carregar"],
        cwd=RAIZ,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr
    assert "jogos carregados: 2" in resultado.stdout


def _carregar(url, **propriedades):
    motor = QQmlEngine()
    from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
    motor.addImageProvider("icone", ProvedorDeIcones())
    componente = QQmlComponent(motor, QUrl.fromLocalFile(str(QML / url)))
    objeto = componente.createWithInitialProperties(propriedades)
    assert objeto is not None, componente.errorString()
    return motor, componente, objeto


def _esperar(ms=300):
    laco = QEventLoop()
    QTimer.singleShot(ms, laco.quit)
    laco.exec()


def test_a_grade_cria_um_cartao_por_jogo(app_qt):
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(Jogo({"game_id": "a", "source": "imported", "name": "Alfa"}))
    _motor, _comp, grade = _carregar("Grade.qml", biblioteca=modelo, width=800, height=600)
    _esperar()
    conteudo = grade.property("contentItem")
    delegates = [item for item in conteudo.childItems() if item.property("jogoId") == "a"]
    assert len(delegates) == 1, "o delegate do jogo não foi criado"
    cartao = delegates[0].childItems()[0]  # o CartaoDoJogo
    assert cartao.property("nome") == "Alfa"


def test_dialogo_de_confirmacao_usa_o_texto_aprovado(app_qt):
    from cartridges.ponte import Ponte  # noqa: PLC0415

    ponte = Ponte()
    pedidos = []
    ponte.confirmacaoPedida.connect(lambda titulo, corpo: pedidos.append((titulo, corpo)))
    chamadas = []
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "Alfa", "executable": "start x.exe", "run_as_admin": True})
    ponte.ligar(jogo)
    jogo.confirmar_comando.emit(lambda: chamadas.append(1))
    assert pedidos == [
        (
            "Iniciar Alfa?",
            "Este jogo foi restaurado de um backup. Antes de iniciá-lo pela primeira vez, "
            "confira se o comando abaixo é o esperado:\n\nstart x.exe\n\nO jogo será executado como administrador.",
        )
    ]
    ponte.confirmar()
    assert chamadas == [1]
    ponte.confirmar()  # nada pendente: não repete
    assert chamadas == [1]


def test_primeiro_lancamento_pede_confirmacao(app_qt, monkeypatch):
    """Um jogo restaurado de um backup só inicia depois de a pessoa conferir o comando."""
    from cartridges.ponte import Ponte  # noqa: PLC0415

    executados = []
    monkeypatch.setattr("cartridges.jogo.run_executable", lambda comando, admin: executados.append((comando, admin)))
    ponte = Ponte()
    pedidos = []
    ponte.confirmacaoPedida.connect(lambda titulo, corpo: pedidos.append((titulo, corpo)))
    jogo = Jogo(
        {"game_id": "a", "source": "imported", "name": "Alfa", "executable": "cmd /c echo x\u202e& calc",
         "run_as_admin": True, "comando_a_conferir": True}
    )  # fmt: skip
    jogo.save = lambda: None
    ponte.ligar(jogo)
    relancados = []

    assert jogo.launch(lambda: relancados.append(1)) is False
    assert executados == [] and len(pedidos) == 1
    assert "cmd /c echo x<U+202E>& calc" in pedidos[0][1] and "administrador" in pedidos[0][1]

    ponte.cancelar()  # a pessoa desistiu: nada inicia e o jogo continua por conferir
    ponte.confirmar()
    assert jogo.comando_a_conferir is True and relancados == [] and executados == []

    jogo.launch(lambda: relancados.append(1))  # tenta de novo e confirma
    ponte.confirmar()
    assert jogo.comando_a_conferir is False and relancados == [1]


def test_aviso_chega_como_texto(app_qt):
    from cartridges.ponte import Ponte  # noqa: PLC0415

    ponte = Ponte()
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "<b>Alfa</b>"})
    ponte.ligar(jogo)
    jogo.aviso.emit("<b>Alfa</b> iniciado", "")
    assert ponte.fila.texto == "<b>Alfa</b> iniciado"


def test_iniciar_roda_o_executavel_do_jogo(app_qt, monkeypatch):
    lancados = []
    monkeypatch.setattr("cartridges.jogo.run_executable", lambda comando, admin: lancados.append((comando, admin)))
    modelo = ModeloDaBiblioteca()
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "Alfa", "executable": "fake.exe"})
    jogo.save = lambda: None
    jogo.update = lambda: None
    modelo.atualizar(jogo)
    modelo.iniciar("a")
    assert lancados == [("fake.exe", False)]


_QML_QUE_FALHA = r"""
import json, sys
from types import SimpleNamespace
from cartridges import app as modulo_app

chamadas = []
modulo_app.session_fita = SimpleNamespace(abrir=lambda: chamadas.append("abrir"), fechar=lambda: chamadas.append("fechar"))
modulo_app.session_wallpaper = SimpleNamespace(restaurar_orfaos=lambda: None)


class MotorQueNaoCarrega(modulo_app.QQmlApplicationEngine):
    def load(self, _url):  # o QML com erro: nenhuma janela
        pass


modulo_app.QQmlApplicationEngine = MotorQueNaoCarrega
# R2: o `AplicacaoQt` que o `main()` cria, guardado para conferir quem recebe o `saindo`.
from PySide6.QtCore import SIGNAL
from cartridges import shared
from cartridges.utils import session_fita, session_wallpaper
instancias = []


class AppQueGuarda(modulo_app.AplicacaoQt):
    def __init__(self, *argumentos):
        super().__init__(*argumentos)
        instancias.append(self)


modulo_app.AplicacaoQt = AppQueGuarda
# O `saindo` não fala com as fitas nem com a parede (R1): se falasse, ficaria anotado aqui.
session_fita.fechar = lambda: chamadas.append("sessao.fechar")
session_wallpaper.restaurar = lambda: chamadas.append("sessao.restaurar")
codigo = modulo_app.main(sys.argv[:1])
fitas = list(chamadas)
app = instancias[0]
receptores = app.receivers(SIGNAL("saindo()"))
antes = shared.sessao._encerrado
app.saindo.emit()
print(json.dumps({"codigo": codigo, "fitas": fitas, "receptores": receptores, "antes": antes,
                  "depois": shared.sessao._encerrado, "depois_do_saindo": chamadas[len(fitas):]}))
"""


def test_qml_que_nao_carrega_nao_deixa_as_fitas_acesas_e_o_saindo_encerra_a_sessao(tmp_path):
    """Sem janela o `app.exec()` não roda e o `aboutToQuit` (que fecha as fitas) nunca vem: o `_abrir` que não
    carregou devolve as fitas acesas.

    Também: o `saindo` tem um receptor só, o `encerrar()` da sessão, que não espera fita nem parede (elas ficam para o
    `aboutToQuit`).
    """
    ambiente = {
        **os.environ,
        "CARTRIDGES_DADOS": str(tmp_path),
        "CARTRIDGES_REGISTRO": rf"Software\CartridgesTestes\app-{uuid.uuid4()}",
        "QT_QPA_PLATFORM": "offscreen",
    }
    resultado = subprocess.run(
        [sys.executable, "-c", _QML_QUE_FALHA], cwd=RAIZ, env=ambiente, capture_output=True, text=True, timeout=60,
        check=False,
    )  # fmt: skip
    assert resultado.returncode == 0, resultado.stderr
    saida = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert saida["codigo"] == 1
    assert saida["fitas"] == ["abrir", "fechar"]
    assert saida["receptores"] == 1
    assert (saida["antes"], saida["depois"]) == (False, True)
    assert saida["depois_do_saindo"] == []


_CONTEXTO_VIVO = r"""
import gc, json, sys
from types import SimpleNamespace
from cartridges import app as modulo_app

modulo_app.session_fita = SimpleNamespace(abrir=lambda: None, fechar=lambda: None)
modulo_app.session_wallpaper = SimpleNamespace(restaurar_orfaos=lambda: None)


class MotorQueNaoCarrega(modulo_app.QQmlApplicationEngine):
    def load(self, _url):  # sem janela: o `_abrir` devolve 1 logo depois do contexto
        pass


modulo_app.QQmlApplicationEngine = MotorQueNaoCarrega
app = modulo_app.AplicacaoQt(sys.argv[:1])
abertura = modulo_app._Abertura()
codigo = modulo_app._abrir(app, sys.argv[:1], abertura)
gc.collect()
contexto = abertura.motor.rootContext()
nomes = ["filtros", "paginaTodos", "paginaZerados", "aplicativo", "ponte", "controle", "detalhes", "edicao",
         "bigPicture", "sessao", "historico", "saves", "conquistasDoJogo", "preferencias", "painelDasTarefas",
         "restauracao", "atualizador", "novidades", "sobre", "zeradosManuais", "geometria", "cortinaDaAbertura"]
print(json.dumps({"codigo": codigo, "mortos": [n for n in nomes if contexto.contextProperty(n) is None]}))
"""


def test_tudo_o_que_vai_ao_contexto_do_qml_sobrevive_ao_fim_do_abrir(tmp_path):
    """Sem dono Python o objeto morre quando o `_abrir` devolve e a biblioteca abre em branco (grade vazia)."""
    ambiente = {
        **os.environ,
        "CARTRIDGES_DADOS": str(tmp_path),
        "CARTRIDGES_REGISTRO": rf"Software\CartridgesTestes\app-{uuid.uuid4()}",
        "QT_QPA_PLATFORM": "offscreen",
    }
    resultado = subprocess.run(
        [sys.executable, "-c", _CONTEXTO_VIVO], cwd=RAIZ, env=ambiente, capture_output=True, text=True, timeout=60,
        check=False,
    )  # fmt: skip
    assert resultado.returncode == 0, resultado.stderr
    saida = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert saida == {"codigo": 1, "mortos": []}


def test_encerrar_roda_todo_passo_mesmo_com_um_que_falha(caplog):
    """Uma falha num passo do fechamento não pula o drenar das gravações (o tempo da sessão no jogo)."""
    from cartridges.app import _encerrar_em_ordem  # noqa: PLC0415

    feitos = []

    def quebra():
        raise RuntimeError("falhou")

    with caplog.at_level("ERROR"):
        _encerrar_em_ordem(lambda: feitos.append("big_picture"), quebra, lambda: feitos.append("drenar"))

    assert feitos == ["big_picture", "drenar"]
    assert "falhou" in caplog.text
