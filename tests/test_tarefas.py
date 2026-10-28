"""O quadro de tarefas: começar, avançar e terminar, de qualquer thread."""

import threading
import time
import weakref

import pytest
from PySide6.QtCore import QEventLoop, Qt, QTimer

from cartridges.modelos import tarefas


def _rodar(limite=0.2):
    """Gira o laço de eventos por um instante: o que foi enfileirado chega."""
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()


def _em_outra_thread(funcao):
    linha = threading.Thread(target=funcao)
    linha.start()
    linha.join()


def _linha(i):
    modelo = tarefas.lista
    indice = modelo.index(i)
    return tuple(modelo.data(indice, papel) for papel in (modelo.NOME, modelo.FEITOS, modelo.TOTAL))


@pytest.fixture(autouse=True)
def lista_vazia(app_qt):  # noqa: ARG001
    yield
    _rodar(0.05)
    for tarefa in list(tarefas.lista._tarefas):  # noqa: SLF001
        tarefas.lista.remover(tarefa)


def test_tarefa_comecada_em_outra_thread_entra_na_lista():
    _em_outra_thread(lambda: tarefas.comecar("Importação", 30))
    assert tarefas.lista.rowCount() == 0  # só depois da entrega na principal
    _rodar()
    assert _linha(0) == ("Importação", 0, 30)


def test_papeis_do_modelo():
    nomes = {bytes(n).decode() for n in tarefas.lista.roleNames().values()}
    assert nomes == {"nome", "feitos", "total"}


def test_atualizar_muda_feitos_e_total():
    tarefa = tarefas.comecar("Importação", 3)
    _em_outra_thread(lambda: tarefa.atualizar(2, 5))
    _rodar()
    assert (tarefa.feitos, tarefa.total) == (2, 5)
    assert _linha(0) == ("Importação", 2, 5)
    tarefa.atualizar(3)
    _rodar()
    assert (tarefa.feitos, tarefa.total) == (3, 5)


def test_terminar_tira_da_lista_e_repetir_nao_faz_nada():
    tarefa = tarefas.comecar("HowLongToBeat", 2)
    tarefa.terminar()
    tarefa.terminar()
    _rodar()
    assert tarefas.lista.rowCount() == 0


def test_lista_segue_a_ordem_de_inicio():
    primeira = tarefas.comecar("Importação", 1)
    tarefas.comecar("Metadados", 1)
    _rodar()
    primeira.terminar()
    tarefas.comecar("Tamanho em disco", 1)
    _rodar()
    assert [_linha(i)[0] for i in range(tarefas.lista.rowCount())] == ["Metadados", "Tamanho em disco"]


def test_tarefa_atualizada_de_thread_chega_em_ordem():
    vistos = []

    def trabalho():
        tarefa = tarefas.comecar("Importação", 50)
        fraca = weakref.ref(tarefa)
        tarefa.mudou.connect(lambda: vistos.append(fraca().feitos), Qt.ConnectionType.DirectConnection)
        for feitos in range(1, 51):
            tarefa.atualizar(feitos)
        tarefa.terminar()  # logo depois do último: nunca chega antes dele

    _em_outra_thread(trabalho)
    _rodar(0.3)
    assert vistos == list(range(1, 51))
    assert tarefas.lista.rowCount() == 0
