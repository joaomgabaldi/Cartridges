"""O Ludusavi como processo: a linha de comando, o JSON de volta e as falhas.

Amostras reais do Ludusavi 0.31.0 em `tests/dados/ludusavi/`. Campos confirmados:

* `find --steam-id N --api` / `find "<título>" --api`: `{"games": {"<nome>": {"score": 1.0}}}`.
  Sem achado, o código de saída é 1, mas o stdout é JSON válido
  (`errors.unknownGames`, `games: {}`) — não é falha, é "não achado".
* `backup "<nome>" --force --api`: `games.<nome>.{decision, change, files}`. Um jogo
  desconhecido sai com código 1 e `errors.unknownGames`; `errors.someGamesFailed`
  (true) é como o Ludusavi avisa que o jogo existe mas a cópia falhou.
* `backups --api`: `games.<nome>.{backupPath, backups[]}`, com `backups[] = {name, when,
  os, locked}` e, só nas versões marcadas, `comment`. `backupPath` é a pasta do jogo
  dentro da pasta de saves; `name` é o que `restore --backup` pede
  (`backup-20261009T154638Z`, ou `.` quando a retenção guarda uma única cópia) e,
  junto de `backupPath`, dá o zip da versão; `when` é UTC, ISO 8601, com 9 casas
  decimais e `Z`.
* `backups edit "<nome>" --backup <name> --comment <texto>`: NÃO aceita `--api`
  (erro "unexpected argument '--api'"); no sucesso sai com 0 e stdout vazio.
* `backup ... --full-limit N`: aceito.
* `restore "<nome>" [--backup <name>] --force --api`: o mesmo formato do `backup`.
* `restore "<nome>" --force --preview --api [--backup <name>]`: o mesmo formato, sem
  copiar nada. `games.<nome>.files` tem por chave o caminho final (e `originalPath`
  quando o Ludusavi o redirecionou); `games.<nome>.registry` tem por chave a chave de
  registro (`HKEY_CURRENT_USER/...`).
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cartridges.saves import ludusavi
from cartridges.saves.ludusavi import LudusaviFalhou, Previa, Versao

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
def exe_ao_lado_do_python(tmp_path, ludusavi_de_verdade):
    (tmp_path / "ludusavi.exe").touch()
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


def test_travou_vira_ludusavi_falhou(tmp_path):
    def executor(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    with pytest.raises(LudusaviFalhou):
        ludusavi.rodar(["backups"], tmp_path, executor)


def test_rodar_passa_um_limite_de_tempo(tmp_path):
    executor = ExecutorFalso(amostra("backups"))
    ludusavi.rodar(["backups"], tmp_path, executor)
    assert executor.chamadas[0][1]["timeout"] == ludusavi.LIMITE_DE_TEMPO


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
    pasta = Path("C:/Temp/cartridges/bk2/Teste Cartridges")
    utc = timezone.utc
    assert por_jogo["Teste Cartridges"] == [
        Versao("backup-20261009T154644Z", datetime(2026, 10, 9, 15, 46, 44, 168796, tzinfo=utc), "", pasta / "backup-20261009T154644Z"),
        Versao("backup-20261009T154641Z", datetime(2026, 10, 9, 15, 46, 41, 594421, tzinfo=utc), "", pasta / "backup-20261009T154641Z"),
        Versao("backup-20261009T154638Z", datetime(2026, 10, 9, 15, 46, 38, 971055, tzinfo=utc), "", pasta / "backup-20261009T154638Z"),
    ]  # fmt: skip


def test_versoes_trazem_comentario_e_arquivo(tmp_path):
    jogo = 'Jogo "Ação" & Cia'
    nova, velha = ludusavi.versoes(tmp_path, ExecutorFalso(amostra("backups_com_comentario")))[jogo]
    assert nova.comentario == "cartridges:incompleta"
    assert nova.arquivo == Path("C:/Saves/Jogo _Ação_ & Cia/backup-20261011T100000Z.zip")
    assert velha.comentario == ""
    assert velha.arquivo == Path("C:/Saves/Jogo _Ação_ & Cia/backup-20261010T100000Z.zip")


def test_versoes_sem_backup_path_ficam_sem_arquivo(tmp_path):
    saida = json.loads(amostra("backups"))
    del saida["games"]["Teste Cartridges"]["backupPath"]
    por_jogo = ludusavi.versoes(tmp_path, ExecutorFalso(json.dumps(saida)))
    versoes = por_jogo["Teste Cartridges"]
    assert versoes and all(v.arquivo is None for v in versoes)


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


def test_restaurar_tem_um_limite_de_tempo_maior(tmp_path):
    """Restauração morta no meio deixa o save pela metade: ela ganha uma hora."""
    executor = ExecutorFalso(amostra("restore_ok"))
    ludusavi.restaurar("Teste Cartridges", tmp_path, executor=executor)
    assert executor.chamadas[0][1]["timeout"] == 60 * 60
    assert ludusavi.LIMITE_DE_TEMPO == 10 * 60  # o resto continua com 10 minutos


def test_marcar_sem_api(tmp_path):
    """`backups edit` não aceita `--api` e sai sem stdout: só o código de saída conta."""
    executor = ExecutorFalso("", returncode=0)
    assert ludusavi.marcar("J", "v1", "x", tmp_path, executor) is None
    args = executor.chamadas[0][0]
    assert args[args.index("--try-manifest-update") + 1 :] == [
        "backups", "edit", "J", "--backup", "v1", "--comment", "x",
    ]  # fmt: skip
    assert "--api" not in args


def test_marcar_que_falha_levanta(tmp_path):
    with pytest.raises(LudusaviFalhou):
        ludusavi.marcar("J", "v1", "x", tmp_path, ExecutorFalso("", returncode=2, stderr="erro"))


def test_fazer_backup_com_limite(tmp_path):
    com = ExecutorFalso(amostra("backup_ok"))
    ludusavi.fazer_backup("J", tmp_path, com, limite=6)
    assert com.chamadas[0][0][-6:] == ["backup", "J", "--force", "--full-limit", "6", "--api"]

    sem = ExecutorFalso(amostra("backup_ok"))
    ludusavi.fazer_backup("J", tmp_path, sem)
    assert "--full-limit" not in sem.chamadas[0][0]


def test_previa_redirecionada(tmp_path):
    executor = ExecutorFalso(amostra("previa_redirecionada"))
    esperada = Previa(("C:/Users/Atual/AppData/Jogo/s.sav",), ())
    assert ludusavi.previa("J", tmp_path, "v1", executor) == esperada
    args = executor.chamadas[0][0]
    assert args[args.index("restore") :] == ["restore", "J", "--force", "--preview", "--backup", "v1", "--api"]


def test_previa_sem_versao_nao_pede_backup(tmp_path):
    executor = ExecutorFalso(amostra("previa_redirecionada"))
    ludusavi.previa("J", tmp_path, executor=executor)
    args = executor.chamadas[0][0]
    assert args[args.index("restore") :] == ["restore", "J", "--force", "--preview", "--api"]


def test_previa_com_registro(tmp_path):
    executor = ExecutorFalso(amostra("previa_com_registro"))
    esperada = Previa((), ("HKEY_CURRENT_USER/Console/%%Startup",))
    assert ludusavi.previa("J", tmp_path, executor=executor) == esperada


def test_previa_de_jogo_ausente_e_vazia(tmp_path):
    assert ludusavi.previa("J", tmp_path, executor=ExecutorFalso('{"games": {}}')) == Previa((), ())


def test_previa_com_jogo_falho_falha(tmp_path):
    saida = json.loads(amostra("previa_redirecionada"))
    saida["errors"] = {"someGamesFailed": True}
    with pytest.raises(LudusaviFalhou):
        ludusavi.previa("J", tmp_path, executor=ExecutorFalso(json.dumps(saida)))
