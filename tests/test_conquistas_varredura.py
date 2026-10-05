"""A varredura de abertura: grava o histórico e avisa do que é novo."""

import json
from types import SimpleNamespace

import pytest

from cartridges.conquistas import catalogo, historico, sessao, varredura
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.varredura import VarreduraConquistas
from tests.apoio_conquistas import criar, pastas  # noqa: F401


_OBTER_REAL = catalogo.obter


@pytest.fixture(autouse=True)
def sem_catalogo(monkeypatch):
    monkeypatch.setattr(catalogo, "obter", lambda _appid, _exe, rede=True, usar_chave=True: catalogo.Renovacao(None))


def _goldberg(pastas, appid, conquistas):  # noqa: F811
    criar(
        pastas.appdata / "GSE Saves" / appid / "achievements.json",
        json.dumps({nome: {"earned": True, "earned_time": hora} for nome, hora in conquistas}),
    )


def _rodar(games, flush_idle):
    instancia = VarreduraConquistas()
    instancia._worker(games, instancia._generation)
    flush_idle()
    return instancia


def _avisos(win):
    return [toast.get_title() for toast in win.toast_queue.added]


def _da_steam_aberta(store, make_game, numero, appid=None):
    """Jogo da Steam (atalho steam://): tem fonte mesmo sem arquivo de emulador."""
    appid = appid or str(numero)
    return _registrado(
        store, make_game, numero, steam_appid=appid, executable=f"steam://rungameid/{appid}"
    )


def _registrado(store, make_game, numero, **campos):
    campos.setdefault("executable", "")
    game = make_game(game_id=f"shortcuts_{numero}", name=f"Jogo {numero}", **campos)
    store.add_game(game, {}, run_pipeline=False)
    return game


def test_primeira_varredura_grava_sem_avisar(store, make_game, pastas, win, flush_idle):
    _goldberg(pastas, "570", [("ACH_A", 100)])
    game = _registrado(store, make_game, 1, steam_appid="570")
    _rodar([game], flush_idle)
    assert historico.ler(game.game_id) == {"ACH_A": 100}
    assert _avisos(win) == []


def test_conquista_nova_desde_a_ultima_abertura(store, make_game, pastas, win, flush_idle):
    game = _registrado(store, make_game, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("ACH_A", 100)])
    _goldberg(pastas, "570", [("ACH_A", 100), ("ACH_B", 200)])
    _rodar([game], flush_idle)
    assert historico.ler(game.game_id) == {"ACH_A": 100, "ACH_B": 200}
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]


def test_aviso_soma_os_jogos(store, make_game, pastas, win, flush_idle):
    um = _registrado(store, make_game, 1, steam_appid="570")
    dois = _registrado(store, make_game, 2, steam_appid="620")
    historico.registrar(um.game_id, [])
    historico.registrar(dois.game_id, [])
    _goldberg(pastas, "570", [("A", 1), ("B", 2)])
    _goldberg(pastas, "620", [("C", 3)])
    _rodar([um, dois], flush_idle)
    assert _avisos(win) == ["3 novas conquistas em 2 jogos"]


def test_mesmo_appid_em_dois_jogos(store, make_game, pastas, flush_idle):
    zerado = _registrado(store, make_game, 1, steam_appid="570", removed=True, status="beaten")
    vivo = _registrado(store, make_game, 2, steam_appid="570")
    _goldberg(pastas, "570", [("ACH_A", 100)])
    _rodar([zerado, vivo], flush_idle)
    assert historico.ler(zerado.game_id) == historico.ler(vivo.game_id) == {"ACH_A": 100}


def test_jogo_que_saiu_durante_a_leitura_nao_ganha_arquivo(store, make_game, pastas, flush_idle):
    _goldberg(pastas, "570", [("ACH_A", 100)])
    game = _registrado(store, make_game, 1, steam_appid="570")
    leitura = varredura.ler_jogo(game)
    store.excluir(game)
    instancia = VarreduraConquistas()
    assert instancia._gravar(leitura) == 0
    flush_idle()
    assert historico.ler(game.game_id) is None


def test_appid_corrigido_durante_a_leitura_descarta_a_leitura(
    store, make_game, pastas, flush_idle
):
    _goldberg(pastas, "570", [("ACH_A", 100)])
    game = _registrado(store, make_game, 1, steam_appid="570")
    leitura = varredura.ler_jogo(game)
    game.steam_appid = "620"
    historico.apagar(game.game_id)
    assert VarreduraConquistas()._gravar(leitura) == 0
    flush_idle()
    assert historico.ler(game.game_id) is None


def test_jogo_em_sessao_com_vigia_fica_para_o_vigia(
    store, make_game, pastas, win, flush_idle, monkeypatch
):
    """Durante a sessão o vigia é dono do histórico do jogo: se a varredura fundisse
    a conquista nova antes dele, o vigia não veria novidade (sem cartão e sem pulso)."""
    game = _registrado(store, make_game, 1, steam_appid="570")
    outro = _registrado(store, make_game, 2, steam_appid="620")
    historico.registrar(game.game_id, [Desbloqueio("ACH_A", 100)])
    historico.registrar(outro.game_id, [])
    _goldberg(pastas, "570", [("ACH_A", 100), ("ACH_B", 200)])
    _goldberg(pastas, "620", [("ACH_C", 300)])
    monkeypatch.setattr(sessao, "_vigia", SimpleNamespace(game=game, ativo=True))
    _rodar([game, outro], flush_idle)
    assert historico.ler(game.game_id) == {"ACH_A": 100}  # o vigia cuida deste
    assert historico.ler(outro.game_id) == {"ACH_C": 300}  # os outros seguem normalmente
    assert _avisos(win) == ["1 nova conquista em Jogo 2"]


def test_vigia_parado_nao_segura_a_varredura(store, make_game, pastas, flush_idle, monkeypatch):
    game = _registrado(store, make_game, 1, steam_appid="570")
    historico.registrar(game.game_id, [])
    _goldberg(pastas, "570", [("ACH_A", 100)])
    monkeypatch.setattr(sessao, "_vigia", SimpleNamespace(game=game, ativo=False))
    _rodar([game], flush_idle)
    assert historico.ler(game.game_id) == {"ACH_A": 100}


def test_chave_recusada_avisa_uma_vez(store, make_game, pastas, win, flush_idle, monkeypatch):
    monkeypatch.setattr(
        catalogo, "obter", lambda _appid, _exe, rede=True, usar_chave=True: catalogo.Renovacao(None, chave_recusada=True)
    )
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert _avisos(win).count(
        "A chave da Steam Web API foi recusada. Verifique-a nas Preferências."
    ) == 1


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"steam_appid": "570"}, True),
        ({"steam_appid": "570", "conquistas": False}, False),
        ({}, True),  # sem appID também participa: a fonte pode ser o Xbox
        ({"steam_appid": "570", "removed": True}, False),  # removido, não zerado
        ({"steam_appid": "570", "removed": True, "status": "beaten"}, True),  # zerado
        ({"steam_appid": "570", "removed": True, "status": "beaten", "blacklisted": True}, False),
    ],
)
def test_quem_participa(make_game, campos, esperado):
    assert varredura.participa(make_game(**campos)) is esperado


def test_mensagem():
    assert varredura.mensagem([]) is None
    assert varredura.mensagem([("A", 0)]) is None
    assert varredura.mensagem([("Hollow Knight", 2)]) == "2 novas conquistas em Hollow Knight"
    assert varredura.mensagem([("A", 1), ("B", 0), ("C", 2)]) == "3 novas conquistas em 2 jogos"


def test_entregar_nao_levanta_no_laco_principal(store, make_game, pastas, flush_idle, monkeypatch):
    game = _registrado(store, make_game, 1, steam_appid="570")
    leitura = varredura.ler_jogo(game)

    def estoura(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(historico, "registrar", estoura)
    assert VarreduraConquistas()._entregar(leitura) is False


def test_concluir_nao_levanta_e_zera_a_lista(monkeypatch):
    instancia = VarreduraConquistas()
    instancia._novas = [("Jogo 1", 2)]

    def estoura(_texto):
        raise RuntimeError("sem janela")

    monkeypatch.setattr(varredura, "_aviso", estoura)
    assert instancia._concluir() is False
    assert instancia._novas == []


def test_varredura_de_um_jogo_fica_calada(store, make_game, pastas, win, flush_idle, monkeypatch):
    monkeypatch.setattr(
        catalogo, "obter", lambda _appid, _exe, rede=True, usar_chave=True: catalogo.Renovacao(None, chave_recusada=True)
    )
    game = _registrado(store, make_game, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("ACH_A", 100)])
    _goldberg(pastas, "570", [("ACH_A", 100), ("ACH_B", 200)])
    instancia = VarreduraConquistas()
    instancia._worker([game], instancia._generation, avisar=False)
    flush_idle()
    assert historico.ler(game.game_id) == {"ACH_A": 100, "ACH_B": 200}
    assert _avisos(win) == []
    assert instancia._novas == []
    # A passada completa que vem depois, sem nada novo, também não avisa do que
    # a varredura de um jogo só já guardou.
    instancia._worker([game], instancia._generation)
    flush_idle()
    assert [aviso for aviso in _avisos(win) if "conquista" in aviso] == []


class _ThreadFalsa:
    iniciadas: list = []

    def __init__(self, target, args=(), daemon=False):
        self.target, self.args, self.daemon = target, args, daemon

    def start(self):
        _ThreadFalsa.iniciadas.append(self)


@pytest.fixture
def threads_falsas(monkeypatch):
    _ThreadFalsa.iniciadas = []
    monkeypatch.setattr(varredura.threading, "Thread", _ThreadFalsa)
    return _ThreadFalsa.iniciadas


def test_varrer_jogos_usa_uma_thread_so_e_ignora_quem_nao_participa(
    store, make_game, threads_falsas
):
    a = _registrado(store, make_game, 1, steam_appid="570")
    b = _registrado(store, make_game, 2, steam_appid="620")
    bloqueado = _registrado(store, make_game, 3, steam_appid="440", blacklisted=True)
    desligado = _registrado(store, make_game, 4, steam_appid="730", conquistas=False)
    VarreduraConquistas().varrer_jogos([a, bloqueado, b, desligado])
    (thread,) = threads_falsas
    jogos, geracao, avisar = thread.args[0], thread.args[1], thread.args[2]
    assert jogos == [a, b] and avisar is False and geracao == 0
    assert thread.daemon is True


def test_varrer_jogos_vazio_ou_sem_ninguem_que_participe_nao_faz_nada(
    store, make_game, threads_falsas
):
    instancia = VarreduraConquistas()
    instancia.varrer_jogos([])
    instancia.varrer_jogos([_registrado(store, make_game, 1, conquistas=False)])
    assert threads_falsas == []


def test_varrer_jogo_e_varrer_jogos_de_um(store, make_game, threads_falsas):
    game = _registrado(store, make_game, 1, steam_appid="570")
    VarreduraConquistas().varrer_jogo(game)
    (thread,) = threads_falsas
    assert thread.args[0] == [game] and thread.args[2] is False


def test_varrer_jogos_entrega_o_filtro_a_thread_sem_aplicar(
    store, make_game, threads_falsas
):
    """O filtro pode ler o disco do jogo: quem aplica é a thread, nunca quem pede."""
    a = _registrado(store, make_game, 1, steam_appid="570")
    b = _registrado(store, make_game, 2, steam_appid="620")
    consultados = []

    def filtro(game):
        consultados.append(game)
        return game is a

    VarreduraConquistas().varrer_jogos([a, b], filtro=filtro)
    (thread,) = threads_falsas
    assert consultados == []
    assert thread.args[3] is filtro


def test_filtro_roda_na_thread_e_deixa_de_fora_quem_nao_passa(
    store, make_game, pastas, win, flush_idle
):
    a = _da_steam_aberta(store, make_game, 1, "570")
    b = _da_steam_aberta(store, make_game, 2, "620")
    instancia = VarreduraConquistas()
    instancia._worker([a, b], instancia._generation, False, lambda game: game is a)
    flush_idle()
    assert historico.ler(a.game_id) == {}
    assert historico.ler(b.game_id) is None


def test_filtro_que_levanta_deixa_o_jogo_de_fora_sem_derrubar_a_thread(
    store, make_game, pastas, win, flush_idle
):
    a = _da_steam_aberta(store, make_game, 1, "570")
    b = _da_steam_aberta(store, make_game, 2, "620")

    def filtro(game):
        if game is a:
            raise RuntimeError("disco")
        return True

    instancia = VarreduraConquistas()
    instancia._worker([a, b], instancia._generation, False, filtro)
    flush_idle()
    assert historico.ler(a.game_id) is None
    assert historico.ler(b.game_id) == {}


def test_varrer_jogos_fica_calada_e_nao_guarda_a_data(
    store, make_game, pastas, win, flush_idle, state_schema, monkeypatch
):
    a = _registrado(store, make_game, 1, steam_appid="570")
    b = _registrado(store, make_game, 2, steam_appid="620")
    historico.registrar(a.game_id, [Desbloqueio("ACH_A", 100)])
    _goldberg(pastas, "570", [("ACH_A", 100), ("ACH_B", 200)])
    _goldberg(pastas, "620", [("ACH_X", 100)])
    ligada = []

    class Sincrona(_ThreadFalsa):
        def start(self):
            ligada.append(1)
            self.target(*self.args)

    monkeypatch.setattr(varredura.threading, "Thread", Sincrona)
    VarreduraConquistas().varrer_jogos([a, b])
    flush_idle()
    assert ligada == [1]
    assert historico.ler(a.game_id) == {"ACH_A": 100, "ACH_B": 200}
    assert historico.ler(b.game_id) == {"ACH_X": 100}
    assert _avisos(win) == []
    assert state_schema.get_int64("conquistas-ultima-varredura") == 0


def _janela_com_jogo_aberto(win, game):
    chamadas = []
    win.active_game = game
    win.update_conquistas_block = chamadas.append
    return chamadas


def test_pagina_aberta_atualiza_quando_so_o_catalogo_chegou(
    store, make_game, pastas, win, flush_idle, monkeypatch
):
    monkeypatch.setattr(
        catalogo,
        "obter",
        lambda _appid, _exe, rede=True, usar_chave=True: catalogo.Renovacao(catalogo.Catalogo((), 1, False)),
    )
    game = _da_steam_aberta(store, make_game, 1, "570")
    historico.registrar(game.game_id, [], fonte="steam:570")
    chamadas = _janela_com_jogo_aberto(win, game)
    _rodar([game], flush_idle)
    assert chamadas == [game]


def test_pagina_aberta_nao_atualiza_sem_novidade(store, make_game, pastas, win, flush_idle):
    game = _da_steam_aberta(store, make_game, 1, "570")
    historico.registrar(game.game_id, [], fonte="steam:570")
    chamadas = _janela_com_jogo_aberto(win, game)
    _rodar([game], flush_idle)
    assert chamadas == []


def test_pagina_de_outro_jogo_nao_atualiza(store, make_game, pastas, win, flush_idle, monkeypatch):
    monkeypatch.setattr(
        catalogo,
        "obter",
        lambda _appid, _exe, rede=True, usar_chave=True: catalogo.Renovacao(catalogo.Catalogo((), 1, False)),
    )
    game = _da_steam_aberta(store, make_game, 1, "570")
    outro = _da_steam_aberta(store, make_game, 2, "620")
    historico.registrar(game.game_id, [], fonte="steam:570")
    chamadas = _janela_com_jogo_aberto(win, outro)
    _rodar([game], flush_idle)
    # O catálogo do jogo chegou (e a página dele atualizaria), mas a aberta é a de outro.
    assert chamadas == []
    chamadas = _janela_com_jogo_aberto(win, game)
    _rodar([game], flush_idle)
    assert chamadas == [game]


# --- duas passadas: arquivos primeiro, rede depois ---------------------------------


def test_arquivos_de_todos_os_jogos_antes_de_qualquer_catalogo(
    store, make_game, pastas, flush_idle, monkeypatch
):
    eventos = []
    ler_de_verdade = varredura.ler_jogo

    def ler(game):
        eventos.append(("arquivos", game.game_id))
        return ler_de_verdade(game)

    def obter(appid, _exe, rede=True, usar_chave=True):
        eventos.append(("catalogo", appid))
        return catalogo.Renovacao(None)

    monkeypatch.setattr(varredura, "ler_jogo", ler)
    monkeypatch.setattr(catalogo, "obter", obter)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert [tipo for tipo, _ in eventos] == ["arquivos"] * 3 + ["catalogo"] * 3


def test_aviso_de_conquista_nova_nao_espera_a_rede(
    store, make_game, pastas, win, flush_idle, monkeypatch
):
    """O aviso sai depois da passada dos arquivos, antes do primeiro catálogo."""
    um = _registrado(store, make_game, 1, steam_appid="570")
    historico.registrar(um.game_id, [])
    _goldberg(pastas, "570", [("ACH_A", 100)])
    vistos = []

    def obter(_appid, _exe, rede=True, usar_chave=True):
        flush_idle()  # o laço principal que rodaria enquanto a thread espera a rede
        vistos.append(_avisos(win))
        return catalogo.Renovacao(None)

    monkeypatch.setattr(catalogo, "obter", obter)
    _rodar([um], flush_idle)
    assert vistos == [["1 nova conquista em Jogo 1"]]
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]  # uma vez só


def test_historico_gravado_antes_do_primeiro_catalogo(
    store, make_game, pastas, flush_idle, monkeypatch
):
    _goldberg(pastas, "570", [("ACH_A", 100)])
    game = _registrado(store, make_game, 1, steam_appid="570")
    vistos = []

    def obter(_appid, _exe, rede=True, usar_chave=True):
        flush_idle()
        vistos.append(historico.ler(game.game_id))
        return catalogo.Renovacao(None)

    monkeypatch.setattr(catalogo, "obter", obter)
    _rodar([game], flush_idle)
    assert vistos == [{"ACH_A": 100}]


class _TarefaFalsa:
    def __init__(self, total):
        self.total = total
        self.feitos = []
        self.terminada = False

    def atualizar(self, feitos, total=None):
        self.feitos.append(feitos)

    def terminar(self):
        self.terminada = True


def test_tarefa_cobre_as_duas_passadas(store, make_game, pastas, flush_idle, monkeypatch):
    criadas = []

    def comecar(_nome, total):
        criadas.append(_TarefaFalsa(total))
        return criadas[0]

    monkeypatch.setattr(varredura.tarefas, "comecar", comecar)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert criadas[0].total == 6
    assert criadas[0].feitos == [0, 1, 2, 3, 4, 5]
    assert criadas[0].terminada


def test_rede_que_falhou_poupa_os_jogos_seguintes(
    store, make_game, pastas, flush_idle, monkeypatch
):
    chamadas = []

    def obter(appid, _exe, rede=True, usar_chave=True):
        chamadas.append((appid, rede))
        return catalogo.Renovacao(None, rede_falhou=rede)

    monkeypatch.setattr(catalogo, "obter", obter)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert chamadas == [("1", True), ("2", False), ("3", False)]


def test_tres_jogos_sem_rede_fazem_um_pedido_so(
    store, make_game, pastas, flush_idle, monkeypatch
):
    from requests.exceptions import ConnectionError as ErroDeConexao  # noqa: PLC0415

    pedidos = []

    def pedir(url):
        pedidos.append(url)
        if len(pedidos) > 1:
            raise AssertionError(f"pedido depois da rede cair: {url}")
        raise ErroDeConexao("sem rede")

    info = catalogo.ConquistaInfo("ACH_L", "Local", "", "", "", False)
    monkeypatch.setattr(catalogo, "obter", _OBTER_REAL)
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [info])
    monkeypatch.setattr(catalogo, "_pedir", pedir)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert len(pedidos) == 1
    # Os três jogos ficaram com o catálogo do arquivo do próprio jogo.
    assert all(catalogo.em_cache(str(n)) is not None for n in (1, 2, 3))


def test_parar_no_meio_da_segunda_passada(store, make_game, pastas, flush_idle, monkeypatch):
    instancia = VarreduraConquistas()
    chamadas = []

    def obter(appid, _exe, rede=True, usar_chave=True):
        chamadas.append(appid)
        instancia.stop()
        return catalogo.Renovacao(None)

    monkeypatch.setattr(catalogo, "obter", obter)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2, 3)]
    instancia._worker(jogos, instancia._generation)
    flush_idle()
    assert chamadas == ["1"]


def test_geracao_nova_para_a_segunda_passada(store, make_game, pastas, flush_idle, monkeypatch):
    instancia = VarreduraConquistas()
    chamadas = []

    def obter(appid, _exe, rede=True, usar_chave=True):
        chamadas.append(appid)
        instancia._generation += 1
        return catalogo.Renovacao(None)

    monkeypatch.setattr(catalogo, "obter", obter)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2)]
    instancia._worker(jogos, instancia._generation)
    flush_idle()
    assert chamadas == ["1"]


def test_catalogo_que_estoura_nao_derruba_a_passada(
    store, make_game, pastas, win, flush_idle, monkeypatch
):
    def obter(appid, _exe, rede=True, usar_chave=True):
        if appid == "1":
            raise RuntimeError("defeito")
        return catalogo.Renovacao(None, chave_recusada=True)

    monkeypatch.setattr(catalogo, "obter", obter)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2)]
    instancia = _rodar(jogos, flush_idle)
    assert instancia._running is False
    assert _avisos(win) == [
        "A chave da Steam Web API foi recusada. Verifique-a nas Preferências."
    ]


def test_entregar_catalogo_nao_levanta_no_laco_principal(store, make_game, win):
    game = _registrado(store, make_game, 1, steam_appid="570")
    win.active_game = game

    def estoura(_game):
        raise RuntimeError("widget morto")

    win.update_conquistas_block = estoura
    resultado = varredura.Catalogacao(game, "570", mudou=True)
    assert VarreduraConquistas()._entregar_catalogo(resultado) is False


def test_chave_recusada_poupa_o_schema_dos_jogos_seguintes(
    store, make_game, pastas, flush_idle, monkeypatch
):
    chamadas = []

    def obter(appid, _exe, rede=True, usar_chave=True):
        chamadas.append((appid, usar_chave))
        return catalogo.Renovacao(None, chave_recusada=usar_chave)

    monkeypatch.setattr(catalogo, "obter", obter)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert chamadas == [("1", True), ("2", False), ("3", False)]


def test_tres_jogos_com_chave_recusada_um_pedido_e_um_aviso(
    store, make_game, pastas, win, flush_idle, monkeypatch, schema
):
    pedidos = []

    def pedir(url):
        pedidos.append(url)
        if len(pedidos) > 1:
            raise AssertionError(f"pedido depois da chave recusada: {url}")
        raise catalogo.ChaveRecusada()

    schema.set_string("conquistas-chave-steam", "ruim")
    monkeypatch.setattr(catalogo, "obter", _OBTER_REAL)
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [])
    monkeypatch.setattr(catalogo, "_pedir", pedir)
    jogos = [_da_steam_aberta(store, make_game, n) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert len(pedidos) == 1 and "GetSchemaForGame" in pedidos[0]
    assert _avisos(win) == [
        "A chave da Steam Web API foi recusada. Verifique-a nas Preferências."
    ]
    # Os três ficam com o "nenhum" guardado: a próxima abertura não pergunta.
    assert all(catalogo.em_cache(str(n)) is not None for n in (1, 2, 3))


# -- Conquistas antigas que chegam agora (jogo da Steam rodado aqui pela primeira vez) --

ANTERIOR = 1_800_000_000  # início da varredura anterior, guardado no estado
VELHA = ANTERIOR - 365 * 24 * 3600  # ganha um ano antes, em outro aparelho
NOVA = ANTERIOR + 3600  # ganha depois da abertura anterior


def _da_steam(store, make_game, numero, appid="570"):
    game = make_game(
        game_id=f"steam_{numero}",
        name=f"Jogo {numero}",
        steam_appid=appid,
        executable=f"steam://rungameid/{appid}",
    )
    store.add_game(game, {}, run_pipeline=False)
    historico.registrar(game.game_id, [])  # já varrido antes, sem nada
    return game


def test_conquista_antiga_de_jogo_da_steam_nao_conta_no_aviso(
    store, make_game, pastas, win, flush_idle, state_schema
):
    state_schema.set_int64("conquistas-ultima-varredura", ANTERIOR)
    game = _da_steam(store, make_game, 1)
    _goldberg(pastas, "570", [("ACH_A", VELHA), ("ACH_B", VELHA)])
    _rodar([game], flush_idle)
    assert historico.ler(game.game_id) == {"ACH_A": VELHA, "ACH_B": VELHA}
    assert _avisos(win) == []


def test_conquista_depois_da_varredura_anterior_conta(
    store, make_game, pastas, win, flush_idle, state_schema
):
    state_schema.set_int64("conquistas-ultima-varredura", ANTERIOR)
    game = _da_steam(store, make_game, 1)
    _goldberg(pastas, "570", [("ACH_A", VELHA), ("ACH_B", NOVA), ("ACH_C", 0)])
    _rodar([game], flush_idle)
    assert set(historico.ler(game.game_id)) == {"ACH_A", "ACH_B", "ACH_C"}
    # A nova e a sem data contam; a de um ano antes, não.
    assert _avisos(win) == ["2 novas conquistas em Jogo 1"]


def test_dentro_da_margem_conta(store, make_game, pastas, win, flush_idle, state_schema):
    state_schema.set_int64("conquistas-ultima-varredura", ANTERIOR)
    game = _da_steam(store, make_game, 1)
    _goldberg(pastas, "570", [("ACH_A", ANTERIOR - 60)])
    _rodar([game], flush_idle)
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]


def test_jogo_fora_da_steam_com_data_antiga_conta_como_antes(
    store, make_game, pastas, win, flush_idle, state_schema
):
    state_schema.set_int64("conquistas-ultima-varredura", ANTERIOR)
    game = _registrado(store, make_game, 1, steam_appid="570")
    historico.registrar(game.game_id, [])
    _goldberg(pastas, "570", [("ACH_A", VELHA)])
    _rodar([game], flush_idle)
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]


def test_sem_varredura_anterior_registrada_conta(store, make_game, pastas, win, flush_idle):
    game = _da_steam(store, make_game, 1)
    _goldberg(pastas, "570", [("ACH_A", VELHA)])
    _rodar([game], flush_idle)
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]


def test_varredura_completa_guarda_quando_comecou(
    store, make_game, pastas, flush_idle, state_schema, monkeypatch
):
    monkeypatch.setattr(varredura.time, "time", lambda: ANTERIOR + 99.7)
    game = _da_steam(store, make_game, 1)
    _rodar([game], flush_idle)
    assert state_schema.get_int64("conquistas-ultima-varredura") == ANTERIOR + 99


def test_varredura_interrompida_nao_guarda(store, make_game, pastas, flush_idle, state_schema):
    game = _da_steam(store, make_game, 1)
    instancia = VarreduraConquistas()
    instancia.stop()  # para antes de ler qualquer arquivo
    instancia._worker([game], instancia._generation)
    flush_idle()
    assert state_schema.get_int64("conquistas-ultima-varredura") == 0


def test_varredura_de_um_jogo_nao_guarda(store, make_game, pastas, flush_idle, state_schema):
    game = _da_steam(store, make_game, 1)
    instancia = VarreduraConquistas()
    instancia._worker([game], instancia._generation, False)
    flush_idle()
    assert state_schema.get_int64("conquistas-ultima-varredura") == 0


# -- As fontes e o Xbox ----------------------------------------------------------

_AUMID = 'start "" "shell:AppsFolder\\Pkg.Jogo_abc!Game"'


@pytest.fixture
def xbox(monkeypatch):
    """Conta conectada e uma API falsa que devolve o que o teste puser em `estado`."""
    from cartridges.conquistas.xbox import api, conta  # noqa: PLC0415

    estado = SimpleNamespace(desbloqueios=[], titulo="7", falha=None, chamadas=0, xuid="111")
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "xuid", lambda: estado.xuid)
    monkeypatch.setattr(api, "titulo_local", lambda pfn, bases: None)
    monkeypatch.setattr(api, "titulo", lambda pfn, bases: estado.titulo)

    def ler(titulo):
        estado.chamadas += 1
        if estado.falha is not None:
            raise estado.falha
        cat = catalogo.Catalogo(
            tuple(catalogo.ConquistaInfo(f"XBOX:{n}", "T", "", "", "", False) for n in range(1, 4)), 0, False
        )
        catalogo.guardar(f"xbox-{titulo}", cat)
        return api.Leitura(cat, list(estado.desbloqueios))

    monkeypatch.setattr(api, "ler", ler)
    return estado


def test_varredura_grava_a_fonte_steam(store, make_game, pastas, flush_idle):
    _goldberg(pastas, "570", [("ACH_A", 100)])
    game = _registrado(store, make_game, 1, steam_appid="570")
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) == "steam:570"


def test_varrer_jogo_mantem_o_cartao_do_jogo_da_steam(store, make_game, pastas, flush_idle, monkeypatch):
    from cartridges.conquistas import fontes  # noqa: PLC0415

    class Sincrona(_ThreadFalsa):
        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(varredura.threading, "Thread", Sincrona)
    game = _da_steam(store, make_game, 1)
    VarreduraConquistas().varrer_jogo(game)
    flush_idle()
    assert fontes.gravada(game) == fontes.Fonte("steam", "570")


def test_sem_fonte_esquece_a_gravada(store, make_game, pastas, flush_idle):
    game = _registrado(store, make_game, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("A", 1)], fonte="steam:570")
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) is None
    assert historico.ler(game.game_id) == {"A": 1}


def test_sem_fonte_nao_renova_catalogo_da_steam(store, make_game, pastas, flush_idle, monkeypatch):
    chamadas = []

    def obter(appid, _exe, rede=True, usar_chave=True):
        chamadas.append(appid)
        return catalogo.Renovacao(None)

    monkeypatch.setattr(catalogo, "obter", obter)
    game = _registrado(store, make_game, 1, steam_appid="570")
    _rodar([game], flush_idle)
    assert chamadas == []


def test_jogo_do_xbox_entra_e_grava_a_fonte(store, make_game, pastas, flush_idle, xbox):
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100)]
    game = _registrado(store, make_game, 1, executable=_AUMID)
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) == "xbox:7"
    assert historico.ler(game.game_id) == {"XBOX:1": 100}


def test_fonte_pendente_do_xbox_nunca_e_gravada(store, make_game, pastas, flush_idle, xbox):
    from cartridges.conquistas.xbox import api  # noqa: PLC0415

    xbox.falha = api.FalhaDeRede()
    game = _registrado(store, make_game, 1, executable=_AUMID)
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) is None


def test_primeira_leitura_do_xbox_nao_avisa(store, make_game, pastas, win, flush_idle, xbox):
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100), Desbloqueio("XBOX:2", 200)]
    game = _registrado(store, make_game, 1, executable=_AUMID)
    historico.registrar(game.game_id, [Desbloqueio("ACH_STEAM", 5)])  # já havia histórico, de outra fonte
    _rodar([game], flush_idle)
    assert _avisos(win) == []


def test_xbox_novas_desde_a_ultima_abertura_avisam(store, make_game, pastas, win, flush_idle, xbox):
    game = _registrado(store, make_game, 1, executable=_AUMID)
    historico.registrar(game.game_id, [Desbloqueio("XBOX:1", 100)], fonte="xbox:7", conta="111")
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100), Desbloqueio("XBOX:2", 200)]
    _rodar([game], flush_idle)
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]


def test_aviso_do_xbox_soma_os_jogos_num_so(store, make_game, pastas, win, flush_idle, xbox):
    jogos = [_registrado(store, make_game, n, executable=_AUMID.replace("Jogo", f"J{n}")) for n in (1, 2)]
    for jogo in jogos:
        historico.registrar(jogo.game_id, [], fonte="xbox:7", conta="111")
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100)]
    _rodar(jogos, flush_idle)
    assert _avisos(win) == ["2 novas conquistas em 2 jogos"]


def test_varredura_de_um_jogo_do_xbox_fica_calada(store, make_game, pastas, win, flush_idle, xbox):
    game = _registrado(store, make_game, 1, executable=_AUMID)
    historico.registrar(game.game_id, [], fonte="xbox:7", conta="111")
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100)]
    instancia = VarreduraConquistas()
    instancia._worker([game], instancia._generation, False)
    flush_idle()
    assert historico.ler(game.game_id) == {"XBOX:1": 100}
    assert _avisos(win) == []


def test_reconectar_nao_avisa_o_que_ja_existia(store, make_game, pastas, win, flush_idle, xbox, monkeypatch):
    from cartridges.conquistas.xbox import conta  # noqa: PLC0415

    game = _registrado(store, make_game, 1, executable=_AUMID)
    historico.registrar(game.game_id, [Desbloqueio("XBOX:1", 100)], fonte="xbox:7", conta="111")
    monkeypatch.setattr(conta, "conectada", lambda: False)
    _rodar([game], flush_idle)  # desconectado: a fonte é esquecida
    assert historico.fonte(game.game_id) is None
    monkeypatch.setattr(conta, "conectada", lambda: True)
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100), Desbloqueio("XBOX:2", 200)]
    _rodar([game], flush_idle)
    assert _avisos(win) == []
    assert "XBOX:2" in historico.ler(game.game_id)


def test_outra_conta_nao_avisa_o_que_a_nova_ja_tinha(
    store, make_game, pastas, win, flush_idle, xbox
):
    """A conta A cai e o usuário entra com a B, que já tinha conquistas que a A não tinha:
    a fonte (`xbox:<titleId>`) é a mesma, mas a conta não: é a primeira leitura da B."""
    game = _registrado(store, make_game, 1, executable=_AUMID)
    historico.registrar(game.game_id, [Desbloqueio("XBOX:1", 100)], fonte="xbox:7", conta="AAA")
    xbox.xuid = "BBB"
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100), Desbloqueio("XBOX:2", 200)]
    _rodar([game], flush_idle)
    assert _avisos(win) == []
    assert historico.conta(game.game_id) == "BBB"
    assert "XBOX:2" in historico.ler(game.game_id)
    # Na leitura seguinte já é a conta B: o que entrar de novo avisa.
    xbox.desbloqueios.append(Desbloqueio("XBOX:3", 300))
    _rodar([game], flush_idle)
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]


def test_xbox_sem_conta_gravada_conta_como_primeira_leitura(
    store, make_game, pastas, win, flush_idle, xbox
):
    game = _registrado(store, make_game, 1, executable=_AUMID)
    historico.registrar(game.game_id, [Desbloqueio("XBOX:1", 100)], fonte="xbox:7")
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100), Desbloqueio("XBOX:2", 200)]
    _rodar([game], flush_idle)
    assert _avisos(win) == []
    assert historico.conta(game.game_id) == "111"


def test_varredura_do_xbox_grava_a_conta_com_a_fonte(store, make_game, pastas, flush_idle, xbox):
    game = _registrado(store, make_game, 1, executable=_AUMID)
    _rodar([game], flush_idle)
    assert historico.conta(game.game_id) == "111"


def test_rede_fora_no_xbox_para_os_outros(store, make_game, pastas, flush_idle, xbox):
    from cartridges.conquistas.xbox import api  # noqa: PLC0415

    xbox.falha = api.FalhaDeRede()
    jogos = [_registrado(store, make_game, n, executable=_AUMID.replace("Jogo", f"J{n}")) for n in (1, 2)]
    _rodar(jogos, flush_idle)
    assert xbox.chamadas == 1


def test_rede_fora_no_xbox_poupa_tambem_a_steam(store, make_game, pastas, flush_idle, xbox, monkeypatch):
    from cartridges.conquistas.xbox import api  # noqa: PLC0415

    chamadas = []

    def obter(appid, _exe, rede=True, usar_chave=True):
        chamadas.append((appid, rede))
        return catalogo.Renovacao(None)

    monkeypatch.setattr(catalogo, "obter", obter)
    xbox.falha = api.FalhaDeRede()
    _goldberg(pastas, "570", [("ACH_A", 1)])
    jogos = [
        _registrado(store, make_game, 1, executable=_AUMID),
        _registrado(store, make_game, 2, steam_appid="570"),
    ]
    _rodar(jogos, flush_idle)
    assert chamadas == [("570", False)]


def test_conta_caida_no_meio_pula_os_outros_xbox(store, make_game, pastas, flush_idle, xbox, monkeypatch):
    from cartridges.conquistas.xbox import api, conta  # noqa: PLC0415

    estado = {"conectada": True}
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])

    def ler(_titulo):
        xbox.chamadas += 1
        estado["conectada"] = False
        return None

    monkeypatch.setattr(api, "ler", ler)
    jogos = [_registrado(store, make_game, n, executable=_AUMID.replace("Jogo", f"J{n}")) for n in (1, 2)]
    _rodar(jogos, flush_idle)
    assert xbox.chamadas == 1


def test_pacote_sem_xbox_live_nao_vira_fonte(store, make_game, pastas, flush_idle, xbox):
    xbox.titulo = ""
    game = _registrado(store, make_game, 1, executable=_AUMID)
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) is None
    assert xbox.chamadas == 0


def test_xbox_sem_conquistas_grava_a_fonte(store, make_game, pastas, flush_idle, xbox, monkeypatch):
    from cartridges.conquistas.xbox import api  # noqa: PLC0415

    monkeypatch.setattr(api, "ler", lambda titulo: api.Leitura(catalogo.Catalogo((), 0, False), []))
    game = _registrado(store, make_game, 1, executable=_AUMID)
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) == "xbox:7"


def test_xbox_durante_a_sessao_fica_para_o_vigia(store, make_game, pastas, flush_idle, xbox, monkeypatch):
    monkeypatch.setattr(sessao, "acompanhando", lambda g: True)
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100)]
    game = _registrado(store, make_game, 1, executable=_AUMID)
    _rodar([game], flush_idle)
    assert historico.ler(game.game_id) is None


def test_xbox_de_jogo_excluido_no_meio_nao_grava(store, make_game, pastas, flush_idle, xbox):
    game = _registrado(store, make_game, 1, executable=_AUMID)
    leitura, falhou = varredura.ler_da_conta(game, varredura.Fonte("xbox", ""))
    assert falhou is False and leitura.fonte.texto == "xbox:7"
    store.excluir(game)
    assert VarreduraConquistas()._entregar_da_conta(leitura) is False
    assert historico.ler(game.game_id) is None


def test_xbox_desconectado_no_meio_nao_grava(store, make_game, pastas, flush_idle, xbox, monkeypatch):
    from cartridges.conquistas.xbox import conta  # noqa: PLC0415

    game = _registrado(store, make_game, 1, executable=_AUMID)
    leitura, _ = varredura.ler_da_conta(game, varredura.Fonte("xbox", ""))
    monkeypatch.setattr(conta, "conectada", lambda: False)
    VarreduraConquistas()._entregar_da_conta(leitura)
    assert historico.ler(game.game_id) is None


def test_entregar_xbox_nao_levanta(store, make_game, pastas, xbox, monkeypatch):
    game = _registrado(store, make_game, 1, executable=_AUMID)
    leitura, _ = varredura.ler_da_conta(game, varredura.Fonte("xbox", "7"))

    def estoura(*_args, **_kwargs):
        raise OSError("disco cheio")

    monkeypatch.setattr(historico, "registrar", estoura)
    assert VarreduraConquistas()._entregar_da_conta(leitura) is False


def test_concluir_xbox_nao_levanta_e_zera_a_lista(monkeypatch):
    instancia = VarreduraConquistas()
    instancia._novas_da_conta = [("Jogo 1", 2)]

    def estoura(_texto):
        raise RuntimeError("sem janela")

    monkeypatch.setattr(varredura, "_aviso", estoura)
    assert instancia._concluir_da_conta() is False
    assert instancia._novas_da_conta == []


def test_ler_xbox_titulo_pendente_sem_xbox_live_e_nada(store, make_game, xbox):
    game = _registrado(store, make_game, 1, executable=_AUMID)
    xbox.titulo = ""
    assert varredura.ler_da_conta(game, varredura.Fonte("xbox", "")) == (None, False)


def test_ler_xbox_sem_rede(store, make_game, xbox):
    from cartridges.conquistas.xbox import api  # noqa: PLC0415

    game = _registrado(store, make_game, 1, executable=_AUMID)
    xbox.falha = api.FalhaDeRede()
    assert varredura.ler_da_conta(game, varredura.Fonte("xbox", "7")) == (None, True)


def test_pagina_aberta_atualiza_quando_a_fonte_muda(store, make_game, pastas, win, flush_idle):
    _goldberg(pastas, "570", [])
    game = _registrado(store, make_game, 1, steam_appid="570")
    chamadas = _janela_com_jogo_aberto(win, game)
    _rodar([game], flush_idle)
    assert chamadas == [game]


def test_executavel_editado_entre_a_leitura_e_a_entrega_descarta_a_leitura(
    store, make_game, pastas, win, flush_idle, xbox
):
    game = _registrado(store, make_game, 1, executable=_AUMID)
    historico.registrar(game.game_id, [Desbloqueio("ACH_STEAM", 5)], fonte="steam:570")
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100)]
    leitura, _ = varredura.ler_da_conta(game, varredura.Fonte("xbox", "7"))
    game.executable = "steam://rungameid/570"
    assert VarreduraConquistas()._entregar_da_conta(leitura) is False
    flush_idle()
    assert historico.ler(game.game_id) == {"ACH_STEAM": 5}
    assert historico.fonte(game.game_id) == "steam:570"
    assert _avisos(win) == []


def test_executavel_editado_durante_a_leitura_da_conta_nao_grava(
    store, make_game, pastas, win, flush_idle, xbox, monkeypatch
):
    from cartridges.conquistas.xbox import api  # noqa: PLC0415

    game = _registrado(store, make_game, 1, executable=_AUMID)
    ler_falso = api.ler

    def ler(titulo):
        game.executable = _AUMID.replace("Jogo", "Outro")  # o usuário edita enquanto a thread espera a rede
        return ler_falso(titulo)

    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100)]
    monkeypatch.setattr(api, "ler", ler)
    _rodar([game], flush_idle)
    assert historico.ler(game.game_id) is None
    assert historico.fonte(game.game_id) is None
    assert _avisos(win) == []


# -- A Epic -----------------------------------------------------------------------

_URL_EPIC = 'start "" "com.epicgames.launcher://apps/ns1%3Aitem%3ASugar?action=launch&silent=true"'


@pytest.fixture
def epic(monkeypatch):
    """Conta Epic conectada e uma API falsa que devolve o que o teste puser em `estado`."""
    from cartridges.conquistas.epic import api, conta  # noqa: PLC0415

    estado = SimpleNamespace(desbloqueios=[], falha=None, chamadas=0, conta="c1", biblioteca="ns9")
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "account_id", lambda: estado.conta)
    monkeypatch.setattr(api, "namespace_local_do_app", lambda app: None)
    monkeypatch.setattr(api, "namespace_do_app", lambda app: estado.biblioteca)

    def ler(ns):
        estado.chamadas += 1
        if estado.falha is not None:
            raise estado.falha
        cat = catalogo.Catalogo(
            tuple(catalogo.ConquistaInfo(f"EPIC:{n}", "T", "", "", "", False) for n in range(1, 4)), 0, False
        )
        catalogo.guardar(f"epic-{ns}", cat)
        return api.Leitura(cat, list(estado.desbloqueios))

    monkeypatch.setattr(api, "ler", ler)
    return estado


def test_jogo_da_epic_entra_e_grava_fonte_e_conta(store, make_game, pastas, flush_idle, epic):
    epic.desbloqueios = [Desbloqueio("EPIC:1", 100)]
    game = _registrado(store, make_game, 1, executable=_URL_EPIC)
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) == "epic:ns1"
    assert historico.conta(game.game_id) == "c1"
    assert historico.ler(game.game_id) == {"EPIC:1": 100}


def test_primeira_leitura_da_epic_nao_avisa(store, make_game, pastas, win, flush_idle, epic):
    epic.desbloqueios = [Desbloqueio("EPIC:1", 100), Desbloqueio("EPIC:2", 200)]
    game = _registrado(store, make_game, 1, executable=_URL_EPIC)
    _rodar([game], flush_idle)
    assert _avisos(win) == []


def test_epic_novas_desde_a_ultima_abertura_avisam(store, make_game, pastas, win, flush_idle, epic):
    game = _registrado(store, make_game, 1, executable=_URL_EPIC)
    historico.registrar(game.game_id, [Desbloqueio("EPIC:1", 100)], fonte="epic:ns1", conta="c1")
    epic.desbloqueios = [Desbloqueio("EPIC:1", 100), Desbloqueio("EPIC:2", 200)]
    _rodar([game], flush_idle)
    assert _avisos(win) == ["1 nova conquista em Jogo 1"]


def test_aviso_soma_xbox_e_epic_num_so(store, make_game, pastas, win, flush_idle, xbox, epic):
    jogo_x = _registrado(store, make_game, 1, executable=_AUMID)
    jogo_e = _registrado(store, make_game, 2, executable=_URL_EPIC)
    historico.registrar(jogo_x.game_id, [], fonte="xbox:7", conta="111")
    historico.registrar(jogo_e.game_id, [], fonte="epic:ns1", conta="c1")
    xbox.desbloqueios = [Desbloqueio("XBOX:1", 100)]
    epic.desbloqueios = [Desbloqueio("EPIC:1", 100)]
    _rodar([jogo_x, jogo_e], flush_idle)
    assert _avisos(win) == ["2 novas conquistas em 2 jogos"]


def test_pendente_da_epic_resolvido_na_rede(store, make_game, pastas, flush_idle, epic):
    game = _registrado(store, make_game, 1, executable='start "" "com.epicgames.launcher://apps/Sugar?action=launch"')
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) == "epic:ns9"


def test_pendente_fora_da_biblioteca_fica_sem_fonte(store, make_game, pastas, flush_idle, epic):
    epic.biblioteca = ""
    game = _registrado(store, make_game, 1, executable='start "" "com.epicgames.launcher://apps/Sugar?action=launch"')
    _rodar([game], flush_idle)
    assert historico.fonte(game.game_id) is None and epic.chamadas == 0


def test_rede_fora_na_epic_para_os_outros(store, make_game, pastas, flush_idle, epic):
    from cartridges.conquistas.epic import api  # noqa: PLC0415

    jogos = [_registrado(store, make_game, n, executable=_URL_EPIC) for n in (1, 2)]
    epic.falha = api.FalhaDeRede()
    _rodar(jogos, flush_idle)
    assert epic.chamadas == 1


def test_epic_sem_conta_nao_vai_a_rede_e_fica_oculta(store, make_game, pastas, flush_idle, epic, monkeypatch):
    from cartridges.conquistas.epic import conta  # noqa: PLC0415

    monkeypatch.setattr(conta, "conectada", lambda: False)
    game = _registrado(store, make_game, 1, executable=_URL_EPIC, steam_appid="570")
    _rodar([game], flush_idle)
    assert epic.chamadas == 0 and historico.fonte(game.game_id) is None


def test_outra_conta_epic_e_primeira_leitura(store, make_game, pastas, win, flush_idle, epic):
    game = _registrado(store, make_game, 1, executable=_URL_EPIC)
    historico.registrar(game.game_id, [Desbloqueio("EPIC:1", 100)], fonte="epic:ns1", conta="c1")
    epic.conta = "c2"
    epic.desbloqueios = [Desbloqueio("EPIC:1", 100), Desbloqueio("EPIC:2", 200)]
    _rodar([game], flush_idle)
    assert _avisos(win) == [] and historico.conta(game.game_id) == "c2"
