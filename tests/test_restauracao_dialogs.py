# test_restauracao_dialogs.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As telas da restauração: textos aprovados e o que cada botão faz."""

from cartridges import restauracao_dialogs as telas
from cartridges.utils import restauracao, session_log


def test_pedir_pasta_nao_fecha_sem_escolher(schema):
    schema["shortcuts-location"] = "D:\\Atalhos"
    tela = telas.PedirPasta(lambda: None)
    assert tela.dialogo.get_can_close() is False
    assert tela.texto.get_label() == "A pasta de atalhos D:\\Atalhos não foi encontrada."
    assert tela.botao.get_label() == "Escolher pasta…"


def test_janela_lista_os_pendentes(store, make_game):
    store.add_game(
        make_game(game_id="a", name="Alan Wake", playtime=3600), {}, run_pipeline=False
    )
    restauracao.gravar(["a"], 1)
    janela = telas.JanelaPendentes()
    assert janela.texto.get_label() == "Os atalhos dos jogos abaixo não foram encontrados."
    assert janela.lista.get_row_at_index(0).get_title() == "Alan Wake"
    assert janela.lista.get_row_at_index(1) is None


def test_conflito_textos_e_botoes(make_game):
    restaurado = make_game(
        game_id="gt", name="Gran Turismo 7", playtime=36000, last_played=1_700_000_050
    )
    novo = make_game(game_id="n", name="GT7", playtime=6000, last_played=1_700_000_090)
    session_log.record("gt", 36000, 1_700_000_050)
    session_log.record("n", 6000, 1_700_000_090)
    decisoes = []

    tela = telas.TelaConflito(restaurado, novo, decisoes.append)

    assert tela.texto.get_label() == (
        "Este jogo já possui dados locais. Escolha qual versão deseja manter "
        "ou mescle as duas fontes."
    )
    assert [b.get_label() for b in tela.botoes.values()] == [
        "Manter backup", "Mesclar dados", "Manter este PC"
    ]
    assert tela.dica.get_label() == "Mesclar dados: 11,7 horas em 2 sessões"
    tela.botoes["mesclar"].emit("clicked")
    assert decisoes == ["mesclar"]


def test_escolher_atalho_trava_a_lista_enquanto_importa(store, make_game, win, monkeypatch, tmp_path):
    """Duas importações ao mesmo tempo zerariam as listas uma da outra."""
    eventos = []
    jogo = make_game(game_id="gt", name="Gran Turismo 7")
    monkeypatch.setattr(restauracao, "decidir", lambda *_a: eventos.append("decidir"))
    win.application.on_import_action = lambda **_k: eventos.append("importar")

    tela = telas.EscolherAtalho(jogo, lambda: None, lambda: eventos.append("travar"))
    tela._concluir(tmp_path / "GT7.lnk", None, "backup")

    assert eventos == ["decidir", "travar", "importar"]


def test_janela_destrava_a_lista_ao_atualizar(store, make_game):
    store.add_game(make_game(game_id="a", name="Alan Wake"), {}, run_pipeline=False)
    restauracao.gravar(["a"], 1)
    janela = telas.JanelaPendentes()
    janela.lista.set_sensitive(False)
    janela.atualizar()
    assert janela.lista.get_sensitive() is True


def _avisos(win):
    return [toast.get_title() for toast in win.toast_queue.added]


def test_janela_que_esvazia_avisa_restauracao_concluida(store, make_game, win):
    store.add_game(make_game(game_id="a", name="Alan Wake"), {}, run_pipeline=False)
    restauracao.gravar(["a"], 1)
    janela = telas.JanelaPendentes()

    restauracao.remover("a")
    janela.atualizar()

    assert _avisos(win) == ["Restauração concluída"]


def test_lembrar_mais_tarde_nao_avisa(store, make_game, win):
    store.add_game(make_game(game_id="a", name="Alan Wake"), {}, run_pipeline=False)
    restauracao.gravar(["a"], 1)
    janela = telas.JanelaPendentes()

    janela.depois.emit("clicked")

    assert _avisos(win) == []


def test_importacao_que_resolve_tudo_avisa_sem_abrir_a_janela(store, win, monkeypatch):
    abertas = []
    monkeypatch.setattr(telas.JanelaPendentes, "present", lambda self: abertas.append(self))

    telas.mostrar_pendentes()  # a importação já resolveu tudo: sem arquivo

    assert abertas == []
    assert _avisos(win) == ["Restauração concluída"]


def test_importacao_com_pendencias_abre_a_janela_sem_avisar(store, make_game, win, monkeypatch):
    store.add_game(make_game(game_id="a", name="Alan Wake"), {}, run_pipeline=False)
    restauracao.gravar(["a"], 1)
    abertas = []
    monkeypatch.setattr(telas.JanelaPendentes, "present", lambda self: abertas.append(self))

    telas.mostrar_pendentes()

    assert len(abertas) == 1
    assert _avisos(win) == []
