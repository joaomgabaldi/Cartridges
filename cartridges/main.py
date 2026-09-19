# main.py
#
# Copyright 2022-2024 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import lzma
import os
import sys
import threading
from typing import Any, Optional
from urllib.parse import quote

# Mirrors the launcher (cartridges.in) for direct module runs: MSYS2's
# gtk4 disables DirectComposition by default, which GTK 4.2x's GL/Vulkan
# renderers require — everything silently fell back to Cairo. Re-enable
# DComp and use Vulkan, the combination that works (GL + DComp is the
# broken one). setdefault keeps user-set environment values in charge.
os.environ.setdefault("GDK_WIN32_FORCE_DCOMP", "1")
os.environ.setdefault("GSK_RENDERER", "vulkan")

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

# pylint: disable=wrong-import-position
from gi.repository import Adw, Gdk, Gio, GLib, Gtk, Pango

from cartridges import shared
from cartridges.details_dialog import DetailsDialog
from cartridges.game import Game
from cartridges.gamepad import GamepadManager
from cartridges.importer.importer import Importer  # yo dawg
from cartridges.importer.shortcuts_source import ShortcutsSource
from cartridges.logging.setup import log_system_info, setup_logging
from cartridges.preferences import CartridgesPreferences
from cartridges.store.managers.cover_manager import CoverManager
from cartridges.store.managers.display_manager import DisplayManager
from cartridges.store.managers.file_manager import FileManager
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.store.managers.hltb_manager import HLTBManager
from cartridges.store.managers.steam_api_manager import SteamAPIManager
from cartridges.store.store import Store
from cartridges.utils.app_updater import AppUpdater
from cartridges.utils.hltb_backfill import HLTBBackfill
from cartridges.utils.install_size import InstallSizeSweep
from cartridges.utils.news_checker import NewsChecker
from cartridges.utils.open_uri import open_uri
from cartridges.utils.single_instance import (
    acquire as acquire_single_instance,
    present_running_instance,
)
from cartridges.utils.updates_checker import UpdatesChecker
from cartridges.utils import session_fita, session_log, session_wallpaper, window_geometry
from cartridges.window import CartridgesWindow

# Titulo da secao de agradecimentos nos creditos. Fica numa constante porque
# _translate_about_dialog precisa reconhecer o texto para desligar o "..."
# (a libadwaita corta titulos de grupo com ellipsize em vez de quebrar linha).
ABOUT_THANKS_TITLE = (
    "O autor original agradece as pessoas abaixo pelas suas contribuições:"
)

# A libadwaita monta o dialogo Sobre com as proprias strings e as traduz via
# gettext, lendo os .mo de share/locale. O instalador nao empacota esse
# diretorio, entao no app instalado elas sairiam sempre em ingles, no meio de
# uma interface que e toda pt-BR (a interface do app e hardcoded — ver
# cartridges.in). A saida e reescreve-las percorrendo a arvore de widgets.
#
# As chaves ficam numa forma normalizada por _about_key(): sem o sublinhado
# do mnemonico e com apostrofo reto. Isso e de proposito — a libadwaita move
# o mnemonico de lugar entre versoes (na 1.5 a linha era "_What’s New"; em
# versoes novas e "What’s _New") e usa apostrofo tipografico. Comparar a
# string crua faria a traducao parar de funcionar a cada atualizacao.
#
# O valor vai sem sublinhado; _translate_about_dialog recoloca o mnemonico no
# inicio quando o texto original tinha um. Se uma versao nova mudar a redacao
# de alguma string, ela so nao e encontrada e continua em ingles — nada quebra.
ABOUT_DIALOG_STRINGS = {
    "About": "Sobre",
    "What's New": "Novidades",
    "Details": "Detalhes",
    "Troubleshooting": "Solução de problemas",
    "Debugging Information": "Informações de depuração",
    "Credits": "Créditos",
    "Legal": "Aviso legal",
    "Acknowledgements": "Agradecimentos",
    "Copy Text": "Copiar texto",
    "Save As…": "Salvar como…",
    "Website": "Site",
    "Support Questions": "Dúvidas e suporte",
    "Report an Issue": "Relatar um problema",
    "To assist in troubleshooting, you can view your debugging information. "
    "Providing this information to the application developers can help "
    "diagnose any problems you encounter when you report an issue.": (
        "Para ajudar a resolver problemas, você pode ver as informações de "
        "depuração. Fornecer essas informações a quem desenvolve o aplicativo "
        "ajuda a diagnosticar qualquer problema que você encontrar."
    ),
}


def _about_key(text: str) -> str:
    """Normaliza uma string da libadwaita para servir de chave de traducao.

    Tira o sublinhado do mnemonico, que muda de posicao entre versoes, e
    uniformiza os apostrofos tipograficos para o reto.
    """
    return text.replace("_", "").replace("’", "'").replace("ʼ", "'")


ABOUT_DIALOG_STRINGS = {_about_key(k): v for k, v in ABOUT_DIALOG_STRINGS.items()}

# O aviso de garantia da licenca nao entra no dicionario acima porque a
# libadwaita o concatena com o copyright num unico rotulo — nao ha string
# isolada para casar. Em vez disso trocamos a licenca por uma CUSTOM com o
# mesmo texto ja em pt-BR (o projeto continua sob GPL-3.0-or-later; muda so
# o texto exibido).
ABOUT_LICENSE = (
    "Este aplicativo vem sem absolutamente nenhuma garantia. Veja a "
    '<a href="https://www.gnu.org/licenses/gpl-3.0.html">Licença Pública '
    "Geral GNU, versão 3 ou posterior</a> para mais detalhes."
)


def _translate_release_notes_heading(text_buffer: Gtk.TextBuffer) -> None:
    """Troca o "Version" que encabeca as notas de versao por "Versão".

    A libadwaita monta a pagina Novidades num GtkTextView e prefixa o titulo
    "Version <numero>" direto no buffer, entao nao ha widget com essa string
    para traduzir — e preciso editar o texto. As tags de formatacao do titulo
    (negrito) sao lidas antes e reaplicadas depois.
    """
    start = text_buffer.get_start_iter()
    end = text_buffer.get_iter_at_offset(len("Version"))
    if text_buffer.get_text(start, end, False) != "Version":
        return

    tags = start.get_tags()
    text_buffer.delete(start, end)
    text_buffer.insert(text_buffer.get_start_iter(), "Versão")

    start = text_buffer.get_start_iter()
    end = text_buffer.get_iter_at_offset(len("Versão"))
    for tag in tags:
        text_buffer.apply_tag(tag, start, end)


def _translate_about_dialog(widget: Gtk.Widget) -> None:
    """Reescreve em pt-BR as strings internas do dialogo Sobre.

    Percorre a arvore inteira do AdwAboutDialog. Titulos de pagina e de linha
    vem da propriedade "title"; botoes e paragrafos, de "label".
    """
    for prop in ("title", "label"):
        try:
            value = widget.get_property(prop)
        except TypeError:
            # O widget nao tem essa propriedade — a maioria nao tem.
            continue
        if not isinstance(value, str):
            continue
        translated = ABOUT_DIALOG_STRINGS.get(_about_key(value))
        if translated is None:
            continue
        # Linhas e botoes usam mnemonico, titulos de pagina nao. Segue o
        # original: se ele tinha sublinhado, o traduzido tambem tem.
        if "_" in value:
            translated = "_" + translated
        widget.set_property(prop, translated)

    # O titulo do grupo de agradecimentos e uma frase inteira e a libadwaita
    # corta titulos de grupo com "..." no fim da linha. Aqui ele quebra linha.
    if isinstance(widget, Gtk.Label) and widget.get_label() == ABOUT_THANKS_TITLE:
        widget.set_ellipsize(Pango.EllipsizeMode.NONE)
        widget.set_wrap(True)
        widget.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        widget.set_max_width_chars(0)

    if isinstance(widget, Gtk.TextView):
        _translate_release_notes_heading(widget.get_buffer())

    child = widget.get_first_child()
    while child:
        _translate_about_dialog(child)
        child = child.get_next_sibling()


# O tipo de cada campo que um game_id.json persiste, fora os quatro de
# identidade (conferidos em `load_games_from_disk`). `rating` e `status` têm
# guarda própria na exibição; os demais eram aplicados por setattr sem checagem.
_NUMBER = (int, float)
_GAME_FIELD_TYPES: dict[str, Any] = {
    **dict.fromkeys(
        (
            "added",
            "last_played",
            "playtime",
            "rating",
            "metacritic",
            "steam_checked",
            "hltb_id",
            "hltb_main",
            "hltb_main_extra",
            "hltb_completionist",
            "install_size",
            "install_size_ts",
            "version",
            "shortcut_mtime",
            "update_available_ts",
            "update_dismissed_ts",
        ),
        _NUMBER,
    ),
    **dict.fromkeys(
        (
            "status",
            "notes",
            "developer",
            "publisher",
            "release_date",
            "steam_review",
            "genre",
            "controller_support",
            "description",
            "steam_appid",
            "shortcut_path",
            "process_executable",
            "update_url",
        ),
        str,
    ),
    **dict.fromkeys(
        (
            "hidden",
            "gamepad_recommended",
            "removed",
            "blacklisted",
            "run_as_admin",
            "track_process",
            "track_updates",
        ),
        bool,
    ),
    "hltb_chapters": list,
}

# Os campos cujo default na classe é None: só neles `null` quer dizer "não
# informado". Nos outros, `"version": null` virava `None > 1.6` na carga.
_NULLABLE_GAME_KEYS = frozenset(
    {
        "metacritic",
        "hltb_id",
        "hltb_main",
        "hltb_main_extra",
        "hltb_completionist",
        "developer",
        "publisher",
        "release_date",
        "steam_review",
        "genre",
        "controller_support",
        "description",
        "steam_appid",
        "hltb_chapters",
    }
)


def sanitize_game_fields(data: dict, record_name: str) -> dict:
    """Descarta campos de tipo errado num registro editado à mão.

    ``"playtime": "5h"`` estourava TypeError na tela de detalhes e na
    ordenação; ``"removed": "false"`` contava como verdadeiro e o jogo sumia;
    ``"notes": 5`` derrubava os detalhes. Cai o campo, não o jogo — o default
    da classe vale como "não informado". Muta e devolve ``data``.
    """
    for key, expected in _GAME_FIELD_TYPES.items():
        if key not in data:
            continue
        value = data[key]
        if value is None and key in _NULLABLE_GAME_KEYS:
            continue
        valid = isinstance(value, expected) and not (
            key == "hltb_chapters"
            and not all(isinstance(chapter, dict) for chapter in value)
        )
        if not valid:
            logging.warning("Campo %s inválido em %s, ignorado", key, record_name)
            del data[key]
    return data


class CartridgesApplication(Adw.Application):
    state = shared.AppState.DEFAULT
    win: CartridgesWindow
    init_search_term: Optional[str] = None
    gamepad: Optional[GamepadManager] = None
    updates_checker: Optional[UpdatesChecker] = None
    news_checker: Optional[NewsChecker] = None
    hltb_backfill: Optional[HLTBBackfill] = None
    install_size_sweep: Optional[InstallSizeSweep] = None
    app_updater: Optional[AppUpdater] = None
    # O provider da cor de destaque, guardado para o watcher do registro poder
    # reescrever o CSS no lugar em vez de empilhar um provider por mudança.
    _accent_provider: Optional[Gtk.CssProvider] = None

    def __init__(self) -> None:
        shared.store = Store()
        super().__init__(application_id=shared.APP_ID)

        search = GLib.OptionEntry()
        search.long_name = "search"
        search.short_name = ord("s")
        search.flags = 0
        search.arg = int(GLib.OptionArg.STRING)
        search.arg_data = None
        search.description = "Open the app with this term in the search entry"
        search.arg_description = "TERM"

        self.add_main_option_entries((search,))

    def apply_windows_theme(self) -> bool:
        """Follow the Windows light/dark setting and accent colour.

        GTK/Libadwaita does not pick these up from Windows on its own, so they
        are read from the registry to keep the app visually consistent with the
        rest of the system. Read at startup and re-run by `watch_windows_theme`
        whenever Windows says either key changed; failures fall back silently
        to the bundled defaults.

        Returns False so it can double as a one-shot GLib idle callback.
        """
        import winreg  # pylint: disable=import-outside-toplevel

        # Light / dark scheme
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                apps_use_light = winreg.QueryValueEx(key, "AppsUseLightTheme")[0]
            Adw.StyleManager.get_default().set_color_scheme(
                Adw.ColorScheme.FORCE_LIGHT
                if apps_use_light
                else Adw.ColorScheme.FORCE_DARK
            )
        except OSError:
            pass

        # Accent colour: the DWORD is stored as 0xAABBGGRR (red is the low byte)
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM"
            ) as key:
                value = winreg.QueryValueEx(key, "AccentColor")[0]
            accent = "#{:02x}{:02x}{:02x}".format(
                value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
            )
            if self._accent_provider is None:
                self._accent_provider = Gtk.CssProvider()
                Gtk.StyleContext.add_provider_for_display(
                    Gdk.Display.get_default(),
                    self._accent_provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_USER,
                )
            # Reescrever o provider já instalado atualiza a cor ao vivo.
            self._accent_provider.load_from_string(
                f":root {{ --accent-bg-color: {accent}; --accent-color: {accent}; }}"
            )
        except OSError:
            pass

        return False

    def watch_windows_theme(self) -> None:
        """Reaplica tema e realce quando o Windows muda, sem reiniciar o app.

        `RegNotifyChangeKeyValue` bloqueia até a chave mudar, então cada chave
        vigiada custa um daemon thread parado num wait do kernel — sem polling.
        A aplicação em si volta para o thread principal por idle: tudo que ela
        toca (StyleManager, provider no display) é GTK.
        """
        import ctypes  # pylint: disable=import-outside-toplevel
        import winreg  # pylint: disable=import-outside-toplevel

        advapi32 = ctypes.WinDLL("advapi32")
        reg_notify_change_last_set = 0x00000004

        def watch(subkey: str) -> None:
            while True:
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
                        # Bloqueia dentro do with: o handle precisa viver até a
                        # notificação chegar.
                        result = advapi32.RegNotifyChangeKeyValue(
                            ctypes.c_void_p(key.handle),
                            False,
                            reg_notify_change_last_set,
                            None,
                            False,
                        )
                    if result != 0:
                        return  # a chave sumiu ou o registro recusou: desiste
                except OSError:
                    return
                GLib.idle_add(self.apply_windows_theme)

        for subkey in (
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            r"Software\Microsoft\Windows\DWM",
        ):
            threading.Thread(target=watch, args=(subkey,), daemon=True).start()

    def do_activate(self) -> None:  # pylint: disable=arguments-differ
        """Called on app creation"""
        # A second activation (e.g. launching the app again while it's running)
        # must not re-run the whole startup: it would duplicate managers,
        # reload games and clobber the app state mid-import
        if self.props.active_window:  # pylint: disable=no-member
            if self.init_search_term:
                shared.win.search_bar.set_search_mode(True)
                shared.win.search_entry.set_text(self.init_search_term)
                shared.win.search_entry.set_position(-1)
                self.init_search_term = None
            shared.win.present()
            return

        try:
            setup_logging()
        except ValueError:
            # dictConfig embrulha qualquer falha dos handlers em ValueError
            # (uma rotação de log que não sobreviveu a uma queda, p.ex.).
            # Ficar sem log NENHUM é o pior resultado possível para a sessão
            # seguinte a um crash — o console segura as pontas até a rotação
            # se curar na próxima execução.
            logging.basicConfig(level=logging.DEBUG)
            logging.exception("Não foi possível configurar o log em arquivo")

        log_system_info()

        # Uma sessão anterior pode ter deixado os monitores vestidos: o app
        # morto (ou a máquina desligada) no meio dela não passa por
        # `hide_session_blocker` nem por `do_shutdown`. A marca fica no
        # GSettings justamente para o arranque seguinte poder desfazer.
        session_wallpaper.restaurar_orfaos()

        # As fitas de LED seguem o mesmo ciclo: `abrir` desfaz numa thread o
        # que uma execução anterior deixou pendurado — o app morto no meio da
        # sessão não passa por `hide_session_blocker` nem por `do_shutdown` — e
        # só então guarda o estado de agora e acende no roxo do app.
        session_fita.abrir()

        # Match the Windows light/dark theme and accent colour, and keep
        # matching them while the app runs
        self.apply_windows_theme()
        self.watch_windows_theme()

        # Create the main window. A second activation returned early above, so
        # there is never an existing window here.
        shared.win = CartridgesWindow(application=self)

        # Restore the window's geometry, and save it back on the way out. This
        # used to be three two-way GSettings bindings, which is the usual way to
        # do it and was wrong twice over: it shrank the window by the frame's
        # 28x29 pixels on every run, and it could not remember which monitor the
        # window had been on, so a second screen was unusable. See
        # cartridges/utils/window_geometry.py.
        geometry = window_geometry.Geometry(
            shared.state_schema.get_int("x"),
            shared.state_schema.get_int("y"),
            shared.state_schema.get_int("width"),
            shared.state_schema.get_int("height"),
            shared.state_schema.get_boolean("is-maximized"),
        )
        window_geometry.apply_size(shared.win, geometry)
        # On "map", not the earlier "realize": a window realized but not yet
        # shown does have a Win32 handle, but GTK positions it again on the way
        # to the screen and throws the placement away.
        shared.win.connect(
            "map", lambda *_: window_geometry.apply_placement(shared.win, geometry)
        )
        # Closing the window and quitting the app are different paths and only
        # one of them runs do_shutdown with the window still around, so both save.
        shared.win.connect("close-request", self.save_window_geometry)

        # Load games from disk
        shared.store.add_manager(FileManager(), False)
        shared.store.add_manager(DisplayManager())
        self.state = shared.AppState.LOAD_FROM_DISK
        self.load_games_from_disk()
        self.state = shared.AppState.DEFAULT
        # O aviso "Nenhum jogo" entrou no __init__ da janela, quando a store
        # ainda estava vazia; a carga acima o torna obsoleto, e a reavaliação
        # coalescida é um idle. Síncrono aqui, antes do present(), o primeiro
        # quadro já nasce certo sem depender da ordem dos idles no main loop.
        shared.win.set_library_child()

        # Add rest of the managers for game imports
        shared.store.add_manager(CoverManager())
        shared.store.add_manager(SteamAPIManager())
        shared.store.add_manager(HLTBManager())
        shared.store.add_manager(SgdbManager())
        shared.store.toggle_manager_in_pipelines(FileManager, True)

        # Create actions
        self.create_actions(
            {
                ("quit", ("<primary>q",)),
                ("about",),
                ("shortcuts", ("<primary>question",)),
                ("preferences", ("<primary>comma",)),
                ("launch_game",),
                ("hide_game",),
                ("edit_game",),
                ("add_game", ("<primary>n",)),
                ("import", ("<primary>i",)),
                ("remove_game_details_view", ("Delete",)),
                ("remove_game",),
                ("igdb_search",),
                ("sgdb_search",),
                ("pcgw_search",),
                ("hltb_search",),
                ("show_hidden", ("<primary>h",), shared.win),
                ("show_news", ("<primary>j",), shared.win),
                ("go_to_parent", ("<alt>Up",), shared.win),
                ("go_home", ("<alt>Home",), shared.win),
                ("toggle_search", ("<primary>f",), shared.win),
                ("undo", ("<primary>z",), shared.win),
                ("open_menu", ("F10",), shared.win),
                ("close", ("<primary>w",), shared.win),
            }
        )

        # O Delete só vale com os detalhes à vista; o estado inicial vem daqui,
        # e daí em diante do "pushed"/"popped" da navegação.
        shared.win.set_show_hidden(shared.win.navigation_view)

        sort_action = Gio.SimpleAction.new_stateful(
            "sort_by",
            GLib.VariantType.new("s"),
            sort_mode := GLib.Variant("s", shared.state_schema.get_string("sort-mode")),
        )
        sort_action.connect("activate", shared.win.on_sort_action)
        shared.win.add_action(sort_action)
        shared.win.on_sort_action(sort_action, sort_mode)

        # Xbox controller navigation. The reference is kept on the app because
        # the manager owns a GLib timer and would otherwise be collected. It
        # only polls while the window has focus, so it costs nothing when the
        # setting is off or the app is in the background.
        self.gamepad = GamepadManager()
        self.gamepad.attach(shared.win)

        # Watch the repack feed for patches to opted-in games. Kicks off one poll
        # now (skipped entirely if no game opted in) and arms the recurring
        # timer; both run off the main thread so startup is never blocked.
        self.updates_checker = UpdatesChecker()
        self.updates_checker.start()

        # Same feed, read for the other half of its contents: the posts a person
        # would want to read. Attached to the window before it starts polling so
        # the first result can never land before there is a listener for it.
        self.news_checker = NewsChecker()
        shared.win.attach_news_checker(self.news_checker)
        self.news_checker.start()

        # Catch up the games that predate the HowLongToBeat lookup (or whose
        # lookup failed): the import pipeline only ever runs for games it adds,
        # so without this sweep an existing library could only be filled in one
        # game at a time, by hand. Starts a few seconds in and waits out any
        # running import, so it never competes with what the user is watching.
        self.hltb_backfill = HLTBBackfill()
        self.hltb_backfill.start()

        # Mede o que cada jogo ocupa no disco, pelo mesmo motivo e no mesmo
        # molde: a informação só existe se alguém for atrás dela, e ir atrás
        # custa uma caminhada pela pasta de cada jogo. Uma vez por execução,
        # depois da importação, pulando o que já foi medido nesta semana.
        self.install_size_sweep = InstallSizeSweep()
        self.install_size_sweep.start()

        if self.init_search_term:  # For command line activation
            shared.win.search_bar.set_search_mode(True)
            shared.win.search_entry.set_text(self.init_search_term)
            shared.win.search_entry.set_position(-1)

        shared.win.present()

        # Pergunta ao GitHub se saiu versão nova. Depois do present(): a caixa
        # com as novidades precisa de uma janela na tela para se prender.
        self.app_updater = AppUpdater()
        self.app_updater.start()

        if shared.schema.get_boolean("auto-import"):
            self.on_import_action()

    def save_window_geometry(self, *_args: Any) -> bool:
        """Remember where the window is, if it can still be asked.

        Returns False so that, used as a ``close-request`` handler, it lets the
        window close: a true return would stop it and the app would never quit.
        """
        if shared.win is None:
            return False

        # Fechar o app no meio de uma sessão: a janela está estacionada no
        # monitor do jogo, e o que tem de ser lembrado é de onde ela saiu, não
        # onde ela foi parar. Sem isso, jogar uma vez com a mudança de monitor
        # ligada e fechar o app dali mudaria de vez o lugar onde ele abre.
        geometry = window_geometry.session_geometry() or window_geometry.read(shared.win)
        if geometry is None:
            return False

        shared.state_schema.set_int("x", geometry.x)
        shared.state_schema.set_int("y", geometry.y)
        shared.state_schema.set_boolean("is-maximized", geometry.maximized)
        # A maximized window's rectangle is its monitor, not a size to reopen at,
        # so the last real size is left in place for it to be restored to.
        if not geometry.maximized:
            shared.state_schema.set_int("width", geometry.width)
            shared.state_schema.set_int("height", geometry.height)
        return False

    def do_shutdown(self) -> None:  # pylint: disable=arguments-differ
        """Persist any play session still running before the app exits.

        Without this, quitting mid-session silently dropped up to a minute of
        playtime (both trackers only persist periodically). Only the file flush
        runs here — no toasts or window calls, the UI is already going away.
        """
        # Quitting from the menu or with Ctrl+Q never asks the window to close,
        # so this is the only chance to save its geometry on that path.
        self.save_window_geometry()

        # avoid import cycles
        from cartridges.process_session import ProcessSession
        from cartridges.session_window import SessionWindow

        # E a sessão entra no histórico, como no fim normal: sem isto o total
        # do jogo ficava acima da soma das sessões, por uma diferença que a
        # tela do histórico não tem como apagar.
        if (window := SessionWindow.active) is not None:
            window.flush()
            session_log.record(window.game.game_id, window.session_seconds)
        if (session := ProcessSession.active) is not None:
            session.flush()
            if session.started:
                session_log.record(session.game.game_id, session.session_seconds)

        # A sessão que estava correndo acaba aqui, e as telas vestidas não podem
        # ficar com a arte do jogo depois que o app sumir. Síncrono e antes de
        # tudo o mais deste método: é a última janela em que ainda existe
        # processo para desfazer a troca.
        session_wallpaper.restaurar()

        # As fitas voltam ao que eram quando o app abriu. Esperando, pelo mesmo
        # motivo da parede: depois daqui não há processo para desfazer nada. A
        # espera tem prazo — ver `PRAZO_FECHAMENTO` —, e o que não couber nele
        # fica para o `abrir` do próximo arranque.
        session_fita.fechar()

        if self.gamepad is not None:
            self.gamepad.detach()

        # Order matters: both checkers may have a poll on the wire that cannot
        # be cancelled, only disowned. `stop()` marks them so the result is
        # dropped instead of being written back into games and widgets that are
        # on their way out, and detaching first releases the checker's hold on
        # the window so the whole widget tree can actually be collected.
        if self.news_checker is not None:
            if shared.win is not None:
                shared.win.detach_news_checker()
            self.news_checker.stop()

        if self.updates_checker is not None:
            self.updates_checker.stop()

        # Same reasoning: a lookup already on the wire is disowned rather than
        # written back into games that are being torn down.
        if self.hltb_backfill is not None:
            self.hltb_backfill.stop()

        if self.install_size_sweep is not None:
            self.install_size_sweep.stop()

        # Um download no meio para no próximo pedaço, e o resultado de uma
        # checagem que ainda esteja no caminho é descartado.
        if self.app_updater is not None:
            self.app_updater.stop()

        Gio.Application.do_shutdown(self)

    def do_handle_local_options(self, options: GLib.VariantDict) -> int:
        if search := options.lookup_value("search"):
            self.init_search_term = search.get_string()
        return -1

    def load_games_from_disk(self) -> None:
        if shared.games_dir.is_dir():
            for game_file in shared.games_dir.iterdir():
                # Skip leftovers such as .json.tmp from an interrupted save
                if game_file.suffix != ".json":
                    continue
                try:
                    with game_file.open(encoding="utf-8") as open_file:
                        data = json.load(open_file)
                except (OSError, json.decoder.JSONDecodeError):
                    continue
                # A record missing one of the fields that has no default is not
                # loadable: `Game.__init__` reads `source` to derive
                # `base_source` and would raise here, outside the JSON guard
                # above, so a single corrupt file stopped the app from opening
                # at all rather than costing one game.
                if not isinstance(data, dict) or not all(
                    isinstance(data.get(key), str) and data[key]
                    for key in ("source", "game_id", "name", "executable")
                ):
                    logging.warning("Skipping malformed game record %s", game_file.name)
                    continue
                # Um arquivo por vez: o que escapar da limpeza acima custa esse
                # jogo, e não a janela inteira, que abre depois desta carga.
                try:
                    game = Game(sanitize_game_fields(data, game_file.name))
                    shared.store.add_game(game, {"skip_save": True})
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.exception("Skipping unloadable game record %s", game_file.name)

    def on_about_action(self, *_args: Any) -> None:
        # Get the debug info from the log files
        debug_str = ""
        for index, path in enumerate(shared.log_files):
            # Add a horizontal line between runs
            if index > 0:
                debug_str += "─" * 37 + "\n"
            # Um log ilegível não pode custar o diálogo Sobre. Os .xz de
            # sessões anteriores podem estar truncados por uma queda, e a
            # própria rotação preserva de propósito arquivos com um byte
            # rasgado — o diálogo tem que abrir com o que der para ler.
            try:
                with (
                    lzma.open(path, "rt", encoding="utf-8", errors="replace")
                    if path.name.endswith(".xz")
                    else open(path, "r", encoding="utf-8", errors="replace")
                ) as log_file:
                    debug_str += log_file.read()
            except (OSError, EOFError, lzma.LZMAError):
                debug_str += f"[{path.name}: ilegível]\n"

        about = Adw.AboutDialog.new_from_appdata(
            shared.PREFIX + "/" + shared.APP_ID + ".metainfo.xml", shared.VERSION
        )
        # Esta fork nao tem site nem rastreador de problemas proprios, entao as
        # linhas "Site" e "Relatar um problema" ficam fora do dialogo. As URLs
        # tambem foram removidas do metainfo; isto aqui e apenas garantia.
        about.set_website("")
        about.set_issue_url("")
        about.set_support_url("")

        about.set_developer_name("joaomgabaldi")
        about.set_copyright("© 2022-2024 kramo\n© 2026 joaomgabaldi")

        # Creditos em texto simples, sem link para o site de cada autor.
        # Titulo vazio na primeira secao = grupo sem cabecalho.
        about.add_credit_section(
            "",
            (
                "Copyright (C) 2022-2024 kramo",
                "Copyright (C) 2026 joaomgabaldi",
            ),
        )
        about.add_credit_section(
            ABOUT_THANKS_TITLE,
            (
                "Geoffrey Coulaud",
                "Rilic",
                "Arcitec",
                "Paweł Lidwin",
                "Domenico",
                "Rafael Mardojai CM",
                "Clara Hobbs",
                "Sabri Ünal",
            ),
        )

        about.set_debug_info(debug_str)
        about.set_debug_info_filename("cartridges.log")
        about.set_license_type(Gtk.License.CUSTOM)
        about.set_license(ABOUT_LICENSE)

        # Tem que ser depois do present(): a libadwaita so monta as paginas
        # internas (Novidades, Creditos, Aviso legal...) ao apresentar o
        # dialogo, e remonta a de creditos por cima do que fizermos antes.
        # Roda na mesma iteracao do loop principal, entao nada e desenhado
        # em ingles antes da troca.
        about.present(shared.win)
        _translate_about_dialog(about)

    def on_shortcuts_action(self, *_args: Any) -> None:
        builder = Gtk.Builder.new_from_resource(
            shared.PREFIX + "/shortcuts-dialog.ui"
        )
        builder.get_object("shortcuts_dialog").present(shared.win)

    def on_preferences_action(
        self,
        _action: Any = None,
        _parameter: Any = None,
        page_name: Optional[str] = None,
        expander_row: Optional[str] = None,
    ) -> Optional[CartridgesPreferences]:
        if CartridgesPreferences.is_open:
            return

        win = CartridgesPreferences()
        if page_name:
            win.set_visible_page_name(page_name)
        if expander_row:
            getattr(win, expander_row).set_expanded(True)
        win.present(shared.win)

        return win

    def on_launch_game_action(self, *_args: Any) -> None:
        shared.win.active_game.launch()

    def on_hide_game_action(self, *_args: Any) -> None:
        shared.win.active_game.toggle_hidden()

    def on_edit_game_action(self, *_args: Any) -> None:
        DetailsDialog(shared.win.active_game).present(shared.win)

    def on_add_game_action(self, *_args: Any) -> None:
        if DetailsDialog.is_open:
            return

        DetailsDialog().present(shared.win)

    def on_import_action(self, *_args: Any) -> None:
        shared.importer = Importer()

        if shared.schema.get_boolean("shortcuts"):
            shared.importer.add_source(ShortcutsSource())

        shared.importer.run()

    def on_remove_game_action(self, *_args: Any) -> None:
        shared.win.active_game.remove_game()

    def on_remove_game_details_view_action(self, *_args: Any) -> None:
        if shared.win.navigation_view.get_visible_page() == shared.win.details_page:
            self.on_remove_game_action()

    def search(self, uri: str) -> None:
        open_uri(f"{uri}{quote(shared.win.active_game.name)}")

    def on_igdb_search_action(self, *_args: Any) -> None:
        self.search("https://www.igdb.com/search?type=1&q=")

    def on_sgdb_search_action(self, *_args: Any) -> None:
        self.search("https://www.steamgriddb.com/search/grids?term=")

    def on_pcgw_search_action(self, *_args: Any) -> None:
        self.search("https://www.pcgamingwiki.com/w/index.php?search=")

    def on_hltb_search_action(self, *_args: Any) -> None:
        # A game whose times were fetched already knows its HowLongToBeat id,
        # so open its page directly instead of making the user pick their own
        # game out of a search result list again.
        game = shared.win.active_game
        if game is not None and game.hltb_id:
            open_uri(f"https://howlongtobeat.com/game/{game.hltb_id}")
            return
        self.search("https://howlongtobeat.com/?q=")

    def on_quit_action(self, *_args: Any) -> None:
        self.quit()

    def create_actions(self, actions: set) -> None:
        for action in actions:
            simple_action = Gio.SimpleAction.new(action[0], None)

            scope = action[2] if action[2:3] else self
            simple_action.connect("activate", getattr(scope, f"on_{action[0]}_action"))

            if action[1:2]:
                self.set_accels_for_action(
                    f"app.{action[0]}" if scope == self else f"win.{action[0]}",
                    action[1],
                )

            scope.add_action(simple_action)


def main() -> Any:
    """App entry point.

    Takes no version argument. The launcher used to substitute ``@VERSION@`` at
    build time and pass it in, which read like the version came from there — it
    does not. `shared.VERSION` is generated from the same meson value and is
    what every caller actually reads, so the parameter was a second source of
    truth that nothing consulted.
    """
    # Before anything is loaded: a second copy must not read the game files at
    # all, let alone save over them. GApplication's own uniqueness check runs
    # over the D-Bus session bus, which does not exist on Windows and silently
    # gives up when GLib fails to start one — see `single_instance`.
    if not acquire_single_instance():
        # Logging is not configured yet (that happens on startup, which this
        # process will never reach), so this goes to stderr at warning level
        # rather than into the session log — which is where someone who just
        # double-launched the app is looking anyway.
        logging.warning("Cartridges is already running")
        # O caminho do GApplication que apresentaria a janela existente morre
        # junto com o D-Bus no Windows, então quem realça é este processo,
        # antes de sair — senão o segundo clique no atalho parece não fazer nada.
        present_running_instance()
        return 0

    app = CartridgesApplication()
    return app.run(sys.argv)
