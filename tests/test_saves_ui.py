"""A interface dos saves: o fim da sessão, o menu do jogo, o diálogo de versões e as
Preferências."""

import threading
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from cartridges.game import Game
from cartridges.saves import backup_de_saves, dialogo, pasta
from cartridges.saves.ludusavi import Versao


def _versao(id_: str, quando: datetime, comentario: str = "") -> Versao:
    return Versao(id_, quando.replace(tzinfo=timezone.utc), comentario)


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


# -- abrir o jogo --------------------------------------------------------------


def test_launch_durante_a_restauracao_avisa_e_nao_abre(monkeypatch):
    def nao_abre(*_args):
        pytest.fail("o jogo não pode abrir durante a restauração dos saves dele")

    monkeypatch.setattr(backup_de_saves, "restaurando", lambda _jogo: True)
    monkeypatch.setattr("cartridges.game.run_executable", nao_abre)
    avisos = []
    falso = SimpleNamespace(ludusavi_nome="A", last_played=0, create_toast=avisos.append)

    Game.launch(falso)  # type: ignore[arg-type]  # só precisa dos três atributos acima

    assert avisos == ["Aguarde o fim da restauração dos saves de {}."]
    assert falso.last_played == 0


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


def test_subtitulos_das_versoes(monkeypatch, make_game):
    jogo = make_game(ludusavi_nome="A")
    # Da mais nova para a mais antiga, que é a ordem das linhas; o último é um comentário
    # qualquer, que nunca aparece na tela.
    comentarios = [
        backup_de_saves.INCOMPLETA,
        backup_de_saves.ANTES_DE_RESTAURAR,
        "",
        "comentario do usuario",
    ]
    versoes = [
        _versao(f"v{i}", datetime(2026, 10, 9 - i, 10, 0, tzinfo=timezone.utc), comentario)
        for i, comentario in enumerate(comentarios)
    ]
    monkeypatch.setattr(backup_de_saves, "versoes_do_jogo", lambda _jogo: versoes)

    caixa = dialogo.DialogoDeVersoes(jogo)

    assert [linha.get_subtitle() for linha in caixa.linhas] == [
        "Incompleta: alguns arquivos não puderam ser copiados",
        "Guardada antes de uma restauração",
        "",
        "",
    ]


def test_data_local_no_formato_da_spec(monkeypatch):
    quando = datetime(2026, 10, 9, 21, 14, tzinfo=timezone.utc)
    local = quando.astimezone()
    assert dialogo.formatar(quando) == f"{local:%d/%m/%Y} às {local:%H:%M}"
    assert dialogo.formatar(quando).count(" às ") == 1


def test_confirmacao_tem_o_texto_da_spec(monkeypatch, make_game):
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
        "Os saves atuais deste jogo serão guardados como uma nova versão antes da restauração."
    )
    assert opcoes == {"destructive": True}
    assert rotulo == "Restaurar"

    sinal, funcao = criados[0]
    assert sinal == "response"
    funcao(None, "dismiss")
    assert restaurados == []
    funcao(None, resposta)
    assert restaurados == [(jogo, "v1")]


def test_confirmacao_de_versao_incompleta(monkeypatch, make_game):
    jogo = make_game(ludusavi_nome="A")
    quando = datetime(2026, 10, 9, 21, 14, tzinfo=timezone.utc)
    versao = _versao("v1", quando, backup_de_saves.INCOMPLETA)
    argumentos = []
    monkeypatch.setattr(
        dialogo,
        "create_dialog",
        lambda *a, **k: argumentos.append((a, k)) or SimpleNamespace(connect=lambda *_a: None),
    )

    dialogo.confirmar(None, jogo, versao)

    (_janela, _titulo, corpo, _resposta, _rotulo), _opcoes = argumentos[0]
    local = quando.astimezone()
    assert corpo == (
        f"Tem certeza que deseja restaurar o save de {local:%d/%m/%Y} às {local:%H:%M}? "
        "Os saves atuais deste jogo serão guardados como uma nova versão antes da restauração. "
        "Esta versão está incompleta: alguns arquivos não foram copiados."
    )


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


def test_subtitulo_de_contar_horas_com_ludusavi(monkeypatch):
    """O backup dos saves só acontece ao fim de uma sessão, e sessão só existe com a contagem."""
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    assert _preferencias(monkeypatch).playtime_tracking_switch.get_subtitle() == (
        "Registra o tempo de cada sessão e faz o backup dos saves ao fim dela; quando o jogo "
        "não pode ser acompanhado automaticamente, abre uma janela compacta para encerrar a sessão"
    )


def test_subtitulo_de_contar_horas_sem_ludusavi(monkeypatch):
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: False)
    assert _preferencias(monkeypatch).playtime_tracking_switch.get_subtitle() == (
        "Registra o tempo de cada sessão; quando o jogo não pode ser acompanhado "
        "automaticamente, abre uma janela compacta para encerrar a sessão"
    )


def _exportar_com(monkeypatch, flush_idle, resultado):
    """O caminho inteiro de "Exportar backup" com `exportar` devolvendo `resultado` (ou
    levantando, se for uma exceção); devolve os argumentos de `create_dialog` e os toasts."""
    import cartridges.preferences as preferences_module

    class Resultado:
        def get_path(self):
            return "X:/backup.zip"

    class Seletor:
        def set_initial_name(self, _nome):
            pass

        def set_filters(self, _filtros):
            pass

        def save(self, _janela, _cancelavel, resposta):
            resposta(self, None)

        def save_finish(self, _resultado):
            return Resultado()

    def exportar(_destino, _configuracoes):
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    preferencias = _preferencias(monkeypatch)
    avisos = _toasts(preferencias, monkeypatch)
    dialogos = []
    monkeypatch.setattr(preferences_module.Gtk, "FileDialog", Seletor)
    monkeypatch.setattr(preferences_module.backup, "exportar", exportar)
    monkeypatch.setattr(
        preferences_module.backup, "ler_configuracoes", lambda: {"settings": {}, "state": {}}
    )
    monkeypatch.setattr(
        preferences_module, "create_dialog", lambda *a, **k: dialogos.append(a)
    )

    preferencias.export_backup()
    _drenar(flush_idle, lambda: dialogos or "Backup exportado" in avisos)
    return dialogos, avisos


def test_exportar_com_saves_inacessiveis_mostra_o_texto(monkeypatch, flush_idle):
    from cartridges.utils import backup

    dialogos, avisos = _exportar_com(
        monkeypatch, flush_idle, backup.SavesInacessiveis("Acesso negado")
    )

    assert [(titulo, corpo) for _janela, titulo, corpo in dialogos] == [
        (
            "Não foi possível exportar",
            (
                "Não foi possível ler as cópias dos saves. Verifique se a pasta dos saves está "
                "acessível e tente novamente."
            ),
        )
    ]
    assert "Backup exportado" not in avisos


def test_exportar_com_outro_erro_mantem_o_texto_do_destino(monkeypatch, flush_idle):
    dialogos, avisos = _exportar_com(monkeypatch, flush_idle, OSError("disco cheio"))

    assert [(titulo, corpo) for _janela, titulo, corpo in dialogos] == [
        (
            "Não foi possível exportar",
            (
                "Não foi possível gravar o arquivo. Verifique se a pasta de destino está "
                "acessível e se há espaço livre em disco."
            ),
        )
    ]
    assert "Backup exportado" not in avisos


def test_exportar_sem_os_saves_mostra_o_aviso(monkeypatch, flush_idle):
    dialogos, avisos = _exportar_com(monkeypatch, flush_idle, True)

    assert [(titulo, corpo) for _janela, titulo, corpo in dialogos] == [
        (
            "Backup exportado sem os saves",
            (
                "A pasta dos saves não foi encontrada, então as cópias dos saves não foram "
                "incluídas no backup. Verifique se a pasta está acessível e exporte novamente."
            ),
        )
    ]
    assert "Backup exportado" not in avisos


def test_exportar_com_os_saves_mostra_o_toast(monkeypatch, flush_idle):
    dialogos, avisos = _exportar_com(monkeypatch, flush_idle, False)

    assert dialogos == []
    assert "Backup exportado" in avisos


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
        "Os saves atuais de cada jogo serão guardados como uma nova versão antes da restauração."
    )
    assert opcoes == {"destructive": True}
    sinais[0][1](None, "dismiss")
    assert restaurados == []
    sinais[0][1](None, resposta)
    assert restaurados == [1]


def test_restaurar_backup_com_saves_em_andamento_avisa(monkeypatch):
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    preferencias = _preferencias(monkeypatch)
    avisos = _toasts(preferencias, monkeypatch)
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    monkeypatch.setattr(
        preferences_module,
        "create_dialog",
        lambda *_a, **_k: pytest.fail("confirmou a restauração com os saves em andamento"),
    )

    preferencias._restore_backup(Path("X:/backup.zip"))  # noqa: SLF001

    assert avisos == ["Aguarde o fim do backup ou da restauração dos saves e tente novamente."]


def _com_backup_agendado(monkeypatch, tmp_path):
    """Preferências com um backup já copiado para a pasta do app e o `quit` do app anotado."""
    from cartridges import shared  # noqa: PLC0415
    from cartridges.utils import backup  # noqa: PLC0415

    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    preferencias = _preferencias(monkeypatch)
    origem = tmp_path / "origem.zip"
    origem.write_bytes(b"zip")
    backup.agendar(origem)
    saidas = []
    monkeypatch.setattr(shared.win.application, "quit", lambda: saidas.append(1), raising=False)
    return preferencias, origem, shared.app_dir / "restaurar.zip", saidas


def test_reiniciar_para_restaurar_com_saves_em_andamento_desiste_e_desagenda(monkeypatch, tmp_path):
    """O aviso ao pedir "Restaurar backup" vale só naquele instante: durante a preparação
    (alguns segundos) o usuário pode iniciar um backup ou uma restauração dos saves, e
    fechar o app agora deixaria o Ludusavi órfão."""
    preferencias, _origem, agendado, saidas = _com_backup_agendado(monkeypatch, tmp_path)
    avisos = _toasts(preferencias, monkeypatch)
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    dispensados = []
    progresso = SimpleNamespace(dismiss=lambda: dispensados.append(1))
    assert agendado.is_file()

    assert preferencias._restart_to_restore(progresso) is False  # noqa: SLF001

    assert saidas == []
    assert dispensados == [1]
    assert avisos == ["Aguarde o fim do backup ou da restauração dos saves e tente novamente."]
    # Nada é aplicado por surpresa numa abertura futura; tentar de novo agenda outra vez.
    assert not agendado.exists()


def test_reiniciar_para_restaurar_sem_saves_em_andamento_sai_e_mantem_o_agendado(
    monkeypatch, tmp_path
):
    from cartridges import shared  # noqa: PLC0415

    preferencias, _origem, agendado, saidas = _com_backup_agendado(monkeypatch, tmp_path)
    avisos = _toasts(preferencias, monkeypatch)
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: False)

    assert preferencias._restart_to_restore(SimpleNamespace(dismiss=lambda: None)) is False  # noqa: SLF001

    assert saidas == [1]
    assert shared.win.application.reiniciar is True
    assert avisos == []
    assert agendado.is_file()


def test_restaurar_backup_que_ganha_saves_em_andamento_na_preparacao_nao_sai(
    monkeypatch, tmp_path, flush_idle
):
    """O caminho inteiro: a verificação do começo passou, os saves começaram no meio."""
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    preferencias, origem, agendado, saidas = _com_backup_agendado(monkeypatch, tmp_path)
    agendado.unlink()  # `_schedule_restore` é quem agenda aqui
    avisos = _toasts(preferencias, monkeypatch)
    monkeypatch.setattr(preferences_module.backup, "validar", lambda _caminho: None)
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)

    preferencias._schedule_restore(origem)  # noqa: SLF001
    _drenar(flush_idle, lambda: len(avisos) == 2)

    assert avisos == [
        "Preparando a restauração…",
        "Aguarde o fim do backup ou da restauração dos saves e tente novamente.",
    ]
    assert saidas == []
    assert not agendado.exists()


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


def test_main_avisa_da_pasta_dos_saves_logo_depois_do_aviso_de_falha():
    texto = (Path(__file__).resolve().parent.parent / "cartridges" / "main.py").read_text(
        encoding="utf-8"
    )
    assert (
        "            restauracao_dialogs.avisar_falha()\n\n"
        "        if backup.pasta_dos_saves_desfeita:\n"
        "            restauracao_dialogs.avisar_pasta_dos_saves(backup.pasta_dos_saves_desfeita)\n"
    ) in texto
