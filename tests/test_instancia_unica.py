# test_instancia_unica.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Uma instância só por pasta de dados (D76) e a segunda abertura. Os testes vieram de `test_tarefas_ui.py` e de
`test_reinicio.py` com os mesmos nomes.

Nenhum teste cria o mutex nem o evento com o nome do canal final: os nomes são trocados ou vêm da pasta temporária.
"""

import ctypes
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtGui import QWindow

from cartridges import shared
from cartridges.modelos import tarefas
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.saves import backup_de_saves
from cartridges.utils import single_instance

RAIZ = Path(__file__).resolve().parent.parent
_NOMES_DO_CANAL_FINAL = (
    "Local\\io.github.joaomgabaldi.Cartridges.SingleInstance",
    "Local\\io.github.joaomgabaldi.Cartridges.Present",
)


@pytest.fixture(autouse=True)
def _sem_trava_nem_tarefa(monkeypatch):
    """A trava e a lista de tarefas são globais: cada teste começa e termina sem nenhuma."""
    monkeypatch.setattr(single_instance, "_handle", None)
    _esvaziar()
    yield
    single_instance.release()
    _esvaziar()


def _esvaziar():
    for tarefa in list(tarefas.lista._tarefas):  # noqa: SLF001
        tarefas.lista.remover(tarefa)


def _nomes_de_teste(monkeypatch):
    base = f"Local\\Cartridges.Teste.{uuid.uuid4()}"
    monkeypatch.setattr(single_instance, "nomes", lambda: (f"{base}.SingleInstance", f"{base}.Present"))


# -- os nomes da trava ----------------------------------------------------------------------------------------


def test_nomes_da_trava_no_canal_final_sao_os_de_sempre(tmp_path, monkeypatch):
    """Uma cópia do `shared.py` com o `instalacao.json` do canal final, como os testes do canal: só calcula nomes."""
    monkeypatch.delenv("CARTRIDGES_DADOS", raising=False)
    copia = tmp_path / "shared.py"
    shutil.copy(shared.__file__, copia)
    (tmp_path / "instalacao.json").write_text(json.dumps({"canal": "final"}), encoding="utf-8")
    especificacao = importlib.util.spec_from_file_location("shared_copia", copia)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    monkeypatch.setattr(single_instance, "shared", modulo)
    assert single_instance.nomes() == _NOMES_DO_CANAL_FINAL


def test_nomes_da_trava_mudam_com_a_pasta_de_dados(tmp_path, monkeypatch):
    monkeypatch.setattr(shared, "app_dir", tmp_path / "a")
    mutex, evento = single_instance.nomes()
    assert mutex.startswith(f"Local\\{shared.APP_DIR_NAME}.") and mutex.endswith(".SingleInstance")
    assert evento == mutex.removesuffix(".SingleInstance") + ".Present"
    assert (mutex, evento) != _NOMES_DO_CANAL_FINAL
    monkeypatch.setattr(shared, "app_dir", Path(str(tmp_path / "A").upper()))
    assert single_instance.nomes() == (mutex, evento)  # o Windows não diferencia maiúsculas nos caminhos
    monkeypatch.setattr(shared, "app_dir", tmp_path / "b")
    assert single_instance.nomes()[0] != mutex


def test_release_sem_lock_nao_faz_nada(monkeypatch):
    monkeypatch.setattr(single_instance, "_handle", None)
    single_instance.release()
    assert single_instance._handle is None  # noqa: SLF001


# -- acordar a primeira cópia ---------------------------------------------------------------------------------


def test_segunda_copia_do_app_acorda_a_primeira(monkeypatch):
    """A janela principal escondida só a primeira cópia sabe mostrar."""
    _nomes_de_teste(monkeypatch)
    acordou = threading.Event()
    single_instance.watch_second_launch(acordou.set)
    assert not acordou.wait(0.2)

    single_instance._wake_running_instance()  # noqa: SLF001
    assert acordou.wait(2)


def test_segunda_abertura_mostra_a_principal_escondida(app_qt, monkeypatch, flush_idle):  # noqa: ARG001
    """Review Focus 5: a principal escondida pelas tarefas volta, e não fica marcada como escondida."""
    monkeypatch.setattr(backup_de_saves, "_tarefas_abertas", 0)
    principal = QWindow()
    principal.resize(200, 200)
    principal.show()
    painel = PainelDasTarefas()
    painel.definir_janela(principal)
    try:
        tarefas.comecar("Importação", 1)
        flush_idle()
        painel.mostrar()
        assert painel.principalFechando() is False
        assert not principal.isVisible() and painel.principalEscondida

        painel.mostrarPrincipal()
        assert principal.isVisible()
        assert not painel.principalEscondida
        assert painel.aberta  # a janela das tarefas fica
    finally:
        principal.destroy()


def test_segunda_abertura_desfaz_o_minimizar(app_qt):  # noqa: ARG001
    principal = QWindow()
    principal.resize(200, 200)
    principal.showMinimized()
    painel = PainelDasTarefas()
    painel.definir_janela(principal)
    try:
        painel.mostrarPrincipal()
        assert principal.isVisible()
        assert principal.visibility() != QWindow.Visibility.Minimized
    finally:
        principal.destroy()


# -- o realce pela segunda cópia (user32 falso) ---------------------------------------------------------------


def _user32_falso(monkeypatch, visivel, janelas=((42, "Qt6120QWindowIcon"),)):
    """Um user32 em que o EnumWindows passa pelas `janelas` (hwnd, classe), todas com o título "Cartridges"."""
    classes = dict(janelas)
    user32 = MagicMock()

    def titulo(_hwnd, buffer, _n):
        buffer.value = "Cartridges"

    def classe(hwnd, buffer, _n):
        buffer.value = classes[hwnd]

    def enumerar(callback, _param):
        for hwnd in classes:
            if not callback(hwnd, 0):
                return

    user32.GetWindowTextW.side_effect = titulo
    user32.GetClassNameW.side_effect = classe
    user32.EnumWindows.side_effect = enumerar
    user32.IsWindowVisible.return_value = visivel
    user32.IsIconic.return_value = False
    monkeypatch.setattr(ctypes, "WinDLL", lambda _nome: user32, raising=False)
    monkeypatch.setattr(single_instance.sys, "platform", "win32")
    return user32


def test_segunda_abertura_nao_da_foreground_a_principal_escondida(monkeypatch):
    monkeypatch.setattr(single_instance, "_wake_running_instance", lambda: None)
    user32 = _user32_falso(monkeypatch, visivel=False)
    single_instance.present_running_instance()
    user32.SetForegroundWindow.assert_not_called()


def test_segunda_abertura_realca_a_principal_visivel(monkeypatch):
    monkeypatch.setattr(single_instance, "_wake_running_instance", lambda: None)
    user32 = _user32_falso(monkeypatch, visivel=True)
    single_instance.present_running_instance()
    user32.SetForegroundWindow.assert_called_once()


def test_falha_ao_acordar_a_primeira_copia_nao_pula_o_realce(monkeypatch):
    def falha():
        raise OSError("sem evento")

    monkeypatch.setattr(single_instance, "_wake_running_instance", falha)
    user32 = _user32_falso(monkeypatch, visivel=True)
    single_instance.present_running_instance()
    user32.SetForegroundWindow.assert_called_once()


def test_present_procura_a_janela_do_qt(monkeypatch):
    """A janela do app é do Qt; a do Cartridges GTK (classe `gdk*`) com o mesmo título não é a nossa."""
    monkeypatch.setattr(single_instance, "_wake_running_instance", lambda: None)
    user32 = _user32_falso(monkeypatch, visivel=True, janelas=((7, "gdkSurfaceToplevel"), (42, "Qt6120QWindowIcon")))
    single_instance.present_running_instance()
    user32.SetForegroundWindow.assert_called_once()
    assert user32.SetForegroundWindow.call_args.args[0].value == 42

    user32 = _user32_falso(monkeypatch, visivel=True, janelas=((7, "gdkSurfaceToplevel"),))
    single_instance.present_running_instance()
    user32.SetForegroundWindow.assert_not_called()


# -- a segunda cópia do main() ---------------------------------------------------------------------------------

# O `main()` de verdade com a trava já tomada; o realce é trocado (a busca de janelas seria na área de trabalho real).
_SEGUNDA_COPIA = r"""
import json, sys
from cartridges.utils import single_instance

realces = []
single_instance.present_running_instance = lambda: realces.append(1)
from cartridges import app

codigo = app.main([sys.argv[0], "--sair-apos-carregar"])
print(json.dumps({"codigo": codigo, "realces": realces, "nome": single_instance.nomes()[0]}), flush=True)
"""


def test_segunda_copia_do_main_sai_sem_carregar(tmp_path, monkeypatch):
    """Review Focus 5: com a trava da mesma pasta de dados tomada, o segundo processo sai com 0 sem ler os jogos."""
    games = tmp_path / "games"
    games.mkdir(exist_ok=True)
    (games / "imported_1.json").write_text(
        json.dumps({"game_id": "imported_1", "source": "imported", "name": "Alfa", "executable": "x.exe"}),
        encoding="utf-8",
    )
    monkeypatch.setattr(shared, "app_dir", tmp_path)
    nome = single_instance.nomes()[0]
    assert nome not in _NOMES_DO_CANAL_FINAL
    ambiente = {
        **os.environ,
        "CARTRIDGES_DADOS": str(tmp_path),
        "CARTRIDGES_REGISTRO": rf"Software\CartridgesTestes\instancia-{uuid.uuid4()}",
        "QT_QPA_PLATFORM": "offscreen",
    }
    assert single_instance.acquire()
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", _SEGUNDA_COPIA], cwd=RAIZ, env=ambiente, capture_output=True, text=True,
            timeout=60, check=False,
        )  # fmt: skip
    finally:
        single_instance.release()
    assert resultado.returncode == 0, resultado.stderr
    assert "jogos carregados" not in resultado.stdout
    saida = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert saida == {"codigo": 0, "realces": [1], "nome": nome}
