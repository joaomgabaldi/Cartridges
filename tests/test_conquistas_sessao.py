"""A sessão liga o vigia e decide o que fazer com cada conquista nova."""

from types import SimpleNamespace

import pytest

from kyron import conquista_aviso, shared
from kyron.conquistas import historico, sessao
from kyron.conquistas.catalogo import ConquistaInfo
from kyron.conquistas.vigia import Desbloqueada
from kyron.utils import session_fita


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


@pytest.fixture
def telas(monkeypatch):
    """O `shared.conquistas` falso: anota os `game_id` que as telas precisam reler."""
    chamadas = []
    monkeypatch.setattr(shared, "conquistas", SimpleNamespace(mudou=chamadas.append), raising=False)
    return chamadas


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


def test_lote_pede_um_pulso_do_tipo_mais_forte(make_game, isolar):
    _mostrados, pulsos = isolar
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar(
        [Desbloqueada("A", _info(), False), Desbloqueada("B", _info(rara=True), True)]
    )
    assert pulsos == ["completo"]


def test_lote_de_comuns_pede_um_pulso(make_game, isolar):
    _mostrados, pulsos = isolar
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar([Desbloqueada(n, _info(), False) for n in "ABC"])
    assert pulsos == ["normal"]


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


def test_falha_no_pulso_nao_cala_a_pagina(make_game, isolar, monkeypatch, telas):
    jogo = make_game()

    def quebra(_tipo):
        raise OSError("fita fora do ar")

    monkeypatch.setattr(session_fita, "pulsar_conquista", quebra)
    sessao.comecar(jogo)
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(), False)])
    assert [a.titulo for a in isolar[0]] == ["Título"]
    assert telas == [jogo.game_id]


def test_falha_na_pagina_nao_levanta(make_game, isolar, monkeypatch):
    jogo = make_game()

    def quebra(_game_id):
        raise RuntimeError("página fechada")

    monkeypatch.setattr(shared, "conquistas", SimpleNamespace(mudou=quebra), raising=False)
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


def test_as_telas_do_jogo_sao_avisadas(make_game, isolar, telas):
    jogo = make_game()
    sessao.comecar(jogo)
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", None, False)])
    assert telas == [jogo.game_id]  # o `ConquistasDoJogo` decide quem mostra o jogo


def test_sem_conquistas_no_app_a_sessao_segue(make_game, isolar):
    sessao.comecar(make_game())
    _VigiaFalso.criados[0].avisar([Desbloqueada("A", _info(), False)])  # shared.conquistas é None
    assert isolar[1] == ["normal"]


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
    from kyron.conquistas.xbox import conta, vigia as vigia_xbox  # noqa: PLC0415

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
    from kyron.conquistas.epic import conta, vigia as vigia_epic  # noqa: PLC0415

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


@pytest.fixture
def ea(monkeypatch):
    from kyron.conquistas.ea import conta, vigia as vigia_ea  # noqa: PLC0415

    _VigiaXboxFalso.criados = []
    monkeypatch.setattr(vigia_ea, "Vigia", _VigiaXboxFalso)
    monkeypatch.setattr(conta, "conectada", lambda: True)
    return conta


def test_jogo_da_ea_usa_o_vigia_da_ea_e_so_pulsa(make_game, ea, isolar):
    mostrados, pulsos = isolar
    game = make_game(steam_appid="570")  # appID da Steam nos metadados: a EA vence
    historico.registrar(game.game_id, [], fonte="ea:75158_1_2")
    sessao.comecar(game)
    assert _VigiaFalso.criados == []  # nada do vigia de arquivos
    (vigia_,) = _VigiaXboxFalso.criados
    assert vigia_.game is game and vigia_.ativo and sessao.acompanhando(game)
    assert sessao._so_pulso(game)
    vigia_.avisar([Desbloqueada("A", _info(rara=True), False)])
    assert mostrados == []  # o overlay da EA já mostra o aviso
    assert pulsos == ["rara"]
    sessao.parar()
    assert not vigia_.ativo


@pytest.fixture
def ubisoft(monkeypatch):
    from kyron.conquistas.ubisoft import vigia as vigia_ubisoft  # noqa: PLC0415

    _VigiaXboxFalso.criados = []
    monkeypatch.setattr(vigia_ubisoft, "Vigia", _VigiaXboxFalso)


def test_jogo_da_ubisoft_usa_o_vigia_da_ubisoft_e_so_pulsa(make_game, ubisoft, isolar):
    mostrados, pulsos = isolar
    game = make_game(executable='start "" "uplay://launch/65043/0"', steam_appid="242050")
    historico.registrar(game.game_id, [], fonte="ubisoft:65043")
    sessao.comecar(game)
    assert _VigiaFalso.criados == []  # nada do vigia de arquivos
    (vigia_,) = _VigiaXboxFalso.criados
    assert vigia_.game is game and vigia_.ativo and sessao.acompanhando(game)
    assert sessao._so_pulso(game)
    vigia_.avisar([Desbloqueada("UBI:1", _info(), False)])
    assert mostrados == []  # o overlay do Ubisoft Connect já mostra o aviso
    assert pulsos == ["normal"]


def test_ubisoft_com_interruptor_desligado_nao_cria_vigia(make_game, ubisoft):
    game = make_game(conquistas=False)
    historico.registrar(game.game_id, [], fonte="ubisoft:65043")
    sessao.comecar(game)
    assert _VigiaXboxFalso.criados == [] and _VigiaFalso.criados == []
