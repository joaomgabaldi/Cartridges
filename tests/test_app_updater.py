# test_app_updater.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Checagem de versão nova, notas da release e download do instalador."""

import hashlib
import subprocess
import sys
import threading
import time
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from kyron import shared
from kyron.utils import app_updater
from kyron.utils.app_updater import (
    AppUpdater,
    DownloadCancelled,
    Release,
    download_installer,
    installed_root,
    is_newer,
    notes_to_markup,
    parse_release,
)

_SHA = "932503f6ff3c8714d7c45d862134365a1b8ae064abbb0f4ba8d44ab7b2d9fb9b"

# Formato real de releases/latest, só com os campos lidos.
_API = {
    "tag_name": "v2026.09.10",
    "body": "## Novidades\r\n\r\n- Uma aba nova\r\n\r\n## Instalação\r\n\r\nBaixe o exe.",
    "assets": [
        {"name": "notas.txt", "browser_download_url": "https://x/notas.txt", "size": 1},
        {
            "name": "Cartridges.Windows.exe",
            "url": "https://api.github.com/repos/o/r/releases/assets/2",
            "browser_download_url": "https://x/Cartridges.Windows.exe",
            "size": 63701150,
            "digest": f"sha256:{_SHA.upper()}",
        },
    ],
}


def _is_valid_markup(markup: str) -> bool:
    # `<br>` é HTML do Qt; para o XML ele precisa fechar.
    try:
        ET.fromstring(f"<markup>{markup.replace('<br>', '<br/>')}</markup>")
    except ET.ParseError:
        return False
    return True


# -- parse_release ------------------------------------------------------------


def test_parse_release_picks_the_exe_and_strips_prefixes():
    release = parse_release(_API)
    assert release == Release(
        version="2026.09.10",
        notes=_API["body"],
        url="https://x/Cartridges.Windows.exe",
        size=63701150,
        sha256=_SHA,
    )


def test_parse_release_tira_o_v_da_versao_normal():
    assert parse_release(dict(_API, tag_name="v2.0.1")).version == "2.0.1"


def test_parse_release_without_exe_is_none():
    data = dict(_API, assets=[_API["assets"][0]])
    assert parse_release(data) is None


def test_parse_release_without_digest_keeps_empty_hash():
    exe = {k: v for k, v in _API["assets"][1].items() if k != "digest"}
    release = parse_release(dict(_API, assets=[exe]))
    assert release is not None
    assert release.sha256 == ""


# -- is_newer -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "current", "expected"),
    [
        ("2026.09.13", "2026.09.12", True),
        ("2026.09.12", "2026.09.12", False),
        ("2026.09.01", "2026.09.12", False),
        ("2026.10.01", "2026.09.30", True),
        ("latest", "2026.09.12", False),
        ("2026.9.13", "2026.09.12", False),
        ("2026.09.13", "0.0.1-dev", False),
        ("2.0.1", "2.0.0", True),
        ("2.10.0", "2.9.0", True),
        ("2.0.0", "2.0.0", False),
        ("1.9.9", "2.0.0", False),
        ("2026.10.26", "2.0.0", False),
        ("2.1.0-beta", "2.0.0", False),
        ("2.1", "2.0.0", False),
        ("v2.0.1", "2.0.0", False),
        ("2.0.1", "2026.10.26", False),
    ],
)
def test_is_newer(version, current, expected):
    assert is_newer(version, current) is expected


# -- notes_to_markup ----------------------------------------------------------


def test_notes_markup_formats_headings_bold_code_and_bullets():
    notes = "## Novidades\n\n- A aba **Sessão** mostra `0:00:00`"
    assert notes_to_markup(notes) == (
        "<b>Novidades</b><br><br>• A aba <b>Sessão</b> mostra <tt>0:00:00</tt>"
    )


def test_notes_markup_drops_the_installation_section():
    markup = notes_to_markup(_API["body"])
    assert "Instalação" not in markup
    assert "Baixe" not in markup
    assert markup == "<b>Novidades</b><br><br>• Uma aba nova"


def test_notes_markup_keeps_sections_after_installation():
    notes = "## Instalação\nBaixe.\n## Correções\n- Uma"
    assert notes_to_markup(notes) == "<b>Correções</b><br>• Uma"


def test_notes_markup_escapes_pango_special_characters():
    markup = notes_to_markup("- 800<600 & **R&D**")
    assert markup == "• 800&lt;600 &amp; <b>R&amp;D</b>"
    assert _is_valid_markup(markup)
    # Texto de terceiros com tag e link aparece como está, nada clicável.
    assert notes_to_markup("a & <b>c</b>") == "a &amp; &lt;b&gt;c&lt;/b&gt;"
    assert "<a " not in notes_to_markup('<a href="https://x">clique</a>')


def test_notes_markup_of_real_body_is_valid():
    markup = notes_to_markup(_API["body"])
    assert _is_valid_markup(markup)
    tags = {e.tag for e in ET.fromstring(f"<markup>{markup.replace('<br>', '<br/>')}</markup>").iter()} - {"markup"}
    assert tags <= {"b", "tt", "br"}


def test_notes_markup_do_exemplo_do_brief():
    assert notes_to_markup("## Título\n**a** `b`\n- c") == "<b>Título</b><br><b>a</b> <tt>b</tt><br>• c"


# -- installed_root -----------------------------------------------------------


def test_installed_root_finds_the_uninstaller(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "canal", lambda: "final")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pythonw.exe").write_bytes(b"")
    (tmp_path / "unins000.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "pythonw.exe"))
    assert installed_root() == tmp_path.resolve()


def test_installed_root_is_none_from_source(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "canal", lambda: "final")
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "python.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "python.exe"))
    assert installed_root() is None


def _instalacao_falsa(tmp_path, monkeypatch):
    """Um `unins000.exe` ao lado do Python falso: só o canal decide se é uma instalação."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pythonw.exe").write_bytes(b"")
    (tmp_path / "unins000.exe").write_bytes(b"")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "bin" / "pythonw.exe"))


def test_canal_de_desenvolvimento_nunca_se_atualiza(tmp_path, monkeypatch):
    _instalacao_falsa(tmp_path, monkeypatch)
    monkeypatch.setattr(shared, "canal", lambda: "desenvolvimento")
    assert installed_root() is None

    def no_thread(*_args, **_kwargs):
        pytest.fail("a cópia de desenvolvimento não checa versão nova")

    monkeypatch.setattr(app_updater.threading, "Thread", no_thread)
    AppUpdater().start()

    respostas = []
    AppUpdater().buscar_agora(respostas.append)
    assert respostas == [FORA_DA_INSTALACAO]


def test_canal_final_continua_se_atualizando(tmp_path, monkeypatch):
    _instalacao_falsa(tmp_path, monkeypatch)
    monkeypatch.setattr(shared, "canal", lambda: "final")
    assert installed_root() == tmp_path.resolve()
    iniciadas = []
    monkeypatch.setattr(
        app_updater.threading, "Thread", lambda **kw: types.SimpleNamespace(start=lambda: iniciadas.append(kw))
    )
    AppUpdater().start()
    assert len(iniciadas) == 1


# -- download_installer -------------------------------------------------------

_PAYLOAD = b"instalador de mentira"


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def raise_for_status(self) -> None:
        pass

    def iter_content(self, chunk_size: int):
        for start in range(0, len(self._payload), 8):
            yield self._payload[start : start + 8]


def _release(sha256: str) -> Release:
    return Release("2026.09.13", "", "https://x/setup.exe", len(_PAYLOAD), sha256)


@pytest.fixture
def fake_get(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def get(url, **kwargs):
        calls.append((url, kwargs.get("headers") or {}))
        return _FakeResponse(_PAYLOAD)

    monkeypatch.setattr(app_updater.requests, "get", get)
    return calls


def test_download_writes_verified_installer(tmp_path, fake_get):
    target = tmp_path / "update" / "Cartridges-2026.09.13.exe"
    fractions: list[float] = []

    download_installer(
        _release(hashlib.sha256(_PAYLOAD).hexdigest()),
        target,
        fractions.append,
        threading.Event(),
    )

    # Repositório público: nada de token no pedido.
    assert fake_get[0][1] == {}
    assert target.read_bytes() == _PAYLOAD
    assert list(target.parent.glob("*.part")) == []
    assert fractions[-1] == 1.0
    assert fractions == sorted(fractions)


# O download vai para uma subpasta própria para "não sobrou nada" poder olhar a pasta inteira.


def test_download_with_wrong_hash_leaves_nothing(tmp_path, fake_get):
    target = tmp_path / "update" / "Cartridges-2026.09.13.exe"

    with pytest.raises(ValueError):
        download_installer(_release("0" * 64), target, lambda _f: None, threading.Event())

    assert list(target.parent.iterdir()) == []


def test_download_without_hash_refuses_before_downloading(tmp_path, fake_get):
    with pytest.raises(ValueError):
        download_installer(
            _release(""), tmp_path / "x.exe", lambda _f: None, threading.Event()
        )
    assert fake_get == []


def test_download_cancelled_leaves_nothing(tmp_path, fake_get):
    cancelled = threading.Event()
    cancelled.set()
    target = tmp_path / "update" / "Cartridges-2026.09.13.exe"

    with pytest.raises(DownloadCancelled):
        download_installer(
            _release(hashlib.sha256(_PAYLOAD).hexdigest()),
            target,
            lambda _f: None,
            cancelled,
        )

    assert list(target.parent.iterdir()) == []


# -- AppUpdater ---------------------------------------------------------------


FORA_DA_INSTALACAO = "A busca de atualizações só funciona no aplicativo instalado."


def _relogio_falso(monkeypatch):
    """O `QTimer.singleShot` do reagendamento vira uma lista de (milissegundos, função); a aplicação existe."""
    adiadas: list = []
    monkeypatch.setattr(
        app_updater, "QTimer", types.SimpleNamespace(singleShot=lambda ms, fn: adiadas.append((ms, fn)))
    )
    monkeypatch.setattr(shared, "aplicativo", object(), raising=False)
    return adiadas


def test_start_does_nothing_outside_the_installation(monkeypatch):
    monkeypatch.setattr(app_updater, "installed_root", lambda: None)

    def no_thread(*_args, **_kwargs):
        pytest.fail("rodando do código-fonte, o app não pode checar versão nova")

    monkeypatch.setattr(app_updater.threading, "Thread", no_thread)
    AppUpdater().start()


@pytest.mark.parametrize(
    ("current", "asks"),
    [("2026.09.12", False), ("2026.09.01", True)],
)
def test_check_asks_only_for_a_newer_release(tmp_path, monkeypatch, current, asks):
    # _check_thread apaga a download_dir(): nunca a %TEMP%\Cartridges-update real.
    monkeypatch.setattr(app_updater, "download_dir", lambda: tmp_path / "update")
    monkeypatch.setattr(app_updater.shared, "VERSION", current)
    response = types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: _API)
    sent: list[dict] = []

    def get(_url, **kwargs):
        sent.append(kwargs["headers"])
        return response

    monkeypatch.setattr(app_updater.requests, "get", get)
    queued: list[tuple] = []
    monkeypatch.setattr(app_updater, "na_thread_principal", lambda *args: queued.append(args))

    AppUpdater()._check_thread()  # pylint: disable=protected-access

    assert "Authorization" not in sent[0]
    if asks:
        assert len(queued) == 1
        assert queued[0][1].version == "2026.09.10"
    else:
        assert queued == []


def test_data_antiga_nunca_e_oferecida_a_2_0(tmp_path, monkeypatch):
    monkeypatch.setattr(app_updater, "download_dir", lambda: tmp_path / "update")
    monkeypatch.setattr(app_updater.shared, "VERSION", "2.0.0")
    api = dict(_API, tag_name="v2026.10.26")
    resposta = types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: api)
    monkeypatch.setattr(app_updater.requests, "get", lambda *_a, **_k: resposta)
    perguntas: list[tuple] = []
    monkeypatch.setattr(app_updater, "na_thread_principal", lambda *args: perguntas.append(args))

    AppUpdater()._check_thread()  # pylint: disable=protected-access

    assert perguntas == []


def _sem_sair(monkeypatch):
    """Nenhum teste chama o `QCoreApplication.quit()` do fim do download."""
    sairam = []
    monkeypatch.setattr(app_updater, "QCoreApplication", types.SimpleNamespace(quit=lambda: sairam.append(1)))
    return sairam


def test_finish_after_cancel_neither_installs_nor_quits(tmp_path, monkeypatch, sem_instalador_de_verdade):
    sairam = _sem_sair(monkeypatch)
    updater = AppUpdater()
    updater._cancel.set()  # pylint: disable=protected-access

    # O guarda `sem_instalador_de_verdade` falha o teste se o instalador abrir.
    updater._finish(tmp_path / "x.exe", updater._cancel)  # pylint: disable=protected-access

    assert sem_instalador_de_verdade == []
    assert sairam == []


def test_finish_abre_o_instalador_e_sai_uma_vez(tmp_path, monkeypatch, sem_instalador_de_verdade):
    sairam = _sem_sair(monkeypatch)
    abertos = []
    monkeypatch.setattr(app_updater, "_abrir_instalador", abertos.append)
    updater = AppUpdater()

    updater._finish(tmp_path / "x.exe", updater._cancel)  # pylint: disable=protected-access
    updater._finish(tmp_path / "x.exe", updater._cancel)  # pylint: disable=protected-access

    assert abertos == [tmp_path / "x.exe"]
    assert sairam == [1]


def test_finish_que_nao_abre_o_instalador_avisa_e_nao_sai(tmp_path, monkeypatch, sem_instalador_de_verdade):
    sairam = _sem_sair(monkeypatch)
    avisos = []
    falso = types.SimpleNamespace(avisos=types.SimpleNamespace(adicionar=avisos.append))
    monkeypatch.setattr(shared, "aplicativo", falso, raising=False)

    def recusa(_caminho):
        raise OSError("recusado")

    monkeypatch.setattr(app_updater, "_abrir_instalador", recusa)
    updater = AppUpdater()
    updater._baixando = True  # pylint: disable=protected-access

    updater._finish(tmp_path / "x.exe", updater._cancel)  # pylint: disable=protected-access

    assert avisos == ["Não foi possível abrir o instalador"]
    assert sairam == [] and not updater.baixando


def test_app_updater_sem_gi():
    # O `_` que o `app.py` põe nos builtins; sem ele o `jogo.py` nem importa.
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; "
        "import kyron.utils.app_updater; sys.exit('gi' in sys.modules)"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=Path(__file__).parent.parent,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert resultado.returncode == 0, resultado.stderr


def test_conftest_bloqueia_o_instalador(tmp_path, sem_instalador_de_verdade):
    assert app_updater.download_dir().parent == tmp_path
    with pytest.raises(AssertionError, match="nenhum instalador é aberto nos testes"):
        app_updater._abrir_instalador(tmp_path / "x.exe")  # pylint: disable=protected-access
    assert sem_instalador_de_verdade == [tmp_path / "x.exe"]
    sem_instalador_de_verdade.clear()  # provado de propósito: o fim do teste não falha


def test_fechar_o_app_no_meio_do_download_descarta_o_resultado(tmp_path, monkeypatch, sem_instalador_de_verdade):
    """O `stop()` do fechamento
, antes do `_finish`, não abre o instalador, não sai e não deixa o `.part`."""
    sairam = _sem_sair(monkeypatch)
    fila: list = []
    monkeypatch.setattr(app_updater, "na_thread_principal", lambda f, *a: fila.append((f, a)))
    monkeypatch.setattr(app_updater.threading, "Thread", lambda target, **_kw: types.SimpleNamespace(start=target))
    updater = AppUpdater()
    alvo = app_updater.download_dir() / "Kyron-2026.09.13.exe"

    # 1. O download termina, mas o app fecha antes de o resultado ser tratado.
    monkeypatch.setattr(app_updater.requests, "get", lambda *_a, **_k: _FakeResponse(_PAYLOAD))
    updater._download(_release(hashlib.sha256(_PAYLOAD).hexdigest()))  # pylint: disable=protected-access
    updater.stop()
    for funcao, args in fila:
        funcao(*args)
    assert sem_instalador_de_verdade == [] and sairam == []

    # 2. O app fecha no meio do download: o `.part` sai e nenhum resultado é entregue.
    alvo.unlink(missing_ok=True)
    fila.clear()
    updater = AppUpdater()

    class _Fechando(_FakeResponse):
        def iter_content(self, chunk_size):
            pedacos = super().iter_content(chunk_size)
            yield next(pedacos)
            updater.stop()
            yield from pedacos

    monkeypatch.setattr(app_updater.requests, "get", lambda *_a, **_k: _Fechando(_PAYLOAD))
    updater._download(_release(hashlib.sha256(_PAYLOAD).hexdigest()))  # pylint: disable=protected-access
    assert list(alvo.parent.iterdir()) == []
    assert not any(f.__name__ == "_finish" for f, _a in fila)
    for funcao, args in fila:
        funcao(*args)
    assert sem_instalador_de_verdade == [] and sairam == []


def test_cancelar_e_baixar_de_novo_nao_ressuscita_o_download_antigo(tmp_path, monkeypatch, sem_instalador_de_verdade):
    """O download antigo, preso, termina depois do segundo: o `Event` dele continua ligado e o resultado é descartado."""
    sairam = _sem_sair(monkeypatch)
    fila: list = []
    monkeypatch.setattr(app_updater, "na_thread_principal", lambda f, *a: fila.append((f, a)))
    eventos: list[threading.Event] = []
    soltar = threading.Event()
    iniciadas: list[threading.Thread] = []

    def preso(_release, _target, _progress, cancelled):
        eventos.append(cancelled)
        soltar.wait(5)  # não olha o `cancelled`: termina "bem" mesmo cancelado

    monkeypatch.setattr(app_updater, "download_installer", preso)
    original = threading.Thread

    def thread(target, **kw):
        t = original(target=target, **kw)
        iniciadas.append(t)
        return t

    monkeypatch.setattr(app_updater.threading, "Thread", thread)
    updater = AppUpdater()
    release = _release("ab")
    try:
        updater._download(release)  # pylint: disable=protected-access
        updater.cancelar()
        updater._download(release)  # pylint: disable=protected-access
        deadline = time.monotonic() + 5
        while len(eventos) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert len(eventos) == 2
        assert eventos[0] is not eventos[1]
        assert eventos[0].is_set() and not eventos[1].is_set()

        soltar.set()
        for t in iniciadas:
            t.join(5)
    finally:
        soltar.set()
    # Só o resultado da primeira chegou à fila (a segunda também termina "bem", mas é a vigente).
    resultados = [(f, a) for f, a in fila if f.__name__ == "_finish"]
    primeiro = [a for _f, a in resultados if a[1] is eventos[0]]
    assert len(primeiro) == 1
    updater._finish(*primeiro[0])  # pylint: disable=protected-access
    assert sem_instalador_de_verdade == [] and sairam == []
    assert updater.baixando is True  # o progresso do download vigente não foi escondido

    # O progresso do antigo também é ignorado.
    updater._progresso = 0.3  # pylint: disable=protected-access
    updater._atualizar_progresso(0.9, eventos[0])  # pylint: disable=protected-access
    assert updater.progresso == 0.3


def test_cada_download_tem_o_proprio_part(tmp_path, monkeypatch):
    """Dois downloads do mesmo instalador, em threads diferentes, nunca gravam no mesmo `.part`."""
    partes: list[str] = []
    gravando = threading.Barrier(2)

    class _Lento(_FakeResponse):
        def iter_content(self, chunk_size):
            yield self._payload[:4]
            partes.extend(p.name for p in (tmp_path / "update").glob("*.part"))
            gravando.wait(5)  # os dois estão com o `.part` aberto ao mesmo tempo
            yield self._payload[4:]

    monkeypatch.setattr(app_updater.requests, "get", lambda *_a, **_k: _Lento(_PAYLOAD))
    alvo = tmp_path / "update" / "Cartridges-2026.09.13.exe"
    erros = []

    def baixar():
        try:
            download_installer(
                _release(hashlib.sha256(_PAYLOAD).hexdigest()), alvo, lambda _f: None, threading.Event()
            )
        except Exception as erro:  # pylint: disable=broad-exception-caught
            erros.append(erro)

    threads = [threading.Thread(target=baixar) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert len(set(partes)) == 2, partes
    assert not any(t.is_alive() for t in threads)
    # O que sobra de um `replace` na corrida é problema do Windows, não do `.part`: nenhum sobra.
    assert list(alvo.parent.glob("*.part")) == []


def test_pergunta_espera_os_saves(monkeypatch):
    """Atualizar fecha o app: com o backup ou a restauração dos saves em curso, a
    pergunta espera, como espera a sessão."""
    from kyron.process_session import ProcessSession
    from kyron.saves import backup_de_saves
    from kyron.session_window import SessionWindow

    adiadas = _relogio_falso(monkeypatch)
    monkeypatch.setattr(ProcessSession, "active", None)
    monkeypatch.setattr(SessionWindow, "active", None)
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    release = Release("2026.09.30", "", "https://x", 1, "ab")
    updater = AppUpdater()

    updater._ask(release)  # pylint: disable=protected-access

    assert updater.pergunta == {}, "perguntou com os saves em andamento"
    assert [ms for ms, _fn in adiadas] == [app_updater.ASK_RETRY_SECONDS * 1000]
    # Acabado o backup, a volta do relógio faz a pergunta.
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: False)
    adiadas[0][1]()
    assert updater.pergunta["versao"] == "2026.09.30"


def test_b1_a_pergunta_da_versao_nova_espera_a_sessao(monkeypatch):
    from kyron.process_session import ProcessSession

    adiadas = _relogio_falso(monkeypatch)
    monkeypatch.setattr(ProcessSession, "active", object())
    release = Release("2026.09.30", "", "https://x", 1, "ab")
    updater = AppUpdater()

    updater._ask(release)  # pylint: disable=protected-access

    assert updater.pergunta == {}, "perguntou com o jogo aberto"
    assert len(adiadas) == 1


@pytest.mark.parametrize("informado", [8, 0])
def test_b25_o_download_do_instalador_tem_teto(tmp_path, monkeypatch, informado):
    payload = b"x" * 64
    monkeypatch.setattr(app_updater.requests, "get", lambda *_a, **_k: _FakeResponse(payload))
    monkeypatch.setattr(app_updater, "MAX_INSTALLER_BYTES", 16)
    release = Release("2026.09.30", "", "https://x", informado, hashlib.sha256(payload).hexdigest())
    target = tmp_path / "update" / "setup.exe"

    with pytest.raises(ValueError):
        download_installer(release, target, lambda _f: None, threading.Event())
    assert list(target.parent.iterdir()) == []


def test_b28_dialogo_de_atualizacao_diz_o_que_acontece():
    raiz = Path(__file__).parent.parent / "kyron"
    qml = (raiz / "qml/DialogoDaAtualizacao.qml").read_text(encoding="utf-8")
    assert "Deseja baixar e instalar a atualização agora? O aplicativo será fechado durante a instalação." in qml
    assert '"Agora não"' in qml
    assert '"Atualizar"' in qml
    assert "Atualizar destacado" in qml
    assert "Nova versão disponível: " in qml
    assert "Baixando atualização…" in qml


# -- busca pedida nas Preferências --------------------------------------------


@pytest.fixture
def busca(tmp_path, monkeypatch):
    """Instalado, versão 2026.09.01, GitHub respondendo ``_API`` e o que iria para
    a tela entregue na hora."""
    monkeypatch.setattr(app_updater, "installed_root", lambda: tmp_path)
    monkeypatch.setattr(app_updater.shared, "VERSION", "2026.09.01")
    response = types.SimpleNamespace(raise_for_status=lambda: None, json=lambda: _API)
    monkeypatch.setattr(app_updater.requests, "get", lambda _url, **_kw: response)
    monkeypatch.setattr(app_updater, "na_thread_principal", lambda fn, *args: fn(*args))
    monkeypatch.setattr(
        app_updater.threading,
        "Thread",
        lambda target, **_kw: types.SimpleNamespace(start=target),
    )
    avisos: list[str] = []
    perguntas: list[Release] = []
    monkeypatch.setattr(AppUpdater, "_ask", lambda _self, release: perguntas.append(release))
    monkeypatch.setattr(AppUpdater, "_ocupado", staticmethod(lambda: False))
    return types.SimpleNamespace(avisos=avisos, perguntas=perguntas)


def test_busca_com_versao_nova_faz_a_pergunta(busca):
    AppUpdater().buscar_agora(busca.avisos.append)

    assert [r.version for r in busca.perguntas] == ["2026.09.10"]
    # O None devolve o botão: a resposta é a própria pergunta.
    assert busca.avisos == [None]


def test_busca_sem_versao_nova_avisa(busca, monkeypatch):
    monkeypatch.setattr(app_updater.shared, "VERSION", "2026.09.10")

    AppUpdater().buscar_agora(busca.avisos.append)

    assert busca.perguntas == []
    assert busca.avisos == ["O Kyron já está na versão mais recente."]


def test_busca_sem_rede_avisa(busca, monkeypatch):
    def get(_url, **_kw):
        raise app_updater.requests.ConnectionError("sem rede")

    monkeypatch.setattr(app_updater.requests, "get", get)

    AppUpdater().buscar_agora(busca.avisos.append)

    assert busca.perguntas == []
    assert busca.avisos == [
        "Não foi possível buscar atualizações. Verifique a conexão com a internet."
    ]


def test_busca_com_jogo_aberto_avisa_em_vez_de_perguntar(busca, monkeypatch):
    monkeypatch.setattr(AppUpdater, "_ocupado", staticmethod(lambda: True))

    AppUpdater().buscar_agora(busca.avisos.append)

    assert busca.perguntas == []
    assert busca.avisos == [
        "Versão 2026.09.10 disponível. Conclua o jogo, o backup ou a restauração "
        "dos saves em andamento para atualizar."
    ]


def test_busca_fora_da_instalacao_avisa(busca, monkeypatch):
    monkeypatch.setattr(app_updater, "installed_root", lambda: None)

    AppUpdater().buscar_agora(busca.avisos.append)

    assert busca.perguntas == []
    assert busca.avisos == ["A busca de atualizações só funciona no aplicativo instalado."]


def test_segunda_busca_no_caminho_avisa(busca, monkeypatch):
    """Reabrir as Preferências devolve o botão; a segunda busca não sai."""
    pendentes: list = []
    monkeypatch.setattr(
        app_updater.threading,
        "Thread",
        lambda target, **_kw: types.SimpleNamespace(
            start=lambda: pendentes.append(target)
        ),
    )
    updater = AppUpdater()
    updater.buscar_agora(busca.avisos.append)
    updater.buscar_agora(busca.avisos.append)

    assert len(pendentes) == 1
    assert busca.avisos == ["A busca de atualizações já está em andamento."]

    pendentes[0]()
    updater.buscar_agora(busca.avisos.append)
    assert len(pendentes) == 2


def test_pergunta_na_tela_nao_abre_outra(monkeypatch):
    """A checagem da abertura adiada não abre uma segunda pergunta por cima."""
    monkeypatch.setattr(app_updater.shared, "aplicativo", object(), raising=False)
    updater = AppUpdater()
    updater._perguntando = True  # pylint: disable=protected-access
    release = Release("2026.09.30", "", "https://x", 1, "ab")

    updater._ask(release)  # pylint: disable=protected-access

    assert updater.pergunta == {}


def test_pergunta_leva_versao_e_notas_ja_formatadas(monkeypatch):
    monkeypatch.setattr(app_updater.shared, "aplicativo", object(), raising=False)
    monkeypatch.setattr(AppUpdater, "_ocupado", staticmethod(lambda: False))
    updater = AppUpdater()

    updater._ask(Release("2026.09.30", "## T\n- **a** & b", "https://x", 1, "ab"))  # pylint: disable=protected-access

    assert updater.pergunta == {"versao": "2026.09.30", "notas": "<b>T</b><br>• <b>a</b> &amp; b"}


def test_buscar_agora_sem_aplicativo_descarta_a_resposta(busca, monkeypatch):
    """Sem `shared.aplicativo` a resposta não tem para onde ir: o botão não levanta e nenhuma pergunta nasce."""
    monkeypatch.setattr(app_updater, "installed_root", lambda: None)
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    respostas = []
    original = AppUpdater.buscar_agora
    monkeypatch.setattr(
        AppUpdater, "buscar_agora", lambda self, responder: original(self, lambda t: (respostas.append(t), responder(t)))
    )
    updater = AppUpdater()

    updater.buscarAgora()

    assert respostas == [FORA_DA_INSTALACAO]
    assert updater.pergunta == {} and updater.buscando is False


def test_buscar_agora_poe_a_resposta_na_fila_de_avisos(busca, monkeypatch):
    monkeypatch.setattr(app_updater, "installed_root", lambda: None)
    adicionados = []
    falso = types.SimpleNamespace(avisos=types.SimpleNamespace(adicionar=adicionados.append))
    monkeypatch.setattr(shared, "aplicativo", falso, raising=False)

    AppUpdater().buscarAgora()

    assert adicionados == [FORA_DA_INSTALACAO]
