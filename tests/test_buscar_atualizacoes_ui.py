# test_buscar_atualizacoes_ui.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O botão Buscar das Preferências sempre dá uma resposta na tela."""

import types

from cartridges import shared
from cartridges.utils import app_updater
from cartridges.utils.app_updater import AppUpdater


def _preferencias(monkeypatch):
    import cartridges.preferences as preferences_module
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    return preferences_module.CartridgesPreferences()


def test_clique_fora_da_instalacao_mostra_aviso(monkeypatch):
    monkeypatch.setattr(app_updater, "installed_root", lambda: None)
    app = types.SimpleNamespace(app_updater=AppUpdater())
    monkeypatch.setattr(shared.win, "get_application", lambda: app, raising=False)
    preferencias = _preferencias(monkeypatch)
    avisos: list[str] = []
    monkeypatch.setattr(
        preferencias, "add_toast", lambda toast: avisos.append(toast.get_title())
    )
    monkeypatch.setattr(
        shared.win,
        "toast_queue",
        types.SimpleNamespace(add=lambda toast: avisos.append(toast.get_title())),
        raising=False,
    )

    preferencias.buscar_atualizacoes_botao.emit("clicked")

    assert avisos == ["A busca de atualizações só funciona no aplicativo instalado."]
    assert preferencias.buscar_atualizacoes_botao.get_sensitive()


def test_clique_com_o_dialogo_aberto_mostra_aviso_nele(monkeypatch):
    from gi.repository import Adw

    monkeypatch.setattr(app_updater, "installed_root", lambda: None)
    app = types.SimpleNamespace(app_updater=AppUpdater())
    monkeypatch.setattr(shared.win, "get_application", lambda: app, raising=False)
    preferencias = _preferencias(monkeypatch)
    janela = Adw.Window()
    janela.present()
    preferencias.present(janela)
    avisos: list[str] = []
    original = preferencias.add_toast
    monkeypatch.setattr(
        preferencias,
        "add_toast",
        lambda toast: (avisos.append(toast.get_title()), original(toast)),
    )

    preferencias.buscar_atualizacoes_botao.emit("clicked")

    assert avisos == ["A busca de atualizações só funciona no aplicativo instalado."]
    janela.destroy()
