# conftest.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

r"""Harness de testes do Cartridges (PySide6 + QML).

Nenhum teste lê ou grava os dados reais do usuário: a fixture ``dados_temporarios``
aponta ``KYRON_DADOS`` para uma pasta temporária e ``KYRON_REGISTRO`` para
uma subchave temporária de ``HKCU\Software\KyronTestes``.
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

_RAIZ_REGISTRO = r"Software\KyronTestes"
from tests.apoio_registro import _apagar_chave  # noqa: E402


# Antes de qualquer `import kyron`: o `shared` calcula os caminhos ao ser importado e cairia nos dados reais.
_DADOS_DA_SESSAO = tempfile.mkdtemp(prefix="kyron-testes-")
_REGISTRO_DA_SESSAO = f"{_RAIZ_REGISTRO}\\sessao-{uuid.uuid4()}"
os.environ["KYRON_DADOS"] = _DADOS_DA_SESSAO
os.environ["KYRON_REGISTRO"] = _REGISTRO_DA_SESSAO
os.environ["KYRON_LOG_DETALHADO"] = "0"


def pytest_configure(config):
    config.addinivalue_line("markers", "varredura_real: o teste prova a `enderecos_na_rede` de verdade (com a tinytuya falsa)")


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    _apagar_chave(winreg.HKEY_CURRENT_USER, _REGISTRO_DA_SESSAO)
    shutil.rmtree(_DADOS_DA_SESSAO, ignore_errors=True)


builtins._ = lambda message: message  # type: ignore[attr-defined]
builtins.ngettext = (  # type: ignore[attr-defined]
    lambda singular, plural, n: singular if n == 1 else plural
)


from kyron import shared  # noqa: E402
from kyron.utils import window_geometry as _window_geometry  # noqa: E402

_MONITORS_REAL = _window_geometry.monitors
from kyron.configuracoes import Configuracoes  # noqa: E402

shared.import_time = 1_700_000_000


@pytest.fixture(autouse=True)
def import_time_fixo(monkeypatch):
    """Um `Importer` grava `shared.import_time` com a hora de agora; o teste seguinte não pode herdá-la."""
    monkeypatch.setattr(shared, "import_time", 1_700_000_000, raising=False)


# O corte do Ludusavi é na sessão toda, e não num monkeypatch por teste: uma thread de backup que sobrevive ao seu
# teste acorda com `sys.executable` e `shared.app_dir` já desfeitos e rodaria o Ludusavi desta máquina sobre a pasta
# errada (já baixou o manifesto para `tests/_unset` e criou `~/ludusavi-backup`). Por isso `executavel` só devolve
# um exe que mora dentro do basetemp; quem quer um "presente" pede `ludusavi_de_verdade`.
from kyron.saves import ludusavi as _ludusavi

EXECUTAVEL_DE_VERDADE = _ludusavi.executavel
_basetemp: Path | None = None


def _executavel_so_no_basetemp() -> Path | None:
    exe = EXECUTAVEL_DE_VERDADE()
    if exe is not None and _basetemp is not None and _basetemp in exe.resolve().parents:
        return exe
    return None


_ludusavi.executavel = _executavel_so_no_basetemp


@pytest.fixture(autouse=True)
def app_dirs(tmp_path, monkeypatch):
    """Aponta todas as pastas de dados para uma pasta temporária nova, em todo teste."""
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
    monkeypatch.setattr(shared, "fitas_dir", tmp_path / "fitas", raising=False)
    monkeypatch.setattr(shared, "conquistas_dir", tmp_path / "conquistas", raising=False)
    monkeypatch.setattr(
        shared, "conquistas_cache_dir", tmp_path / "cache" / "conquistas", raising=False
    )
    monkeypatch.setattr(
        shared, "capas_animadas_dir", tmp_path / "cache" / "capas_animadas", raising=False
    )
    monkeypatch.setattr(
        shared, "miniaturas_dir", tmp_path / "cache" / "miniaturas", raising=False
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
    """Uma subchave de registro nova por teste, dentro da da sessão."""
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


@pytest.fixture(scope="session", autouse=True)
def nunca_som_de_verdade():
    """A sessão inteira sem som: uma thread de som que termina depois do teste (o embaralhar do Big Picture) não toca nas caixas."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(winsound, "PlaySound", lambda *_args: None)
        yield


@pytest.fixture(autouse=True)
def sem_som(monkeypatch):
    """Cada `PlaySound` vira um `(dados, flags)` nesta lista, sem tocar som."""
    tocados = []
    monkeypatch.setattr(winsound, "PlaySound", lambda dados, flags: tocados.append((dados, flags)))
    return tocados


@pytest.fixture(autouse=True)
def sem_cortina_de_verdade(monkeypatch):
    """Sem a fábrica falsa, a cortina (janela TOPMOST do fade) falha ao criar."""
    from kyron.utils import cortina_monitor  # noqa: PLC0415

    def recusa():
        raise OSError("cortina de verdade nos testes")

    monkeypatch.setattr(cortina_monitor, "_api", recusa)


@pytest.fixture(autouse=True)
def sem_janela_por_cima_de_verdade(monkeypatch):
    """Sem o `user32_falso`, `janela_por_cima.preparar` falha (e o aviso de conquista não entra)."""
    from kyron.utils import janela_por_cima  # noqa: PLC0415

    def recusa():
        raise AssertionError("o teste tentou falar com o user32 de verdade (janela_por_cima)")

    monkeypatch.setattr(janela_por_cima, "_api", recusa)
    monkeypatch.setattr(janela_por_cima, "_dono", None)


@pytest.fixture(autouse=True)
def sem_monitor_de_verdade(monkeypatch):
    """`window_geometry.monitors` devolve um principal e um segundo, falsos; `monitors_de_verdade` restaura o real."""
    from kyron.utils import window_geometry  # noqa: PLC0415

    monkeypatch.setattr(
        window_geometry,
        "monitors",
        lambda: [
            window_geometry.Monitor(r"\\.\DISPLAY1", 0, 0, 1920, 1080, True, 1, r"\\?\DISPLAY#FALSO#1"),
            window_geometry.Monitor(r"\\.\DISPLAY2", 1920, 0, 1080, 1920, False, 2, r"\\?\DISPLAY#FALSO#2"),
        ],
    )


@pytest.fixture
def monitors_de_verdade(monkeypatch):
    from kyron.utils import window_geometry  # noqa: PLC0415

    monkeypatch.setattr(window_geometry, "monitors", _MONITORS_REAL)


@pytest.fixture(autouse=True)
def sem_placa_de_verdade(monkeypatch):
    """Sem um `criar` falso, a placa "Identificar monitores" falha em vez de aparecer na tela."""
    from kyron.utils import window_geometry  # noqa: PLC0415

    def recusa(*_args, **_kwargs):
        raise AssertionError("placa: nenhuma janela vai a um monitor nos testes")

    monkeypatch.setattr(window_geometry, "_criar_placa", recusa)
    monkeypatch.setattr(window_geometry, "_placas", [])


class User32Falso:
    """O user32 que `janela_por_cima` usa, sem janela de verdade: anota as chamadas.

    ``falhas`` mapeia o nome de uma chamada ao valor devolvido no lugar do de sempre;
    ``primeiro_plano`` é o que ``GetForegroundWindow`` devolve.
    """

    DONO = 9000

    def __init__(self) -> None:
        self.chamadas: list[tuple[str, tuple]] = []
        self.estilos: dict[int, int] = {}
        self.donos: dict[int, int] = {}
        self.primeiro_plano = 50
        self.tamanho = (300, 80)
        self.falhas: dict[str, Any] = {}

    def __getattr__(self, nome):
        if nome.startswith("_"):
            raise AttributeError(nome)
        real = getattr(self, "_" + nome)

        def chamar(*args):
            self.chamadas.append((nome, args))
            if nome in self.falhas:
                return self.falhas[nome]
            return real(*args)

        return chamar

    def pedidos(self, nome):
        return [args for n, args in self.chamadas if n == nome]

    def _GetWindowLongPtrW(self, hwnd, _indice):
        return self.estilos.get(int(hwnd), 0)

    def _SetWindowLongPtrW(self, hwnd, indice, valor):
        from kyron.utils import janela_por_cima as jpc  # noqa: PLC0415

        if indice == jpc.GWLP_HWNDPARENT:
            antes, self.donos[int(hwnd)] = self.donos.get(int(hwnd), 0), int(valor)
        else:
            antes, self.estilos[int(hwnd)] = self.estilos.get(int(hwnd), 0), int(valor)
        return antes

    def _GetWindow(self, hwnd, _qual):
        return self.donos.get(int(hwnd), 0)

    def _GetWindowRect(self, _hwnd, ref):
        ref._obj.left, ref._obj.top = 0, 0
        ref._obj.right, ref._obj.bottom = self.tamanho

    def _GetMonitorInfoW(self, _monitor, ref):
        r = ref._obj.rcMonitor
        r.left, r.top, r.right, r.bottom = 0, 0, 1920, 1080
        return 1

    def _GetForegroundWindow(self):
        return self.primeiro_plano

    def _CreateWindowExW(self, *_args):
        return self.DONO

    def _IsWindow(self, hwnd):
        return int(bool(hwnd))

    def _IsIconic(self, _hwnd):
        return 0

    def _SetLayeredWindowAttributes(self, *_args):
        return 1

    def _SetWindowPos(self, *_args):
        return 1

    def _SetForegroundWindow(self, _hwnd):
        return 1

    def _MonitorFromWindow(self, *_args):
        return 1


@pytest.fixture
def user32_falso(monkeypatch):
    """Troca o user32 do `janela_por_cima` pelo `User32Falso`."""
    from kyron.utils import janela_por_cima  # noqa: PLC0415

    falso = User32Falso()
    monkeypatch.setattr(janela_por_cima, "_api", lambda: falso)
    return falso


@pytest.fixture(autouse=True)
def sem_jogo_de_verdade(monkeypatch):
    """O `launch` que chegar ao `run_executable` falha alto.

    Também zera a sessão (`shared.sessao`), os rastreadores ativos e o vigia das conquistas entre os testes.
    """
    from kyron import jogo, process_session, session_window  # noqa: PLC0415
    from kyron.conquistas import sessao as sessao_conquistas  # noqa: PLC0415

    def recusa(*_args, **_kwargs):
        raise AssertionError("run_executable: nenhum jogo é iniciado nos testes")

    monkeypatch.setattr(jogo, "run_executable", recusa)
    monkeypatch.setattr(shared, "sessao", None, raising=False)
    monkeypatch.setattr(shared, "conquistas", None, raising=False)
    monkeypatch.setattr(shared, "preferencias", None, raising=False)
    monkeypatch.setattr(shared, "edicao", None, raising=False)
    monkeypatch.setattr(process_session.ProcessSession, "active", None)
    monkeypatch.setattr(session_window.SessionWindow, "active", None)
    monkeypatch.setattr(sessao_conquistas, "_vigia", None)


@pytest.fixture(autouse=True)
def sem_relancar_de_verdade(monkeypatch):
    """O `_popen` do `relancar()` levanta; quem prova o comando troca o `_popen`."""
    from kyron import app as modulo_app  # noqa: PLC0415

    def recusa(*_args, **_kwargs):
        raise AssertionError("relancar: o app não é reaberto nos testes")

    monkeypatch.setattr(modulo_app, "_popen", recusa)


@pytest.fixture(autouse=True)
def sem_instalador_de_verdade(monkeypatch, tmp_path):
    """O `_abrir_instalador` levanta (e o teste falha ao fim, mesmo que o erro tenha sido engolido) e o
    `download_dir` aponta para o `tmp_path`.

    Devolve a lista dos caminhos pedidos; quem prova o guarda de propósito a esvazia.
    """
    from kyron.utils import app_updater  # noqa: PLC0415

    chamadas: list = []

    def recusa(caminho):
        chamadas.append(caminho)
        raise AssertionError("atualizador: nenhum instalador é aberto nos testes")

    monkeypatch.setattr(app_updater, "_abrir_instalador", recusa)
    monkeypatch.setattr(app_updater, "download_dir", lambda: tmp_path / "Cartridges-update")
    yield chamadas
    assert not chamadas, f"o teste tentou abrir o instalador: {chamadas}"


@pytest.fixture(autouse=True)
def sem_navegador_de_verdade(monkeypatch):
    """O padrão de `LoginDaLoja` e o de `login.entrar` (Xbox) levantam, e o teste falha ao fim se algum foi chamado
    (o login engole a exceção, como faria com um navegador ausente).

    Devolve a lista das URLs pedidas; quem prova o guarda de propósito a esvazia.
    """
    from kyron.conquistas.xbox import login as login_xbox  # noqa: PLC0415
    from kyron.modelos import contas as modelo_das_contas  # noqa: PLC0415
    from kyron.utils import open_uri  # noqa: PLC0415

    chamadas: list[str] = []

    def recusa(url):
        chamadas.append(url)
        raise AssertionError("navegador: nenhum login abre nos testes")

    # O funil de `abrir_url`; quem importa o nome e o troca no próprio módulo não passa por aqui.
    monkeypatch.setattr(open_uri.QDesktopServices, "openUrl", staticmethod(lambda url: recusa(url.toString())))

    monkeypatch.setattr(modelo_das_contas, "_abrir_navegador", recusa)
    original = login_xbox._abrir_navegador  # noqa: SLF001
    monkeypatch.setattr(login_xbox, "_abrir_navegador", recusa)
    # O padrão de `entrar` foi fixado na definição: trocar o atributo do módulo não o alcança. Troca-se o primeiro
    # padrão, e só se ele for o navegador.
    assert login_xbox.entrar.__defaults__[0] is original, "o primeiro padrão de login.entrar já não é o navegador"
    monkeypatch.setattr(login_xbox.entrar, "__defaults__", (recusa, *login_xbox.entrar.__defaults__[1:]))
    monkeypatch.setattr(modelo_das_contas, "_em_voo", set())
    yield chamadas
    assert not chamadas, f"o teste abriu o navegador: {chamadas}"


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    """Tudo do app sai por `requests`; o envio vira uma falha de conexão."""
    import requests  # noqa: PLC0415

    enviar = requests.sessions.Session.send

    def recusa(self, requisicao, **kwargs):
        # O laço local (servidor de teste em 127.0.0.1) não é rede.
        if urlsplit(requisicao.url).hostname not in ("127.0.0.1", "localhost", "::1"):
            raise requests.ConnectionError("rede bloqueada nos testes")
        kwargs["proxies"] = {}  # nem um proxy de ambiente recebe o tráfego local
        return enviar(self, requisicao, **kwargs)

    monkeypatch.setattr(requests.sessions.Session, "send", recusa)


@pytest.fixture(autouse=True)
def fila_da_principal_vazia(app_qt, app_dirs, schema):  # noqa: ARG001
    """O que um teste deixou na fila da thread principal acaba antes do teste seguinte."""
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
    """Quem precisa de uma Steam monta a sua em ``tmp_path``."""
    from kyron.conquistas import arquivos  # noqa: PLC0415

    monkeypatch.setattr(arquivos, "_valor_do_registro", lambda *_a: None)
    monkeypatch.setattr(arquivos, "_inteiro_do_registro", lambda *_a: None)


@pytest.fixture(autouse=True)
def sem_ubisoft_no_registro(monkeypatch):
    """Quem precisa de instalações da Ubisoft troca `locais._do_registro`."""
    from kyron.conquistas.ubisoft import locais  # noqa: PLC0415

    monkeypatch.setattr(locais, "_do_registro", lambda: {})


@pytest.fixture(autouse=True)
def sem_ea_no_registro(monkeypatch):
    """Quem precisa de instalações da EA troca `ea.jogo.chaves_do_registro`."""
    from kyron.conquistas.ea import jogo  # noqa: PLC0415

    monkeypatch.setattr(jogo, "chaves_do_registro", lambda: [])


@pytest.fixture(autouse=True)
def sem_ludusavi(request, monkeypatch):
    """O fim de uma sessão dispararia um backup de verdade. Os testes dos saves montam o seu próprio executor e ficam
    de fora; os demais que precisem dele disponível trocam `backup_de_saves.disponivel`."""
    if request.module.__name__.startswith("test_saves_"):
        return
    from kyron.saves import backup_de_saves  # noqa: PLC0415

    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: False)


@pytest.fixture(scope="session", autouse=True)
def basetemp_do_ludusavi(tmp_path_factory):
    """Diz à guarda de `ludusavi.executavel` onde fica o basetemp."""
    global _basetemp  # pylint: disable=global-statement
    _basetemp = tmp_path_factory.getbasetemp().resolve()
    yield
    _basetemp = None


@pytest.fixture
def ludusavi_de_verdade(tmp_path, monkeypatch):
    """Um Python de mentira em `tmp_path`: quem pede a fixture põe, ou não, um `ludusavi.exe` ao lado."""
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))


@pytest.fixture
def ludusavi_real_da_maquina(monkeypatch):
    """Só o teste de integração pede: tira a guarda e deixa `ludusavi.executavel` achar o `ludusavi.exe` verdadeiro.
    Quem pede só pode rodá-lo sobre `tmp_path` (config e backups)."""
    monkeypatch.setattr(_ludusavi, "executavel", EXECUTAVEL_DE_VERDADE)


@pytest.fixture(autouse=True)
def sem_thread_de_backup_sobrando():
    """Uma thread dos saves que sobra roda com o ambiente já desfeito: o teste que a abriu tem de esperá-la."""
    yield
    sobraram = [
        thread.name
        for thread in threading.enumerate()
        if thread.is_alive()
        and getattr(getattr(thread, "_target", None), "__module__", "")
        == "kyron.saves.backup_de_saves"
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
    """No lugar do ``Jogo`` nos testes da store. ``saves`` é um contador: vários testes provam quantas vezes uma
    varredura grava um registro."""

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
        for key, value in data.items():
            setattr(self, key, value)

    @property
    def zerado(self) -> bool:
        return self.removed and not self.blacklisted and self.status == "beaten"

    def get_cover_path(self) -> Path | None:
        from kyron.utils.save_cover import ANIMATED_SUFFIXES  # noqa: PLC0415

        for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
            cover_path = shared.covers_dir / f"{self.game_id}{suffix}"
            if cover_path.is_file():
                return cover_path
        return None

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<FakeGame {self.game_id} removed={self.removed}>"


@pytest.fixture
def make_game():
    """Fábrica de registros de jogo para a store."""

    def factory(**overrides) -> FakeGame:
        return FakeGame(**overrides)

    return factory


@pytest.fixture
def store():
    """Uma ``Store`` limpa, sem gerenciadores: ``add_game`` não liga sinais nem roda o pipeline."""
    from kyron.store.store import Store  # noqa: PLC0415

    instance = Store()
    shared.store = instance
    yield instance
    shared.store = None


@pytest.fixture
def write_record(app_dirs):
    """Grava o JSON de um jogo como o ``FileManager`` faria."""

    def writer(game_id: str, **fields) -> Path:
        path = app_dirs.games / f"{game_id}.json"
        data = {"game_id": game_id, "source": "shortcuts", "name": "Test Game"}
        data.update(fields)
        path.write_text(json.dumps(data, indent=4, sort_keys=True), encoding="utf-8")
        return path

    return writer


@pytest.fixture
def write_asset(app_dirs):
    """Põe uma capa ou logo para as migrações terem o que mover."""

    def writer(directory: str, name: str, content: bytes = b"x") -> Path:
        target = getattr(app_dirs, directory) / name
        target.write_bytes(content)
        return target

    return writer


@pytest.fixture(autouse=True)
def sem_area_de_trabalho(monkeypatch):
    """Sem COM nos testes: quem precisa da `IDesktopWallpaper` troca `_AreaDeTrabalho` por um falso."""

    def proibida(*_args, **_kwargs):
        raise AssertionError("o teste tentou abrir a área de trabalho de verdade (IDesktopWallpaper)")

    from kyron.utils import session_wallpaper  # noqa: PLC0415

    monkeypatch.setattr(session_wallpaper, "_AreaDeTrabalho", proibida)


@pytest.fixture(autouse=True)
def sem_fita_de_verdade(monkeypatch):
    """O `_dispositivo` (a tinytuya, com rede) falha alto; quem prova a conversa o troca por um módulo falso (`falsas`)."""
    from kyron.utils import session_fita  # noqa: PLC0415

    def proibido(*_args, **_kwargs):
        raise AssertionError("o teste tentou falar com uma fita de verdade (tinytuya)")

    monkeypatch.setattr(session_fita, "_dispositivo", proibido)


@pytest.fixture(autouse=True)
def sem_tuya_de_verdade(request, monkeypatch):
    """A nuvem da Tuya e a varredura da rede falham alto. Quem prova o assistente troca `fita_wizard._nuvem` e
    `session_fita.enderecos_na_rede`; quem prova a própria `enderecos_na_rede` leva a marca `varredura_real`."""
    from kyron import fita_wizard  # noqa: PLC0415
    from kyron.utils import session_fita  # noqa: PLC0415

    def proibido(*_args, **_kwargs):
        raise AssertionError("tuya: nenhuma busca na nuvem nem na rede nos testes")

    monkeypatch.setattr(fita_wizard, "_nuvem", proibido)
    if request.node.get_closest_marker("varredura_real") is None:
        monkeypatch.setattr(session_fita, "enderecos_na_rede", proibido)


@pytest.fixture(autouse=True)
def dados_temporarios(tmp_path, monkeypatch):
    """Pasta e subchave de registro próprias de cada teste."""
    registro = f"{_RAIZ_REGISTRO}\\{uuid.uuid4()}"
    monkeypatch.setenv("KYRON_DADOS", str(tmp_path))
    monkeypatch.setenv("KYRON_REGISTRO", registro)
    yield tmp_path
    _apagar_chave(winreg.HKEY_CURRENT_USER, registro)


@pytest.fixture(scope="session", autouse=True)
def app_qt():
    """Uma única `QGuiApplication` para a sessão toda."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

    # A opção desliga a animação dos diálogos: os testes leem o `visible` na hora.
    app = QGuiApplication.instance() or QGuiApplication(["pytest", "--sem-animacao-de-dialogo"])
    from kyron.utils.coleta_de_lixo import coletar_so_na_principal  # noqa: PLC0415

    coletar_so_na_principal(app)
    yield app
