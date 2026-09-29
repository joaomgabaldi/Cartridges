"""A janela de tarefas e a regra de quando o botão do canto pode aparecer."""

from types import SimpleNamespace

from gi.repository import Gtk

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
    dialogo.emit("closed")


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
    dialogo.emit("closed")


def _janela(pagina="biblioteca", dialogo=None, sessao=None):
    biblioteca, zerados, detalhes = object(), object(), object()
    paginas = {"biblioteca": biblioteca, "zerados": zerados, "detalhes": detalhes}
    return SimpleNamespace(
        library_page=biblioteca,
        zerados_library_page=zerados,
        navigation_view=SimpleNamespace(get_visible_page=lambda: paginas[pagina]),
        get_visible_dialog=lambda: dialogo,
        session_game=sessao,
    )


def test_sem_tarefa_o_botao_nunca_aparece():
    from cartridges.botao_tarefas import pode_mostrar  # noqa: PLC0415

    assert not pode_mostrar(_janela())


def test_com_tarefa_aparece_so_nas_duas_bibliotecas_livres(flush_idle):
    from cartridges.botao_tarefas import pode_mostrar  # noqa: PLC0415

    tarefas.comecar("Importação", 1)
    flush_idle()
    assert pode_mostrar(_janela("biblioteca"))
    assert pode_mostrar(_janela("zerados"))
    assert not pode_mostrar(_janela("detalhes"))
    assert not pode_mostrar(_janela(dialogo=object()))
    assert not pode_mostrar(_janela(sessao=object()))


def test_tarefa_nova_faz_o_botao_entrar_e_o_fim_recolhe(real_window, flush_idle):
    botao = real_window.botao_tarefas
    assert not botao.revealer.get_reveal_child()
    assert not botao.get_can_target()

    tarefa = tarefas.comecar("Importação", 1)
    flush_idle()
    assert botao.revealer.get_reveal_child()
    assert botao.get_can_target()

    tarefa.terminar()
    flush_idle()
    assert not botao.revealer.get_reveal_child()
    assert not botao.get_can_target()


def test_mouse_no_canto_traz_o_botao_de_volta(real_window, flush_idle):
    botao = real_window.botao_tarefas
    tarefas.comecar("Importação", 1)
    flush_idle()
    botao.revealer.set_reveal_child(False)  # os 3 s da entrada já passaram

    botao._ao_entrar()  # pylint: disable=protected-access
    assert botao.revealer.get_reveal_child()


def test_sessao_esconde_o_botao(real_window, flush_idle, make_game):
    botao = real_window.botao_tarefas
    tarefas.comecar("Importação", 1)
    flush_idle()
    real_window.session_game = make_game(game_id="x")
    botao.reavaliar()
    assert not botao.revealer.get_reveal_child()
    assert not botao.get_can_target()
    botao._ao_entrar()  # pylint: disable=protected-access
    assert not botao.revealer.get_reveal_child()


def test_girar_para_quando_a_tarefa_acaba(real_window, flush_idle):
    botao = real_window.botao_tarefas
    tarefa = tarefas.comecar("Importação", 1)
    flush_idle()
    assert botao.botao.has_css_class("girando")

    tarefa.terminar()
    flush_idle()
    assert not botao.botao.has_css_class("girando")


def test_canto_escondido_nao_recebe_entrada(real_window, flush_idle):
    botao = real_window.botao_tarefas
    tarefas.comecar("Importação", 1)
    flush_idle()
    botao.revealer.set_reveal_child(False)  # os 3 s da entrada já passaram
    assert not botao.get_can_target()


def test_movimento_no_canto_mostra_e_fora_agenda_o_recuo(
    real_window, flush_idle, monkeypatch
):
    botao = real_window.botao_tarefas
    monkeypatch.setattr(real_window.session_overlay, "get_height", lambda: 600)
    tarefas.comecar("Importação", 1)
    flush_idle()
    botao.revealer.set_reveal_child(False)

    botao._ao_mover(None, 500, 100)  # pylint: disable=protected-access
    assert not botao.revealer.get_reveal_child()

    botao._ao_mover(None, 10, 590)  # pylint: disable=protected-access
    assert botao.revealer.get_reveal_child()
    assert botao.get_can_target()
    botao._recolher()  # pylint: disable=protected-access
    assert botao.revealer.get_reveal_child()  # com o mouse em cima, fica

    botao._ao_mover(None, 200, 590)  # pylint: disable=protected-access
    assert botao._recolher_id  # pylint: disable=protected-access
    botao._recolher()  # pylint: disable=protected-access
    assert not botao.revealer.get_reveal_child()


def test_sair_da_janela_agenda_o_recuo(real_window, flush_idle, monkeypatch):
    botao = real_window.botao_tarefas
    monkeypatch.setattr(real_window.session_overlay, "get_height", lambda: 600)
    tarefas.comecar("Importação", 1)
    flush_idle()
    botao._ao_mover(None, 10, 590)  # pylint: disable=protected-access
    botao._ao_deixar(None)  # pylint: disable=protected-access
    assert botao._recolher_id  # pylint: disable=protected-access


def test_sessao_esconde_o_botao_sem_deslizar(real_window, flush_idle, make_game):
    botao = real_window.botao_tarefas
    tarefas.comecar("Importação", 1)
    flush_idle()
    transicoes = []
    botao.revealer.connect(
        "notify::reveal-child", lambda r, _p: transicoes.append(r.get_transition_type())
    )

    real_window.session_game = make_game(game_id="x")
    botao.reavaliar()
    assert transicoes == [Gtk.RevealerTransitionType.NONE]
    assert (
        botao.revealer.get_transition_type() == Gtk.RevealerTransitionType.SLIDE_RIGHT
    )
