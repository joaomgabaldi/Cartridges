# conftest.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

r"""Harness de testes do Cartridges (PySide6 + QML).

Nenhum teste lê ou grava os dados reais do usuário: a fixture ``dados_temporarios``
aponta ``CARTRIDGES_DADOS`` para uma pasta temporária e ``CARTRIDGES_REGISTRO`` para
uma subchave temporária de ``HKCU\Software\CartridgesTestes``.
"""

import builtins
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import uuid
import winreg
import winsound
from pathlib import Path
from urllib.parse import urlsplit
from typing import Any

import pytest
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_RAIZ_REGISTRO = r"Software\CartridgesTestes"
# Referências guardadas na importação: um teste que troca `winreg.OpenKey` ainda
# está com o monkeypatch ativo quando a limpeza abaixo roda.
_abrir_chave, _enum_chave, _apagar = winreg.OpenKey, winreg.EnumKey, winreg.DeleteKey


def _apagar_chave(raiz: int, caminho: str) -> None:
    try:
        with _abrir_chave(raiz, caminho, 0, winreg.KEY_ALL_ACCESS) as chave:
            while True:
                try:
                    filha = _enum_chave(chave, 0)
                except OSError:
                    break
                _apagar_chave(raiz, f"{caminho}\\{filha}")
    except FileNotFoundError:
        return
    _apagar(raiz, caminho)


# Antes de qualquer `import cartridges`: o `shared` real calcula os caminhos ao ser importado,
# e sem isso cairia nos dados reais do usuário. Cada teste ganha a sua própria pasta e subchave
# (`dados_temporarios`); estas valem para o que roda na importação e entre testes.
_DADOS_DA_SESSAO = tempfile.mkdtemp(prefix="cartridges-testes-")
_REGISTRO_DA_SESSAO = f"{_RAIZ_REGISTRO}\\sessao-{uuid.uuid4()}"
os.environ["CARTRIDGES_DADOS"] = _DADOS_DA_SESSAO
os.environ["CARTRIDGES_REGISTRO"] = _REGISTRO_DA_SESSAO


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    _apagar_chave(winreg.HKEY_CURRENT_USER, _REGISTRO_DA_SESSAO)
    shutil.rmtree(_DADOS_DA_SESSAO, ignore_errors=True)


# Testes que ainda dependem do `gi` (direta ou indiretamente), em ordem alfabética.
# Cada plano que porta o módulo tira o teste daqui; a fase final exige a lista vazia.
TESTES_AINDA_GTK: list[str] = [
    "test_abertura.py",
    "test_app_updater.py",
    "test_area_de_trabalho_oculta.py",
    "test_assistente.py",
    "test_auditoria_0918_fitas.py",
    "test_auditoria_0918_importadores.py",
    "test_auditoria_0918_store.py",
    "test_auditoria_0918_ui.py",
    "test_auditoria_0923_resto.py",
    "test_auditoria_0923_zerados.py",
    "test_auditoria_1023_seguranca.py",
    "test_backup.py",
    "test_botao_novidades.py",
    "test_buscar_atualizacoes_ui.py",
    "test_caixa_redimensionavel.py",
    "test_calibracao_janela.py",
    "test_conquistas_ciclo.py",  # importa utils/backup (plano 8, D56) e tests.test_zerados (GTK)
    "test_conquistas_ea_janela.py",
    "test_conquistas_epic_janela.py",
    "test_conquistas_preferencias.py",
    "test_conquistas_ui.py",
    "test_estilo_css.py",
    "test_fita_wizard.py",
    "test_hwnd_ordem_import.py",
    "test_janela_por_cima.py",
    "test_janela_restaurando.py",
    "test_ler_json.py",
    "test_log_engolidos.py",
    "test_log_excecoes.py",
    "test_menu_do_card.py",
    "test_metadata_refresh.py",
    "test_na_tela.py",
    "test_preferencias_big_picture.py",
    "test_redefinir.py",
    "test_reinicio.py",
    "test_restauracao_dialogs.py",
    "test_saves_backup.py",
    "test_saves_conferencia.py",
    "test_saves_config.py",
    "test_saves_ludusavi_real.py",
    "test_saves_pasta.py",
    "test_saves_ui.py",
    "test_session_fita_preferencias.py",
    "test_store_ligacao_manual.py",
    "test_tarefas_trabalhos.py",
    "test_tarefas_ui.py",
    "test_tela_de_download.py",
    "test_ui_logic.py",
    "test_zerados.py",
    "test_zerados_manuais.py",
]

collect_ignore = TESTES_AINDA_GTK

# Como em `cartridges.in`: o texto da interface passa por `_()` já na definição das classes.
builtins._ = lambda message: message  # type: ignore[attr-defined]
builtins.ngettext = (  # type: ignore[attr-defined]
    lambda singular, plural, n: singular if n == 1 else plural
)


class FakeToastQueue:
    def __init__(self) -> None:
        self.added: list = []
        self.dismissed: list = []

    def add(self, toast) -> None:
        self.added.append(toast)

    def dismiss(self, toast) -> None:
        self.dismissed.append(toast)

    def dismiss_after(self, toast, _seconds) -> None:
        self.dismissed.append(toast)


class FakeAction:
    def __init__(self) -> None:
        self.enabled = True

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled


class FakeApplication:
    """``Game.__init__`` takes a reference to the application."""

    def __init__(self) -> None:
        self.state = AppState.DEFAULT
        self.activated: list = []
        self._actions: dict = {}

    def activate_action(self, name, target=None) -> None:
        self.activated.append((name, target))

    def lookup_action(self, name) -> FakeAction:
        return self._actions.setdefault(name, FakeAction())


class FakeWindow:
    """Only what the store, the session and a Game reach for."""

    def __init__(self) -> None:
        self.game_covers: dict = {}
        self.toasts: dict = {}
        self.toast_queue = FakeToastQueue()
        self.session_blocker_shown: list = []
        self.notes_toast_games: list = []
        self.presented = 0
        self.application = FakeApplication()

    def get_application(self) -> FakeApplication:
        return self.application

    # DetailsDialog snapshots and restores the library's scroll position so
    # editing a game does not move the grid underneath the user.
    def store_library_scroll(self) -> None:
        self.scroll_stored = True

    def restore_library_scroll(self) -> None:
        self.scroll_restored = True

    def show_session_blocker(self, game: Any) -> None:
        self.session_blocker_shown.append(game)

    def hide_session_blocker(self) -> None:
        self.session_blocker_shown.append(None)

    def session_toast(self, game: Any, seconds: int) -> None:
        """O aviso de fim de sessão é montado pela janela de verdade.

        Delegado em vez de imitado: é ali que mora a regra de não interpretar o
        título como markup, e um duplo aqui a testaria no lugar dela.
        """
        from cartridges.window import CartridgesWindow  # noqa: PLC0415

        CartridgesWindow.session_toast(self, game, seconds)

    def on_session_toast_notes(self, _toast: Any, game: Any) -> None:
        self.notes_toast_games.append(game)

    def present(self) -> None:
        self.presented += 1


from cartridges import shared  # noqa: E402
from cartridges.configuracoes import Configuracoes  # noqa: E402

AppState = shared.AppState

# `import_time` fixo, como antes.
shared.import_time = 1_700_000_000


@pytest.fixture(autouse=True)
def import_time_fixo(monkeypatch):
    """Um `Importer` grava `shared.import_time` com a hora de agora; o teste seguinte não pode herdá-la."""
    monkeypatch.setattr(shared, "import_time", 1_700_000_000, raising=False)


# O `ludusavi.exe` desta máquina nunca roda nos testes. O corte é na sessão toda, e não num
# monkeypatch por teste: uma thread de backup que sobrevive ao seu teste acorda com
# `sys.executable` e `shared.app_dir` já desfeitos, acharia o Ludusavi daqui e o rodaria
# sobre a pasta de lugar nenhum. (Foi o que aconteceu em 11/10/2026: ele baixou o manifesto
# de 17 MB para `tests/_unset` e criou `~/ludusavi-backup`.) Por isso `ludusavi.executavel`
# vira um embrulho que só devolve um exe que mora dentro do basetemp do pytest, seja qual for
# o `sys.executable`. Quem quer um exe "presente" pede `ludusavi_de_verdade` (um de mentira,
# em `tmp_path`); só o teste de integração de propósito usa `ludusavi_real_da_maquina`.
from cartridges.saves import ludusavi as _ludusavi

EXECUTAVEL_DE_VERDADE = _ludusavi.executavel
_basetemp: Path | None = None  # preenchido no início da sessão por `basetemp_do_ludusavi`


def _executavel_so_no_basetemp() -> Path | None:
    exe = EXECUTAVEL_DE_VERDADE()
    if exe is not None and _basetemp is not None and _basetemp in exe.resolve().parents:
        return exe
    return None


_ludusavi.executavel = _executavel_so_no_basetemp


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def app_dirs(tmp_path, monkeypatch):
    """Point every data directory at a fresh tmp dir, for every test.

    Autouse on purpose: forgetting it would mean a test writing into the real
    library, and that failure mode is silent and unrecoverable.
    """
    games = tmp_path / "games"
    covers = tmp_path / "covers"
    logos = tmp_path / "logos"
    wallpapers = tmp_path / "wallpapers"
    logs = tmp_path / "logs"
    for directory in (games, covers, logos, wallpapers, logs):
        directory.mkdir(parents=True)

    monkeypatch.setattr(shared, "home", tmp_path, raising=False)
    monkeypatch.setattr(shared, "data_dir", tmp_path, raising=False)
    monkeypatch.setattr(shared, "app_dir", tmp_path, raising=False)
    monkeypatch.setattr(shared, "games_dir", games, raising=False)
    monkeypatch.setattr(shared, "covers_dir", covers, raising=False)
    monkeypatch.setattr(shared, "logos_dir", logos, raising=False)
    monkeypatch.setattr(shared, "wallpapers_dir", wallpapers, raising=False)
    monkeypatch.setattr(shared, "log_dir", logs, raising=False)
    # Not created: the fita code makes it on first write, like the real app.
    monkeypatch.setattr(shared, "fitas_dir", tmp_path / "fitas", raising=False)
    monkeypatch.setattr(shared, "conquistas_dir", tmp_path / "conquistas", raising=False)
    monkeypatch.setattr(
        shared, "conquistas_cache_dir", tmp_path / "cache" / "conquistas", raising=False
    )
    # Not created: quem gera as cópias cria a pasta na primeira gravação.
    monkeypatch.setattr(
        shared, "capas_animadas_dir", tmp_path / "cache" / "capas_animadas", raising=False
    )
    monkeypatch.setattr(shared, "contas_dir", tmp_path / "contas", raising=False)
    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json", raising=False)
    monkeypatch.setattr(
        shared, "tuya_conta_arquivo", tmp_path / "tuya_conta.json", raising=False
    )
    return types.SimpleNamespace(
        root=tmp_path,
        games=games,
        covers=covers,
        logos=logos,
        wallpapers=wallpapers,
        logs=logs,
    )


@pytest.fixture(autouse=True)
def chave_do_registro(monkeypatch):
    """Uma subchave de registro nova por teste, dentro da da sessão (apagada no fim dela)."""
    chave = _REGISTRO_DA_SESSAO + "\\" + uuid.uuid4().hex
    monkeypatch.setattr(shared, "chave_do_registro", chave, raising=False)
    return chave


@pytest.fixture(autouse=True)
def schema(monkeypatch, chave_do_registro):
    """Preferências nos padrões do gschema, numa subchave temporária própria do teste."""
    real = Configuracoes(chave_do_registro, "@APP_ID@")
    monkeypatch.setattr(shared, "schema", real, raising=False)
    return real


@pytest.fixture(autouse=True)
def state_schema(monkeypatch, chave_do_registro):
    real = Configuracoes(chave_do_registro + r"\State", "@APP_ID@.State")
    monkeypatch.setattr(shared, "state_schema", real, raising=False)
    return real


@pytest.fixture(autouse=True)
def sem_som(monkeypatch):
    """Nenhum teste toca som de verdade: cada `PlaySound` vira um `(dados, flags)` nesta lista."""
    tocados = []
    monkeypatch.setattr(winsound, "PlaySound", lambda dados, flags: tocados.append((dados, flags)))
    return tocados


@pytest.fixture(autouse=True)
def sem_cortina_de_verdade(monkeypatch):
    """Nenhum teste abre a janela preta TOPMOST do fade: sem a fábrica falsa, a cortina falha ao criar."""
    from cartridges.utils import cortina_monitor  # noqa: PLC0415

    def recusa():
        raise OSError("cortina de verdade nos testes")

    monkeypatch.setattr(cortina_monitor, "_api", recusa)


@pytest.fixture(autouse=True)
def win(monkeypatch):
    fake = FakeWindow()
    monkeypatch.setattr(shared, "win", fake, raising=False)
    return fake


@pytest.fixture(autouse=True)
def sem_jogo_de_verdade(monkeypatch):
    """Nenhum teste inicia um jogo: o `launch` que chegar ao `run_executable` falha alto.

    Também zera a sessão: o `ModeloDaSessao` (`shared.sessao`) e os rastreadores ativos não passam de um teste ao outro.
    """
    from cartridges import jogo, process_session, session_window  # noqa: PLC0415

    def recusa(*_args, **_kwargs):
        raise AssertionError("run_executable: nenhum jogo é iniciado nos testes")

    monkeypatch.setattr(jogo, "run_executable", recusa)
    monkeypatch.setattr(shared, "sessao", None, raising=False)
    monkeypatch.setattr(shared, "conquistas", None, raising=False)
    monkeypatch.setattr(process_session.ProcessSession, "active", None)
    monkeypatch.setattr(session_window.SessionWindow, "active", None)


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    """Nenhum teste fala com a rede (D57): tudo do app sai por `requests`, e o envio vira uma falha de conexão."""
    import requests  # noqa: PLC0415

    enviar = requests.sessions.Session.send

    def recusa(self, requisicao, **kwargs):
        # O laço local (servidor de teste em 127.0.0.1) não é rede.
        if urlsplit(requisicao.url).hostname not in ("127.0.0.1", "localhost", "::1"):
            raise requests.ConnectionError("rede bloqueada nos testes")
        kwargs["proxies"] = {}  # nem um proxy de ambiente recebe o tráfego do laço local
        return enviar(self, requisicao, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "send", recusa)


@pytest.fixture(autouse=True)
def fila_da_principal_vazia(app_qt, app_dirs, schema):  # noqa: ARG001
    """O que um teste deixou na fila da thread principal (`na_thread_principal`) acaba antes do teste seguinte."""
    yield
    QCoreApplication.processEvents()


@pytest.fixture
def flush_idle(app_qt):  # noqa: ARG001
    """Gira o laço de eventos por um instante: o que foi enfileirado para a thread principal chega."""

    def girar(limite=0.1):
        fim = time.monotonic() + limite
        while time.monotonic() < fim:
            laco = QEventLoop()
            QTimer.singleShot(10, laco.quit)
            laco.exec()

    return girar


class AvisosAnotados:
    """No lugar da `FilaDeAvisos`: guarda os textos e a última chamada inteira."""

    def __init__(self) -> None:
        self.textos: list[str] = []
        self.ultima: dict | None = None

    def adicionar(self, texto, botao="", ao_clicar=None, segundos=5, chave=None) -> int:
        self.textos.append(texto)
        self.ultima = {"texto": texto, "botao": botao, "ao_clicar": ao_clicar, "segundos": segundos, "chave": chave}
        return len(self.textos)


@pytest.fixture
def avisos(monkeypatch):
    """Os avisos que o app mostraria, em `shared.aplicativo` (sem varredura de conquistas)."""
    anotados = AvisosAnotados()
    monkeypatch.setattr(
        shared, "aplicativo", types.SimpleNamespace(avisos=anotados, varredura_conquistas=None), raising=False
    )
    return anotados


@pytest.fixture(autouse=True)
def sem_steam_no_registro(monkeypatch):
    """A Steam desta máquina (se houver) não entra nos testes: quem precisa de
    uma Steam monta a sua em ``tmp_path``."""
    try:
        from cartridges.conquistas import arquivos  # noqa: PLC0415
    except ImportError:  # ainda depende do gi
        return

    monkeypatch.setattr(arquivos, "_valor_do_registro", lambda *_a: None)
    monkeypatch.setattr(arquivos, "_inteiro_do_registro", lambda *_a: None)


@pytest.fixture(autouse=True)
def sem_ubisoft_no_registro(monkeypatch):
    """Os jogos da Ubisoft instalados nesta máquina (se houver) não entram nos testes:
    quem precisa de instalações troca `locais._do_registro`."""
    try:
        from cartridges.conquistas.ubisoft import locais  # noqa: PLC0415
    except ImportError:  # ainda depende do gi
        return

    monkeypatch.setattr(locais, "_do_registro", lambda: {})


@pytest.fixture(autouse=True)
def sem_ea_no_registro(monkeypatch):
    """Os jogos da EA instalados nesta máquina (se houver) não entram nos testes:
    quem precisa de instalações troca `ea.jogo.chaves_do_registro`."""
    try:
        from cartridges.conquistas.ea import jogo  # noqa: PLC0415
    except ImportError:  # ainda depende do gi
        return

    monkeypatch.setattr(jogo, "chaves_do_registro", lambda: [])


@pytest.fixture(autouse=True)
def sem_ludusavi(request, monkeypatch):
    """O Ludusavi desta máquina (se houver um ao lado do Python) não roda nos testes:
    o fim de uma sessão dispararia um backup de verdade. Os testes dos saves montam o
    seu próprio executor e ficam de fora; os demais que precisem dele disponível
    trocam `backup_de_saves.disponivel`."""
    if request.module.__name__.startswith("test_saves_"):
        return
    try:
        from cartridges.saves import backup_de_saves  # noqa: PLC0415
    except ImportError:  # ainda depende do gi
        return

    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: False)


@pytest.fixture(scope="session", autouse=True)
def basetemp_do_ludusavi(tmp_path_factory):
    """Diz à guarda de `ludusavi.executavel` onde fica o basetemp; fora da sessão, nada passa."""
    global _basetemp  # pylint: disable=global-statement
    _basetemp = tmp_path_factory.getbasetemp().resolve()
    yield
    _basetemp = None


@pytest.fixture
def ludusavi_de_verdade(tmp_path, monkeypatch):
    """Um Python de mentira em `tmp_path`: o `ludusavi.executavel` (a função real, atrás da
    guarda) olha só para lá, e quem pede a fixture põe, ou não, um `ludusavi.exe` ao lado."""
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))


@pytest.fixture
def ludusavi_real_da_maquina(monkeypatch):
    """OPT-IN DE PROPÓSITO (Task 10, teste de integração): tira a guarda e deixa
    `ludusavi.executavel` achar o `ludusavi.exe` verdadeiro desta máquina. Nenhum outro
    teste deve pedir; quem pede só pode rodá-lo sobre `tmp_path` (config e backups)."""
    monkeypatch.setattr(_ludusavi, "executavel", EXECUTAVEL_DE_VERDADE)


@pytest.fixture(autouse=True)
def sem_thread_de_backup_sobrando():
    """Uma thread de trabalho dos saves que sobra depois do teste roda com o ambiente
    já desfeito: o teste que a abriu tem de esperá-la (`esperar`)."""
    yield
    sobraram = [
        thread.name
        for thread in threading.enumerate()
        if thread.is_alive()
        and getattr(getattr(thread, "_target", None), "__module__", "")
        == "cartridges.saves.backup_de_saves"
    ]
    assert not sobraram, f"threads de backup_de_saves ainda vivas depois do teste: {sobraram}"


class _FakeSinal:
    """Um sinal do `Jogo` que só anota quem a store ligou nele."""

    def __init__(self, nome: str, ligacoes: list) -> None:
        self.nome = nome
        self.ligacoes = ligacoes

    def connect(self, callback, _tipo=None) -> None:
        self.ligacoes.append((self.nome, callback))


class FakeGame:
    """Duck-type standing in for ``Jogo`` in store tests.

    The store never needs a real ``Jogo`` — it reads a handful of fields and
    calls ``save``/``update`` — so the fake keeps these tests about the store. ``saves`` is a counter because several tests are precisely
    about how *many* times a scan writes a record.
    """

    def __init__(self, **overrides) -> None:
        self.source = overrides.pop("source", "shortcuts")
        self.game_id = overrides.pop("game_id", "shortcuts_0000000000000000")
        self.name = overrides.pop("name", "Test Game")
        self.executable = overrides.pop("executable", 'start "" "C:\\g\\game.exe"')
        self.shortcut_path = overrides.pop("shortcut_path", "")
        self.shortcut_mtime = overrides.pop("shortcut_mtime", 0)
        self.removed = overrides.pop("removed", False)
        self.blacklisted = overrides.pop("blacklisted", False)
        self.playtime = overrides.pop("playtime", 0)
        self.version = overrides.pop("version", shared.SPEC_VERSION)
        self.added = overrides.pop("added", 0)
        self.last_played = overrides.pop("last_played", 0)
        self.developer = overrides.pop("developer", None)
        self.run_as_admin = overrides.pop("run_as_admin", False)
        self.track_process = overrides.pop("track_process", False)
        self.process_executable = overrides.pop("process_executable", "")
        self.status = overrides.pop("status", "")
        self.notes = overrides.pop("notes", "")
        self.rating = overrides.pop("rating", 0)
        self.track_updates = overrides.pop("track_updates", False)
        self.steam_appid = overrides.pop("steam_appid", None)
        self.conquistas = overrides.pop("conquistas", True)
        self.ludusavi_nome = overrides.pop("ludusavi_nome", "")
        self.saves_local_desconhecido_avisado = overrides.pop("saves_local_desconhecido_avisado", False)
        self.backup_dos_saves_desligado = overrides.pop("backup_dos_saves_desligado", False)
        for key, value in overrides.items():
            setattr(self, key, value)
        # Derived exactly the way Jogo.__init__ derives it.
        self.base_source = self.source.split("_")[0]
        self.saves = 0
        self.updates = 0
        self.signals: list = []
        self.salvar = _FakeSinal("salvar", self.signals)
        self.atualizado = _FakeSinal("atualizado", self.signals)

    def save(self) -> None:
        self.saves += 1

    def update(self) -> None:
        self.updates += 1

    def update_values(self, data: dict) -> None:
        # Duck-types Jogo.update_values (plain setattr, no _KNOWN_KEYS
        # filtering).
        for key, value in data.items():
            setattr(self, key, value)

    @property
    def zerado(self) -> bool:
        # A mesma regra de Jogo.zerado.
        return self.removed and not self.blacklisted and self.status == "beaten"

    def get_cover_path(self) -> Path | None:
        # Duck-types Jogo.get_cover_path: the backup exporter calls this on
        # whatever `shared.store` holds, real Jogo or this fake.
        from cartridges.utils.save_cover import ANIMATED_SUFFIXES  # noqa: PLC0415

        for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
            cover_path = shared.covers_dir / f"{self.game_id}{suffix}"
            if cover_path.is_file():
                return cover_path
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FakeGame {self.game_id} removed={self.removed}>"


@pytest.fixture
def make_game():
    """Factory for store-facing game records."""

    def factory(**overrides) -> FakeGame:
        return FakeGame(**overrides)

    return factory


@pytest.fixture
def store():
    """A clean ``Store`` with no managers registered.

    No managers means ``add_game`` connects no signals and runs no pipeline
    work, which is what keeps these tests about bookkeeping.
    """
    from cartridges.store.store import Store  # noqa: PLC0415

    instance = Store()
    shared.store = instance
    yield instance
    shared.store = None


@pytest.fixture
def write_record(app_dirs):
    """Write a game's JSON record the way ``FileManager`` would."""

    def writer(game_id: str, **fields) -> Path:
        path = app_dirs.games / f"{game_id}.json"
        data = {"game_id": game_id, "source": "shortcuts", "name": "Test Game"}
        data.update(fields)
        path.write_text(json.dumps(data, indent=4, sort_keys=True), encoding="utf-8")
        return path

    return writer


@pytest.fixture
def write_asset(app_dirs):
    """Drop a cover/logo file so migrations have something real to move."""

    def writer(directory: str, name: str, content: bytes = b"x") -> Path:
        target = getattr(app_dirs, directory) / name
        target.write_bytes(content)
        return target

    return writer


@pytest.fixture(autouse=True)
def sem_area_de_trabalho(monkeypatch):
    """O papel de parede de verdade da área de trabalho nunca é tocado: sem COM nos testes.

    Quem precisa da `IDesktopWallpaper` troca `_AreaDeTrabalho` por um falso.
    """

    def proibida(*_args, **_kwargs):
        raise AssertionError("o teste tentou abrir a área de trabalho de verdade (IDesktopWallpaper)")

    from cartridges.utils import session_wallpaper  # noqa: PLC0415

    monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", proibida)


@pytest.fixture(autouse=True)
def sem_fita_de_verdade(monkeypatch):
    """Nenhum teste fala com uma fita de LED: o `_dispositivo` (a tinytuya, com rede) falha alto.

    Quem prova a conversa troca `_dispositivo` por um módulo falso (`falsas`, de `tests/apoio_fita.py`).
    """
    from cartridges.utils import session_fita  # noqa: PLC0415

    def proibido(*_args, **_kwargs):
        raise AssertionError("o teste tentou falar com uma fita de verdade (tinytuya)")

    monkeypatch.setattr(session_fita, "_dispositivo", proibido)


@pytest.fixture(autouse=True)
def dados_temporarios(tmp_path, monkeypatch):
    """Pasta e subchave de registro próprias de cada teste (as da sessão ficam no topo do arquivo)."""
    registro = f"{_RAIZ_REGISTRO}\\{uuid.uuid4()}"
    monkeypatch.setenv("CARTRIDGES_DADOS", str(tmp_path))
    monkeypatch.setenv("CARTRIDGES_REGISTRO", registro)
    yield tmp_path
    _apagar_chave(winreg.HKEY_CURRENT_USER, registro)


@pytest.fixture(scope="session", autouse=True)
def app_qt():
    """Uma única `QGuiApplication` para a sessão toda, sem janela na tela."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

    app = QGuiApplication.instance() or QGuiApplication([])
    yield app
