# test_emuladores_play.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A conferência dos .ini a cada play: aplica o idioma e o nome antes de o jogo abrir."""

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from kyron import jogo as modulo
from kyron.emuladores import aplicacao, varredura
from kyron.jogo import Jogo
from kyron.ponte import Ponte


def _pasta(tmp_path, nome="Jogo") -> Path:
    pasta = tmp_path / nome
    pasta.mkdir()
    (pasta / "j.exe").write_bytes(b"")
    (pasta / "steam_emu.ini").write_bytes(b"[Settings]\r\nAppId=620\r\nUserName=Velho\r\n")
    return pasta


def _jogo(pasta: Path, **campos) -> Jogo:
    dados = {"game_id": "shortcuts_1", "source": "shortcuts", "name": "Portal", "executable": str(pasta / "j.exe"), "added": 0}
    return Jogo({**dados, **campos})


class _ThreadNaHora:
    """A thread da conferência roda inteira no `start`: os pedidos à principal ficam em `fila` para o teste soltar."""

    def __init__(self, target, **_k):
        self._alvo = target

    def start(self):
        self._alvo()


def _threading(thread) -> SimpleNamespace:
    """O módulo `threading` do `jogo` com a `Thread` trocada; o `Jogo.__del__` ainda pergunta em que thread está."""
    return SimpleNamespace(Thread=thread, current_thread=threading.current_thread, main_thread=threading.main_thread)


@pytest.fixture
def play(monkeypatch, schema):
    schema.set_string("nome-do-jogador", "Fulano")
    executados, fila = [], []
    monkeypatch.setattr(modulo, "run_executable", lambda *a: executados.append(a))
    monkeypatch.setattr(modulo, "threading", _threading(_ThreadNaHora))
    monkeypatch.setattr(modulo, "na_thread_principal", lambda f, *a: fila.append((f, a)))
    monkeypatch.setattr(Jogo, "save", lambda self: None)
    monkeypatch.setattr(varredura, "_despachar", lambda jogos: None)  # sem refresh de metadados nem ligação

    def soltar():
        while fila:
            f, a = fila.pop(0)
            f(*a)

    return executados, fila, soltar


def _um(fila):
    f, a = fila.pop(0)
    f(*a)


def _contar(sinal) -> list:
    emitidos = []
    sinal.connect(lambda *a: emitidos.append(a), Qt.ConnectionType.DirectConnection)
    return emitidos


def test_sem_nada_a_aplicar_abre_direto(monkeypatch, tmp_path):
    executados = []
    monkeypatch.setattr(modulo, "run_executable", lambda *a: executados.append(a))
    jogo = _jogo(_pasta(tmp_path))
    assert jogo.launch() is True  # na hora, sem thread
    assert len(executados) == 1


def test_inis_presentes_aplica_e_lanca_uma_vez(play, tmp_path):
    executados, fila, soltar = play
    pasta = _pasta(tmp_path)
    jogo = _jogo(pasta, inis=[str(pasta / "steam_emu.ini")])
    pedidos = _contar(jogo.procurando_inis)

    assert jogo.launch() is False
    assert executados == [] and b"UserName=Fulano\r\n" in (pasta / "steam_emu.ini").read_bytes()
    soltar()
    assert len(executados) == 1 and pedidos == []


def test_faltando_procura_e_lanca_ao_terminar(play, tmp_path):
    executados, fila, soltar = play
    pasta = _pasta(tmp_path)
    jogo = _jogo(pasta)  # inis None: nunca procurado
    pedidos, terminados = _contar(jogo.procurando_inis), _contar(jogo.inis_procurados)

    assert jogo.launch() is False
    _um(fila)  # "procurando"
    assert len(pedidos) == 1 and executados == []
    soltar()
    assert jogo.inis == [str(pasta / "steam_emu.ini")]
    assert b"UserName=Fulano" in (pasta / "steam_emu.ini").read_bytes()
    assert len(terminados) == 1 and len(executados) == 1


def test_jogar_mesmo_assim_lanca_uma_vez_so(play, tmp_path):
    executados, fila, soltar = play
    jogo = _jogo(_pasta(tmp_path))
    pedidos = _contar(jogo.procurando_inis)

    jogo.launch()
    _um(fila)
    jogar_agora, _cancelar = pedidos[0]
    jogar_agora()
    jogar_agora()
    assert len(executados) == 1
    soltar()  # a busca termina depois: não lança de novo
    assert len(executados) == 1


def test_cancelar_nao_lanca(play, tmp_path):
    executados, fila, soltar = play
    jogo = _jogo(_pasta(tmp_path))
    pedidos = _contar(jogo.procurando_inis)

    jogo.launch()
    _um(fila)
    pedidos[0][1]()
    soltar()
    assert executados == []
    assert jogo.inis  # a busca gravou para a próxima vez


def test_duplo_clique_durante_a_conferencia_lanca_uma_vez(play, tmp_path, monkeypatch):
    executados, fila, soltar = play
    jogo = _jogo(_pasta(tmp_path))
    threads = []
    monkeypatch.setattr(modulo, "threading", _threading(lambda target, **_k: threads.append(target) or _ThreadNaHora(target)))

    assert jogo.launch() is False
    assert jogo.launch() is False
    soltar()
    assert len(threads) == 1 and len(executados) == 1


def test_sem_pasta_lanca_sem_dialogo(play, tmp_path):
    executados, fila, soltar = play
    jogo = Jogo({"game_id": "a", "source": "steam", "name": "S", "executable": "steam://rungameid/620", "added": 0})
    pedidos = _contar(jogo.procurando_inis)
    jogo.launch()
    soltar()
    assert pedidos == [] and len(executados) == 1


def test_erro_na_conferencia_nao_impede_o_jogo(play, tmp_path, monkeypatch):
    executados, fila, soltar = play
    monkeypatch.setattr(aplicacao, "aplicar_no_jogo", lambda j: 1 / 0)
    jogo = _jogo(_pasta(tmp_path))
    jogo.launch()
    soltar()
    assert len(executados) == 1


def test_relanca_pelo_ao_confirmar_sem_laco(play, tmp_path):
    """O `ao_confirmar` da Big Picture chama o `launch` de novo: a flag de uso único o deixa passar uma vez."""
    executados, fila, soltar = play
    pasta = _pasta(tmp_path)
    jogo = _jogo(pasta, inis=[str(pasta / "steam_emu.ini")])
    jogo.launch(ao_confirmar=lambda: jogo.launch())
    soltar()
    assert len(executados) == 1
    assert jogo.launch() is False  # a flag foi consumida: o próximo play confere de novo


def test_ponte_mostra_e_fecha_o_dialogo(play, tmp_path, app_qt):
    executados, fila, soltar = play
    ponte, jogo = Ponte(), _jogo(_pasta(tmp_path))
    ponte.ligar(jogo)
    pedidos, fechados = _contar(ponte.preparoPedido), _contar(ponte.preparoTerminou)

    jogo.launch()
    _um(fila)
    assert pedidos == [(
        "Preparando Portal",
        "Procurando os arquivos de configuração do jogo para aplicar o idioma e o nome do jogador.",
    )]
    soltar()
    assert len(fechados) == 1 and len(executados) == 1
    ponte.jogarMesmoAssim()  # resposta tardia: nada
    assert len(executados) == 1


def test_ponte_jogar_mesmo_assim_e_cancelar(play, tmp_path, app_qt):
    executados, fila, soltar = play
    ponte = Ponte()
    a, b = _jogo(_pasta(tmp_path, "A")), _jogo(_pasta(tmp_path, "B"), game_id="shortcuts_2")
    ponte.ligar(a)
    ponte.ligar(b)

    a.launch()
    _um(fila)
    ponte.jogarMesmoAssim()
    assert len(executados) == 1
    soltar()

    b.launch()
    _um(fila)
    ponte.cancelarPreparo()
    soltar()
    assert len(executados) == 1


def test_cancelar_e_jogar_de_novo_reabre_o_preparo(play, tmp_path):
    executados, fila, soltar = play
    jogo = _jogo(_pasta(tmp_path))
    pedidos = _contar(jogo.procurando_inis)

    jogo.launch()
    _um(fila)
    pedidos[0][1]()  # Cancelar
    assert jogo.launch() is False  # o fim ainda está na fila
    assert len(pedidos) == 2
    soltar()
    assert len(executados) == 1


def test_jogar_mesmo_assim_e_jogar_de_novo_reabre_o_preparo(play, tmp_path):
    executados, fila, soltar = play
    jogo = _jogo(_pasta(tmp_path))
    pedidos = _contar(jogo.procurando_inis)

    jogo.launch()
    _um(fila)
    pedidos[0][0]()  # Jogar mesmo assim
    assert len(executados) == 1 and not jogo.inis_conferidos  # a marca não sobra para o próximo play
    jogo.launch()
    assert len(pedidos) == 2
    soltar()
    assert len(executados) == 2  # a rodada nova lança no fim; a antiga não


def test_ponte_ignora_o_preparo_de_outro_jogo(play, tmp_path, app_qt):
    executados, fila, soltar = play
    ponte = Ponte()
    a, b = _jogo(_pasta(tmp_path, "A")), _jogo(_pasta(tmp_path, "B"), game_id="shortcuts_2", name="Outro")
    ponte.ligar(a)
    ponte.ligar(b)
    pedidos = _contar(ponte.preparoPedido)

    a.launch()
    b.launch()
    _um(fila)  # procurando de a
    fila.insert(0, fila.pop(1))  # procurando de b chega com o diálogo de a na tela
    _um(fila)
    assert [p[0] for p in pedidos] == ["Preparando Portal"]
    soltar()
    assert len(executados) == 2  # ninguém decidiu: os dois abrem no fim


def test_procurando_adota_o_appid(play, tmp_path, monkeypatch):
    executados, fila, soltar = play
    despachados = []
    monkeypatch.setattr(varredura, "_despachar", despachados.extend)
    jogo = _jogo(_pasta(tmp_path), steam_appid="10")
    jogo.launch()
    soltar()
    assert jogo.steam_appid == "620" and despachados == [jogo]
    assert len(executados) == 1


def test_falha_na_gravacao_avisa_depois_de_lancar(play, tmp_path, monkeypatch):
    executados, fila, soltar = play
    pasta = _pasta(tmp_path)
    jogo = _jogo(pasta, inis=[str(pasta / "steam_emu.ini")])
    avisos = _contar(jogo.aviso)
    monkeypatch.setattr(aplicacao, "aplicar_no_jogo", lambda j: aplicacao.FALHOU)
    jogo.launch()
    soltar()
    assert len(executados) == 1
    assert avisos[-1] == ("Não foi possível aplicar o idioma e o nome do jogador em Portal.", "")  # depois do "iniciado"


def test_cancelado_e_falhou_nao_avisa(play, tmp_path, monkeypatch):
    executados, fila, soltar = play
    jogo = _jogo(_pasta(tmp_path))
    pedidos, avisos = _contar(jogo.procurando_inis), _contar(jogo.aviso)
    monkeypatch.setattr(varredura, "procurar_jogo", lambda j, **k: aplicacao.FALHOU)
    jogo.launch()
    _um(fila)
    pedidos[0][1]()
    soltar()
    assert executados == [] and avisos == []


def test_play_nao_consulta_a_steam(play, tmp_path, monkeypatch):
    executados, fila, soltar = play
    chamadas = []
    monkeypatch.setattr(varredura, "_buscar_idiomas", chamadas.append)
    jogo = _jogo(_pasta(tmp_path), steam_appid="10")
    jogo.launch()
    soltar()
    assert chamadas == [] and len(executados) == 1


def test_jogo_que_saiu_da_biblioteca_nao_abre(play, tmp_path, store):
    executados, fila, soltar = play
    pasta = _pasta(tmp_path)
    jogo = _jogo(pasta, inis=[str(pasta / "steam_emu.ini")])
    store.add_game(jogo, {}, run_pipeline=False)
    jogo.launch()
    store.games_by_id.pop(jogo.game_id)  # excluído durante a conferência
    soltar()
    assert executados == []


def test_jogo_removido_durante_a_conferencia_nao_abre(play, tmp_path):
    executados, fila, soltar = play
    pasta = _pasta(tmp_path)
    jogo = _jogo(pasta, inis=[str(pasta / "steam_emu.ini")])
    jogo.launch()
    jogo.removed = True
    soltar()
    assert executados == []


def test_gse_sem_configs_user_ini_abre_sem_dialogo_e_cria(play, tmp_path):
    executados, fila, soltar = play
    pasta = tmp_path / "Jogo"
    (pasta / "steam_settings").mkdir(parents=True)
    (pasta / "j.exe").write_bytes(b"")
    gse = pasta / "steam_settings" / "configs.user.ini"
    jogo = _jogo(pasta, inis=[str(gse)])
    pedidos = _contar(jogo.procurando_inis)
    jogo.launch()
    soltar()
    assert pedidos == [] and len(executados) == 1
    assert b"account_name=Fulano" in gse.read_bytes()


def test_conferindo_inis_so_para_o_launch_que_a_comecou(play, tmp_path):
    """Um launch ignorado (Big Picture com a conferência de outro clique em curso) não fica esperando o relançamento."""
    executados, fila, soltar = play
    pasta = _pasta(tmp_path)
    jogo = _jogo(pasta, inis=[str(pasta / "steam_emu.ini")])
    assert jogo.launch() is False and jogo.conferindo_inis is True
    assert jogo.launch() is False and jogo.conferindo_inis is False
    soltar()
    assert len(executados) == 1


def test_jogo_de_loja_abre_direto_sem_conferir(play):
    executados, fila, _soltar = play
    jogo = Jogo({"game_id": "shortcuts_9", "source": "shortcuts", "name": "TF2", "executable": "steam://rungameid/440", "added": 0})
    assert jogo.launch() is True
    assert len(executados) == 1 and not fila
