"""A varredura de abertura: grava o histórico e avisa do que é novo."""

import json

import pytest

from cartridges.conquistas import catalogo, historico, varredura
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


def _registrado(store, make_game, numero, **campos):
    game = make_game(game_id=f"shortcuts_{numero}", name=f"Jogo {numero}", executable="", **campos)
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


def test_chave_recusada_avisa_uma_vez(store, make_game, pastas, win, flush_idle, monkeypatch):
    monkeypatch.setattr(
        catalogo, "obter", lambda _appid, _exe, rede=True, usar_chave=True: catalogo.Renovacao(None, chave_recusada=True)
    )
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert _avisos(win).count(
        "A chave da Steam Web API foi recusada. Verifique-a nas Preferências."
    ) == 1


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"steam_appid": "570"}, True),
        ({"steam_appid": "570", "conquistas": False}, False),
        ({}, False),
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
    game = _registrado(store, make_game, 1, steam_appid="570")
    chamadas = _janela_com_jogo_aberto(win, game)
    _rodar([game], flush_idle)
    assert chamadas == [game]


def test_pagina_aberta_nao_atualiza_sem_novidade(store, make_game, pastas, win, flush_idle):
    game = _registrado(store, make_game, 1, steam_appid="570")
    chamadas = _janela_com_jogo_aberto(win, game)
    _rodar([game], flush_idle)
    assert chamadas == []


def test_pagina_de_outro_jogo_nao_atualiza(store, make_game, pastas, win, flush_idle, monkeypatch):
    monkeypatch.setattr(
        catalogo,
        "obter",
        lambda _appid, _exe, rede=True, usar_chave=True: catalogo.Renovacao(catalogo.Catalogo((), 1, False)),
    )
    game = _registrado(store, make_game, 1, steam_appid="570")
    outro = _registrado(store, make_game, 2, steam_appid="620")
    chamadas = _janela_com_jogo_aberto(win, outro)
    _rodar([game], flush_idle)
    assert chamadas == []


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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2)]
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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2)]
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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
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
    jogos = [_registrado(store, make_game, n, steam_appid=str(n)) for n in (1, 2, 3)]
    _rodar(jogos, flush_idle)
    assert len(pedidos) == 1 and "GetSchemaForGame" in pedidos[0]
    assert _avisos(win) == [
        "A chave da Steam Web API foi recusada. Verifique-a nas Preferências."
    ]
    # Os três ficam com o "nenhum" guardado: a próxima abertura não pergunta.
    assert all(catalogo.em_cache(str(n)) is not None for n in (1, 2, 3))
