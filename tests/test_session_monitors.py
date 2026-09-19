# test_session_monitors.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As opções de sessão que usam outras telas, num computador com uma tela só.

Levar a janela para outro monitor e trocar o papel de parede supõem que o jogo
roda no principal e que há mais um monitor para mostrar alguma coisa. Sem esse
segundo monitor, as duas ficam bloqueadas e desligadas — e desligadas de vez:
quando um segundo monitor volta, quem religa é o usuário.
"""

from types import SimpleNamespace

import pytest

from cartridges.utils import session_wallpaper, window_geometry

PRINCIPAL = window_geometry.Monitor("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, True)
SEGUNDO = window_geometry.Monitor("\\\\.\\DISPLAY2", -1080, -512, 1080, 1920, False)
TERCEIRO = window_geometry.Monitor("\\\\.\\DISPLAY3", 1920, -512, 1080, 1920, False)


@pytest.fixture
def ligados(monkeypatch):
    """Troca os monitores que o Windows responde."""

    def trocar(*monitores):
        monkeypatch.setattr(window_geometry, "monitors", lambda: list(monitores))

    return trocar


def _preferencias(monkeypatch):
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges import shared  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    # O `bind` do dublê não faz nada; imitado aqui para os interruptores
    # nascerem com o valor da chave, como no app. O grupo do monitor acompanha
    # o de contar horas, que vem ligado de fábrica.
    monkeypatch.setattr(
        shared.schema,
        "bind",
        lambda chave, widget, prop, _flags: widget.set_property(
            prop, shared.schema.get_boolean(chave)
        ),
    )
    return preferences_module.CartridgesPreferences()


class TestPreferencias:
    def test_sem_segundo_monitor_bloqueia_e_desliga(self, schema, ligados, monkeypatch):
        schema["session-move-window"] = True
        schema["session-wallpaper"] = True
        ligados(PRINCIPAL)

        dialog = _preferencias(monkeypatch)

        assert schema.get_boolean("session-move-window") is False
        assert schema.get_boolean("session-wallpaper") is False
        assert not dialog.session_monitor_group.get_sensitive()
        assert not dialog.session_wallpaper_switch.get_sensitive()
        for row in (dialog.session_move_window_switch, dialog.session_wallpaper_switch):
            assert row.get_subtitle() == "Precisa de um segundo monitor"

    def test_com_segundo_monitor_nada_e_desligado(self, schema, ligados, monkeypatch):
        schema["session-move-window"] = True
        schema["session-wallpaper"] = True
        ligados(PRINCIPAL, SEGUNDO)

        dialog = _preferencias(monkeypatch)

        assert schema.get_boolean("session-move-window") is True
        assert schema.get_boolean("session-wallpaper") is True
        assert dialog.session_monitor_group.get_sensitive()
        assert dialog.session_wallpaper_switch.get_sensitive()

    def test_desligadas_ficam_desligadas_quando_o_monitor_volta(
        self, schema, ligados, monkeypatch
    ):
        """Religar é escolha do usuário: o segundo monitor de volta não basta."""
        schema["session-move-window"] = False
        schema["session-wallpaper"] = False
        ligados(PRINCIPAL, SEGUNDO)

        _preferencias(monkeypatch)

        assert schema.get_boolean("session-move-window") is False
        assert schema.get_boolean("session-wallpaper") is False

    def test_a_lista_nao_oferece_o_principal(self, schema, ligados, monkeypatch):
        """E um principal já gravado, pelo palpite de antes, vira o primeiro outro."""
        schema["session-monitor"] = PRINCIPAL.device
        ligados(PRINCIPAL, SEGUNDO, TERCEIRO)

        dialog = _preferencias(monkeypatch)

        modelo = dialog.session_monitor_row.get_model()
        assert [modelo.get_string(i) for i in range(modelo.get_n_items())] == [
            "Monitor 2",
            "Monitor 3",
        ]
        assert schema.get_string("session-monitor") == SEGUNDO.device


class TestTelaDeEdicao:
    def test_sem_segundo_monitor_a_linha_fica_bloqueada(self, ligados, win):
        from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

        ligados(PRINCIPAL)
        dialog = DetailsDialog()

        assert not dialog.wallpaper_row.get_sensitive()
        assert dialog.wallpaper_row.get_subtitle() == "Precisa de um segundo monitor"

    def test_com_segundo_monitor_a_linha_mostra_a_escolha(self, ligados, win):
        from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415

        ligados(PRINCIPAL, SEGUNDO)
        dialog = DetailsDialog()

        assert dialog.wallpaper_row.get_sensitive()
        assert dialog.wallpaper_row.get_subtitle() == "Automático (wallhaven)"


class TestSessao:
    def test_sem_segundo_monitor_a_janela_nao_sai_e_a_opcao_desliga(
        self, schema, ligados, monkeypatch
    ):
        from cartridges.window import CartridgesWindow  # noqa: PLC0415

        schema["session-move-window"] = True
        schema["session-monitor"] = PRINCIPAL.device
        ligados(PRINCIPAL)

        def nao_move(*_args):
            raise AssertionError("sem segundo monitor não há para onde levar a janela")

        monkeypatch.setattr(window_geometry, "move_to_monitor", nao_move)

        # `self` só chegaria a `move_to_monitor`, que não pode ser chamado.
        assert CartridgesWindow.move_to_session_monitor(object()) is False
        assert schema.get_boolean("session-move-window") is False

    def test_sem_segundo_monitor_o_papel_de_parede_nao_comeca_e_desliga(
        self, schema, ligados, monkeypatch
    ):
        schema["session-wallpaper"] = True
        ligados(PRINCIPAL)
        iniciadas = []
        monkeypatch.setattr(
            session_wallpaper,
            "threading",
            SimpleNamespace(Thread=lambda **kwargs: iniciadas.append(kwargs)),
        )

        session_wallpaper.comecar(object())

        assert iniciadas == []
        assert schema.get_boolean("session-wallpaper") is False

    def test_com_segundo_monitor_o_papel_de_parede_comeca(
        self, schema, ligados, monkeypatch
    ):
        schema["session-wallpaper"] = True
        ligados(PRINCIPAL, SEGUNDO)
        iniciadas = []

        def thread(**kwargs):
            iniciadas.append(kwargs)
            return SimpleNamespace(start=lambda: None)

        monkeypatch.setattr(session_wallpaper, "threading", SimpleNamespace(Thread=thread))

        session_wallpaper.comecar(object())

        assert len(iniciadas) == 1
        assert schema.get_boolean("session-wallpaper") is True
