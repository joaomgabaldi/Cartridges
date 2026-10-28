# test_modelo_biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O modelo da grade da biblioteca e o manager que o alimenta."""

import threading
import time

from PySide6.QtCore import QEventLoop, QTimer

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.store.managers.exibicao_manager import ExibicaoManager
from cartridges.utils import thread_principal
from cartridges.utils.thread_principal import eh_thread_principal


def _jogo(game_id, nome, **extra):
    return Jogo({"game_id": game_id, "source": "imported", "name": nome, **extra})


def _nomes(modelo):
    return [modelo.data(modelo.index(i), ModeloDaBiblioteca.Papel.Nome) for i in range(modelo.rowCount())]


def _rodar_ate(condicao, limite=5.0):
    fim = time.monotonic() + limite
    while not condicao() and time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
    return condicao()


def test_entram_so_os_visiveis(app_qt):
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    modelo.atualizar(_jogo("b", "B", removed=True))
    modelo.atualizar(_jogo("c", "C", blacklisted=True))
    assert _nomes(modelo) == ["A"]


def test_ordem_por_nome_sem_caixa(app_qt):
    modelo = ModeloDaBiblioteca()
    for i, nome in enumerate(["zelda", "Banjo", "alpha", "Celeste"]):
        modelo.atualizar(_jogo(str(i), nome))
    assert _nomes(modelo) == ["alpha", "Banjo", "Celeste", "zelda"]


def test_atualizar_muda_o_papel_nome(app_qt):
    modelo = ModeloDaBiblioteca()
    jogo = _jogo("a", "Alfa")
    modelo.atualizar(jogo)
    mudancas = []
    modelo.dataChanged.connect(lambda de, ate, papeis: mudancas.append((de.row(), tuple(papeis))))
    jogo.name = "Alfa 2"
    modelo.atualizar(jogo)
    assert _nomes(modelo) == ["Alfa 2"]
    assert mudancas and mudancas[0][0] == 0


def test_renomear_reordena(app_qt):
    modelo = ModeloDaBiblioteca()
    a, b = _jogo("a", "A"), _jogo("b", "B")
    modelo.atualizar(a)
    modelo.atualizar(b)
    a.name = "Z"
    modelo.atualizar(a)
    assert _nomes(modelo) == ["B", "Z"]


def test_jogo_removido_sai_do_modelo(app_qt):
    modelo = ModeloDaBiblioteca()
    jogo = _jogo("a", "A")
    modelo.atualizar(jogo)
    jogo.removed = True
    modelo.atualizar(jogo)
    assert modelo.rowCount() == 0


def test_capa_vazia_sem_arquivo(app_qt):
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    assert modelo.data(modelo.index(0), ModeloDaBiblioteca.Papel.Capa) == ""


def test_capa_e_url_de_arquivo(app_qt):
    (shared.covers_dir / "a.tiff").write_bytes(b"x")
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    assert modelo.data(modelo.index(0), ModeloDaBiblioteca.Papel.Capa).startswith("file:///")


def test_iniciar_lanca_o_jogo(app_qt, monkeypatch):
    modelo = ModeloDaBiblioteca()
    jogo = _jogo("a", "A")
    lancados = []
    monkeypatch.setattr(jogo, "launch", lambda *a: lancados.append(jogo) or True)
    modelo.atualizar(jogo)
    modelo.iniciar("a")
    modelo.iniciar("inexistente")
    assert lancados == [jogo]


def test_atualizacao_vinda_de_thread_chega_na_principal(app_qt, store):
    thread_principal.na_thread_principal(lambda: None)  # garante a ponte
    modelo = ModeloDaBiblioteca()
    vistos = []
    original = modelo.atualizar
    modelo.atualizar = lambda jogo: (vistos.append(eh_thread_principal()), original(jogo))
    store.add_manager(ExibicaoManager(modelo))
    jogo = _jogo("a", "Alfa")
    store.add_game(jogo, {}, run_pipeline=False)
    jogo.name = "Beta"
    thread = threading.Thread(target=jogo.save)
    thread.start()
    thread.join()
    assert vistos == []
    assert _rodar_ate(lambda: vistos)
    assert vistos == [True]
    assert _nomes(modelo) == ["Beta"]


def test_grade_carrega_no_qml(app_qt):
    from pathlib import Path  # noqa: PLC0415

    from PySide6.QtCore import QUrl  # noqa: PLC0415
    from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: PLC0415

    qml = Path(shared.__file__).parent / "qml"
    motor = QQmlEngine()
    motor.addImportPath(str(qml.parent))
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    componente = QQmlComponent(motor, QUrl.fromLocalFile(str(qml / "Grade.qml")))
    objeto = componente.createWithInitialProperties({"biblioteca": modelo})
    assert objeto is not None, componente.errorString()
