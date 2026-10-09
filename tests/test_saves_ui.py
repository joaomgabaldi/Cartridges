"""A interface dos saves: o fim da sessão, o menu do jogo, o diálogo de versões e as
Preferências."""

import threading
from datetime import datetime, timezone
from pathlib import Path

import pytest

from cartridges.saves import backup_de_saves, pasta
from cartridges.saves.ludusavi import Versao


def _versao(id_: str, quando: datetime) -> Versao:
    return Versao(id_, quando.replace(tzinfo=timezone.utc))


# -- fim da sessão -------------------------------------------------------------


def test_fim_de_sessao_dispara_backup(monkeypatch, win, make_game):
    chamados = []
    monkeypatch.setattr(backup_de_saves, "no_fim_da_sessao", chamados.append)
    jogo = make_game()
    win.session_toast(jogo, 60)
    assert chamados == [jogo]


def test_falha_ao_iniciar_o_backup_nao_perde_o_aviso(monkeypatch, win, make_game):
    def explode(_jogo):
        raise RuntimeError("falhou")

    monkeypatch.setattr(backup_de_saves, "no_fim_da_sessao", explode)
    with pytest.raises(RuntimeError):
        win.session_toast(make_game(), 60)
    assert len(win.toast_queue.added) == 1


# -- menu do jogo --------------------------------------------------------------


def test_acao_some_sem_backup(monkeypatch, win, make_game):
    from cartridges.window import CartridgesWindow  # noqa: PLC0415

    com_backup = make_game(ludusavi_nome="A")
    sem_backup = make_game(ludusavi_nome="B")
    monkeypatch.setattr(backup_de_saves, "tem_backup", lambda jogo: jogo is com_backup)
    acao = win.get_application().lookup_action("restore_save")

    CartridgesWindow.set_active_game(win, None, None, sem_backup)
    assert win.active_game is sem_backup
    assert acao.enabled is False

    CartridgesWindow.set_active_game(win, None, None, com_backup)
    assert acao.enabled is True


def test_restore_save_esta_registrada_e_no_menu():
    texto = (Path(__file__).resolve().parent.parent / "data" / "gtk" / "game.blp").read_text(
        encoding="utf-8"
    )
    assert 'label: _("Restaurar save");' in texto
    assert 'action: "app.restore_save";' in texto
    assert 'hidden-when: "action-disabled";' in texto
    principal = (Path(__file__).resolve().parent.parent / "cartridges" / "main.py").read_text(
        encoding="utf-8"
    )
    assert '("restore_save",)' in principal
    assert "def on_restore_save_action" in principal


# -- diálogo de versões --------------------------------------------------------


def test_dialogo_lista_versoes_mais_recente_primeiro(monkeypatch, make_game):
    from cartridges.saves import dialogo  # noqa: PLC0415

    jogo = make_game(ludusavi_nome="A")
    # 00:14 UTC: no fuso local o dia pode mudar, então o esperado sai da mesma conversão.
    velha = _versao("v1", datetime(2026, 10, 8, 12, 0))
    nova = _versao("v2", datetime(2026, 10, 9, 21, 14))
    monkeypatch.setattr(backup_de_saves, "versoes_do_jogo", lambda _jogo: [velha, nova])

    caixa = dialogo.DialogoDeVersoes(jogo)

    local = nova.quando.astimezone()
    esperado = f"{local:%d/%m/%Y} às {local:%H:%M}"
    titulos = [linha.get_title() for linha in caixa.linhas]
    assert titulos[0] == esperado
    assert len(titulos) == 2
    assert titulos[1] == dialogo.formatar(velha.quando)


def test_data_local_no_formato_da_spec(monkeypatch):
    from cartridges.saves import dialogo  # noqa: PLC0415

    quando = datetime(2026, 10, 9, 21, 14, tzinfo=timezone.utc)
    local = quando.astimezone()
    assert dialogo.formatar(quando) == f"{local:%d/%m/%Y} às {local:%H:%M}"
    assert dialogo.formatar(quando).count(" às ") == 1


def test_confirmacao_tem_o_texto_da_spec(monkeypatch, make_game):
    from cartridges.saves import dialogo  # noqa: PLC0415

    jogo = make_game(ludusavi_nome="A")
    versao = _versao("v1", datetime(2026, 10, 9, 21, 14))
    criados = []

    class Dialogo:
        def connect(self, sinal, funcao):
            criados.append((sinal, funcao))

    argumentos = []
    monkeypatch.setattr(
        dialogo, "create_dialog", lambda *a, **k: argumentos.append((a, k)) or Dialogo()
    )
    restaurados = []
    monkeypatch.setattr(backup_de_saves, "restaurar", lambda g, v: restaurados.append((g, v)))

    dialogo.confirmar(None, jogo, versao)

    (janela, titulo, corpo, resposta, rotulo), opcoes = argumentos[0]
    local = versao.quando.astimezone()
    assert corpo == (
        f"Tem certeza que deseja restaurar o save de {local:%d/%m/%Y} às {local:%H:%M}? "
        "Os saves atuais deste jogo serão substituídos."
    )
    assert opcoes == {"destructive": True}
    assert rotulo == "Restaurar"

    sinal, funcao = criados[0]
    assert sinal == "response"
    funcao(None, "dismiss")
    assert restaurados == []
    funcao(None, resposta)
    assert restaurados == [(jogo, "v1")]


# -- Preferências --------------------------------------------------------------


def _preferencias(monkeypatch):
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    return preferences_module.CartridgesPreferences()


def test_preferencias_sem_ludusavi_escondem_as_linhas(monkeypatch):
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: False)
    preferencias = _preferencias(monkeypatch)
    assert preferencias.pasta_dos_saves_row.get_visible() is False
    assert preferencias.restaurar_saves_button_row.get_visible() is False


def test_preferencias_com_ludusavi_mostram_as_linhas(monkeypatch):
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    preferencias = _preferencias(monkeypatch)
    assert preferencias.pasta_dos_saves_row.get_visible() is True
    assert preferencias.restaurar_saves_button_row.get_visible() is True
    assert preferencias.pasta_dos_saves_row.get_subtitle() == str(pasta.atual()).replace("/", "\\")


def test_subtitulo_da_pasta_dos_saves_no_formato_do_windows_e_com_e_comercial(monkeypatch, schema):
    """O subtítulo é markup: um `&` cru o deixaria em branco; e `/` não é como o
    Windows mostra uma pasta."""
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    schema.set_string("pasta-dos-saves", "D:/Jogos & Saves/Cartridges")
    preferencias = _preferencias(monkeypatch)
    assert preferencias.pasta_dos_saves_row.get_subtitle() == r"D:\Jogos &amp; Saves\Cartridges"


def test_descricao_do_backup_menciona_os_saves_so_com_ludusavi(monkeypatch):
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    assert _preferencias(monkeypatch).backup_group.get_description() == (
        "Salve em um arquivo .zip a biblioteca completa, as cópias dos saves dos jogos e "
        "todas as configurações. A restauração substitui a biblioteca, as configurações e as "
        "cópias dos saves pelas do backup. Para devolver os saves aos jogos, use "
        "“Restaurar saves de todos os jogos”."
    )
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: False)
    assert _preferencias(monkeypatch).backup_group.get_description() == (
        "Salve em um arquivo .zip a biblioteca completa e todas as configurações. "
        "A restauração substitui a biblioteca e as configurações atuais pelas do backup."
    )


def _toasts(preferencias, monkeypatch):
    avisos = []
    monkeypatch.setattr(preferencias, "add_toast", lambda toast: avisos.append(toast.get_title()))
    return avisos


def _esperar_troca(preferencias, monkeypatch, resultado):
    """Troca a pasta com `trocar_pasta` simulada e devolve a thread que a chamou."""
    chamada = threading.Event()
    thread = []

    def falsa(nova):
        thread.append(threading.current_thread())
        chamada.set()
        if resultado is not None:
            raise resultado

    monkeypatch.setattr(backup_de_saves, "trocar_pasta", falsa)
    preferencias._trocar_pasta_dos_saves(Path("X:/nova"))  # noqa: SLF001
    assert chamada.wait(5)
    return thread[0]


def test_troca_da_pasta_roda_fora_da_tela_e_atualiza_o_subtitulo(
    monkeypatch, flush_idle, schema
):
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    preferencias = _preferencias(monkeypatch)
    avisos = _toasts(preferencias, monkeypatch)
    schema.set_string("pasta-dos-saves", "X:/nova")  # o que o trocar_pasta de verdade faria

    thread = _esperar_troca(preferencias, monkeypatch, None)
    _drenar(flush_idle, lambda: preferencias.pasta_dos_saves_row.get_subtitle() == r"X:\nova")

    assert thread is not threading.main_thread()
    assert avisos == []
    assert preferencias.pasta_dos_saves_row.get_subtitle() == r"X:\nova"


@pytest.mark.parametrize(
    "mensagem",
    [
        "Escolha uma pasta fora da pasta atual dos saves.",
        "Escolha uma pasta que não contenha a pasta atual dos saves.",
        "A pasta escolhida já tem arquivos com os mesmos nomes dos saves. Escolha outra pasta.",
        "Escolha uma pasta fora da pasta de dados do Cartridges.",
    ],
)
def test_troca_recusada_mostra_a_mensagem_de_cada_motivo(monkeypatch, flush_idle, mensagem):
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    preferencias = _preferencias(monkeypatch)
    avisos = _toasts(preferencias, monkeypatch)

    _esperar_troca(preferencias, monkeypatch, pasta.TrocaRecusada(mensagem))
    _drenar(flush_idle, lambda: avisos)

    assert avisos == [mensagem]


def test_troca_que_falha_avisa(monkeypatch, flush_idle):
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    preferencias = _preferencias(monkeypatch)
    avisos = _toasts(preferencias, monkeypatch)

    _esperar_troca(preferencias, monkeypatch, OSError("disco cheio"))
    _drenar(flush_idle, lambda: avisos)

    assert avisos == ["Não foi possível trocar a pasta dos saves."]


def test_restaurar_todos_pede_confirmacao_com_o_texto_da_spec(monkeypatch):
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    preferencias = _preferencias(monkeypatch)
    argumentos = []
    sinais = []

    class Dialogo:
        def connect(self, sinal, funcao):
            sinais.append((sinal, funcao))

    monkeypatch.setattr(
        preferences_module,
        "create_dialog",
        lambda *a, **k: argumentos.append((a, k)) or Dialogo(),
    )
    restaurados = []
    monkeypatch.setattr(backup_de_saves, "restaurar_todos", lambda: restaurados.append(1))

    preferencias.restaurar_todos_os_saves()

    (_janela, _titulo, corpo, resposta, _rotulo), opcoes = argumentos[0]
    assert corpo == (
        "Tem certeza que deseja restaurar os saves de todos os jogos? "
        "Os saves atuais serão substituídos pela versão mais recente de cada um."
    )
    assert opcoes == {"destructive": True}
    sinais[0][1](None, "dismiss")
    assert restaurados == []
    sinais[0][1](None, resposta)
    assert restaurados == [1]


def _drenar(flush_idle, pronto):
    import time  # noqa: PLC0415

    limite = time.monotonic() + 5
    while time.monotonic() < limite:
        flush_idle()
        if pronto():
            return
        time.sleep(0.01)


# -- início do app -------------------------------------------------------------


def test_main_atualiza_o_cache_na_abertura():
    texto = (Path(__file__).resolve().parent.parent / "cartridges" / "main.py").read_text(
        encoding="utf-8"
    )
    assert "backup_de_saves.atualizar_cache()" in texto
