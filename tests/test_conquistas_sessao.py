"""A sessão liga o vigia e decide o que fazer com cada conquista nova."""

from types import SimpleNamespace

import pytest

from cartridges import conquista_aviso
from cartridges.conquistas import historico, sessao
from cartridges.conquistas.catalogo import ConquistaInfo
from cartridges.conquistas.vigia import Desbloqueada
from cartridges.utils import session_fita


class _VigiaFalso:
    criados: list = []

    def __init__(self, game, avisar):
        self.game, self.avisar, self.iniciado, self.parado = game, avisar, False, False
        _VigiaFalso.criados.append(self)

    @property
    def ativo(self):
        return self.iniciado and not self.parado

    def iniciar(self):
        self.iniciado = True

    def parar(self):
        self.parado = True


@pytest.fixture(autouse=True)
def isolar(monkeypatch):
    _VigiaFalso.criados = []
    monkeypatch.setattr(sessao, "Vigia", _VigiaFalso)
    monkeypatch.setattr(sessao, "acompanha", lambda _g: True)
    mostrados, pulsos = [], []
    monkeypatch.setattr(conquista_aviso, "mostrar", mostrados.append)
    monkeypatch.setattr(conquista_aviso, "fechar", lambda: mostrados.append("fechar"))
    monkeypatch.setattr(session_fita, "pulsar_conquista", pulsos.append)
    yield mostrados, pulsos
    sessao.parar()


def _info(rara=False):
    return ConquistaInfo("A", "Título", "Desc", "", "", False, 4.0 if rara else 50.0)


def test_comecar_e_parar(make_game, isolar):
    jogo = make_game(name="Jogo")
    sessao.comecar(jogo)
    (vigia_,) = _VigiaFalso.criados
    assert vigia_.iniciado and vigia_.game is jogo
    sessao.parar()
    assert vigia_.parado
    assert isolar[0] == ["fechar"]


def test_jogo_nao_acompanhado_nao_cria_vigia(make_game, monkeypatch):
    monkeypatch.setattr(sessao, "acompanha", lambda _g: False)
    sessao.comecar(make_game())
    assert _VigiaFalso.criados == []


def test_conquista_nova_mostra_cartao_e_pulsa(make_game, isolar):
    mostrados, pulsos = isolar
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(rara=True), False)])
    assert [a.titulo for a in mostrados] == ["Título"]
    assert pulsos == ["rara"]


def test_sem_catalogo_pulsa_sem_cartao(make_game, isolar):
    mostrados, pulsos = isolar
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", None, False)])
    assert mostrados == []
    assert pulsos == ["normal"]


def test_preferencias_desligadas(make_game, isolar, schema):
    mostrados, pulsos = isolar
    schema.set_boolean("conquistas-aviso", False)
    schema.set_boolean("conquistas-iluminacao", False)
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(), False)])
    assert mostrados == [] and pulsos == []


def test_tipo_do_pulso():
    assert sessao.tipo_do_pulso(Desbloqueada("A", _info(rara=True), True)) == "completo"
    assert sessao.tipo_do_pulso(Desbloqueada("A", _info(rara=True), False)) == "rara"
    assert sessao.tipo_do_pulso(Desbloqueada("A", _info(), False)) == "normal"
    assert sessao.tipo_do_pulso(Desbloqueada("A", None, False)) == "normal"


def test_erro_no_despacho_nao_levanta(make_game, isolar, monkeypatch):
    mostrados, pulsos = isolar
    sessao.comecar(make_game())
    monkeypatch.setattr(conquista_aviso.Aviso, "de", classmethod(lambda cls, d: 1 / 0))
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(), False)])  # não levanta
    assert mostrados == [] and pulsos == ["normal"]  # a falha no cartão não cala o pulso


def test_falha_no_pulso_nao_cala_a_pagina(make_game, isolar, monkeypatch, win):
    jogo = make_game()
    chamadas = []
    win.active_game = jogo
    win.update_conquistas_block = chamadas.append

    def quebra(_tipo):
        raise OSError("fita fora do ar")

    monkeypatch.setattr(session_fita, "pulsar_conquista", quebra)
    sessao.comecar(jogo)
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(), False)])
    assert [a.titulo for a in isolar[0]] == ["Título"]
    assert chamadas == [jogo]


def test_falha_na_pagina_nao_levanta(make_game, isolar, win):
    jogo = make_game()
    win.active_game = jogo

    def quebra(_jogo):
        raise RuntimeError("página fechada")

    win.update_conquistas_block = quebra
    sessao.comecar(jogo)
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(), False)])
    assert isolar[1] == ["normal"]


def test_falha_ao_parar_o_vigia_ainda_fecha_os_cartoes(make_game, isolar):
    mostrados, _pulsos = isolar
    sessao.comecar(make_game())

    def quebra():
        raise RuntimeError("falha de teste")

    _VigiaFalso.criados[0].parar = quebra
    sessao.parar()  # não levanta
    assert "fechar" in mostrados  # nada de cartão depois do fim do jogo


def test_acompanhando_so_enquanto_a_sessao_do_jogo_esta_aberta(make_game):
    jogo, outro = make_game(game_id="g1"), make_game(game_id="g2")
    assert not sessao.acompanhando(jogo)
    sessao.comecar(jogo)
    assert sessao.acompanhando(jogo) and not sessao.acompanhando(outro)
    sessao.parar()
    assert not sessao.acompanhando(jogo)


def test_pagina_aberta_do_jogo_e_atualizada(make_game, isolar, win):
    jogo = make_game()
    chamadas = []
    win.active_game = jogo
    win.update_conquistas_block = chamadas.append
    sessao.comecar(jogo)
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", None, False)])
    assert chamadas == [jogo]


def test_o_fechamento_do_app_para_o_vigia_antes_de_devolver_papel_e_fitas(monkeypatch):
    """Simétrico ao `hide_session_blocker`: um pulso pedido depois de as fitas
    voltarem à cor do app não teria sessão para pulsar."""
    import cartridges.main as main_module  # noqa: PLC0415
    from cartridges import shared  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(main_module.sessao_conquistas, "parar", lambda: chamadas.append("vigia"))
    monkeypatch.setattr(
        main_module.session_wallpaper, "restaurar", lambda: chamadas.append("papel")
    )
    monkeypatch.setattr(main_module.session_fita, "fechar", lambda: chamadas.append("fitas"))
    monkeypatch.setattr(shared, "win", None)
    monkeypatch.setattr(shared, "store", shared.store)

    main_module.CartridgesApplication().do_shutdown()
    assert chamadas == ["vigia", "papel", "fitas"]


def test_a_sessao_da_janela_liga_e_desliga_o_vigia(real_window, make_game, monkeypatch):
    import cartridges.window as window_module  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(window_module.sessao_conquistas, "comecar", chamadas.append)
    monkeypatch.setattr(window_module.sessao_conquistas, "parar", lambda: chamadas.append("parar"))
    jogo = make_game(name="Hollow Knight")
    real_window.show_session_blocker(jogo)
    real_window.hide_session_blocker()
    assert chamadas == [jogo, "parar"]


def _app_com_varredura(real_window, monkeypatch):
    varridos = []
    app = SimpleNamespace(
        varredura_conquistas=SimpleNamespace(varrer_jogo=lambda jogo: varridos.append(jogo))
    )
    monkeypatch.setattr(real_window, "get_application", lambda: app)
    return varridos


def test_o_fim_da_sessao_pede_a_leitura_final_depois_de_parar_o_vigia(
    real_window, make_game, monkeypatch
):
    import cartridges.window as window_module  # noqa: PLC0415

    ordem = []
    monkeypatch.setattr(window_module.sessao_conquistas, "comecar", lambda _j: None)
    monkeypatch.setattr(window_module.sessao_conquistas, "parar", lambda: ordem.append("parar"))
    app = SimpleNamespace(
        varredura_conquistas=SimpleNamespace(varrer_jogo=lambda j: ordem.append(("varrer", j)))
    )
    monkeypatch.setattr(real_window, "get_application", lambda: app)
    jogo = make_game(name="Hollow Knight", steam_appid="570")
    real_window.show_session_blocker(jogo)
    assert ordem == []  # o começo da sessão não varre
    real_window.hide_session_blocker()
    # Depois de o vigia parar: com ele ativo, o histórico do jogo é dele.
    assert ordem == ["parar", ("varrer", jogo)]


def test_fim_de_sessao_sem_varredura_ou_sem_jogo_nao_levanta(real_window, make_game, monkeypatch):
    import cartridges.window as window_module  # noqa: PLC0415

    monkeypatch.setattr(window_module.sessao_conquistas, "comecar", lambda _j: None)
    app = SimpleNamespace(varredura_conquistas=None)
    monkeypatch.setattr(real_window, "get_application", lambda: app)
    real_window.show_session_blocker(make_game(name="X"))
    real_window.hide_session_blocker()  # varredura None: nada
    varridos = _app_com_varredura(real_window, monkeypatch)
    real_window.hide_session_blocker()  # sem jogo de sessão: nada
    assert varridos == []


def test_varredura_que_estoura_no_fim_da_sessao_nao_derruba_o_resto(
    real_window, make_game, monkeypatch
):
    import cartridges.window as window_module  # noqa: PLC0415

    def estoura(_jogo):
        raise RuntimeError("falhou")

    app = SimpleNamespace(varredura_conquistas=SimpleNamespace(varrer_jogo=estoura))
    monkeypatch.setattr(real_window, "get_application", lambda: app)
    voltou = []
    monkeypatch.setattr(window_module.session_fita, "voltar", lambda: voltou.append(1))
    real_window.show_session_blocker(make_game(name="X"))
    real_window.hide_session_blocker()
    assert voltou == [1]


def test_o_fechamento_do_app_nao_pede_a_leitura_final(monkeypatch):
    import cartridges.main as main_module  # noqa: PLC0415
    from cartridges import shared  # noqa: PLC0415

    varridos, parou = [], []
    monkeypatch.setattr(main_module.sessao_conquistas, "parar", lambda: None)
    monkeypatch.setattr(main_module.session_wallpaper, "restaurar", lambda: None)
    monkeypatch.setattr(main_module.session_fita, "fechar", lambda: None)
    monkeypatch.setattr(shared, "win", None)
    monkeypatch.setattr(shared, "store", shared.store)
    app = main_module.CartridgesApplication()
    app.varredura_conquistas = SimpleNamespace(
        varrer_jogo=varridos.append, varrer_jogos=varridos.extend, stop=lambda: parou.append(1)
    )
    app.do_shutdown()
    assert varridos == [] and parou == [1]


def test_jogo_da_steam_so_pulsa(make_game, isolar):
    mostrados, pulsos = isolar
    sessao.comecar(make_game(executable="steam://rungameid/570"))
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(rara=True), False)])
    assert mostrados == []
    assert pulsos == ["rara"]


class _VigiaXboxFalso:
    criados: list = []

    def __init__(self, game, avisar, **_kw):
        self.game, self.avisar, self.ativo = game, avisar, False
        _VigiaXboxFalso.criados.append(self)

    def iniciar(self):
        self.ativo = True

    def parar(self):
        self.ativo = False


@pytest.fixture
def xbox(monkeypatch):
    from cartridges.conquistas.xbox import conta, vigia as vigia_xbox  # noqa: PLC0415

    _VigiaXboxFalso.criados = []
    monkeypatch.setattr(vigia_xbox, "Vigia", _VigiaXboxFalso)
    monkeypatch.setattr(conta, "conectada", lambda: True)
    return conta


def test_jogo_do_xbox_usa_o_vigia_do_xbox_e_so_pulsa(make_game, xbox, isolar):
    mostrados, pulsos = isolar
    game = make_game()
    historico.registrar(game.game_id, [], fonte="xbox:7")
    sessao.comecar(game)
    assert _VigiaFalso.criados == []  # nada do vigia de arquivos
    (vigia_,) = _VigiaXboxFalso.criados
    assert vigia_.game is game and vigia_.ativo and sessao.acompanhando(game)
    assert sessao._so_pulso(game)
    vigia_.avisar([Desbloqueada("A", _info(rara=True), False)])
    assert mostrados == []  # a Xbox Game Bar já mostra o aviso
    assert pulsos == ["rara"]
    sessao.parar()
    assert not vigia_.ativo


def test_jogo_do_xbox_sem_conta_nao_e_acompanhado(make_game, xbox, monkeypatch):
    monkeypatch.setattr(xbox, "conectada", lambda: False)
    game = make_game()
    historico.registrar(game.game_id, [], fonte="xbox:7")
    sessao.comecar(game)
    assert sessao._vigia is None
    assert _VigiaXboxFalso.criados == [] and _VigiaFalso.criados == []


def test_jogo_do_xbox_com_conquistas_desligadas_nao_e_acompanhado(make_game, xbox):
    game = make_game(conquistas=False)
    historico.registrar(game.game_id, [], fonte="xbox:7")
    sessao.comecar(game)
    assert sessao._vigia is None and _VigiaXboxFalso.criados == []


def test_fonte_steam_gravada_segue_o_caminho_dos_arquivos(make_game, xbox):
    game = make_game()
    historico.registrar(game.game_id, [], fonte="steam:570")
    sessao.comecar(game)
    assert _VigiaXboxFalso.criados == [] and len(_VigiaFalso.criados) == 1
    assert not sessao._so_pulso(game)  # sem executável da Steam: cartão e pulso


def test_so_pulso_sem_jogo_ou_sem_fonte(make_game):
    assert not sessao._so_pulso(None)
    assert not sessao._so_pulso(make_game())


@pytest.fixture
def epic(monkeypatch):
    from cartridges.conquistas.epic import conta, vigia as vigia_epic  # noqa: PLC0415

    _VigiaXboxFalso.criados = []
    monkeypatch.setattr(vigia_epic, "Vigia", _VigiaXboxFalso)
    monkeypatch.setattr(conta, "conectada", lambda: True)
    return conta


def test_jogo_da_epic_usa_o_vigia_da_epic_e_so_pulsa(make_game, epic, isolar):
    mostrados, pulsos = isolar
    game = make_game(executable='start "" "com.epicgames.launcher://apps/Sugar"', steam_appid="570")
    historico.registrar(game.game_id, [], fonte="epic:ns1")
    sessao.comecar(game)
    assert _VigiaFalso.criados == []  # nada do vigia de arquivos
    (vigia_,) = _VigiaXboxFalso.criados
    assert vigia_.game is game and vigia_.ativo and sessao.acompanhando(game)
    assert sessao._so_pulso(game)
    vigia_.avisar([Desbloqueada("A", _info(rara=True), False)])
    assert mostrados == []  # o overlay da Epic já mostra o aviso
    assert pulsos == ["rara"]
    sessao.parar()
    assert not vigia_.ativo


def test_jogo_da_epic_sem_conta_nao_e_acompanhado(make_game, epic, monkeypatch):
    monkeypatch.setattr(epic, "conectada", lambda: False)
    game = make_game(executable='start "" "com.epicgames.launcher://apps/Sugar"')
    historico.registrar(game.game_id, [], fonte="epic:ns1")
    sessao.comecar(game)
    assert sessao._vigia is None
    assert _VigiaXboxFalso.criados == [] and _VigiaFalso.criados == []
