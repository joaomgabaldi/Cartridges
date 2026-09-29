"""O quadro de tarefas: começar, avançar e terminar, de qualquer thread."""

import threading

from cartridges.utils import tarefas


def _em_outra_thread(funcao):
    linha = threading.Thread(target=funcao)
    linha.start()
    linha.join()


def test_tarefa_comecada_em_outra_thread_entra_na_lista(flush_idle):
    _em_outra_thread(lambda: tarefas.comecar("Importação", 30))
    assert tarefas.lista.get_n_items() == 0  # só depois da entrega na tela
    flush_idle()
    tarefa = tarefas.lista.get_item(0)
    assert (tarefa.nome, tarefa.feitos, tarefa.total) == ("Importação", 0, 30)


def test_atualizar_muda_feitos_e_total(flush_idle):
    tarefa = tarefas.comecar("Importação", 3)
    _em_outra_thread(lambda: tarefa.atualizar(2, 5))
    flush_idle()
    assert (tarefa.feitos, tarefa.total) == (2, 5)
    tarefa.atualizar(3)
    flush_idle()
    assert (tarefa.feitos, tarefa.total) == (3, 5)


def test_terminar_tira_da_lista_e_repetir_nao_faz_nada(flush_idle):
    tarefa = tarefas.comecar("HowLongToBeat", 2)
    tarefa.terminar()
    tarefa.terminar()
    flush_idle()
    assert tarefas.lista.get_n_items() == 0


def test_lista_segue_a_ordem_de_inicio(flush_idle):
    primeira = tarefas.comecar("Importação", 1)
    tarefas.comecar("Metadados", 1)
    flush_idle()
    primeira.terminar()
    tarefas.comecar("Tamanho em disco", 1)
    flush_idle()
    nomes = [tarefas.lista.get_item(i).nome for i in range(tarefas.lista.get_n_items())]
    assert nomes == ["Metadados", "Tamanho em disco"]
