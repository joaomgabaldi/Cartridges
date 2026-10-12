# test_saves_backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup dos saves por jogo: nome no Ludusavi, tarefa, aviso de falha, a trava e a
restauração segura (versão conferida, cópia dos saves atuais, destinos validados).

O Ludusavi é um executor falso (`LudusaviFalso`); as threads de verdade rodam e o
teste espera por todas (`esperar`) antes de olhar a tela.
"""

import json
import subprocess
import threading
import time
import zipfile
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from cartridges import shared
from cartridges.saves import backup_de_saves, conferencia, pasta
from cartridges.saves.ludusavi import Versao
from cartridges.utils import tarefas

NAO_ACHADO = {"errors": {"unknownGames": ["x"]}, "games": {}}
FALHOU = {"errors": {"someGamesFailed": True}, "games": {}}
# Guardado sem compressão dentro do zip: um byte trocado nele quebra só o CRC.
CONTEUDO = b"dados do save 0123456789"


class LudusaviFalso:
    """Responde como o `ludusavi.exe`, guarda o que recebeu e mede a concorrência."""

    def __init__(self, pasta: Path) -> None:
        self.pasta = pasta  # cada jogo em `<pasta>/<jogo>`, o `backupPath`; cada versão, um zip
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
        self.comentarios: dict[tuple[str, str], str] = {}  # (jogo, id) -> marca
        self.previas: dict[str, dict] = {}  # jogo -> "files" da prévia
        self.registros: dict[str, dict] = {}  # jogo -> "registry" da prévia
        self.cria_versao: dict[str, bool] = {}  # jogo -> o `backup` cria uma versão nova
        self.no_zip: dict[str, list[str]] = {}  # id -> nomes dentro do zip da versão
        self._agora = datetime.now(timezone.utc)
        self._quando: dict[tuple[str, str], datetime] = {}  # as criadas pelo `backup`
        self._zipadas: set[tuple[str, str]] = set()

    def __call__(self, args, **kwargs):
        # O `backups edit` não leva `--api`; os outros, sempre no fim.
        fim = -1 if args[-1] == "--api" else len(args)
        comando = args[args.index("--try-manifest-update") + 1 : fim]
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
        if nome == "backup" and self.cria_versao.get(comando[1]):
            # Antes da falha: com um arquivo travado, o Ludusavi cria a versão mesmo assim.
            nova = f"nova{len(self._quando) + 1}"
            self.versoes.setdefault(comando[1], []).insert(0, nova)
            self._quando[(comando[1], nova)] = datetime.now(timezone.utc)
        if comando[:2] == ["backups", "edit"]:
            self.comentarios[(comando[2], comando[4])] = comando[6]
            return subprocess.CompletedProcess(args, 0, "", "")
        if "--preview" in comando:
            jogo = comando[1]
            arquivos = self.previas.get(jogo, {})
            saida = {"games": {jogo: {"files": arquivos, "registry": self.registros.get(jogo, {})}}}
            codigo = 0
        elif nome in self.falhas:
            saida, codigo = self.falhas[nome], self.codigo_de.get(nome, 0)
        elif nome == "find":
            chave = ("appid", comando[2]) if comando[1] == "--steam-id" else ("titulo", comando[1])
            achado = self.achados.get(chave)
            saida = {"games": {achado: {"score": 1.0}}} if achado else NAO_ACHADO
            codigo = 0 if achado else 1
        elif nome == "backups":
            saida = {"games": {jogo: self._jogo(jogo, ids) for jogo, ids in self.versoes.items()}}
            codigo = 0
        else:
            saida, codigo = {"games": {}}, 0
        return subprocess.CompletedProcess(args, codigo, json.dumps(saida), "")

    def _jogo(self, jogo: str, ids: list[str]) -> dict:
        pasta = self.pasta / jogo
        pasta.mkdir(parents=True, exist_ok=True)
        copias = []
        for i, id_ in enumerate(ids):
            # Uma vez só, quando a versão aparece: o teste pode estragar ou apagar o zip depois.
            if (jogo, id_) not in self._zipadas:
                self._zipadas.add((jogo, id_))
                with zipfile.ZipFile(pasta / id_, "w") as zip_:
                    for dentro in self.no_zip.get(id_, ["drive-C/Jogos/save.sav"]):
                        zip_.writestr(dentro, CONTEUDO)
            # Relativo a agora: a versão que já existia é sempre mais velha que a cópia.
            quando = self._quando.get((jogo, id_), self._agora - timedelta(days=i + 1))
            copias.append(
                {"name": id_, "when": quando.isoformat(), "comment": self.comentarios.get((jogo, id_), "")}
            )
        return {"backupPath": str(pasta), "backups": copias}

    def chamou(self, comando: str) -> list[list[str]]:
        return [c for c in self.comandos if c[0] == comando]

    def restauracoes(self) -> list[list[str]]:
        """Os `restore` de verdade, sem as prévias."""
        return [c for c in self.chamou("restore") if "--preview" not in c]

    def marcas(self) -> list[list[str]]:
        return [c for c in self.chamou("backups") if c[1:2] == ["edit"]]


@pytest.fixture(autouse=True)
def ambiente(settings, tmp_path, monkeypatch, ludusavi_de_verdade):
    """Um `ludusavi.exe` (de mentira) ao lado do Python, GSettings de verdade (a pasta
    dos saves lê dele) e o cache em memória zerado."""
    (tmp_path / "ludusavi.exe").touch()
    monkeypatch.setattr(backup_de_saves, "_cache", {})
    monkeypatch.setattr(backup_de_saves, "_restaurando", Counter())
    monkeypatch.setattr(backup_de_saves, "_jogos_restaurando", Counter())
    monkeypatch.setattr(backup_de_saves, "_restaurando_todos", 0)


@pytest.fixture
def falso(monkeypatch, tmp_path):
    falso = LudusaviFalso(tmp_path / "zips")
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

    yield aguardar
    # Também quando o teste falha antes de chamar `aguardar`: a thread não pode sobreviver
    # ao teste, porque acordaria com o executor falso, o `tmp_path` e o `sys.executable` já desfeitos.
    for thread in criadas:
        thread.join(10)


def toasts() -> list:
    return shared.win.toast_queue.added


def titulos() -> list[str]:
    return [toast.get_title() for toast in toasts()]


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


def _com_manifesto(tmp_path) -> None:
    """O manifesto que o Ludusavi baixa para a pasta de configuração dele."""
    (tmp_path / "ludusavi").mkdir(exist_ok=True)
    (tmp_path / "ludusavi" / "manifest.yaml").write_text("{}", "utf-8")


def test_appid_sem_entrada_usa_entrada_propria(store, make_game, falso, esperar, tmp_path):
    _com_manifesto(tmp_path)
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo Raro", steam_appid="42")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert [c[:2] for c in falso.chamou("find")] == [["find", "--steam-id"], ["find", "Jogo Raro"]]
    entrada = falso.configs["backup"]["customGames"][0]
    assert (entrada["name"], entrada["integration"]) == ("Jogo Raro", "override")
    assert "<winPublic>/Documents/Steam/RUNE/42" in entrada["files"]
    assert jogo.ludusavi_nome == "Jogo Raro"
    assert falso.chamou("backup") == [["backup", "Jogo Raro", "--force"]]


def test_com_manifesto_guarda_a_entrada_propria(store, make_game, falso, esperar, tmp_path):
    _com_manifesto(tmp_path)
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo Raro", steam_appid="42")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert jogo.ludusavi_nome == "Jogo Raro"
    assert falso.chamou("backup") == [["backup", "Jogo Raro", "--force"]]
    assert toasts() == []


def test_sem_manifesto_nao_guarda_o_nome(store, make_game, falso, esperar):
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo Raro", steam_appid="42")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert [c[:2] for c in falso.chamou("find")] == [["find", "--steam-id"], ["find", "Jogo Raro"]]
    assert jogo.ludusavi_nome == ""  # a próxima sessão procura de novo
    assert falso.chamou("backup") == []
    assert titulos() == ["Não foi possível fazer o backup dos saves de Jogo Raro."]
    assert tarefas.lista.get_n_items() == 0


def test_sem_appid_e_sem_entrada_nao_faz_nada(store, make_game, falso, esperar, tmp_path):
    _com_manifesto(tmp_path)  # "fora do manifesto" pressupõe que há um manifesto
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo Sem Nada")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert falso.chamou("backup") == []
    assert jogo.ludusavi_nome == ""
    assert toasts() == []
    assert tarefas.lista.get_n_items() == 0


def test_sem_appid_sem_manifesto_avisa(store, make_game, falso, esperar):
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo Sem Nada")

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert [c[:2] for c in falso.chamou("find")] == [["find", "Jogo Sem Nada"]]
    assert falso.chamou("backup") == []
    assert jogo.ludusavi_nome == ""  # a próxima sessão procura de novo
    assert titulos() == ["Não foi possível fazer o backup dos saves de Jogo Sem Nada."]
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


def test_backup_que_falha_marca_a_versao_nova(store, make_game, falso, esperar):
    falso.falhas["backup"] = FALHOU
    falso.versoes["X"] = ["v1"]
    falso.cria_versao["X"] = True  # o arquivo travado deixa a versão pela metade
    jogo = na_biblioteca(
        store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X"
    )

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert falso.marcas() == [
        ["backups", "edit", "X", "--backup", "nova1", "--comment", "cartridges:incompleta"]
    ]
    assert titulos() == ["Não foi possível fazer o backup dos saves de Meu Jogo."]


def test_backup_que_falha_relê_o_cache(store, make_game, falso, esperar):
    falso.falhas["backup"] = FALHOU
    falso.versoes["X"] = ["v1"]
    falso.cria_versao["X"] = True
    jogo = na_biblioteca(
        store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X"
    )

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    # O diálogo de versões vê a versão incompleta, já marcada, sem esperar outra leitura.
    versoes = backup_de_saves.versoes_do_jogo(jogo)
    assert [v.id for v in versoes] == ["nova1", "v1"]
    assert versoes[0].comentario == "cartridges:incompleta"
    assert titulos() == ["Não foi possível fazer o backup dos saves de Meu Jogo."]


def test_backup_que_falha_sem_versao_nova_nao_marca(store, make_game, falso, esperar):
    falso.falhas["backup"] = FALHOU
    falso.versoes["X"] = ["v1"]  # a boa de antes: nunca leva a marca
    jogo = na_biblioteca(
        store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X"
    )

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert falso.marcas() == []
    assert titulos() == ["Não foi possível fazer o backup dos saves de Meu Jogo."]


def test_falha_antes_do_backup_nao_marca(store, make_game, falso, esperar, tmp_path):
    # Sem a pasta dos saves o Ludusavi nem é chamado: não há versão nova a marcar.
    shared.schema.set_string("pasta-dos-saves", str(tmp_path / "disco-desconectado" / "saves"))
    falso.versoes["X"] = ["v1"]
    jogo = na_biblioteca(
        store, make_game, game_id="a", name="Jogo", steam_appid="7", ludusavi_nome="X"
    )

    backup_de_saves.no_fim_da_sessao(jogo)
    esperar()

    assert falso.marcas() == []
    assert falso.chamou("backups") == []
    assert len(toasts()) == 1


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
    backup_de_saves.restaurar(jogo, "v1")
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
    falso.versoes["X"] = ["novo", "velho"]
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.restaurar(jogo, "velho")
    esperar()

    assert falso.restauracoes() == [["restore", "X", "--force", "--backup", "velho"]]
    assert vistas == [("Restaurando o save de Meu Jogo", 1)]
    assert toasts() == []
    assert tarefas.lista.get_n_items() == 0


def test_restaurar_falha_vira_toast(store, make_game, falso, esperar):
    falso.versoes["X"] = ["v1"]
    falso.falhas["restore"] = FALHOU  # só o `restore` de verdade: a prévia passa
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.restaurar(jogo, "v1")
    esperar()

    assert len(falso.restauracoes()) == 1
    assert titulos() == ["Não foi possível restaurar o save de Meu Jogo."]
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

    assert falso.restauracoes() == [["restore", "A", "--force", "--backup", "v1"]]
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

    assert falso.comandos[0] == ["backups"]  # antes
    assert falso.comandos[-1] == ["backups"]  # e depois


def test_restaurar_todos_segue_depois_de_uma_falha_e_avisa_uma_vez(store, make_game, falso, esperar):
    falso.versoes = {"A": ["v1"], "B": ["v1"]}
    na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")
    na_biblioteca(store, make_game, game_id="b", name="Jogo B", steam_appid="2", ludusavi_nome="B")
    falso.falhas["restore"] = FALHOU

    backup_de_saves.restaurar_todos()
    esperar()

    assert len(falso.restauracoes()) == 2
    assert titulos() == ["Não foi possível restaurar os saves de 2 jogos."]


def test_restaurando_durante_e_depois(store, make_game, falso, esperar):
    falso.versoes["X"] = ["v1"]
    falso.demora = 0.2
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")
    outro = na_biblioteca(store, make_game, game_id="b", name="Outro", steam_appid="8", ludusavi_nome="Y")

    backup_de_saves.restaurar(jogo, "v1")

    assert backup_de_saves.restaurando(jogo) is True
    assert backup_de_saves.restaurando(outro) is False
    esperar()
    assert backup_de_saves.restaurando(jogo) is False


def test_restaurando_se_desfaz_quando_a_restauracao_falha(store, make_game, falso, esperar):
    falso.versoes["X"] = ["v1"]
    falso.explode = RuntimeError("ludusavi quebrou")
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.restaurar(jogo, "v1")
    assert backup_de_saves.restaurando(jogo) is True
    esperar()

    assert backup_de_saves.restaurando(jogo) is False


def test_restaurando_se_desfaz_quando_a_thread_levanta(store, make_game, falso, esperar, monkeypatch):
    def explode(*_args):
        raise RuntimeError("levantou")

    monkeypatch.setattr(threading, "excepthook", lambda _args: None)  # a thread vai morrer de propósito
    monkeypatch.setattr(tarefas, "comecar", explode)
    falso.versoes = {"X": ["v1"]}
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.restaurar(jogo, "v1")
    backup_de_saves.restaurar_todos()
    esperar()

    assert backup_de_saves.restaurando(jogo) is False
    assert not backup_de_saves._trava.locked()


def test_restaurar_todos_bloqueia_todos_mesmo_com_cache_vazio(store, make_game, falso, esperar):
    falso.demora = 0.2
    com_nome = na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")
    sem_nome = na_biblioteca(store, make_game, game_id="b", name="Jogo B", steam_appid="2")
    assert not backup_de_saves._cache

    backup_de_saves.restaurar_todos()

    assert backup_de_saves.restaurando(com_nome) is True
    assert backup_de_saves.restaurando(sem_nome) is False
    esperar()
    assert backup_de_saves.restaurando(com_nome) is False


@pytest.mark.parametrize("quebra", ["_em_segundo_plano", "_biblioteca"])
@pytest.mark.parametrize("pedido", ["um", "todos"])
def test_pedido_que_nao_chega_a_abrir_a_thread_nao_deixa_marca(
    store, make_game, falso, monkeypatch, quebra, pedido
):
    def explode(*_args):
        raise RuntimeError("não abriu")

    monkeypatch.setattr(backup_de_saves, quebra, explode)
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    with pytest.raises(RuntimeError):
        if pedido == "um":
            backup_de_saves.restaurar(jogo, "v1")
        else:
            backup_de_saves.restaurar_todos()

    assert backup_de_saves.restaurando(jogo) is False
    assert not backup_de_saves._restaurando
    assert not backup_de_saves._jogos_restaurando
    assert backup_de_saves._restaurando_todos == 0


def _sem_marcas():
    assert not backup_de_saves._restaurando
    assert not backup_de_saves._jogos_restaurando
    assert backup_de_saves._restaurando_todos == 0


def test_restauracao_aborta_se_o_nome_mudou_no_meio(store, make_game, falso, esperar):
    falso.versoes["X"] = ["v1"]
    falso.demora = 0.1
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.restaurar(jogo, "v1")
    jogo.ludusavi_nome = ""  # o diálogo de detalhes faz isto ao corrigir o appID, no meio da restauração

    assert backup_de_saves.restaurando(jogo) is True  # a marca acompanha o jogo, não só o nome
    esperar()

    # O config já não leva o que o nome de quando pediu precisava: nada é copiado nem gravado.
    assert falso.chamou("backup") == []
    assert falso.restauracoes() == []
    assert titulos() == ["Não foi possível restaurar o save de Meu Jogo."]
    assert backup_de_saves.restaurando(jogo) is False
    _sem_marcas()


def test_restaurar_todos_aborta_o_jogo_cujo_nome_mudou_no_meio(store, make_game, falso, esperar, monkeypatch):
    falso.versoes = {"A": ["v1"], "B": ["v1"]}
    a = na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")
    b = na_biblioteca(store, make_game, game_id="b", name="Jogo B", steam_appid="2", ludusavi_nome="B")
    limpados = []

    def executor(args, **kwargs):
        resultado = falso(args, **kwargs)
        if "backup" in args and not limpados:
            # A cópia do primeiro acabou de rodar: o nome do outro some antes da vez dele.
            feito = args[args.index("backup") + 1]
            limpados.extend(j for j in (a, b) if j.ludusavi_nome != feito)
            limpados[0].ludusavi_nome = ""
        return resultado

    monkeypatch.setattr(backup_de_saves, "executor", executor)

    backup_de_saves.restaurar_todos()
    esperar()

    assert len(falso.chamou("backup")) == 1  # só o do jogo que ficou
    assert len(falso.restauracoes()) == 1
    assert titulos() == ["Não foi possível restaurar os saves de 1 jogo."]
    _sem_marcas()


def test_restaurar_todos_marca_o_objeto_mesmo_se_o_nome_for_limpo(store, make_game, falso, esperar):
    falso.versoes["A"] = ["v1"]
    falso.demora = 0.1
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")

    backup_de_saves.restaurar_todos()
    jogo.ludusavi_nome = ""

    assert backup_de_saves.restaurando(jogo) is True
    esperar()

    assert backup_de_saves.restaurando(jogo) is False
    _sem_marcas()


@pytest.fixture
def threads(monkeypatch):
    """As threads de trabalho que o módulo abre, para o teste esperar só por uma delas."""
    abertas: list[threading.Thread] = []

    def abrir(alvo, *argumentos):
        thread = threading.Thread(target=alvo, args=argumentos, daemon=True)
        abertas.append(thread)
        thread.start()

    monkeypatch.setattr(backup_de_saves, "_em_segundo_plano", abrir)
    yield abertas
    for thread in abertas:  # mesmo que o teste falhe antes de esperar (ver `esperar`)
        thread.join(10)


def _espera_a_primeira_terminar(abertas, flush_idle):
    """Espera uma das threads acabar e entrega à tela o que ela deixou; a outra segue na vez."""
    limite = time.monotonic() + 10
    while all(thread.is_alive() for thread in abertas):
        assert time.monotonic() < limite
        time.sleep(0.01)
    flush_idle()
    assert [thread.is_alive() for thread in abertas].count(True) == 1


def test_duas_restauracoes_seguidas_seguram_a_marca(store, make_game, falso, esperar, flush_idle, threads):
    falso.versoes["X"] = ["v1"]
    falso.demora = 0.1
    jogo = na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")

    backup_de_saves.restaurar(jogo, "v1")
    backup_de_saves.restaurar(jogo, "v1")  # na fila, atrás da trava da primeira
    _espera_a_primeira_terminar(threads, flush_idle)

    assert backup_de_saves.restaurando(jogo) is True
    esperar()
    assert backup_de_saves.restaurando(jogo) is False


def test_dois_restaurar_todos_seguidos_seguram_a_marca(store, make_game, falso, esperar, flush_idle, threads):
    falso.versoes["A"] = ["v1"]
    falso.demora = 0.1
    jogo = na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")

    backup_de_saves.restaurar_todos()
    backup_de_saves.restaurar_todos()
    _espera_a_primeira_terminar(threads, flush_idle)

    assert backup_de_saves.restaurando(jogo) is True
    esperar()
    assert backup_de_saves.restaurando(jogo) is False


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


# -- restauração segura ------------------------------------------------------


def _jogo_x(store, make_game, versoes, falso):
    falso.versoes["X"] = versoes
    return na_biblioteca(store, make_game, game_id="a", name="Meu Jogo", steam_appid="7", ludusavi_nome="X")


def test_restaurar_segue_a_ordem(store, make_game, falso, esperar):
    jogo = _jogo_x(store, make_game, ["v3", "v2", "v1"], falso)

    backup_de_saves.restaurar(jogo, "v2")
    esperar()

    assert [c for c in falso.comandos if c[0] != "backups"] == [
        ["backup", "X", "--force", "--full-limit", "4"],
        ["restore", "X", "--force", "--preview", "--backup", "v2"],
        ["restore", "X", "--force", "--backup", "v2"],
    ]
    assert toasts() == []


def _nada_foi_tocado(falso) -> None:
    assert falso.chamou("backup") == []
    assert falso.chamou("restore") == []


def test_versao_danificada_nao_restaura(store, make_game, falso, esperar):
    jogo = _jogo_x(store, make_game, ["v2", "v1"], falso)
    backup_de_saves.atualizar_cache()
    esperar()
    zip_ = falso.pasta / "X" / "v2"
    bruto = bytearray(zip_.read_bytes())
    bruto[bruto.index(b"0123456789")] ^= 0xFF
    zip_.write_bytes(bruto)

    backup_de_saves.restaurar(jogo, "v2")
    esperar()

    _nada_foi_tocado(falso)
    assert titulos() == ["A versão escolhida dos saves de Meu Jogo está danificada e não foi restaurada."]
    assert toasts()[0].get_use_markup() is False


def test_versao_que_sumiu_nao_restaura(store, make_game, falso, esperar):
    jogo = _jogo_x(store, make_game, ["v2", "v1"], falso)
    backup_de_saves.atualizar_cache()
    esperar()
    (falso.pasta / "X" / "v2").unlink()  # a retenção ou o OneDrive levou o zip depois da lista

    backup_de_saves.restaurar(jogo, "v2")
    esperar()

    _nada_foi_tocado(falso)
    assert titulos() == ["A versão escolhida dos saves de Meu Jogo está danificada e não foi restaurada."]


def test_versao_que_nao_existe_mais_nao_restaura(store, make_game, falso, esperar):
    jogo = _jogo_x(store, make_game, ["v1"], falso)

    backup_de_saves.restaurar(jogo, "apagada")
    esperar()

    _nada_foi_tocado(falso)
    assert titulos() == ["Não foi possível restaurar o save de Meu Jogo."]


@pytest.mark.parametrize(("quantas", "limite"), [(5, "6"), (6, "7"), (255, "255")])
def test_limite_da_copia_e_versoes_mais_um(store, make_game, falso, esperar, quantas, limite):
    jogo = _jogo_x(store, make_game, [f"v{n}" for n in range(quantas, 0, -1)], falso)

    backup_de_saves.restaurar(jogo, "v1")  # a mais antiga: a cópia não pode apagá-la
    esperar()

    assert falso.chamou("backup") == [["backup", "X", "--force", "--full-limit", limite]]
    assert falso.restauracoes() == [["restore", "X", "--force", "--backup", "v1"]]


def test_copia_que_falha_cancela_e_marca(store, make_game, falso, esperar):
    jogo = _jogo_x(store, make_game, ["v1"], falso)
    falso.cria_versao["X"] = True
    falso.falhas["backup"] = FALHOU

    backup_de_saves.restaurar(jogo, "v1")
    esperar()

    assert falso.chamou("restore") == []
    assert falso.marcas() == [["backups", "edit", "X", "--backup", "nova1", "--comment", "cartridges:incompleta"]]
    assert titulos() == [
        (
            "Não foi possível guardar os saves atuais de Meu Jogo antes da restauração. "
            "Verifique se o jogo está fechado e tente novamente."
        )
    ]


def test_copia_marca_antes_de_restaurar(store, make_game, falso, esperar):
    jogo = _jogo_x(store, make_game, ["v2", "v1"], falso)
    falso.cria_versao["X"] = True

    backup_de_saves.restaurar(jogo, "v1")
    esperar()

    assert falso.marcas() == [
        ["backups", "edit", "X", "--backup", "nova1", "--comment", "cartridges:antes-de-restaurar"]
    ]
    assert falso.restauracoes() == [["restore", "X", "--force", "--backup", "v1"]]
    assert toasts() == []


def test_copia_sem_mudanca_nao_marca(store, make_game, falso, esperar):
    jogo = _jogo_x(store, make_game, ["v2", "v1"], falso)

    backup_de_saves.restaurar(jogo, "v1")
    esperar()

    assert falso.marcas() == []  # a mais nova é de antes da cópia: não é dela
    assert falso.restauracoes() == [["restore", "X", "--force", "--backup", "v1"]]


def test_destino_proibido_nao_restaura(store, make_game, falso, esperar, caplog):
    jogo = _jogo_x(store, make_game, ["v1"], falso)
    falso.previas["X"] = {"C:/Windows/x.ini": {}}

    backup_de_saves.restaurar(jogo, "v1")
    esperar()

    assert falso.restauracoes() == []
    assert titulos() == ["O backup dos saves de Meu Jogo contém arquivos fora das pastas de save e não foi restaurado."]
    assert "C:/Windows/x.ini" in caplog.text  # o caminho só no log


def test_conferencia_que_levanta_nao_restaura(store, make_game, falso, esperar, monkeypatch):
    def unidade_travada(*_args):
        raise OSError("unidade travada pelo BitLocker")

    monkeypatch.setattr(conferencia, "recusado", unidade_travada)
    jogo = _jogo_x(store, make_game, ["v1"], falso)

    backup_de_saves.restaurar(jogo, "v1")
    esperar()

    assert falso.restauracoes() == []
    assert titulos() == ["Não foi possível restaurar o save de Meu Jogo."]


def test_redirecionamento_vai_no_config(store, make_game, falso, esperar):
    jogo = _jogo_x(store, make_game, ["v1"], falso)
    falso.no_zip["v1"] = ["drive-C/Users/NaoExiste123/AppData/a.sav"]

    backup_de_saves.restaurar(jogo, "v1")
    esperar()

    assert falso.restauracoes() == [["restore", "X", "--force", "--backup", "v1"]]
    assert falso.configs["restore"]["redirects"] == [
        {"kind": "restore", "source": "C:/Users/NaoExiste123", "target": Path.home().as_posix()}
    ]


def test_restaurar_todos_pula_incompleta(store, make_game, falso, esperar):
    falso.versoes = {"A": ["v3", "v2"], "B": ["w1"]}
    falso.comentarios[("A", "v3")] = "cartridges:incompleta"
    falso.comentarios[("B", "w1")] = "cartridges:incompleta"
    na_biblioteca(store, make_game, game_id="a", name="Jogo A", steam_appid="1", ludusavi_nome="A")
    na_biblioteca(store, make_game, game_id="b", name="Jogo B", steam_appid="2", ludusavi_nome="B")

    backup_de_saves.restaurar_todos()
    esperar()

    assert [c[1] for c in falso.chamou("backup")] == ["A"]  # B nem ganha cópia
    assert falso.restauracoes() == [["restore", "A", "--force", "--backup", "v2"]]
    assert titulos() == ["Não foi possível restaurar os saves de 1 jogo."]
