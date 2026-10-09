"""O Ludusavi como processo: a linha de comando, o JSON de volta e as falhas.

Amostras reais do Ludusavi 0.31.0 em `tests/dados/ludusavi/`. Campos confirmados:

* `find --steam-id N --api` / `find "<título>" --api`: `{"games": {"<nome>": {"score": 1.0}}}`.
  Sem achado, o código de saída é 1, mas o stdout é JSON válido
  (`errors.unknownGames`, `games: {}`) — não é falha, é "não achado".
* `backup "<nome>" --force --api`: `games.<nome>.{decision, change, files}`. Um jogo
  desconhecido sai com código 1 e `errors.unknownGames`; `errors.someGamesFailed`
  (true) é como o Ludusavi avisa que o jogo existe mas a cópia falhou.
* `backups --api`: `games.<nome>.backups[] = {name, when, os, locked}`. `name` é o
  que `restore --backup` pede (`backup-20261009T154638Z`, ou `.` quando a retenção
  guarda uma única cópia); `when` é UTC, ISO 8601, com 9 casas decimais e `Z`.
* `restore "<nome>" [--backup <name>] --force --api`: o mesmo formato do `backup`.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cartridges.saves import ludusavi
from cartridges.saves.ludusavi import LudusaviFalhou, Versao

DADOS = Path(__file__).parent / "dados" / "ludusavi"


def amostra(nome: str) -> str:
    return (DADOS / f"{nome}.json").read_text(encoding="utf-8")


class ExecutorFalso:
    """Devolve a mesma saída a cada chamada e guarda o que recebeu."""

    def __init__(self, stdout: str = "", returncode: int = 0, stderr: str = ""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.chamadas: list[tuple[list[str], dict]] = []

    def __call__(self, args, **kwargs):
        self.chamadas.append((args, kwargs))
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, self.stderr)


@pytest.fixture(autouse=True)
def exe_ao_lado_do_python(tmp_path, monkeypatch):
    (tmp_path / "ludusavi.exe").touch()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    return tmp_path / "ludusavi.exe"


def test_rodar_monta_a_linha(exe_ao_lado_do_python, tmp_path):
    executor = ExecutorFalso(amostra("find_achado"))
    ludusavi.rodar(["find", "--steam-id", "3669870"], tmp_path / "cfg", executor)
    args, kwargs = executor.chamadas[0]
    assert isinstance(args, list)
    assert args == [
        str(exe_ao_lado_do_python),
        "--config", str(tmp_path / "cfg"),
        "--try-manifest-update",
        "find", "--steam-id", "3669870",
        "--api",
    ]  # fmt: skip
    assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
    # Medido com o Ludusavi de verdade: sem isto ele não termina quando herda a entrada.
    assert kwargs["stdin"] == subprocess.DEVNULL


def test_nome_com_aspas_e_acento_vai_intacto(tmp_path):
    nome = 'Tom Clancy\'s "Ação" & Cia'
    executor = ExecutorFalso(amostra("backup_ok"))
    ludusavi.fazer_backup(nome, tmp_path, executor)
    assert executor.chamadas[0][0].count(nome) == 1


def test_sem_executavel_falha(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "vazia" / "python.exe"))
    with pytest.raises(LudusaviFalhou):
        ludusavi.rodar(["backups"], tmp_path, ExecutorFalso("{}"))


def test_saida_vazia_falha(tmp_path):
    with pytest.raises(LudusaviFalhou):
        ludusavi.rodar(["backups"], tmp_path, ExecutorFalso(""))


def test_saida_que_nao_e_json_falha(tmp_path):
    with pytest.raises(LudusaviFalhou):
        ludusavi.rodar(["backups"], tmp_path, ExecutorFalso("No info for these games"))


def test_saida_que_nao_e_objeto_falha(tmp_path):
    with pytest.raises(LudusaviFalhou):
        ludusavi.rodar(["backups"], tmp_path, ExecutorFalso("[]"))


def test_codigo_de_erro_falha(tmp_path):
    executor = ExecutorFalso(amostra("backup_desconhecido"), returncode=1, stderr="No info")
    with pytest.raises(LudusaviFalhou):
        ludusavi.fazer_backup("Jogo Que Nao Existe", tmp_path, executor)


def test_falha_ao_iniciar_o_processo_vira_ludusavi_falhou(tmp_path):
    def executor(args, **kwargs):
        raise OSError("sem permissão")

    with pytest.raises(LudusaviFalhou):
        ludusavi.rodar(["backups"], tmp_path, executor)


def test_backup_com_jogo_falho_falha(tmp_path):
    saida = json.loads(amostra("backup_ok"))
    saida["errors"] = {"someGamesFailed": True}
    with pytest.raises(LudusaviFalhou):
        ludusavi.fazer_backup("Teste Cartridges", tmp_path, ExecutorFalso(json.dumps(saida)))


def test_backup_com_sucesso_nao_devolve_nada(tmp_path):
    executor = ExecutorFalso(amostra("backup_ok"))
    assert ludusavi.fazer_backup("Teste Cartridges", tmp_path, executor) is None
    assert executor.chamadas[0][0][-4:] == ["backup", "Teste Cartridges", "--force", "--api"]


def test_nome_por_appid_achado(tmp_path):
    executor = ExecutorFalso(amostra("find_achado"))
    assert ludusavi.nome_por_appid("3669870", tmp_path, executor) == "Control Resonant"
    args = executor.chamadas[0][0]
    assert args[args.index("find") + 1 :][:2] == ["--steam-id", "3669870"]


def test_nome_por_appid_nao_achado(tmp_path):
    # O Ludusavi sai com código 1 quando não conhece o jogo, mas o JSON é válido.
    executor = ExecutorFalso(amostra("find_nao_achado"), returncode=1)
    assert ludusavi.nome_por_appid("1", tmp_path, executor) is None


def test_nome_por_appid_com_falha_de_verdade_falha(tmp_path):
    with pytest.raises(LudusaviFalhou):
        ludusavi.nome_por_appid("1", tmp_path, ExecutorFalso("", returncode=1))


def test_nome_por_titulo_achado_e_nao_achado(tmp_path):
    assert (
        ludusavi.nome_por_titulo("Alien: Isolation", tmp_path, ExecutorFalso(amostra("find_titulo")))
        == "Alien: Isolation"
    )
    assert (
        ludusavi.nome_por_titulo(
            "Nada", tmp_path, ExecutorFalso(amostra("find_nao_achado"), returncode=1)
        )
        is None
    )


def test_o_achado_de_maior_pontuacao_vence(tmp_path):
    saida = json.dumps({"games": {"A": {"score": 0.4}, "B": {"score": 0.9}, "C": {"score": 0.6}}})
    assert ludusavi.nome_por_titulo("x", tmp_path, ExecutorFalso(saida)) == "B"


def test_versoes_por_jogo(tmp_path):
    por_jogo = ludusavi.versoes(tmp_path, ExecutorFalso(amostra("backups")))
    assert list(por_jogo) == ["Teste Cartridges"]
    assert por_jogo["Teste Cartridges"] == [
        Versao("backup-20261009T154644Z", datetime(2026, 10, 9, 15, 46, 44, 168796, tzinfo=timezone.utc)),
        Versao("backup-20261009T154641Z", datetime(2026, 10, 9, 15, 46, 41, 594421, tzinfo=timezone.utc)),
        Versao("backup-20261009T154638Z", datetime(2026, 10, 9, 15, 46, 38, 971055, tzinfo=timezone.utc)),
    ]  # fmt: skip


def test_versoes_ignora_o_que_nao_tem_data_legivel(tmp_path):
    saida = {
        "games": {
            "Jogo": {
                "backups": [
                    {"name": "a", "when": "2026-10-09T10:00:00Z"},
                    {"name": "b", "when": "ontem"},
                    {"when": "2026-10-09T11:00:00Z"},
                ]
            },
            "Sem cópias": {"backups": []},
        }
    }
    por_jogo = ludusavi.versoes(tmp_path, ExecutorFalso(json.dumps(saida)))
    assert [v.id for v in por_jogo["Jogo"]] == ["a"]
    assert por_jogo["Sem cópias"] == []


def test_restaurar_a_ultima_e_uma_versao(tmp_path):
    ultima = ExecutorFalso(amostra("restore_ok"))
    ludusavi.restaurar("Teste Cartridges", tmp_path, executor=ultima)
    args = ultima.chamadas[0][0]
    assert "restore" in args and "--force" in args and "--backup" not in args

    antiga = ExecutorFalso(amostra("restore_ok"))
    ludusavi.restaurar("Teste Cartridges", tmp_path, "backup-20261009T154638Z", antiga)
    args = antiga.chamadas[0][0]
    assert args[args.index("--backup") + 1] == "backup-20261009T154638Z"


def test_restaurar_com_jogo_falho_falha(tmp_path):
    saida = json.loads(amostra("restore_ok"))
    saida["errors"] = {"someGamesFailed": True}
    with pytest.raises(LudusaviFalhou):
        ludusavi.restaurar("Teste Cartridges", tmp_path, executor=ExecutorFalso(json.dumps(saida)))


def test_executavel_ausente(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "executable", str(tmp_path / "vazia" / "python.exe"))
    assert ludusavi.executavel() is None


def test_executavel_presente(exe_ao_lado_do_python):
    assert ludusavi.executavel() == exe_ao_lado_do_python
