"""O que sobrou do GTK da área das tarefas (Task 4 do plano 8a): o fechamento da principal e a segunda abertura.

O botão do canto e a janela foram para `test_tarefas_qt.py`."""

from types import SimpleNamespace

from cartridges.modelos import tarefas


# -- a janela solta ------------------------------------------------------------


def _principal(visivel, sair):
    return SimpleNamespace(
        get_visible=lambda: visivel, get_application=lambda: SimpleNamespace(quit=sair)
    )


def test_fechar_a_janela_com_a_principal_escondida_encerra_o_app(monkeypatch):
    from cartridges import shared  # noqa: PLC0415
    from cartridges.tarefas_janela import TarefasJanela

    saidas = []
    monkeypatch.setattr(shared, "win", _principal(False, lambda: saidas.append(1)))
    janela = TarefasJanela()
    assert not janela.emit("close-request")
    assert saidas == [1]


def test_fechar_a_janela_com_a_principal_visivel_so_a_fecha(monkeypatch):
    from cartridges import shared  # noqa: PLC0415
    from cartridges.tarefas_janela import TarefasJanela

    saidas = []
    monkeypatch.setattr(shared, "win", _principal(True, lambda: saidas.append(1)))
    janela = TarefasJanela()
    assert not janela.emit("close-request")
    assert saidas == []


class _JanelaFalsa:
    def __init__(self):
        self.fechada = False

    def close(self):
        self.fechada = True


def _fechar_principal(monkeypatch, com_janela):
    from cartridges.main import CartridgesApplication
    from cartridges.tarefas_janela import TarefasJanela

    janela = _JanelaFalsa() if com_janela else None
    monkeypatch.setattr(TarefasJanela, "aberta", janela)
    escondidas = []
    principal = SimpleNamespace(set_visible=escondidas.append)
    devolvido = CartridgesApplication.on_win_close_request(None, principal)
    return devolvido, escondidas, janela


def test_fechar_a_principal_com_tarefa_e_janela_so_esconde(monkeypatch, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    devolvido, escondidas, janela = _fechar_principal(monkeypatch, True)
    assert devolvido is True
    assert escondidas == [False]
    assert not janela.fechada


def test_fechar_a_principal_sem_tarefa_fecha_tambem_a_janela(monkeypatch):
    devolvido, escondidas, janela = _fechar_principal(monkeypatch, True)
    assert devolvido is False
    assert escondidas == []
    assert janela.fechada


def test_fechar_a_principal_com_tarefa_sem_janela_fecha_tudo(monkeypatch, flush_idle):
    tarefas.comecar("Importação", 1)
    flush_idle()
    devolvido, escondidas, _ = _fechar_principal(monkeypatch, False)
    assert devolvido is False
    assert escondidas == []


def test_fechar_com_saves_em_andamento_esconde_e_mostra_as_tarefas(monkeypatch):
    """O backup ou a restauração dos saves em curso não pode ficar órfão: o app não
    fecha, mas some da tela e abre a janela das tarefas, que o encerra ao ser fechada."""
    from cartridges.main import CartridgesApplication
    from cartridges.saves import backup_de_saves
    from cartridges.tarefas_janela import TarefasJanela

    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    monkeypatch.setattr(TarefasJanela, "aberta", None)
    mostradas = []
    monkeypatch.setattr(TarefasJanela, "mostrar", mostradas.append)
    escondidas = []
    principal = SimpleNamespace(set_visible=escondidas.append)

    devolvido = CartridgesApplication.on_win_close_request(None, principal)

    assert devolvido is True
    assert escondidas == [False]
    assert mostradas == [principal]


def test_fechar_logo_depois_de_pedir_o_backup_dos_saves_esconde(monkeypatch):
    """O backup conta desde o pedido: fechar o app antes de a thread chegar ao Ludusavi
    (a busca do nome, a espera pela trava) também não o perde."""
    from cartridges.main import CartridgesApplication
    from cartridges.saves import backup_de_saves
    from cartridges.tarefas_janela import TarefasJanela

    monkeypatch.setattr(backup_de_saves, "_tarefas_abertas", 0)
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    monkeypatch.setattr(backup_de_saves, "_biblioteca", list)
    monkeypatch.setattr(backup_de_saves, "_em_segundo_plano", lambda *_args: None)  # nem roda
    monkeypatch.setattr(TarefasJanela, "aberta", None)
    mostradas = []
    monkeypatch.setattr(TarefasJanela, "mostrar", mostradas.append)
    escondidas = []
    principal = SimpleNamespace(set_visible=escondidas.append)

    backup_de_saves.no_fim_da_sessao(SimpleNamespace(name="Meu Jogo"))
    devolvido = CartridgesApplication.on_win_close_request(None, principal)

    assert devolvido is True
    assert escondidas == [False]
    assert mostradas == [principal]


def test_segunda_copia_do_app_acorda_a_primeira(monkeypatch):
    """A janela principal escondida só a primeira cópia sabe mostrar."""
    import threading  # noqa: PLC0415

    from cartridges.utils import single_instance  # noqa: PLC0415

    # Nome próprio: um app de verdade aberto na máquina vigia o evento real.
    monkeypatch.setattr(single_instance, "_EVENT_NAME", "Local\\Cartridges.Teste.Acordar")
    acordou = threading.Event()
    single_instance.watch_second_launch(acordou.set)
    assert not acordou.wait(0.2)

    single_instance._wake_running_instance()  # pylint: disable=protected-access
    assert acordou.wait(2)


def test_segunda_abertura_mostra_a_principal_escondida(monkeypatch):
    from cartridges import shared  # noqa: PLC0415
    from cartridges.main import CartridgesApplication

    chamadas = []
    monkeypatch.setattr(shared, "win", SimpleNamespace(present=lambda: chamadas.append(1)))
    assert CartridgesApplication.on_second_launch(None) is False  # idle de uma vez só
    assert chamadas == [1]


def _user32_falso(monkeypatch, visivel):
    """Um user32 em que EnumWindows acha a principal (HWND 42); devolve as chamadas."""
    import ctypes  # noqa: PLC0415
    from unittest.mock import MagicMock  # noqa: PLC0415

    from cartridges.utils import single_instance  # noqa: PLC0415

    user32 = MagicMock()

    def titulo(_hwnd, buffer, _n):
        buffer.value = "Cartridges"

    def classe(_hwnd, buffer, _n):
        buffer.value = "gdkSurfaceToplevel"

    user32.GetWindowTextW.side_effect = titulo
    user32.GetClassNameW.side_effect = classe
    user32.EnumWindows.side_effect = lambda callback, _param: callback(42, 0)
    user32.IsWindowVisible.return_value = visivel
    user32.IsIconic.return_value = False
    monkeypatch.setattr(ctypes, "WinDLL", lambda _nome: user32, raising=False)
    monkeypatch.setattr(single_instance.sys, "platform", "win32")
    return user32


def test_segunda_abertura_nao_da_foreground_a_principal_escondida(monkeypatch):
    from cartridges.utils import single_instance  # noqa: PLC0415

    monkeypatch.setattr(single_instance, "_wake_running_instance", lambda: None)
    user32 = _user32_falso(monkeypatch, visivel=False)
    single_instance.present_running_instance()
    user32.SetForegroundWindow.assert_not_called()


def test_segunda_abertura_realca_a_principal_visivel(monkeypatch):
    from cartridges.utils import single_instance  # noqa: PLC0415

    monkeypatch.setattr(single_instance, "_wake_running_instance", lambda: None)
    user32 = _user32_falso(monkeypatch, visivel=True)
    single_instance.present_running_instance()
    user32.SetForegroundWindow.assert_called_once()


def test_falha_ao_acordar_a_primeira_copia_nao_pula_o_realce(monkeypatch):
    from cartridges.utils import single_instance  # noqa: PLC0415

    def falha():
        raise OSError("sem evento")

    monkeypatch.setattr(single_instance, "_wake_running_instance", falha)
    user32 = _user32_falso(monkeypatch, visivel=True)
    single_instance.present_running_instance()
    user32.SetForegroundWindow.assert_called_once()


