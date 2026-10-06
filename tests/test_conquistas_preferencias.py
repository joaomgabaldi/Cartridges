"""A página Conquistas das Preferências."""

import pytest

from cartridges import shared
from cartridges.conquistas import fontes
from cartridges.conquistas.epic import conta as epic_conta
from cartridges.conquistas.epic import janela as epic_janela
from cartridges.conquistas.xbox import conta, login


def _preferencias(monkeypatch):
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    return preferences_module.CartridgesPreferences()


def test_chave_digitada_vai_para_o_schema(monkeypatch, schema):
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_chave_row.set_text("  abc123  ")
    assert schema.get_string("conquistas-chave-steam") == "abc123"


def test_descricao_do_grupo_da_chave(monkeypatch):
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_chave_group.get_description() == (
        "Informe a chave da Steam Web API. "
        '<a href="https://steamcommunity.com/dev/apikey">Obtenha aqui</a>.'
    )


def test_chave_guardada_aparece_na_linha(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "xyz")
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_chave_row.get_text() == "xyz"


def test_posicao_escolhida_vai_para_o_schema(monkeypatch, schema):
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_posicao_row.set_selected(0)
    assert schema.get_string("conquistas-aviso-posicao") == "superior-esquerdo"
    preferencias.conquistas_posicao_row.set_selected(3)
    assert schema.get_string("conquistas-aviso-posicao") == "inferior-direito"


def test_posicao_guardada_aparece_na_linha(monkeypatch, schema):
    schema.set_string("conquistas-aviso-posicao", "superior-direito")
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_posicao_row.get_selected() == 1


def test_posicao_estranha_no_schema_cai_no_padrao(monkeypatch, schema):
    schema.set_string("conquistas-aviso-posicao", "meio")
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_posicao_row.get_selected() == 3


def test_posicao_sem_selecao_nao_levanta_nem_grava(monkeypatch, schema):
    """O ComboRow ignora ``set_selected(INVALID_LIST_POSITION)``; o handler é chamado
    direto, com uma linha cujo ``get_selected`` devolve a posição inválida."""
    from gi.repository import Gtk  # noqa: PLC0415

    class LinhaSemSelecao:
        def get_selected(self):
            return Gtk.INVALID_LIST_POSITION

    schema.set_string("conquistas-aviso-posicao", "superior-direito")
    preferencias = _preferencias(monkeypatch)
    preferencias._gravar_posicao_do_aviso(LinhaSemSelecao(), None)
    assert schema.get_string("conquistas-aviso-posicao") == "superior-direito"


def test_botao_de_exemplo_mostra_um_aviso(monkeypatch):
    from cartridges import conquista_aviso  # noqa: PLC0415

    mostrados = []
    monkeypatch.setattr(conquista_aviso, "mostrar", mostrados.append)
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_exemplo_row.emit("activated")
    assert len(mostrados) == 1 and mostrados[0] == conquista_aviso.Aviso.exemplo()


def test_botao_de_exemplo_fecha_o_anterior_antes_de_mostrar(monkeypatch):
    from cartridges import conquista_aviso  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(conquista_aviso, "fechar", lambda: chamadas.append("fechar"))
    monkeypatch.setattr(conquista_aviso, "mostrar", lambda _a: chamadas.append("mostrar"))
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_exemplo_row.emit("activated")
    assert chamadas == ["fechar", "mostrar"]


def test_cliques_repetidos_no_exemplo_nao_enfileiram(monkeypatch):
    from cartridges import conquista_aviso  # noqa: PLC0415

    # Sem janela de verdade: só a fila importa.
    monkeypatch.setattr(conquista_aviso, "_proximo", lambda: False)
    preferencias = _preferencias(monkeypatch)
    try:
        for _clique in range(3):
            preferencias.conquistas_exemplo_row.emit("activated")
        assert len(conquista_aviso._fila) == 1
    finally:
        conquista_aviso.fechar()


def test_posicao_so_responde_com_o_aviso_ligado(monkeypatch):
    # O FakeSchema não implementa ``bind``: o interruptor é quem manda aqui.
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_aviso_switch.set_active(True)
    assert preferencias.conquistas_posicao_row.get_sensitive() is True
    preferencias.conquistas_aviso_switch.set_active(False)
    assert preferencias.conquistas_posicao_row.get_sensitive() is False


def test_textos_do_grupo_durante_o_jogo(monkeypatch):
    from gi.repository import Adw  # noqa: PLC0415

    preferencias = _preferencias(monkeypatch)
    aviso = preferencias.conquistas_aviso_switch
    assert aviso.get_title() == "Mostrar aviso durante o jogo"
    assert aviso.get_subtitle() == (
        "Exibe um aviso por cima do jogo ao desbloquear uma conquista. "
        "Nos jogos da Steam, aparece o aviso da própria Steam."
    )
    iluminacao = preferencias.conquistas_iluminacao_switch
    assert iluminacao.get_title() == "Piscar a iluminação inteligente"
    assert iluminacao.get_subtitle() == (
        "Os dispositivos piscam ao desbloquear uma conquista"
    )
    grupo = aviso.get_ancestor(Adw.PreferencesGroup)
    assert grupo.get_title() == "Durante o jogo"
    assert not grupo.get_description()


# A conta Microsoft


class _AppFalso:
    def __init__(self, varredura) -> None:
        self.varredura_conquistas = varredura


class _JanelaFalsa:
    def __init__(self, app) -> None:
        self._app = app

    def get_application(self):
        return self._app


def _varredura_falsa(monkeypatch, varridos, pedidos=None):
    class Varredura:
        def varrer_jogos(self, games, filtro=None):
            # O filtro é de quem varre (na thread dela): a falsa aplica aqui o que a
            # varredura de verdade aplicaria lá, a menos que o teste só queira ver o pedido.
            if pedidos is not None:
                pedidos.append((list(games), filtro))
                return
            varridos.extend(game for game in games if filtro is None or filtro(game))

    monkeypatch.setattr(shared, "win", _JanelaFalsa(_AppFalso(Varredura())))


def test_conta_desconectada(monkeypatch):
    monkeypatch.setattr(conta, "conectada", lambda: False)
    dialogo = _preferencias(monkeypatch)
    assert dialogo.conquistas_conta_row.get_subtitle() == "Não conectada"
    assert dialogo.conquistas_conta_botao.get_label() == "Entrar"


def test_conta_conectada_mostra_o_gamertag(monkeypatch):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    dialogo = _preferencias(monkeypatch)
    assert dialogo.conquistas_conta_row.get_subtitle() == "Jogador"
    assert dialogo.conquistas_conta_botao.get_label() == "Sair"


def test_conta_conectada_sem_gamertag_mostra_o_nome_da_conta(monkeypatch):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: None)
    dialogo = _preferencias(monkeypatch)
    assert dialogo.conquistas_conta_row.get_subtitle() == "Conta Microsoft"


def test_entrar_espera_e_cancelar(monkeypatch):
    monkeypatch.setattr(conta, "conectada", lambda: False)
    pedidos = []

    class Pedido:
        def cancelar(self):
            pedidos.append("cancelado")

    monkeypatch.setattr(
        login, "entrar", lambda ao_terminar, **_k: pedidos.append(ao_terminar) or Pedido()
    )
    dialogo = _preferencias(monkeypatch)
    dialogo.conquistas_conta_botao.emit("clicked")
    assert dialogo.conquistas_conta_row.get_subtitle() == "Aguardando o login no navegador…"
    assert dialogo.conquistas_conta_botao.get_label() == "Cancelar"
    dialogo.conquistas_conta_botao.emit("clicked")
    assert pedidos[-1] == "cancelado"


def test_entrar_que_levanta_vira_aviso_e_nao_escapa(monkeypatch):
    """Socket bloqueado, limite de handles, falha de bind: o clique não levanta,
    a linha volta ao estado certo e o usuário vê o aviso."""
    monkeypatch.setattr(conta, "conectada", lambda: False)

    def entrar(_ao_terminar, **_k):
        raise OSError("bloqueado")

    monkeypatch.setattr(login, "entrar", entrar)
    dialogo = _preferencias(monkeypatch)
    avisos = []
    monkeypatch.setattr(dialogo, "add_toast", lambda toast: avisos.append(toast.get_title()))
    dialogo.conquistas_conta_botao.emit("clicked")
    assert avisos == ["Não foi possível entrar na conta Microsoft."]
    assert dialogo.conquistas_conta_row.get_subtitle() == "Não conectada"
    assert dialogo.conquistas_conta_botao.get_label() == "Entrar"


@pytest.mark.parametrize(
    "nome, aviso",
    [
        ("SEM_PERFIL_XBOX", "Esta conta Microsoft não tem um perfil Xbox."),
        (
            "CONTA_INFANTIL",
            "Esta conta precisa de permissão de um responsável para usar o Xbox.",
        ),
        ("FALHOU", "Não foi possível entrar na conta Microsoft."),
        ("CANCELADO", None),
    ],
)
def test_resultado_do_login(monkeypatch, nome, aviso):
    monkeypatch.setattr(conta, "conectada", lambda: False)
    dialogo = _preferencias(monkeypatch)
    avisos = []
    monkeypatch.setattr(dialogo, "add_toast", lambda toast: avisos.append(toast.get_title()))
    dialogo._ao_entrar(login.Resultado[nome])
    assert avisos == ([aviso] if aviso else [])
    assert dialogo.conquistas_conta_botao.get_label() == "Entrar"


def test_login_ok_varre_os_jogos_do_xbox(monkeypatch, store, make_game):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    xbox = make_game(
        game_id="shortcuts_1", executable='start "" "shell:AppsFolder\\P_a!G"'
    )
    outro = make_game(game_id="shortcuts_2")
    for g in (xbox, outro):
        store.add_game(g, {}, run_pipeline=False)
    varridos = []
    _varredura_falsa(monkeypatch, varridos)
    dialogo = _preferencias(monkeypatch)
    dialogo._ao_entrar(login.Resultado.OK)
    assert varridos == [xbox]
    assert dialogo.conquistas_conta_row.get_subtitle() == "Jogador"


def test_login_ok_nao_olha_o_disco_dos_jogos_na_thread_principal(
    monkeypatch, store, make_game
):
    """A foto da store sai na thread principal; o filtro (que lê o disco do jogo)
    vai para a thread da varredura, que o aplica lá."""
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    xbox = make_game(
        game_id="shortcuts_1", executable='start "" "shell:AppsFolder\\P_a!G"'
    )
    outro = make_game(game_id="shortcuts_2")
    for g in (xbox, outro):
        store.add_game(g, {}, run_pipeline=False)
    consultados = []
    monkeypatch.setattr(
        fontes, "eh_do_xbox", lambda game: consultados.append(game) or game is xbox
    )
    pedidos = []
    _varredura_falsa(monkeypatch, [], pedidos)
    dialogo = _preferencias(monkeypatch)
    dialogo._ao_entrar(login.Resultado.OK)
    ((jogos, filtro),) = pedidos
    assert set(jogos) == {xbox, outro}
    assert consultados == []
    assert filtro(xbox) is True and filtro(outro) is False


def test_cancelar_na_troca_com_a_conta_conectada_conta_como_ok(
    monkeypatch, store, make_game
):
    """Cancelar durante a troca pode deixar a conta conectada: o resultado chega
    como CANCELADO, mas o que vale é o estado da conta."""
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    xbox = make_game(
        game_id="shortcuts_1", executable='start "" "shell:AppsFolder\\P_a!G"'
    )
    store.add_game(xbox, {}, run_pipeline=False)
    varridos = []
    _varredura_falsa(monkeypatch, varridos)
    dialogo = _preferencias(monkeypatch)
    avisos = []
    monkeypatch.setattr(dialogo, "add_toast", lambda toast: avisos.append(toast))
    dialogo._ao_entrar(login.Resultado.CANCELADO)
    assert varridos == [xbox]
    assert avisos == []
    assert dialogo.conquistas_conta_botao.get_label() == "Sair"


def test_falha_com_a_conta_conectada_nao_varre(monkeypatch, store, make_game):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    varridos = []
    _varredura_falsa(monkeypatch, varridos)
    dialogo = _preferencias(monkeypatch)
    monkeypatch.setattr(dialogo, "add_toast", lambda toast: None)
    dialogo._ao_entrar(login.Resultado.FALHOU)
    assert varridos == []
    assert dialogo.conquistas_conta_botao.get_label() == "Sair"


def test_varredura_do_xbox_que_falha_nao_levanta(monkeypatch, store, make_game):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")

    class Varredura:
        def varrer_jogos(self, games, filtro=None):
            raise RuntimeError("falhou")

    monkeypatch.setattr(shared, "win", _JanelaFalsa(_AppFalso(Varredura())))
    xbox = make_game(
        game_id="shortcuts_1", executable='start "" "shell:AppsFolder\\P_a!G"'
    )
    store.add_game(xbox, {}, run_pipeline=False)
    dialogo = _preferencias(monkeypatch)
    dialogo._ao_entrar(login.Resultado.OK)


def test_sair(monkeypatch):
    estado = {"conectada": True}
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    monkeypatch.setattr(conta, "sair", lambda: estado.update(conectada=False))
    dialogo = _preferencias(monkeypatch)
    dialogo.conquistas_conta_botao.emit("clicked")
    assert dialogo.conquistas_conta_row.get_subtitle() == "Não conectada"
    assert dialogo.conquistas_conta_botao.get_label() == "Entrar"


def test_conta_que_muda_atualiza_a_linha(monkeypatch):
    estado = {"conectada": False}
    ouvintes = []
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    monkeypatch.setattr(
        conta, "ao_mudar", lambda ouvinte: ouvintes.append(ouvinte) or (lambda: None)
    )
    dialogo = _preferencias(monkeypatch)
    estado["conectada"] = True
    ouvintes[0]()
    assert dialogo.conquistas_conta_row.get_subtitle() == "Jogador"


def test_fechar_cancela_o_login_e_solta_o_ouvinte(monkeypatch):
    cancelados = []
    removidos = []
    monkeypatch.setattr(login, "cancelar_pendente", lambda: cancelados.append(1))
    monkeypatch.setattr(conta, "ao_mudar", lambda _o: lambda: removidos.append(1))
    dialogo = _preferencias(monkeypatch)
    dialogo.emit("closed")
    assert cancelados == [1]
    assert removidos == [1]


# --- A conta Epic ---------------------------------------------------------


def test_descricao_do_grupo_das_contas(monkeypatch):
    dialogo = _preferencias(monkeypatch)
    assert dialogo.conquistas_contas_group.get_description() == (
        "Entre com as contas das lojas para acompanhar as conquistas dos jogos do Xbox, "
        "do Game Pass e da Epic Games Store."
    )


def test_conta_epic_desconectada(monkeypatch):
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    dialogo = _preferencias(monkeypatch)
    assert dialogo.conquistas_epic_row.get_subtitle() == "Não conectada"
    assert dialogo.conquistas_epic_botao.get_label() == "Entrar"


def test_conta_epic_conectada_mostra_o_nome(monkeypatch):
    monkeypatch.setattr(epic_conta, "conectada", lambda: True)
    monkeypatch.setattr(epic_conta, "nome", lambda: "Jogador")
    dialogo = _preferencias(monkeypatch)
    assert dialogo.conquistas_epic_row.get_subtitle() == "Jogador"
    assert dialogo.conquistas_epic_botao.get_label() == "Sair"


class _LoginEpicFalso:
    criados: list = []

    def __init__(self, ao_conectar, **_kw):
        self.ao_conectar, self.mostrada, self.fechada, self._fechar = ao_conectar, None, False, []
        _LoginEpicFalso.criados.append(self)

    def connect(self, sinal, funcao):
        assert sinal == "closed"
        self._fechar.append(funcao)

    def mostrar(self, pai):
        self.mostrada = pai

    def force_close(self):
        self.fechada = True
        for funcao in self._fechar:
            funcao(self)


def test_entrar_abre_a_janela_e_o_sucesso_varre_os_jogos_da_epic(monkeypatch, store):
    _LoginEpicFalso.criados = []
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(epic_janela, "JanelaDeLogin", _LoginEpicFalso)
    pedidos = []
    _varredura_falsa(monkeypatch, [], pedidos)
    dialogo = _preferencias(monkeypatch)
    dialogo.conquistas_epic_botao.emit("clicked")
    (janela_,) = _LoginEpicFalso.criados
    assert janela_.mostrada is dialogo
    janela_.ao_conectar()
    assert [filtro for _games, filtro in pedidos] == [fontes.eh_da_epic]


def test_entrar_com_janela_que_falha_ao_mostrar_deixa_tentar_de_novo(monkeypatch):
    class _LoginQueFalha(_LoginEpicFalso):
        def mostrar(self, pai):
            raise RuntimeError("falha ao apresentar")

    _LoginEpicFalso.criados = []
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(epic_janela, "JanelaDeLogin", _LoginQueFalha)
    dialogo = _preferencias(monkeypatch)
    dialogo.conquistas_epic_botao.emit("clicked")
    dialogo.conquistas_epic_botao.emit("clicked")
    # O segundo clique não fica morto: cria outra janela.
    assert len(_LoginEpicFalso.criados) == 2


def test_sair_da_epic(monkeypatch):
    estado = {"conectada": True}
    monkeypatch.setattr(epic_conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(epic_conta, "nome", lambda: "Jogador")
    monkeypatch.setattr(epic_conta, "sair", lambda: estado.update(conectada=False))
    dialogo = _preferencias(monkeypatch)
    dialogo.conquistas_epic_botao.emit("clicked")
    assert dialogo.conquistas_epic_row.get_subtitle() == "Não conectada"


def test_conta_epic_que_muda_atualiza_a_linha(monkeypatch):
    estado = {"conectada": False}
    ouvintes = []
    monkeypatch.setattr(epic_conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(epic_conta, "nome", lambda: "Jogador")
    monkeypatch.setattr(epic_conta, "ao_mudar", lambda ouvinte: ouvintes.append(ouvinte) or (lambda: None))
    dialogo = _preferencias(monkeypatch)
    estado["conectada"] = True
    ouvintes[0]()
    assert dialogo.conquistas_epic_row.get_subtitle() == "Jogador"


def test_fechar_as_preferencias_fecha_a_janela_e_solta_o_ouvinte(monkeypatch):
    _LoginEpicFalso.criados = []
    removidos = []
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(epic_conta, "ao_mudar", lambda _o: lambda: removidos.append(1))
    monkeypatch.setattr(epic_janela, "JanelaDeLogin", _LoginEpicFalso)
    dialogo = _preferencias(monkeypatch)
    dialogo.conquistas_epic_botao.emit("clicked")
    dialogo.emit("closed")
    assert _LoginEpicFalso.criados[0].fechada and removidos == [1]
