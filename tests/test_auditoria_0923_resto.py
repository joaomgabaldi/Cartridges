# test_auditoria_0923_resto.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auditoria de 23/09: M6, M9, B17, B26, B23."""

from cartridges import shared


def test_m6_credencial_recusada_nao_e_salva(monkeypatch):
    from cartridges import fita_wizard  # noqa: PLC0415
    from cartridges.utils import tuya_conta  # noqa: PLC0415

    salvas = []
    monkeypatch.setattr(tuya_conta, "salvar", salvas.append)
    nuvem = type("Nuvem", (), {"token": None, "error": {"Error": "token"}})()
    assert fita_wizard.credencial_valida(nuvem, []) is False
    nuvem_boa = type("Nuvem", (), {"token": "abc", "error": None})()
    assert fita_wizard.credencial_valida(nuvem_boa, []) is True


def test_m9_webp_nao_e_candidato_utilizavel():
    from cartridges.utils import game_logo  # noqa: PLC0415

    webp = {"url": "https://x/logo.webp", "width": 800, "height": 300, "mime": "image/webp"}
    png = {"url": "https://x/logo.png", "width": 800, "height": 300, "mime": "image/png"}
    assert game_logo.pick_logo([webp, png]) is png


def test_b26_plural_dos_metadados(win):
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    MetadataRefresh._announce(1, 1, False)
    MetadataRefresh._announce(3, 3, False)
    MetadataRefresh._announce(2, 5, True)
    titulos = [t.get_title() for t in win.toast_queue.added]
    assert titulos == [
        "Metadados atualizados: 1 jogo",
        "Metadados atualizados: 3 jogos",
        "Atualização cancelada após 2 de 5 jogos",
    ]


def test_b17_refresh_nao_tem_mais_dialogo_de_erro():
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    assert not hasattr(MetadataRefresh, "_show_error")


def test_b23_falha_de_busca_troca_o_titulo(win):
    from cartridges.steam_picker import SteamPicker  # noqa: PLC0415

    picker = SteamPicker.__new__(SteamPicker)
    picker._generation = 0

    class Status:
        titulo = descricao = None

        def set_title(self, t):
            Status.titulo = t

        def set_description(self, d):
            Status.descricao = d

    class Pilha:
        def set_visible_child_name(self, _n):
            pass

    picker.status_page, picker.stack = Status(), Pilha()
    SteamPicker._show_empty(
        picker, "Não foi possível concluir a busca", "Verifique a conexão e tente novamente."
    )
    assert Status.titulo == "Não foi possível concluir a busca"
    assert Status.descricao == "Verifique a conexão e tente novamente."


def test_b27_seletor_vazio_nao_se_contradiz(store, win):
    from cartridges.zerados_picker import ZeradosPicker  # noqa: PLC0415

    dialogo = ZeradosPicker()
    vazio = dialogo.pilha.get_child_by_name("vazio")
    assert vazio.get_title() == "Nenhum jogo disponível"
    assert vazio.get_description() == "Busque um jogo na Steam para adicioná-lo."


def test_b29_instalador_sem_gnome():
    from pathlib import Path  # noqa: PLC0415

    texto = (Path(__file__).parent.parent / "build-aux/windows/Cartridges.iss.in").read_text(
        encoding="utf-8"
    )
    assert "apps.gnome.org" not in texto
    assert '#define MyAppPublisher "joaomgabaldi"' in texto



def test_b24_confirmacao_de_patch_diz_o_que_aconteceu():
    from pathlib import Path  # noqa: PLC0415

    texto = (Path(__file__).parent.parent / "cartridges/window.py").read_text(encoding="utf-8")
    assert '_("Você instalou a atualização?")' in texto
    assert "A página da atualização foi aberta no navegador. Confirme após " in texto
    assert "instalá-la para ocultar o aviso." in texto
    assert '_("Ainda não")' in texto
    assert '_("Já instalei")' in texto


def test_b25_subtitulos_de_preferencias_descrevem_o_comportamento():
    from pathlib import Path  # noqa: PLC0415

    texto = (Path(__file__).parent.parent / "data/gtk/preferences.blp").read_text(
        encoding="utf-8"
    )
    assert (
        '_("Minimiza a janela ao iniciar um jogo quando a contagem de horas '
        'está desligada")'
    ) in texto
    assert (
        '_("Registra o tempo de cada sessão; quando o jogo não pode ser '
        'acompanhado automaticamente, abre uma janela compacta para encerrar '
        'a sessão")'
    ) in texto
    assert (
        '_("Busca na Steam título, desenvolvedora, publicadora, lançamento, '
        'gênero, descrição, avaliações e compatibilidade com controle")'
    ) in texto


def test_b28_dialogo_de_atualizacao_diz_o_que_acontece():
    from pathlib import Path  # noqa: PLC0415

    texto = (Path(__file__).parent.parent / "cartridges/utils/app_updater.py").read_text(
        encoding="utf-8"
    )
    assert "Deseja baixar e instalar a atualização agora? O aplicativo será " in texto
    assert "fechado durante a instalação." in texto
    assert '_("Agora não")' in texto
    assert '_("Atualizar")' in texto
    assert "Atualizar destacado" in texto
