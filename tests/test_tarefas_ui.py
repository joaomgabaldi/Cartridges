"""A janela de tarefas e a regra de quando o botão do canto pode aparecer."""

from types import SimpleNamespace

import pytest

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
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    importacao = tarefas.comecar("Importação", 30)
    tarefas.comecar("HowLongToBeat", 4)
    flush_idle()
    dialogo = TarefasJanela()
    assert _textos(dialogo) == [("Importação", "0 de 30"), ("HowLongToBeat", "0 de 4")]
    assert not dialogo.vazio.get_visible()

    importacao.atualizar(3)
    flush_idle()
    assert _textos(dialogo)[0] == ("Importação", "3 de 30")
    dialogo.emit("close-request")


def test_janela_vazia_avisa(flush_idle):
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    tarefa = tarefas.comecar("Metadados", 2)
    flush_idle()
    dialogo = TarefasJanela()
    tarefa.terminar()
    flush_idle()
    assert _textos(dialogo) == []
    assert dialogo.vazio.get_visible()
    assert dialogo.vazio.get_label() == "Nenhuma tarefa em andamento"
    dialogo.emit("close-request")


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
    botao.revealer.set_reveal_child(False)  # os 10 s da entrada já passaram

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
    botao.revealer.set_reveal_child(False)  # os 10 s da entrada já passaram
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


def test_so_a_faixa_junto_a_borda_chama_e_o_botao_a_vista_segura(
    real_window, flush_idle, monkeypatch
):
    botao = real_window.botao_tarefas
    monkeypatch.setattr(real_window.session_overlay, "get_height", lambda: 600)
    tarefas.comecar("Importação", 1)
    flush_idle()
    botao.revealer.set_reveal_child(False)

    botao._ao_mover(None, 30, 590)  # pylint: disable=protected-access
    assert not botao.revealer.get_reveal_child()  # fora da faixa de 16 px

    botao._ao_mover(None, 10, 590)  # pylint: disable=protected-access
    assert botao.revealer.get_reveal_child()

    # Da faixa até o botão, para clicar: o botão à vista segura a área.
    botao._ao_mover(None, 30, 575)  # pylint: disable=protected-access
    assert not botao._recolher_id  # pylint: disable=protected-access


def test_tempos_de_entrada_e_de_saida():
    from cartridges import botao_tarefas  # noqa: PLC0415

    assert botao_tarefas._ENTRADA_MS == 10000  # pylint: disable=protected-access
    assert botao_tarefas._SAIDA_MS == 5000  # pylint: disable=protected-access


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


def test_mouse_ainda_no_canto_depois_de_fechar_a_janela_traz_o_botao(
    real_window, flush_idle, monkeypatch
):
    botao = real_window.botao_tarefas
    monkeypatch.setattr(real_window.session_overlay, "get_height", lambda: 600)
    tarefas.comecar("Importação", 1)
    flush_idle()
    botao._ao_mover(None, 10, 590)  # pylint: disable=protected-access
    botao._esconder()  # pylint: disable=protected-access  # o que _abrir faz
    assert not botao.revealer.get_reveal_child()

    botao._ao_mover(None, 12, 588)  # pylint: disable=protected-access
    assert botao.revealer.get_reveal_child()


def test_movimento_sem_tarefas_nao_faz_nada_e_a_tarefa_nova_funciona(
    real_window, flush_idle, monkeypatch
):
    botao = real_window.botao_tarefas
    monkeypatch.setattr(real_window.session_overlay, "get_height", lambda: 600)
    botao._ao_mover(None, 10, 590)  # pylint: disable=protected-access
    assert not botao.revealer.get_reveal_child()

    tarefas.comecar("Importação", 1)
    flush_idle()
    botao.revealer.set_reveal_child(False)
    botao._ao_mover(None, 10, 590)  # pylint: disable=protected-access
    assert botao.revealer.get_reveal_child()


def test_tarefa_que_comeca_com_o_mouse_parado_no_canto_nao_recua(
    real_window, flush_idle, monkeypatch
):
    botao = real_window.botao_tarefas
    monkeypatch.setattr(real_window.session_overlay, "get_height", lambda: 600)
    botao._ao_mover(None, 10, 590)  # pylint: disable=protected-access

    tarefas.comecar("Importação", 1)
    flush_idle()
    botao._recolher()  # pylint: disable=protected-access  # os 10 s da entrada
    assert botao.revealer.get_reveal_child()


# -- a janela solta ------------------------------------------------------------


@pytest.fixture
def sem_tela(monkeypatch):
    """`present` só conta: a janela não chega a ir para a tela nos testes."""
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(TarefasJanela, "present", lambda self: chamadas.append(self))
    monkeypatch.setattr(TarefasJanela, "aberta", None)
    return chamadas


def test_mostrar_duas_vezes_e_a_mesma_janela(real_window, flush_idle, sem_tela):
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    TarefasJanela.mostrar(real_window)
    primeira = TarefasJanela.aberta
    TarefasJanela.mostrar(real_window)
    assert TarefasJanela.aberta is primeira
    assert sem_tela == [primeira, primeira]
    assert primeira.get_opacity() == 0  # nasce invisível, até ir para o lugar

    assert not primeira.emit("close-request")  # deixa fechar
    assert TarefasJanela.aberta is None


def test_janela_solta_nao_e_transiente_nem_modal_nem_redimensionavel():
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    janela = TarefasJanela()
    assert janela.get_transient_for() is None
    assert not janela.get_modal()
    assert not janela.get_resizable()
    assert janela.cabecalho.get_decoration_layout() == ":minimize,close"
    janela.emit("close-request")


def test_esc_fecha_a_janela():
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    janela = TarefasJanela()
    controladores = janela.observe_controllers()
    atalhos = [
        controladores.get_item(i)
        for i in range(controladores.get_n_items())
        if isinstance(controladores.get_item(i), Gtk.ShortcutController)
    ]
    gatilhos = [
        (atalho.get_trigger().to_string(), atalho.get_action().get_action_name())
        for controlador in atalhos
        for atalho in controlador
        if isinstance(atalho.get_action(), Gtk.NamedAction)
    ]
    assert ("Escape", "window.close") in gatilhos
    janela.emit("close-request")


def _principal(visivel, sair):
    return SimpleNamespace(
        get_visible=lambda: visivel, get_application=lambda: SimpleNamespace(quit=sair)
    )


def test_fechar_a_janela_com_a_principal_escondida_encerra_o_app(monkeypatch):
    from cartridges import shared  # noqa: PLC0415
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    saidas = []
    monkeypatch.setattr(shared, "win", _principal(False, lambda: saidas.append(1)))
    janela = TarefasJanela()
    assert not janela.emit("close-request")
    assert saidas == [1]


def test_fechar_a_janela_com_a_principal_visivel_so_a_fecha(monkeypatch):
    from cartridges import shared  # noqa: PLC0415
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    saidas = []
    monkeypatch.setattr(shared, "win", _principal(True, lambda: saidas.append(1)))
    janela = TarefasJanela()
    assert not janela.emit("close-request")
    assert saidas == []


class _JanelaFalsa:
    def __init__(self):
        self.fechada = False

    def close(self):
        self.fechada = True


def _fechar_principal(monkeypatch, com_janela):
    from cartridges.main import CartridgesApplication  # noqa: PLC0415
    from cartridges.tarefas_janela import TarefasJanela  # noqa: PLC0415

    janela = _JanelaFalsa() if com_janela else None
    monkeypatch.setattr(TarefasJanela, "aberta", janela)
    escondidas = []
    principal = SimpleNamespace(set_visible=escondidas.append)
    devolvido = CartridgesApplication.on_win_close_request(None, principal)
    return devolvido, escondidas, janela


def test_fechar_a_principal_com_tarefa_e_janela_so_esconde(monkeypatch, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    devolvido, escondidas, janela = _fechar_principal(monkeypatch, True)
    assert devolvido is True
    assert escondidas == [False]
    assert not janela.fechada


def test_fechar_a_principal_sem_tarefa_fecha_tambem_a_janela(monkeypatch):
    devolvido, escondidas, janela = _fechar_principal(monkeypatch, True)
    assert devolvido is False
    assert escondidas == []
    assert janela.fechada


def test_fechar_a_principal_com_tarefa_sem_janela_fecha_tudo(monkeypatch, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    devolvido, escondidas, _ = _fechar_principal(monkeypatch, False)
    assert devolvido is False
    assert escondidas == []


def test_posicao_acima_do_botao_com_os_numeros_do_prototipo():
    from cartridges.utils import window_geometry  # noqa: PLC0415

    x, y = window_geometry.posicao_acima_do_botao(
        app_rect=(234, 156, 1404, 951),
        app_sombra=(25, 25),
        nova_sombra=(25, 25),
        app_altura=745,
        nova_altura=200,
        escala=1,
    )
    # esquerda visível do app: 234 + 25 = 259; x = 259 + 12 - 25
    assert x == 246
    # base visível do app: 156 + 25 + 745 = 926; alvo = 926 - (12 + 34 + 12) = 868
    # y = 868 - 200 (altura da nova) - 25 (sombra de cima da nova)
    assert y == 643


def test_posicao_acima_do_botao_respeita_a_escala():
    from cartridges.utils import window_geometry  # noqa: PLC0415

    x, y = window_geometry.posicao_acima_do_botao(
        app_rect=(100, 100, 0, 0),
        app_sombra=(10, 10),
        nova_sombra=(10, 10),
        app_altura=500,
        nova_altura=200,
        escala=2,
    )
    # 100 + 10*2 = 120 (esquerda visível); x = 120 + 12*2 - 10*2 = 124
    assert x == 124
    # base visível = 100 + (10 + 500)*2 = 1120; alvo = 1120 - 58*2 = 1004
    # y = 1004 - 200*2 - 10*2 = 584
    assert y == 584


def test_segunda_copia_do_app_acorda_a_primeira(monkeypatch):
    """A janela principal escondida só a primeira cópia sabe mostrar."""
    import threading  # noqa: PLC0415

    from cartridges.utils import single_instance  # noqa: PLC0415

    # Nome próprio: um app de verdade aberto na máquina vigia o evento real.
    monkeypatch.setattr(single_instance, "_EVENT_NAME", "Local\\Cartridges.Teste.Acordar")
    acordou = threading.Event()
    single_instance.watch_second_launch(acordou.set)
    assert not acordou.wait(0.2)

    single_instance._wake_running_instance()  # pylint: disable=protected-access
    assert acordou.wait(2)


def test_segunda_abertura_mostra_a_principal_escondida(monkeypatch):
    from cartridges import shared  # noqa: PLC0415
    from cartridges.main import CartridgesApplication  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(shared, "win", SimpleNamespace(present=lambda: chamadas.append(1)))
    assert CartridgesApplication.on_second_launch(None) is False  # idle de uma vez só
    assert chamadas == [1]
