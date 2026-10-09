# test_saves_backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup dos saves por jogo: nome no Ludusavi, tarefa, aviso de falha e a trava.

O Ludusavi é um executor falso (`LudusaviFalso`); as threads de verdade rodam e o
teste espera por todas (`esperar`) antes de olhar a tela.
"""

import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from cartridges import shared
from cartridges.saves import backup_de_saves, pasta
from cartridges.saves.ludusavi import Versao
from cartridges.utils import tarefas

NAO_ACHADO = {"errors": {"unknownGames": ["x"]}, "games": {}}


class LudusaviFalso:
    """Responde como o `ludusavi.exe`, guarda o que recebeu e mede a concorrência."""

    def __init__(self) -> None:
        self.comandos: list[list[str]] = []
        self.achados: dict[tuple[str, str], str] = {}  # ("appid"|"titulo", valor) -> nome
        self.versoes: dict[str, list[str]] = {}  # nome -> ids, do mais novo ao mais velho
        self.falhas: dict[str, dict] = {}  # comando -> resposta no lugar da normal
        self.codigo_de: dict[str, int] = {}  # comando -> código de saída no lugar do 0
        self.demora = 0.0
        self.explode: Exception | None = None
        self._trava = threading.Lock()
        self.ativos = 0
        self.max_ativos = 0
        self.configs: dict[str, dict | None] = {}  # o config.yaml visto por cada comando

    def __call__(self, args, **kwargs):
        comando = args[args.index("--try-manifest-update") + 1 : -1]
        pasta_config = Path(args[args.index("--config") + 1])
        with self._trava:
            self.comandos.append(comando)
            self.ativos += 1
            self.max_ativos = max(self.max_ativos, self.ativos)
        try:
            if self.explode is not None:
                raise self.explode
            arquivo = pasta_config / "config.yaml"
            self.configs[comando[0]] = json.loads(arquivo.read_text("utf-8")) if arquivo.is_file() else None
            time.sleep(self.demora)
            return self._responder(args, comando)
        finally:
            with self._trava:
                self.ativos -= 1

    def _responder(self, args, comando):
        nome = comando[0]
        if nome in self.falhas:
            saida, codigo = self.falhas[nome], self.codigo_de.get(nome, 0)
        elif nome == "find":
            chave = ("appid", comando[2]) if comando[1] == "--steam-id" else ("titulo", comando[1])
            achado = self.achados.get(chave)
            saida = {"games": {achado: {"score": 1.0}}} if achado else NAO_ACHADO
            codigo = 0 if achado else 1
        elif nome == "backups":
            saida = {
                "games": {
                    jogo: {
                        "backups": [
                            {"name": id_, "when": f"2026-10-0{9 - i}T10:00:00Z"}
                            for i, id_ in enumerate(ids)
                        ]
                    }
                    for jogo, ids in self.versoes.items()
                }
            }
            codigo = 0
        else:
            saida, codigo = {"games": {}}, 0
        return subprocess.CompletedProcess(args, codigo, json.dumps(saida), "")

    def chamou(self, comando: str) -> list[list[str]]:
        return [c for c in self.comandos if c[0] == comando]


@pytest.fixture(autouse=True)
def ambiente(settings, tmp_path, monkeypatch):
    """O `ludusavi.exe` ao lado do Python, GSettings de verdade (a pasta dos saves
    lê dele) e o cache em memória zerado."""
    (tmp_path / "ludusavi.exe").touch()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr(backup_de_saves, "_cache", {})


@pytest.fixture
def falso(monkeypatch):
    falso = LudusaviFalso()
    monkeypatch.setattr(backup_de_saves, "executor", falso)
    return falso


@pytest.fixture
def esperar(monkeypatch, flush_idle):
    """Registra cada thread que o módulo cria; chamar espera todas e esvazia a fila da tela."""
    criadas: list[threading.Thread] = []
    original = threading.Thread

    class Registrada(original):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            criadas.append(self)

    monkeypatch.setattr(backup_de_saves.threading, "Thread", Registrada)

    def aguardar():
        for thread in criadas:
            thread.join(10)
            assert not thread.is_alive()
        flush_idle()

    return aguardar


def toasts() -> list:
    return shared.win.toast_queue.added


def na_biblioteca(store, make_game, **campos):
    jogo = make_game(**campos)
    store.add_game(jogo, {})
    return jogo


def test_resolve_por_appid_e_guarda(store, make_game, falso, esperar, tmp_path):
    falso.achados[("appid", "3669870")] = "Nome do Manifesto"
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="3669870")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert jogo.ludusavi_nome == "Nome do Manifesto"
    assert jogo.saves == 1  # gravado pelo caminho normal de salvar
    assert falso.chamou("backup") == [["backup", "Nome do Manifesto", "--force"]]
    entrada = falso.configs["backup"]["customGames"][0]
    assert (entrada["name"], entrada["integration"]) == ("Nome do Manifesto", "extend")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert len(falso.chamou("find")) == 1  # a segunda sessão não procura de novo
    assert len(falso.chamou("backup")) == 2


def test_resolve_por_titulo_sem_appid(store, make_game, falso, esperar, tmp_path):
    falso.achados[("titulo", "Alien: Isolation")] = "Alien: Isolation"
    jogo = na_biblioteca(store, make_game, game_id="a", name="Alien: Isolation")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert jogo.ludusavi_nome == "Alien: Isolation"
    assert falso.chamou("find") == [["find", "Alien: Isolation"]]
    assert falso.chamou("backup") == [["backup", "Alien: Isolation", "--force"]]
    assert falso.configs["backup"]["customGames"] == []  # sem appID não há o que acrescentar


def test_appid_sem_entrada_usa_entrada_propria(store, make_game, falso, esperar, tmp_path):
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo Raro", steam_appid="42")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert [c[:2] for c in falso.chamou("find")] == [["find", "--steam-id"], ["find", "Jogo Raro"]]
    entrada = falso.configs["backup"]["customGames"][0]
    assert (entrada["name"], entrada["integration"]) == ("Jogo Raro", "override")
    assert "<winPublic>/Documents/Steam/RUNE/42" in entrada["files"]
    assert jogo.ludusavi_nome == "Jogo Raro"
    assert falso.chamou("backup") == [["backup", "Jogo Raro", "--force"]]


def test_sem_appid_e_sem_entrada_nao_faz_nada(store, make_game, falso, esperar):
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo Sem Nada")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert falso.chamou("backup") == []
    assert jogo.ludusavi_nome == ""
    assert toasts() == []
    assert tarefas.lista.get_n_items() == 0


def test_falha_vira_toast(store, make_game, falso, esperar):
    falso.falhas["backup"] = {"errors": {"someGamesFailed": True}, "games": {}}
    jogo = na_biblioteca(
        store, make_game, game_id="a", name="Tom & <b>Jerry</b>", steam_appid="7", ludusavi_nome="X"
    )

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert len(toasts()) == 1
    assert toasts()[0].get_title() == "Não foi possível fazer o backup dos saves de Tom & <b>Jerry</b>."
    assert toasts()[0].get_use_markup() is False


def test_pasta_sumiu_vira_toast(store, make_game, falso, esperar, tmp_path):
    shared.schema.set_string("pasta-dos-saves", str(tmp_path / "disco-desconectado" / "saves"))
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert falso.chamou("backup") == []  # não recria a pasta em outro lugar com o histórico perdido
    assert [t.get_title() for t in toasts()] == ["Não foi possível fazer o backup dos saves de Jogo."]
    assert tarefas.lista.get_n_items() == 0


def test_ludusavi_que_explode_vira_toast(store, make_game, falso, esperar):
    falso.explode = OSError("sem permissão")
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert len(toasts()) == 1


def test_sessoes_em_sequencia_nao_se_cruzam(store, make_game, falso, esperar, tmp_path):
    falso.demora = 0.05
    primeiro = na_biblioteca(store, make_game, game_id="a", name="A", steam_appid="1", ludusavi_nome="A")
    segundo = na_biblioteca(store, make_game, game_id="b", name="B", steam_appid="2", ludusavi_nome="B")

    backup_de_saves.no_fim_da_sessao(primeiro)
    backup_de_saves.no_fim_da_sessao(segundo)
    esperar()

    assert len(falso.chamou("backup")) == 2
    assert falso.max_ativos == 1
    assert toasts() == []


def test_tarefa_aparece_e_some(store, make_game, falso, esperar, monkeypatch):
    vistas = []
    comecar = tarefas.comecar
    monkeypatch.setattr(tarefas, "comecar", lambda nome, total: vistas.append((nome, total)) or comecar(nome, total))
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert vistas == [("Backup dos saves de Meu Jogo", 1)]
    assert tarefas.lista.get_n_items() == 0


def test_sem_executavel_nada_roda(store, make_game, falso, esperar, tmp_path):
    (tmp_path / "ludusavi.exe").unlink()
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo", steam_appid="7", ludusavi_nome="X")

    assert backup_de_saves.disponivel() is False
    backup_de_saves.no_fim_da_sessao(jogo)
    backup_de_saves.atualizar_cache()
    backup_de_saves.restaurar(jogo, None)
    backup_de_saves.restaurar_todos()
    esperar()

    assert falso.comandos == []
    assert toasts() == []
    assert tarefas.lista.get_n_items() == 0


def test_o_config_leva_todos_os_jogos_com_nome(store, make_game, falso, esperar, tmp_path):
    na_biblioteca(store, make_game, game_id="a", name="A", steam_appid="1", ludusavi_nome="Nome A")
    na_biblioteca(store, make_game, game_id="r", name="R", steam_appid="2", ludusavi_nome="Nome R", removed=True)
    na_biblioteca(store, make_game, game_id="s", name="S", steam_appid="3")  # ainda sem nome
    atual = na_biblioteca(store, make_game, game_id="c", name="C", steam_appid="4", ludusavi_nome="Nome C")

    backup_de_saves.no_fim_da_sessao(atual)
    esperar()

    nomes = {jogo["name"] for jogo in falso.configs["backup"]["customGames"]}
    assert nomes == {"Nome A", "Nome C"}  # o removido e o sem nome ficam de fora


def test_backup_atualiza_o_cache(store, make_game, falso, esperar):
    falso.versoes["X"] = ["novo", "velho"]
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo", steam_appid="7", ludusavi_nome="X")
    assert backup_de_saves.tem_backup(jogo) is False

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert backup_de_saves.tem_backup(jogo) is True
    assert [v.id for v in backup_de_saves.versoes_do_jogo(jogo)] == ["novo", "velho"]
    assert isinstance(backup_de_saves.versoes_do_jogo(jogo)[0], Versao)


def test_atualizar_cache_grava_o_config_antes(store, make_game, falso, esperar, tmp_path):
    """Sem o config.yaml o Ludusavi leria a pasta de backup padrão dele, não a nossa."""
    falso.versoes["X"] = ["v1"]
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.atualizar_cache()
    esperar()

    assert falso.configs["backups"] is not None
    assert falso.configs["backups"]["backup"]["path"] == str(tmp_path / "saves")
    assert backup_de_saves.tem_backup(jogo) is True


def test_restaurar_uma_versao(store, make_game, falso, esperar, monkeypatch):
    vistas = []
    comecar = tarefas.comecar
    monkeypatch.setattr(tarefas, "comecar", lambda nome, total: vistas.append((nome, total)) or comecar(nome, total))
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.restaurar(jogo, "velho")
    esperar()

    assert falso.chamou("restore") == [["restore", "X", "--force", "--backup", "velho"]]
    assert vistas == [("Restaurando o save de Meu Jogo", 1)]
    assert toasts() == []
    assert tarefas.lista.get_n_items() == 0


def test_restaurar_falha_vira_toast(store, make_game, falso, esperar):
    falso.falhas["restore"] = {"errors": {"someGamesFailed": True}, "games": {}}
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.restaurar(jogo, None)
    esperar()

    assert [t.get_title() for t in toasts()] == ["Não foi possível restaurar o save de Meu Jogo."]
    assert toasts()[0].get_use_markup() is False


def test_restaurar_todos_so_os_da_biblioteca(store, make_game, falso, esperar, monkeypatch):
    vistas = []
    comecar = tarefas.comecar
    monkeypatch.setattr(tarefas, "comecar", lambda nome, total: vistas.append((nome, total)) or comecar(nome, total))
    falso.versoes = {"A": ["v1"], "Z": ["v1"]}
    na_biblioteca(store, make_game, game_id="a", name="A", steam_appid="1", ludusavi_nome="A")
    na_biblioteca(store, make_game, game_id="b", name="B", steam_appid="2", ludusavi_nome="B")  # sem backup

    backup_de_saves.restaurar_todos()
    esperar()

    assert falso.chamou("restore") == [["restore", "A", "--force"]]
    assert vistas == [("Restaurando os saves", 1)]
    assert toasts() == []
    assert tarefas.lista.get_n_items() == 0


def test_restaurar_todos_sem_conseguir_ler_os_backups_avisa_uma_vez(store, make_game, falso, esperar):
    falso.falhas["backups"] = {}  # saída vazia: o Ludusavi não devolveu nada útil
    falso.codigo_de["backups"] = 1
    na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")

    backup_de_saves.restaurar_todos()
    esperar()

    assert falso.chamou("restore") == []
    assert [t.get_title() for t in toasts()] == ["Não foi possível restaurar os saves."]
    assert toasts()[0].get_use_markup() is False
    assert tarefas.lista.get_n_items() == 0


def test_restaurar_todos_relê_o_cache_no_fim(store, make_game, falso, esperar):
    falso.versoes = {"A": ["v1"]}
    na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")

    backup_de_saves.restaurar_todos()
    esperar()

    assert [c[0] for c in falso.comandos].count("backups") == 2  # antes e depois


def test_restaurar_todos_avisa_de_cada_falha_e_segue(store, make_game, falso, esperar):
    falso.versoes = {"A": ["v1"], "B": ["v1"]}
    na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")
    na_biblioteca(store, make_game, game_id="b", name="Jogo B", steam_appid="2", ludusavi_nome="B")
    falso.falhas["restore"] = {"errors": {"someGamesFailed": True}, "games": {}}

    backup_de_saves.restaurar_todos()
    esperar()

    assert len(falso.chamou("restore")) == 2
    assert sorted(t.get_title() for t in toasts()) == [
        "Não foi possível restaurar o save de Jogo A.",
        "Não foi possível restaurar o save de Jogo B.",
    ]


def test_trocar_pasta_segura_a_trava(store, falso, esperar, monkeypatch, tmp_path):
    visto = []
    monkeypatch.setattr(pasta, "trocar", lambda nova: visto.append((nova, backup_de_saves._trava.locked())))

    backup_de_saves.trocar_pasta(tmp_path / "nova")
    esperar()

    assert visto == [(tmp_path / "nova", True)]
    assert not backup_de_saves._trava.locked()
    assert falso.chamou("backups")  # o cache é relido depois da troca


def test_trocar_pasta_recusada_solta_a_trava_e_avisa_quem_chamou(store, falso, tmp_path):
    with pytest.raises(pasta.TrocaRecusada):
        backup_de_saves.trocar_pasta(pasta.atual())
    assert not backup_de_saves._trava.locked()
