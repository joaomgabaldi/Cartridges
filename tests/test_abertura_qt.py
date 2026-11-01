# test_abertura_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A abertura em etapas (D74): redefinição antes do log, restauração agendada com a janela própria, os avisos depois
da janela, a segunda abertura durante a restauração e o reinício pedido pelo app (D75)."""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
import uuid
import winreg
from pathlib import Path

from PySide6.QtCore import QEventLoop, Qt, QTimer

from cartridges import app as modulo_app
from cartridges import shared
from cartridges.aplicativo import Aplicativo
from cartridges.utils import backup, redefinir
from tests.apoio_abertura import preparar_main
from tests.apoio_aplicativo import AplicativoAnotado
from tests.apoio_registro import _apagar_chave

RAIZ = Path(__file__).resolve().parent.parent


def _esperar(ate=None, limite=5.0):
    fim = time.monotonic() + (0.2 if ate is None else limite)
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(20, laco.quit)
        laco.exec()
        if ate is not None and ate():
            return True
    return ate is None


def _ficha(pasta: Path, game_id: str, nome: str) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    dados = {"game_id": game_id, "source": "imported", "name": nome, "executable": "start game.exe"}
    (pasta / f"{game_id}.json").write_text(json.dumps(dados), encoding="utf-8")


def _rodar(argumentos: list[str], dados: Path) -> subprocess.CompletedProcess:
    registro = rf"Software\CartridgesTestes\abertura-{uuid.uuid4()}"
    ambiente = {**os.environ, "CARTRIDGES_DADOS": str(dados), "CARTRIDGES_REGISTRO": registro, "QT_QPA_PLATFORM": "offscreen"}
    try:
        return subprocess.run(
            [sys.executable, *argumentos], cwd=RAIZ, env=ambiente, capture_output=True, text=True, timeout=90, check=False
        )
    finally:
        _apagar_chave(winreg.HKEY_CURRENT_USER, registro)


# -- a restauração agendada ---------------------------------------------------------------------------------------


def test_backup_agendado_e_aplicado_antes_da_biblioteca(tmp_path):
    _ficha(shared.games_dir, "imported_1", "Alfa")
    _ficha(shared.games_dir, "imported_2", "Beta")
    zip_ = tmp_path / "origem.zip"
    backup.exportar(zip_, backup.ler_configuracoes())
    dados = tmp_path / "dados"
    _ficha(dados / "games", "imported_9", "Antes")  # a biblioteca de antes não sobra
    shutil.copyfile(zip_, dados / "restaurar.zip")

    resultado = _rodar(["-m", "cartridges", "--sair-apos-carregar"], dados)

    assert resultado.returncode == 0, resultado.stderr
    assert "jogos carregados: 2" in resultado.stdout
    assert not (dados / "restaurar.zip").exists()
    assert sorted(p.name for p in (dados / "games").glob("*.json")) == ["imported_1.json", "imported_2.json"]


def _restaurar(monkeypatch, abrir):
    """O `_restaurar_e_abrir` de verdade (janela, thread, `backup.aplicar_pendente`), com o `_abrir` dado."""
    monkeypatch.setattr(modulo_app, "_abrir", abrir)
    abertura = modulo_app._Abertura()  # noqa: SLF001
    modulo_app._restaurar_e_abrir(modulo_app.QGuiApplication.instance(), ["cartridges"], abertura)  # noqa: SLF001
    janela = abertura.restauracao.rootObjects()[0]
    restaurando = abertura.restauracao.rootContext().contextProperty("restaurando")
    return abertura, janela, restaurando


def _fechar_restauracao(abertura):
    if abertura.restauracao is not None:
        for raiz in abertura.restauracao.rootObjects():
            raiz.close()
        abertura.restauracao.deleteLater()
    _esperar()


def test_restauracao_que_falha_abre_o_app_com_o_aviso(app_qt, monkeypatch):  # noqa: ARG001
    """Review Focus 2: um zip corrompido não leva nada; os dados de antes ficam e o primeiro aviso é o da falha."""
    _ficha(shared.games_dir, "imported_9", "Antes")
    (shared.app_dir / "restaurar.zip").write_bytes(b"isto nao e um zip")
    monkeypatch.setattr(backup, "pasta_dos_saves_desfeita", None)
    monkeypatch.setattr(redefinir, "falha", None)

    def abrir(_app, _argv, abertura):
        abertura.aplicativo = AplicativoAnotado()

    abertura, janela, _restaurando = _restaurar(monkeypatch, abrir)
    try:
        assert _esperar(lambda: abertura.aplicativo is not None and abertura.aplicativo.dialogos)
        assert abertura.aplicativo.dialogos[0] == (
            "Não foi possível restaurar", "Não foi possível restaurar o backup. Tente novamente."
        )
        assert (shared.games_dir / "imported_9.json").is_file()
        assert not (shared.app_dir / "restaurar.zip").exists()
        assert _esperar(lambda: not janela.isVisible())
    finally:
        _fechar_restauracao(abertura)


def test_abertura_quebrada_depois_da_restauracao_fecha_a_janela(app_qt, monkeypatch, caplog):  # noqa: ARG001
    """Review Focus 2: uma janela sem fechar, presa em 100%, só sairia pelo Gerenciador de Tarefas."""
    saidas = []
    monkeypatch.setattr(modulo_app.QGuiApplication, "exit", staticmethod(saidas.append))

    def abrir(_app, _argv, _abertura):
        raise RuntimeError("abertura quebrada")

    with caplog.at_level(logging.ERROR):
        abertura, janela, restaurando = _restaurar(monkeypatch, abrir)
        try:
            assert _esperar(lambda: restaurando.podeFechar)
            assert _esperar(lambda: not janela.isVisible())
            assert saidas == [1]
        finally:
            _fechar_restauracao(abertura)
    assert "abertura quebrada" in caplog.text


def test_principal_aparece_antes_de_a_restauracao_fechar(app_qt, monkeypatch):  # noqa: ARG001
    """O app nunca fica sem janela: a principal nasce com a da restauração ainda à vista."""
    vista = []
    janela_da_restauracao = []

    def abrir(_app, _argv, abertura):
        vista.append(janela_da_restauracao[0].isVisible())
        abertura.aplicativo = AplicativoAnotado()

    monkeypatch.setattr(modulo_app, "_abrir", abrir)
    abertura = modulo_app._Abertura()  # noqa: SLF001
    original = modulo_app._janela_da_restauracao  # noqa: SLF001

    def guardar():
        motor = original()
        janela_da_restauracao.append(motor.rootObjects()[0])
        return motor

    monkeypatch.setattr(modulo_app, "_janela_da_restauracao", guardar)
    modulo_app._restaurar_e_abrir(app_qt, ["cartridges"], abertura)  # noqa: SLF001
    try:
        assert _esperar(lambda: vista)
        assert vista == [True]
        assert _esperar(lambda: not janela_da_restauracao[0].isVisible())
    finally:
        _fechar_restauracao(abertura)


def test_segunda_abertura_durante_a_restauracao_traz_a_janela(app_qt):  # noqa: ARG001
    """Review Focus 5: sem principal ainda, o segundo clique no atalho traz a janela da restauração."""
    abertura = modulo_app._Abertura()  # noqa: SLF001
    abertura.restauracao = modulo_app._janela_da_restauracao()  # noqa: SLF001
    janela = abertura.restauracao.rootObjects()[0]
    try:
        janela.showMinimized()
        _esperar()
        modulo_app._acordar(abertura)  # noqa: SLF001
        _esperar()
        assert janela.isVisible()
        assert not janela.windowStates() & Qt.WindowState.WindowMinimized
    finally:
        abertura.restauracao.rootContext().contextProperty("restaurando").terminar()
        _fechar_restauracao(abertura)


# -- os avisos e a redefinição ---------------------------------------------------------------------------------------


def test_main_avisa_da_pasta_dos_saves_logo_depois_do_aviso_de_falha(app_qt, monkeypatch):  # noqa: ARG001
    """A ordem da fila da D72: o segundo diálogo espera o primeiro fechar."""
    monkeypatch.setattr(backup, "pasta_dos_saves_desfeita", "D:/Saves & Cia")
    monkeypatch.setattr(redefinir, "falha", OSError("preso"))
    aplicativo = Aplicativo()
    pedidos = []
    aplicativo.dialogoPedido.connect(lambda titulo, corpo, _itens: pedidos.append((titulo, corpo)))

    modulo_app._avisos_da_abertura(aplicativo, True)  # noqa: SLF001

    assert pedidos == [("Não foi possível restaurar", "Não foi possível restaurar o backup. Tente novamente.")]
    aplicativo.dialogoFechado()
    assert pedidos[1] == (
        "Cópias dos saves na pasta padrão",
        "As cópias dos saves do backup foram para a pasta padrão. "
        "Para voltar a usar D:\\Saves & Cia, escolha-a novamente em Preferências.",
    )
    aplicativo.dialogoFechado()
    assert pedidos[2] == (
        "Não foi possível redefinir", "Não foi possível concluir a redefinição do Cartridges. Tente novamente."
    )
    aplicativo.dialogoFechado()
    assert len(pedidos) == 3


def test_sem_falhas_a_abertura_nao_avisa(monkeypatch):
    monkeypatch.setattr(backup, "pasta_dos_saves_desfeita", None)
    monkeypatch.setattr(redefinir, "falha", None)
    aplicativo = AplicativoAnotado()
    modulo_app._avisos_da_abertura(aplicativo, False)  # noqa: SLF001
    assert aplicativo.dialogos == []


def test_redefinir_roda_antes_do_log(tmp_path):
    """O log antigo mora na pasta do app: aberto antes, ele sobraria (e travaria) numa pasta redefinida."""
    dados = tmp_path / "dados"
    _ficha(dados / "games", "imported_1", "Alfa")
    (dados / "logs").mkdir()
    (dados / "logs" / "cartridges.log").write_text("linha antiga\n", encoding="utf-8")
    (dados / "redefinir").touch()

    resultado = _rodar(["-m", "cartridges", "--sair-apos-carregar"], dados)

    assert resultado.returncode == 0, resultado.stderr
    assert "jogos carregados: 0" in resultado.stdout
    textos = [p.read_text(encoding="utf-8", errors="replace") for p in (dados / "logs").iterdir() if p.is_file()]
    assert not any("linha antiga" in texto for texto in textos)
    assert any("Cartridges redefinido" in texto for texto in textos)
    assert not (dados / "redefinir").exists()


def test_redefinicao_que_falha_avisa_depois_da_janela(monkeypatch, caplog):
    eventos = []

    def redefinir_que_falha():
        monkeypatch.setattr(redefinir, "falha", OSError("arquivo preso"))
        return False

    class Anotado(AplicativoAnotado):
        reiniciar = False

        def pedir_dialogo(self, titulo, corpo, itens, ao_fechar, preferencias=None):
            eventos.append(("dialogo", titulo))
            super().pedir_dialogo(titulo, corpo, itens, ao_fechar, preferencias)

    def abrir(_app, _argv, abertura):
        eventos.append("janela")
        abertura.aplicativo = Anotado()

    monkeypatch.setattr(redefinir, "falha", None)
    monkeypatch.setattr(backup, "pasta_dos_saves_desfeita", None)
    preparar_main(monkeypatch, abrir, eventos)
    monkeypatch.setattr(modulo_app.redefinir, "aplicar_pendente", redefinir_que_falha)

    with caplog.at_level(logging.INFO):
        assert modulo_app.main(["cartridges"]) == 0

    assert eventos == ["log", "janela", ("dialogo", "Não foi possível redefinir")]
    registro = next(r for r in caplog.records if r.getMessage() == "Não foi possível redefinir o Cartridges")
    assert registro.levelno == logging.ERROR and registro.exc_info is not None


def test_fechar_durante_a_restauracao_pula_o_que_ainda_nao_existe(monkeypatch, caplog):
    """O desligar do Windows durante a restauração: o `aboutToQuit` vem sem a biblioteca aberta."""
    feitos = []

    class Anotado:
        def __init__(self, nome):
            self._nome = nome

        def __getattr__(self, metodo):
            return lambda: feitos.append(f"{self._nome}.{metodo}")

    for nome in ("login", "ea_conta", "async_manager", "copias_animadas", "icones"):
        monkeypatch.setattr(modulo_app, nome, Anotado(nome))
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)
    with caplog.at_level(logging.ERROR):
        modulo_app._fechar(modulo_app._Abertura())  # noqa: SLF001
    assert feitos == [
        "login.cancelar_pendente", "ea_conta.gravar_pendente", "async_manager.encerrar", "copias_animadas.encerrar",
        "icones.encerrar",
    ]  # fmt: skip
    assert "Falha ao encerrar" not in caplog.text


# -- o assistente da primeira abertura (D86) -------------------------------------------------------------------------


def _assistente(app_qt, monkeypatch, eventos, restaurar=None):
    """O `_mostrar_assistente` de verdade (a janela num motor próprio), com o `_abrir` e o `_restaurar_e_abrir` espiões."""
    from cartridges import assistente as modulo_assistente  # noqa: PLC0415

    monkeypatch.setattr(shared, "store", None, raising=False)
    monkeypatch.setattr(modulo_assistente, "precisa_mostrar", lambda: True)
    monkeypatch.setattr(modulo_app, "_abrir", lambda _app, _argv, _abertura: eventos.append("abrir"))
    monkeypatch.setattr(modulo_app, "_avisos_da_abertura", lambda *_a: eventos.append("avisos"))

    def restaurar_espiao(_app, _argv, _abertura):
        eventos.append("restaurar")
        if restaurar is not None:
            restaurar()

    monkeypatch.setattr(modulo_app, "_restaurar_e_abrir", restaurar_espiao)
    abertura = modulo_app._Abertura()  # noqa: SLF001
    assert modulo_app._mostrar_assistente(app_qt, ["cartridges"], abertura) is True  # noqa: SLF001
    janela = abertura.assistente.rootObjects()[0]
    modelo = abertura.assistente.rootContext().contextProperty("assistente")
    _esperar()
    return abertura, janela, modelo


def _fechar_assistente(abertura):
    if abertura.assistente is not None:
        for raiz in abertura.assistente.rootObjects():
            raiz.close()
        abertura.assistente.deleteLater()
    _esperar()


def test_primeira_abertura_mostra_o_assistente_e_nao_abre(app_qt, monkeypatch):
    eventos = []
    abertura, janela, modelo = _assistente(app_qt, monkeypatch, eventos)
    try:
        assert janela.isVisible() and eventos == []
        assert shared.store is not None and list(shared.store) == []  # a store vazia das contas (Pré-voo 9)
        modelo.concluir()
        assert eventos == ["abrir", "avisos"]
        assert _esperar(lambda: not janela.isVisible())
    finally:
        _fechar_assistente(abertura)


def test_segunda_ativacao_com_o_assistente_traz_o_assistente(app_qt, monkeypatch):
    """D76: o segundo clique no atalho com o assistente à vista traz o assistente."""
    eventos = []
    abertura, janela, _modelo = _assistente(app_qt, monkeypatch, eventos)
    try:
        janela.showMinimized()
        _esperar()
        modulo_app._acordar(abertura)  # noqa: SLF001
        _esperar()
        assert janela.isVisible()
        assert not janela.windowStates() & Qt.WindowState.WindowMinimized
        assert eventos == []
    finally:
        _fechar_assistente(abertura)


def test_restaurar_pelo_assistente_segue_a_restauracao(app_qt, monkeypatch, tmp_path):
    from cartridges import assistente as modulo_assistente  # noqa: PLC0415

    monkeypatch.setattr(modulo_assistente, "_em_thread", lambda tarefa: tarefa())
    monkeypatch.setattr(backup, "validar", lambda _caminho: {})
    monkeypatch.setattr(backup, "agendar", lambda _caminho: None)
    eventos, vista = [], []
    abertura, janela, modelo = _assistente(app_qt, monkeypatch, eventos, restaurar=lambda: vista.append(janela.isVisible()))
    try:
        modelo.restaurarBackup(modulo_app.QUrl.fromLocalFile(str(tmp_path / "b.zip")))
        assert _esperar(lambda: eventos)
        # A janela "Restaurando…" nasce com o assistente ainda na tela; só depois ele fecha.
        assert eventos == ["restaurar"] and vista == [True]
        assert shared.schema.get_boolean("assistente-concluido") is True
        assert _esperar(lambda: not janela.isVisible())
    finally:
        _fechar_assistente(abertura)


def test_backup_pendente_vem_antes_do_assistente(monkeypatch):
    eventos = []
    preparar_main(monkeypatch, lambda *_a: eventos.append("abrir"), eventos)
    monkeypatch.setattr(modulo_app.backup, "ha_pendente", lambda: True)
    monkeypatch.setattr(modulo_app, "_restaurar_e_abrir", lambda *_a: eventos.append("restaurar"))
    monkeypatch.setattr(modulo_app, "_mostrar_assistente", lambda *_a, **_k: eventos.append("assistente") or True)
    assert modulo_app.main(["cartridges"]) == 0
    assert eventos == ["log", "restaurar"]


def test_sem_backup_agendado_abre_na_hora(monkeypatch):
    from cartridges import assistente as modulo_assistente  # noqa: PLC0415

    eventos = []

    preparar_main(monkeypatch, lambda *_a: eventos.append("abrir"), eventos)
    monkeypatch.setattr(modulo_assistente, "precisa_mostrar", lambda: False)
    monkeypatch.setattr(modulo_app, "_restaurar_e_abrir", lambda *_a: eventos.append("restaurar"))
    monkeypatch.setattr(backup, "pasta_dos_saves_desfeita", None)
    monkeypatch.setattr(redefinir, "falha", None)
    assert modulo_app.main(["cartridges"]) == 0
    assert eventos == ["log", "abrir"]


def test_sair_apos_carregar_nao_mostra_o_assistente(tmp_path):
    """Pré-voo 8: o modo de teste da carga, sem tela, sobre uma pasta de dados vazia (a primeira abertura)."""
    resultado = _rodar(["-m", "cartridges", "--sair-apos-carregar"], tmp_path / "dados")
    assert resultado.returncode == 0, resultado.stderr
    assert "jogos carregados: 0" in resultado.stdout


# O `main()` de verdade sobre uma pasta de dados vazia: o assistente aparece e o roteiro o fecha pelo X.
_FECHAR_PELO_X = r"""
import sys
from pathlib import Path
from PySide6.QtCore import QTimer
from cartridges import app as modulo_app

anotacoes = Path(sys.argv[1])

def anotar(texto):
    with anotacoes.open("a", encoding="utf-8") as arquivo:
        arquivo.write(texto + "\n")

def abrir(*_a):
    anotar("abrir")
    return 1

modulo_app._abrir = abrir
fechar_original = modulo_app._fechar

def fechar(abertura):
    anotar("aboutToQuit")
    fechar_original(abertura)

modulo_app._fechar = fechar
mostrar_original = modulo_app._mostrar_assistente

def mostrar(app, argv, abertura, *a, **k):
    mostrado = mostrar_original(app, argv, abertura, *a, **k)
    anotar(f"assistente {mostrado}")
    janela = abertura.assistente.rootObjects()[0]
    QTimer.singleShot(500, janela.close)
    return mostrado

modulo_app._mostrar_assistente = mostrar
sys.exit(modulo_app.main(["cartridges"]))
"""


def test_fechar_o_assistente_pelo_x_encerra_o_app_sem_abrir_a_biblioteca(tmp_path):
    anotacoes = tmp_path / "anotacoes.txt"
    inicio = time.monotonic()
    resultado = _rodar(["-c", _FECHAR_PELO_X, str(anotacoes)], tmp_path / "dados")
    assert resultado.returncode == 0, resultado.stderr
    assert time.monotonic() - inicio < 15
    assert anotacoes.read_text(encoding="utf-8").splitlines() == ["assistente True", "aboutToQuit"]


# -- o reinício ------------------------------------------------------------------------------------------------------

# Com a principal à vista e saves em andamento, o X seria recusado (D78); o `quit()` do reinício não pode ser.
_REINICIO = r"""
import json
from PySide6.QtCore import QTimer
from PySide6.QtQml import QQmlApplicationEngine
from cartridges import app as modulo_app
from cartridges.aplicativo import Aplicativo
from cartridges.modelos.tarefas import PainelDasTarefas
from cartridges.saves import backup_de_saves

backup_de_saves.em_andamento = lambda: True
qt = modulo_app.AplicacaoQt([])
painel = PainelDasTarefas()
qt.saindo.connect(painel.encerrando)  # como o `_abrir`
motor = QQmlApplicationEngine()
motor.rootContext().setContextProperty("painelDasTarefas", painel)
motor.loadData(b"import QtQuick\nWindow { visible: true; width: 200; height: 200; "
               b"onClosing: (fechar) => fechar.accepted = painelDasTarefas.principalFechando() }")
assert motor.rootObjects()
aplicativo = Aplicativo()
QTimer.singleShot(0, aplicativo.pedir_reinicio)
QTimer.singleShot(8000, lambda: qt.exit(7))  # o `quit()` recusado deixaria o app aberto
codigo = qt.exec()
print(json.dumps({"codigo": codigo, "reiniciar": aplicativo.reiniciar}), flush=True)
"""


def test_pedir_reinicio_sai_e_marca(tmp_path):
    resultado = _rodar(["-c", _REINICIO], tmp_path / "dados")
    assert resultado.returncode == 0, resultado.stderr
    saida = json.loads(resultado.stdout.strip().splitlines()[-1])
    assert saida == {"codigo": 0, "reiniciar": True}


def test_aplicativo_nasce_sem_reinicio(app_qt):  # noqa: ARG001
    assert Aplicativo().reiniciar is False
