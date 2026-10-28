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


def test_aviso_chega_como_texto(app_qt):
    from cartridges.ponte import Ponte  # noqa: PLC0415

    ponte = Ponte()
    avisos = []
    ponte.avisoRecebido.connect(avisos.append)
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "<b>Alfa</b>"})
    ponte.ligar(jogo)
    jogo.aviso.emit("<b>Alfa</b> iniciado", "")
    assert avisos == ["<b>Alfa</b> iniciado"]


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
