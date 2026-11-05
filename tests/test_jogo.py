# test_jogo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`Jogo`: o modelo do jogo e as regras de domínio."""

import json
import os
import subprocess
import sys
import threading

import pytest
from PySide6.QtCore import Qt

from cartridges import shared
from cartridges.jogo import PERSISTED_ATTRS, STATUS_LABELS, Jogo, status_label


def _jogo(**campos) -> Jogo:
    dados = {
        "game_id": "shortcuts_1",
        "source": "shortcuts",
        "name": "Probe",
        "executable": "x.exe",
        "added": 0,
    }
    dados.update(campos)
    return Jogo(dados)


def _contar(sinal) -> list:
    emitidos = []
    sinal.connect(lambda *args: emitidos.append(args), Qt.ConnectionType.DirectConnection)
    return emitidos


def test_as_chaves_gravadas_sao_as_da_versao_gtk():
    """A ficha em `games/*.json` é lida também pela versão anterior (GTK): nenhuma chave
    renomeada, acrescentada ou retirada, e na mesma ordem."""
    assert PERSISTED_ATTRS == (
        "added", "executable", "game_id", "source", "last_played", "playtime",
        "status", "rating", "notes", "name", "developer", "publisher",
        "release_date", "metacritic", "steam_review", "genre",
        "controller_support", "gamepad_recommended", "description",
        "steam_checked", "steam_appid", "hltb_id", "hltb_main",
        "hltb_main_extra", "hltb_completionist", "hltb_chapters", "removed",
        "blacklisted", "version", "install_size", "install_size_ts",
        "shortcut_mtime", "shortcut_path", "run_as_admin", "track_process",
        "process_executable", "track_updates", "update_available_ts",
        "update_dismissed_ts", "update_url", "conquistas", "ludusavi_nome",
        "saves_local_desconhecido_avisado", "backup_dos_saves_desligado",
        "comando_a_conferir", "inis", "idioma_proprio", "nome_proprio", "appid_manual",
        "idiomas_steam",
    )  # fmt: skip


def test_padroes_de_uma_ficha_minima():
    jogo = _jogo()
    gravado = {chave: getattr(jogo, chave) for chave in PERSISTED_ATTRS}
    assert gravado["version"] == shared.SPEC_VERSION
    assert gravado["developer"] is None and gravado["hltb_chapters"] is None
    assert gravado["conquistas"] is True
    assert gravado["status"] == "" and gravado["rating"] == 0
    assert jogo.base_source == "shortcuts"
    json.dumps(gravado)  # tudo serializável


def test_status_labels():
    assert list(STATUS_LABELS) == ["backlog", "playing", "beaten", "dropped"]
    assert status_label("beaten") == "Zerado"
    assert status_label("banana") == ""
    assert status_label("") == ""


def test_zerado():
    assert _jogo(removed=True, status="beaten").zerado
    assert not _jogo(removed=False, status="beaten").zerado
    assert not _jogo(removed=True, blacklisted=True, status="beaten").zerado
    assert not _jogo(removed=True, status="playing").zerado


def test_desmarcar_zerado_com_atalho_volta_a_biblioteca(tmp_path):
    atalho = tmp_path / "jogo.lnk"
    atalho.write_bytes(b"")
    jogo = _jogo(removed=True, status="beaten", shortcut_path=str(atalho))

    jogo.definir_status("playing")

    assert jogo.status == "playing"
    assert jogo.removed is False


def test_desmarcar_zerado_sem_atalho_vira_desinstalado(tmp_path):
    jogo = _jogo(
        removed=True, status="beaten", shortcut_path=str(tmp_path / "sumiu.lnk")
    )
    jogo.definir_status("")
    assert jogo.removed is True

    sem_executavel = _jogo(removed=True, status="beaten", executable="")
    sem_executavel.definir_status("")
    assert sem_executavel.removed is True


def test_dismiss_update_guarda_o_maior_e_salva():
    jogo = _jogo(
        track_updates=True,
        update_available_ts=200,
        update_dismissed_ts=100,
        update_url="https://exemplo",
    )
    assert jogo.has_update
    salvos, atualizados = _contar(jogo.salvar), _contar(jogo.atualizado)

    jogo.dismiss_update()

    assert jogo.update_dismissed_ts == 200
    assert jogo.update_available_ts == 0 and jogo.update_url == ""
    assert not jogo.has_update
    assert len(salvos) == 1 and len(atualizados) == 1

    antigo = _jogo(update_available_ts=50, update_dismissed_ts=100)
    antigo.dismiss_update()
    assert antigo.update_dismissed_ts == 100


def test_stars_tolera_valor_editado_a_mao():
    assert _jogo(rating=3).stars == 3
    assert _jogo(rating=9).stars == 5
    assert _jogo(rating=-1).stars == 0
    assert _jogo(rating="ótimo").stars == 0
    assert _jogo().stars == 0


def test_hltb():
    assert not _jogo().has_hltb_times
    assert _jogo(hltb_main=10).hltb_times == (10, None, None)
    assert _jogo(hltb_chapters=[{"number": 1}]).has_hltb_times


def test_update_values_ignora_chave_desconhecida():
    jogo = _jogo()
    jogo.update_values({"launch": "x", "save": 1, "atualizado": 2, "inventada": 3, "name": "Novo"})

    assert callable(jogo.launch) and callable(jogo.save)
    assert not hasattr(jogo, "inventada")
    assert jogo.name == "Novo"
    jogo.update()  # o sinal continua sendo um sinal


def test_get_cover_path_prefere_a_animada(app_dirs):
    jogo = _jogo()
    assert jogo.get_cover_path() is None

    tiff = app_dirs.covers / "shortcuts_1.tiff"
    tiff.write_bytes(b"x")
    assert jogo.get_cover_path() == tiff

    gif = app_dirs.covers / "shortcuts_1.gif"
    gif.write_bytes(b"x")
    assert jogo.get_cover_path() == gif


def test_get_cover_path_acha_a_capa_apng(app_dirs):
    apng = app_dirs.covers / "shortcuts_1.apng"
    apng.write_bytes(b"x")
    assert _jogo().get_cover_path() == apng


def test_save_e_update_emitem_os_sinais():
    jogo = _jogo()
    salvos, atualizados = _contar(jogo.salvar), _contar(jogo.atualizado)
    jogo.save()
    jogo.update()
    jogo.update()
    assert len(salvos) == 1 and len(atualizados) == 2


def test_jogo_criado_e_emitido_numa_thread_de_trabalho():
    """O importador cria e salva jogos fora da thread principal."""
    vistos = []

    def trabalho():
        jogo = _jogo()
        jogo.salvar.connect(
            lambda: vistos.append(threading.current_thread().name),
            Qt.ConnectionType.DirectConnection,
        )
        jogo.save()
        jogo.update()

    thread = threading.Thread(target=trabalho, name="importador")
    thread.start()
    thread.join()

    assert vistos == ["importador"]


def test_remove_game_avisa_com_desfazer():
    jogo = _jogo(name="Probe")
    avisos, salvos = _contar(jogo.aviso), _contar(jogo.salvar)

    jogo.remove_game()

    assert jogo.removed is True
    assert len(salvos) == 1
    assert avisos == [("Probe removido", "remove")]

    zerado = _jogo(name="Fim", status="beaten")
    avisos = _contar(zerado.aviso)
    zerado.remove_game()
    assert avisos == [("Fim movido para Jogos Zerados", "remove")]


@pytest.fixture
def executados(monkeypatch):
    from cartridges import jogo as modulo  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(modulo, "run_executable", lambda *args: chamadas.append(args))
    return chamadas


def test_launch_roda_e_avisa(executados):
    jogo = _jogo(name="Probe", executable="game.exe", run_as_admin=True)
    avisos, salvos = _contar(jogo.aviso), _contar(jogo.salvar)
    saidas = _contar(jogo.sair_da_frente)

    assert jogo.launch() is True

    assert executados == [("game.exe", True)]
    assert jogo.last_played > 0
    assert len(salvos) == 1
    assert avisos == [("Probe iniciado", "")]
    assert saidas == []


def test_launch_sai_da_frente_com_a_preferencia(executados, schema):
    schema.set_boolean("minimize-after-launch", True)
    jogo = _jogo()
    saidas = _contar(jogo.sair_da_frente)

    jogo.launch()

    assert len(saidas) == 1


def test_comando_restaurado_pede_confirmacao(executados):
    jogo = _jogo(executable="cmd‮.exe", comando_a_conferir=True)
    pedidos, salvos = _contar(jogo.confirmar_comando), _contar(jogo.salvar)

    assert jogo.launch() is False
    assert executados == []
    assert len(pedidos) == 1
    # Invisíveis aparecem como código no texto a conferir.
    assert jogo.comando_visivel == "cmd<U+202E>.exe"

    (confirmar,) = pedidos[0]
    confirmar()

    assert jogo.comando_a_conferir is False
    assert executados == [("cmd‮.exe", False)]
    assert len(salvos) == 2  # a confirmação e o lançamento


def test_comando_restaurado_relanca_pelo_ao_confirmar(executados):
    jogo = _jogo(comando_a_conferir=True)
    pedidos = _contar(jogo.confirmar_comando)
    relancados = []

    jogo.launch(ao_confirmar=lambda: relancados.append(True))
    pedidos[0][0]()

    assert relancados == [True]
    assert executados == []


class _SessaoQueAnota:
    def __init__(self, passos, moveu=False):
        self.passos, self.moveu = passos, moveu

    def move_to_session_monitor(self):
        self.passos.append("mover")
        return self.moveu

    def vibrar_abertura(self):
        self.passos.append("vibrar")


@pytest.fixture
def com_sessao(monkeypatch, schema):
    """Um `shared.sessao` que anota a ordem e rastreadores que só anotam o que fariam."""
    from cartridges import jogo as modulo  # noqa: PLC0415

    passos = []
    sessao = _SessaoQueAnota(passos)
    monkeypatch.setattr(shared, "sessao", sessao, raising=False)
    monkeypatch.setattr(modulo, "run_executable", lambda *args: passos.append("rodar"))

    class Processo:
        active = None

        def __init__(self, jogo):
            passos.append("processo")

        def start(self):
            passos.append("processo.start")

    class Manual:
        active = None

        def __init__(self, jogo):
            passos.append("manual")

        def present(self):
            passos.append("manual.present")

    monkeypatch.setattr(modulo, "ProcessSession", Processo)
    monkeypatch.setattr(modulo, "SessionWindow", Manual)
    schema.set_boolean("playtime-tracking", True)
    sessao.passos = passos
    return sessao


_POR_LOJA = 'start "" "steam://rungameid/1"'


def test_launch_rastreavel_comeca_por_processo_e_sai_da_frente(com_sessao):
    jogo = _jogo(track_process=True, process_executable="halo.exe")
    saidas = _contar(jogo.sair_da_frente)

    assert jogo.launch() is True

    assert com_sessao.passos == ["mover", "rodar", "vibrar", "processo", "processo.start"]
    assert len(saidas) == 1


def test_launch_nao_rastreavel_abre_a_manual(com_sessao):
    jogo = _jogo(executable=_POR_LOJA)
    saidas = _contar(jogo.sair_da_frente)

    jogo.launch()

    assert com_sessao.passos[-2:] == ["manual", "manual.present"]
    assert len(saidas) == 1


def test_launch_que_moveu_a_janela_nao_minimiza(com_sessao):
    com_sessao.moveu = True
    jogo = _jogo(track_process=True, process_executable="halo.exe")
    saidas = _contar(jogo.sair_da_frente)

    jogo.launch()

    assert saidas == [] and "processo.start" in com_sessao.passos


@pytest.mark.parametrize("minimizar", [False, True])
def test_launch_sem_rastreio_so_sai_da_frente_com_a_preferencia(com_sessao, schema, minimizar):
    schema.set_boolean("playtime-tracking", False)
    schema.set_boolean("minimize-after-launch", minimizar)
    jogo = _jogo(track_process=True, process_executable="halo.exe")
    saidas = _contar(jogo.sair_da_frente)

    jogo.launch()

    assert "processo" not in com_sessao.passos and "manual" not in com_sessao.passos
    assert len(saidas) == (1 if minimizar else 0)


def test_launch_em_tela_cheia_nao_sai_da_frente(com_sessao):
    jogo = _jogo(track_process=True, process_executable="halo.exe")
    saidas = _contar(jogo.sair_da_frente)

    assert jogo.launch(em_tela_cheia=True) is True

    assert "mover" not in com_sessao.passos and "processo.start" in com_sessao.passos
    assert saidas == []


def test_launch_em_tela_cheia_ignora_minimizar_ao_abrir(com_sessao, schema):
    schema.set_boolean("playtime-tracking", False)
    schema.set_boolean("minimize-after-launch", True)
    jogo = _jogo(track_process=True, process_executable="halo.exe")
    saidas = _contar(jogo.sair_da_frente)

    assert jogo.launch(em_tela_cheia=True) is True

    assert saidas == []


def test_segundo_launch_encerra_o_primeiro(com_sessao):
    """A sessão anterior é encerrada, com registro, antes de outra começar."""
    from cartridges import jogo as modulo  # noqa: PLC0415

    passos = com_sessao.passos

    class Anterior:
        def close(self):
            passos.append("manual.close")

        def stop(self, record):
            passos.append(("processo.stop", record))

    modulo.SessionWindow.active = Anterior()
    modulo.ProcessSession.active = Anterior()

    _jogo(track_process=True, process_executable="halo.exe").launch()

    assert passos == [
        "mover", "rodar", "vibrar", "manual.close", ("processo.stop", True), "processo", "processo.start",
    ]  # fmt: skip


def test_launch_sem_sessao_nao_rastreia(executados, schema):
    """Sem `shared.sessao` (os testes antigos), o launch só lança e avisa."""
    schema.set_boolean("playtime-tracking", True)
    assert shared.sessao is None

    assert _jogo(track_process=True, process_executable="halo.exe").launch() is True
    assert len(executados) == 1


def test_conftest_proibe_o_run_executable():
    with pytest.raises(AssertionError, match="nenhum jogo"):
        _jogo().launch()


def test_jogo_nao_importa_interface():
    codigo = (
        "import builtins, sys\n"
        "builtins._ = lambda m: m\n"
        "import cartridges.jogo\n"
        "proibidos = [m for m in sys.modules if m == 'gi' or m.startswith('gi.')"
        " or m in ('PySide6.QtQuick', 'PySide6.QtWidgets')]\n"
        "print(proibidos)\n"
    )
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    saida = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=raiz,
        capture_output=True,
        text=True,
        check=True,
    )
    assert saida.stdout.strip() == "[]"


def test_campos_dos_ini_toleram_tipo_errado():
    assert _jogo().inis is None and _jogo().idiomas_steam is None
    assert (_jogo().idioma_proprio, _jogo().nome_proprio, _jogo().appid_manual) == ("", "", False)
    jogo = _jogo(inis="x", idiomas_steam=3, idioma_proprio=1, nome_proprio=None)
    assert (jogo.inis, jogo.idiomas_steam, jogo.idioma_proprio, jogo.nome_proprio) == (None, None, "", "")
    assert _jogo(inis=["a"]).inis == ["a"]
    assert _jogo(inis=["a", 3]).inis is None
