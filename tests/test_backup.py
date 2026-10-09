# test_backup.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O backup como retrato completo do app: a pasta de dados e as configurações
num .zip, restaurado com o app fechado (`agendar` + `aplicar_pendente`)."""

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from cartridges import shared
from cartridges.utils import backup

_PASTAS_DO_APP = (
    "app_dir", "games_dir", "covers_dir", "logos_dir", "wallpapers_dir", "log_dir",
    "fitas_dir", "conquistas_dir", "conquistas_cache_dir", "capas_animadas_dir",
    "contas_dir", "fitas_arquivo", "tuya_conta_arquivo",
)


@pytest.fixture(autouse=True)
def _app_isolado(tmp_path, monkeypatch, app_dirs, settings):
    """A pasta do app dentro de ``tmp_path/app``, com as configurações de verdade.

    O conftest põe ``app_dir`` no próprio ``tmp_path``, e a restauração cria
    irmãs dele (``.anterior``, ``.restaurando``, ``.lixo``) em ``tmp_path.parent``:
    a pasta de base do pytest, compartilhada por todos os testes da sessão.
    Um nível a mais e as irmãs ficam na pasta deste teste, só dele; e a troca
    deixa de varrer junto o que o teste guarda ao lado (o backup exportado, os
    schemas).
    """
    raiz = tmp_path / "app"
    for nome in _PASTAS_DO_APP:
        monkeypatch.setattr(shared, nome, raiz / getattr(shared, nome).relative_to(tmp_path))
    for pasta in (shared.games_dir, shared.covers_dir, shared.logos_dir,
                  shared.wallpapers_dir, shared.log_dir):
        pasta.mkdir(parents=True)
        # As do conftest, vazias e agora fora do app.
        (tmp_path / pasta.name).rmdir()


# --------------------------------------------------------------------------
# Backup completo (.zip)
# --------------------------------------------------------------------------


def test_an_old_json_backup_is_not_a_full_backup(tmp_path) -> None:
    old = tmp_path / "antigo.zip"
    with zipfile.ZipFile(old, "w") as archive:
        archive.writestr("backup.json", json.dumps({"version": 2, "games": {}}))
    with pytest.raises(ValueError):
        backup.validar(old)


def test_a_setting_the_schema_does_not_accept_falls_back_to_default(settings) -> None:
    """Um valor editado à mão com tipo errado, ou fora das opções do schema,
    volta ao padrão em vez de ser gravado; o resto do backup entra; a chave
    que o backup não tem também volta ao padrão."""
    main, state = settings
    main.set_uint("library-rows", 2)
    main.set_boolean("gamepad-rumble", False)
    main.set_boolean("gamepad", True)
    state.set_string("sort-mode", "a-z")
    backup.aplicar_configuracoes(
        {
            "settings": {"library-rows": "três", "sgdb": True, "gamepad-rumble": "sim"},
            "state": {"sort-mode": "inexistente"},
        }
    )
    assert main.get_uint("library-rows") == 0
    assert main.get_boolean("sgdb") is True
    assert main.get_boolean("gamepad-rumble") is True
    assert main.get_boolean("gamepad") is False
    assert state.get_string("sort-mode") == "last_played"


def test_a_setting_removed_from_the_schema_is_ignored(settings) -> None:
    """Backup de uma versão que ainda tinha "Capa inicia o jogo"."""
    main, _state = settings
    backup.aplicar_configuracoes(
        {"settings": {"cover-launches-game": True, "sgdb": True}, "state": {}}
    )
    assert main.get_boolean("sgdb") is True


# --------------------------------------------------------------------------
# Exportar e validar
# --------------------------------------------------------------------------


def _sobrou(pasta):
    """Se ``pasta`` ainda guarda alguma coisa. No Windows, o antivírus ou o
    indexador seguram uma pasta ou um arquivo recém-gravado por alguns
    milissegundos, e a remoção deixa para trás a pasta, já vazia: o que importa
    à restauração é que não sobre dado nela (a abertura seguinte a descarta)."""
    return pasta.exists() and any(pasta.iterdir())


def _encher_pasta_do_app():
    (shared.games_dir / "shortcuts_1.json").write_text(
        json.dumps({"game_id": "shortcuts_1", "source": "shortcuts", "name": "Jogo"}),
        encoding="utf-8",
    )
    (shared.games_dir / "imported_1.json").write_text(
        json.dumps({"game_id": "imported_1", "source": "imported", "name": "Manual"}),
        encoding="utf-8",
    )
    (shared.games_dir / "shortcuts_1.json.tmp").write_text("sobra", encoding="utf-8")
    (shared.covers_dir / "shortcuts_1.tiff").write_bytes(b"capa")
    (shared.logos_dir / "shortcuts_1.png").write_bytes(b"logo")
    (shared.wallpapers_dir / "shortcuts_1.jpg").write_bytes(b"parede")
    shared.fitas_dir.mkdir(exist_ok=True)
    (shared.fitas_dir / "shortcuts_1.json").write_text("{}", encoding="utf-8")
    shared.fitas_arquivo.write_text('{"fitas": []}', encoding="utf-8")
    shared.tuya_conta_arquivo.write_text("{}", encoding="utf-8")
    (shared.app_dir / "sessions.jsonl").write_text("", encoding="utf-8")
    (shared.log_dir / "cartridges.log").write_text("log", encoding="utf-8")


def _exportar(tmp_path):
    destino = tmp_path / "saida" / "backup.zip"
    destino.parent.mkdir()
    backup.exportar(destino, {"settings": {"sgdb": True}, "state": {"sort-mode": "a-z"}})
    return destino


def test_exportar_leva_a_capa_apng(tmp_path):
    _encher_pasta_do_app()
    (shared.covers_dir / "imported_1.apng").write_bytes(b"capa animada")

    with zipfile.ZipFile(_exportar(tmp_path)) as arquivo:
        assert "covers/imported_1.apng" in arquivo.namelist()


def test_exportar_leva_a_pasta_do_app_e_as_configuracoes(tmp_path):
    _encher_pasta_do_app()
    destino = _exportar(tmp_path)
    with zipfile.ZipFile(destino) as arquivo:
        nomes = set(arquivo.namelist())
        manifesto = json.loads(arquivo.read("configuracoes.json"))
    assert nomes == {
        "configuracoes.json",
        "games/shortcuts_1.json",
        "games/imported_1.json",
        "covers/shortcuts_1.tiff",
        "logos/shortcuts_1.png",
        "wallpapers/shortcuts_1.jpg",
        "fitas/shortcuts_1.json",
        "fitas.json",
        "tuya_conta.json",
        "sessions.jsonl",
    }
    assert manifesto["version"] == backup.VERSAO
    assert manifesto["settings"] == {"sgdb": True}
    assert manifesto["state"] == {"sort-mode": "a-z"}


def test_backup_leva_as_copias(tmp_path):
    _encher_pasta_do_app()
    shared.capas_animadas_dir.mkdir(parents=True)
    (shared.capas_animadas_dir / "g1_200x300.webp").write_bytes(b"copia")
    (shared.capas_animadas_dir / "g1_200x300.webp.tmp").write_bytes(b"sobra")

    destino = _exportar(tmp_path)

    with zipfile.ZipFile(destino) as arquivo:
        nomes = arquivo.namelist()
    assert "cache/capas_animadas/g1_200x300.webp" in nomes
    assert not any(nome.endswith(".tmp") for nome in nomes)
    # E o que `exportar` grava, `validar` aceita: uma pasta aninhada não pode
    # tornar o próprio backup inválido.
    assert backup.validar(destino)["version"] == backup.VERSAO


def test_restaurar_traz_as_copias_de_volta(tmp_path, monkeypatch):
    aplicadas = _preparar_restauracao(tmp_path, monkeypatch, com_copias=True)

    assert backup.aplicar_pendente() is True

    assert aplicadas
    assert (shared.capas_animadas_dir / "g1_200x300.webp").read_bytes() == b"copia"


def test_exportar_deixa_de_fora_o_agendado_e_as_pendencias(tmp_path):
    _encher_pasta_do_app()
    (shared.app_dir / "restaurar.zip").write_bytes(b"zip")
    (shared.app_dir / "restauracao_pendente.json").write_text("{}", encoding="utf-8")
    with zipfile.ZipFile(_exportar(tmp_path)) as arquivo:
        nomes = arquivo.namelist()
    assert "restaurar.zip" not in nomes
    assert "restauracao_pendente.json" not in nomes
    assert not any(nome.startswith("logs/") for nome in nomes)


def test_configuracoes_levam_a_pasta_de_atalhos_e_o_monitor():
    assert backup._filtrar_chaves(
        ["shortcuts-location", "session-monitor", "session-wallpaper-saved", "fita-estado-anterior"]
    ) == ["shortcuts-location", "session-monitor"]


def _zip(caminho, entradas):
    with zipfile.ZipFile(caminho, "w") as arquivo:
        for nome, conteudo in entradas.items():
            arquivo.writestr(nome, conteudo)
    return caminho


_MANIFESTO = json.dumps({"version": backup.VERSAO, "settings": {}, "state": {}})


@pytest.mark.parametrize(
    "nome",
    ["../fora.json", "/games/x.json", "games/../x.json", "games\\..\\x.json", "C:x.json",
     "games/x.exe", "outra/x.json", "games/sub/x.json", "logs/cartridges.log",
     "cache/x.webp", "cache/capas_animadas/x.exe", "cache/capas_animadas/sub/x.webp",
     "cache/capas_animadas/../x.webp"],
)
def test_validar_recusa_nome_inesperado(tmp_path, nome):
    caminho = _zip(tmp_path / "b.zip", {"configuracoes.json": _MANIFESTO, nome: "x"})
    with pytest.raises(backup.BackupInvalido):
        backup.validar(caminho)


def test_validar_recusa_o_formato_4(tmp_path):
    antigo = json.dumps({"version": 4, "settings": {}, "jogos": {}})
    with pytest.raises(backup.BackupInvalido):
        backup.validar(_zip(tmp_path / "b.zip", {"backup.json": antigo}))
    with pytest.raises(backup.BackupInvalido):
        backup.validar(_zip(tmp_path / "c.zip", {"configuracoes.json": antigo}))


def test_validar_recusa_entrada_corrompida(tmp_path):
    _encher_pasta_do_app()
    destino = _exportar(tmp_path)
    dados = bytearray(destino.read_bytes())
    posicao = dados.find(b"capa")
    dados[posicao] ^= 0xFF
    destino.write_bytes(bytes(dados))
    with pytest.raises(backup.BackupInvalido):
        backup.validar(destino)


def test_validar_aceita_o_que_exportar_grava(tmp_path):
    _encher_pasta_do_app()
    assert backup.validar(_exportar(tmp_path))["version"] == backup.VERSAO


# --------------------------------------------------------------------------
# Restaurar
# --------------------------------------------------------------------------


def test_agendar_copia_para_a_pasta_do_app(tmp_path):
    origem = _zip(tmp_path / "b.zip", {"configuracoes.json": _MANIFESTO})
    backup.agendar(origem)
    assert (shared.app_dir / "restaurar.zip").read_bytes() == origem.read_bytes()
    assert origem.is_file()


def test_aplicar_pendente_sem_nada_agendado():
    assert backup.aplicar_pendente() is None


def _preparar_restauracao(tmp_path, monkeypatch, com_copias=False):
    """Exporta um backup, troca a pasta do app por outra biblioteca e agenda."""
    aplicadas = []
    monkeypatch.setattr(backup, "aplicar_configuracoes", aplicadas.append)
    monkeypatch.setattr(
        backup, "ler_configuracoes", lambda: {"settings": {"antes": 1}, "state": {}}
    )
    _encher_pasta_do_app()
    if com_copias:
        shared.capas_animadas_dir.mkdir(parents=True)
        (shared.capas_animadas_dir / "g1_200x300.webp").write_bytes(b"copia")
    destino = _exportar(tmp_path)
    if com_copias:
        (shared.capas_animadas_dir / "g1_200x300.webp").unlink()
    for arquivo in shared.games_dir.iterdir():
        arquivo.unlink()
    (shared.games_dir / "atual.json").write_text("{}", encoding="utf-8")
    backup.agendar(destino)
    return aplicadas


def test_aplicar_pendente_troca_tudo_e_cria_as_pendencias(tmp_path, monkeypatch):
    from cartridges.utils import restauracao  # noqa: PLC0415

    aplicadas = _preparar_restauracao(tmp_path, monkeypatch)

    assert backup.aplicar_pendente() is True

    assert sorted(p.name for p in shared.games_dir.iterdir()) == [
        "imported_1.json", "shortcuts_1.json"
    ]
    assert (shared.log_dir / "cartridges.log").read_text("utf-8") == "log"
    assert not (shared.app_dir / "restaurar.zip").exists()
    assert not (shared.app_dir / "configuracoes.json").exists()
    assert not _sobrou(shared.app_dir.with_name(shared.app_dir.name + ".anterior"))
    assert not _sobrou(shared.app_dir.with_name(shared.app_dir.name + ".restaurando"))
    assert aplicadas[-1]["settings"] == {"sgdb": True}
    assert restauracao.ids() == frozenset({"shortcuts_1"})


def test_restaurar_mantem_a_conta_microsoft_deste_pc(tmp_path, monkeypatch):
    """A pasta `contas` é desta máquina e deste usuário do Windows (o DPAPI não
    abre em outro PC): restaurar um backup não a leva nem a apaga."""
    _preparar_restauracao(tmp_path, monkeypatch)
    shared.contas_dir.mkdir()
    (shared.contas_dir / "microsoft.json").write_text('{"gamertag": "Jogador"}', encoding="utf-8")

    assert backup.aplicar_pendente() is True

    assert (shared.contas_dir / "microsoft.json").read_text("utf-8") == '{"gamertag": "Jogador"}'
    assert sorted(p.name for p in shared.games_dir.iterdir()) == ["imported_1.json", "shortcuts_1.json"]


def test_aplicar_pendente_que_falha_devolve_tudo(tmp_path, monkeypatch):
    aplicadas = _preparar_restauracao(tmp_path, monkeypatch)

    def aplicar(configuracoes):
        # Falha só com as do backup; as de antes, na volta atrás, gravam.
        aplicadas.append(configuracoes)
        if configuracoes["settings"] != {"antes": 1}:
            raise OSError("registro travado")

    monkeypatch.setattr(backup, "aplicar_configuracoes", aplicar)

    assert backup.aplicar_pendente() is False

    assert [p.name for p in shared.games_dir.iterdir()] == ["atual.json"]
    assert not (shared.app_dir / "restauracao_pendente.json").exists()
    assert not (shared.app_dir / "restaurar.zip").exists()
    assert not _sobrou(shared.app_dir.with_name(shared.app_dir.name + ".anterior"))
    # As configurações de antes voltam ao registro.
    assert aplicadas[-1] == {"settings": {"antes": 1}, "state": {}}


def test_queda_no_meio_da_troca_e_recuperada(tmp_path, monkeypatch):
    """Uma abertura que acha `.anterior` devolve os dados de antes."""
    _preparar_restauracao(tmp_path, monkeypatch)
    anterior = shared.app_dir.with_name(shared.app_dir.name + ".anterior")
    anterior.mkdir()
    shared.games_dir.replace(anterior / "games")
    (anterior / ".completo").write_text("", encoding="utf-8")
    (shared.app_dir / "games").mkdir()
    (shared.app_dir / "games" / "do_backup.json").write_text("{}", encoding="utf-8")
    (shared.app_dir / "restaurar.zip").unlink()

    assert backup.aplicar_pendente() is None

    assert [p.name for p in shared.games_dir.iterdir()] == ["atual.json"]
    assert not _sobrou(anterior)


def test_falha_ao_apagar_a_pasta_anterior_nao_apaga_o_que_voltou(tmp_path, monkeypatch):
    """A volta atrás devolve os dados e, ao apagar `.anterior`, o antivírus
    segura um arquivo. Na abertura seguinte, o que voltou não pode ser tomado
    por dado do backup e apagado."""
    aplicadas = _preparar_restauracao(tmp_path, monkeypatch)

    def aplicar(configuracoes):
        aplicadas.append(configuracoes)
        if configuracoes["settings"] != {"antes": 1}:
            raise OSError("registro travado")

    monkeypatch.setattr(backup, "aplicar_configuracoes", aplicar)
    rmtree_original = shutil.rmtree

    def rmtree_que_trava(caminho, *args, **kwargs):
        if str(caminho).endswith(".anterior"):
            raise OSError("arquivo em uso")
        return rmtree_original(caminho, *args, **kwargs)

    with monkeypatch.context() as travado:
        travado.setattr(shutil, "rmtree", rmtree_que_trava)
        travado.setattr(backup, "sleep", lambda _s: None)
        assert backup.aplicar_pendente() is False

    assert backup.aplicar_pendente() is None
    assert [p.name for p in shared.games_dir.iterdir()] == ["atual.json"]


def test_pasta_anterior_que_demora_a_esvaziar_e_apagada_na_segunda_tentativa(
    tmp_path, monkeypatch
):
    """O antivírus segura um arquivo por instantes: a remoção insiste."""
    _preparar_restauracao(tmp_path, monkeypatch)
    rmtree_original = shutil.rmtree
    recusas = []

    def rmtree_que_recusa_uma_vez(caminho, *args, **kwargs):
        if str(caminho).endswith(".anterior") and not recusas:
            recusas.append(caminho)
            raise OSError("A pasta não está vazia")
        return rmtree_original(caminho, *args, **kwargs)

    anterior = shared.app_dir.with_name(shared.app_dir.name + ".anterior")
    anterior.mkdir()
    shared.games_dir.replace(anterior / "games")
    (shared.app_dir / "restaurar.zip").unlink()
    monkeypatch.setattr(shutil, "rmtree", rmtree_que_recusa_uma_vez)
    monkeypatch.setattr(backup, "sleep", lambda _s: None)

    assert backup.aplicar_pendente() is None

    assert recusas
    assert [p.name for p in shared.games_dir.iterdir()] == ["atual.json"]
    assert not anterior.exists()


def test_sobra_de_lixo_e_apagada_na_abertura():
    lixo = shared.app_dir.with_name(shared.app_dir.name + ".lixo")
    (lixo / "games").mkdir(parents=True)
    assert backup.aplicar_pendente() is None
    assert not lixo.exists()


def test_restauracao_concluida_nao_e_desfeita_se_a_pasta_antiga_nao_sai(tmp_path, monkeypatch):
    """Antivírus segurando um arquivo trava a renomeação de `.anterior`: a
    abertura seguinte não pode tomá-la por uma troca interrompida."""
    _preparar_restauracao(tmp_path, monkeypatch)
    replace_original = Path.replace

    def replace_que_trava(self, alvo):
        if str(alvo).endswith(".lixo"):
            raise PermissionError("arquivo em uso")
        return replace_original(self, alvo)

    with monkeypatch.context() as travado:
        travado.setattr(Path, "replace", replace_que_trava)
        travado.setattr(shutil, "rmtree", lambda *_a, **_k: None)
        assert backup.aplicar_pendente() is True

    (shared.games_dir / "jogado_depois.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(backup, "aplicar_configuracoes", lambda _c: None)
    monkeypatch.setattr(backup, "ler_configuracoes", lambda: {"settings": {}, "state": {}})

    assert backup.aplicar_pendente() is None
    assert sorted(p.name for p in shared.games_dir.iterdir()) == [
        "imported_1.json", "jogado_depois.json", "shortcuts_1.json"
    ]
    assert not _sobrou(shared.app_dir.with_name(shared.app_dir.name + ".anterior"))
