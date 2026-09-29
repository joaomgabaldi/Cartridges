"""A janela de tarefas e a regra de quando o botão do canto pode aparecer."""

from cartridges.utils import tarefas


def _textos(dialogo):
    """Os rótulos de cada bloco, na ordem: [(nome, contagem), ...]."""
    blocos = []
    filho = dialogo.caixa.get_first_child()
    while filho is not None:
        nome = filho.get_first_child()
        blocos.append((nome.get_label(), nome.get_next_sibling().get_label()))
        filho = filho.get_next_sibling()
    return blocos


def test_janela_mostra_cada_tarefa_e_acompanha(flush_idle):
    from cartridges.tarefas_dialog import TarefasDialog  # noqa: PLC0415

    importacao = tarefas.comecar("Importação", 30)
    tarefas.comecar("HowLongToBeat", 4)
    flush_idle()
    dialogo = TarefasDialog()
    assert _textos(dialogo) == [("Importação", "0 de 30"), ("HowLongToBeat", "0 de 4")]
    assert not dialogo.vazio.get_visible()

    importacao.atualizar(3)
    flush_idle()
    assert _textos(dialogo)[0] == ("Importação", "3 de 30")


def test_janela_vazia_avisa_e_continua_aberta(flush_idle):
    from cartridges.tarefas_dialog import TarefasDialog  # noqa: PLC0415

    tarefa = tarefas.comecar("Metadados", 2)
    flush_idle()
    dialogo = TarefasDialog()
    tarefa.terminar()
    flush_idle()
    assert _textos(dialogo) == []
    assert dialogo.vazio.get_visible()
    assert dialogo.vazio.get_label() == "Nenhuma tarefa em andamento"
