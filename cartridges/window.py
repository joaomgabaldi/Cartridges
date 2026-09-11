# window.py
#
# Copyright 2022-2023 kramo
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

# pyright: reportAssignmentType=none

import logging
import threading
import unicodedata
from pathlib import Path
from time import monotonic
from typing import Any, Optional

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from cartridges import shared
from cartridges.game import Game, STATUS_LABELS, status_label
from cartridges.game_cover import GameCover
from cartridges.utils.animated_flow_box import AnimatedFlowBox
from cartridges.utils.dialog_backdrop import block_window_drag
from cartridges.utils.format_playtime import format_playtime, format_stopwatch
from cartridges.utils.game_logo import (
    LOGO_MAX_HEIGHT,
    cached_logo_path,
    fetch_logo,
    load_logo,
    logo_lookup_needed,
)
from cartridges.utils.hltb import format_hltb_time
from cartridges.utils.install_size import format_size
from cartridges.utils.news_feed import NewsPost
from cartridges.utils.open_uri import open_uri
from cartridges.session_history import SessionHistoryDialog
from cartridges.utils import session_log, session_wallpaper, window_geometry
from cartridges.utils.relative_date import relative_date
from cartridges.utils.spring_scroll import attach as attach_spring_scroll
from cartridges.utils.steam import format_release_date, parse_release_date
from cartridges.utils.toast_queue import ToastQueue


def can_edit_notes(game: Game) -> bool:
    """Onde a anotação se edita: num jogo sendo jogado, ou que já tem uma.

    A anotação responde "onde eu parei?", que só é pergunta enquanto se joga —
    e o jogo que já tem uma precisa continuar tendo onde apagá-la, senão o
    texto fica preso na tela de detalhes para sempre.
    """
    return game.status == "playing" or bool((game.notes or "").strip())


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/window.ui")
class CartridgesWindow(Adw.ApplicationWindow):
    __gtype_name__ = "CartridgesWindow"

    navigation_view: Adw.NavigationView = Gtk.Template.Child()
    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    session_blocker: Gtk.Box = Gtk.Template.Child()
    session_blocker_label: Gtk.Label = Gtk.Template.Child()
    session_blocker_button: Gtk.Button = Gtk.Template.Child()
    session_blocker_notes_button: Gtk.MenuButton = Gtk.Template.Child()
    session_blocker_notes_popover: Gtk.Popover = Gtk.Template.Child()
    session_blocker_notes_view: Gtk.TextView = Gtk.Template.Child()
    session_blocker_timer: Gtk.Label = Gtk.Template.Child()
    primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    details_view: Gtk.Overlay = Gtk.Template.Child()
    library_page: Adw.NavigationPage = Gtk.Template.Child()
    library_view: Adw.ToolbarView = Gtk.Template.Child()
    library: AnimatedFlowBox = Gtk.Template.Child()
    scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    library_overlay: Gtk.Overlay = Gtk.Template.Child()
    notice_empty: Adw.StatusPage = Gtk.Template.Child()
    notice_no_results: Adw.StatusPage = Gtk.Template.Child()
    search_bar: Gtk.SearchBar = Gtk.Template.Child()
    search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    search_button: Gtk.ToggleButton = Gtk.Template.Child()
    news_button: Gtk.Button = Gtk.Template.Child()
    news_badge: Gtk.Box = Gtk.Template.Child()

    news_page: Adw.NavigationPage = Gtk.Template.Child()
    news_stack: Gtk.Stack = Gtk.Template.Child()
    news_list: Gtk.ListBox = Gtk.Template.Child()
    news_status: Adw.StatusPage = Gtk.Template.Child()
    news_scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    news_refresh_button: Gtk.Button = Gtk.Template.Child()
    news_retry_button: Gtk.Button = Gtk.Template.Child()

    details_page: Adw.NavigationPage = Gtk.Template.Child()
    details_view_toolbar_view: Adw.ToolbarView = Gtk.Template.Child()
    details_view_cover: Gtk.Picture = Gtk.Template.Child()
    details_view_spinner: Adw.Spinner = Gtk.Template.Child()
    details_view_header: Gtk.Box = Gtk.Template.Child()
    details_view_logo_clamp: Adw.Clamp = Gtk.Template.Child()
    details_view_logo: Gtk.Picture = Gtk.Template.Child()
    details_view_title: Gtk.Label = Gtk.Template.Child()
    details_view_blurred_cover: Gtk.Picture = Gtk.Template.Child()
    details_view_play_button: Gtk.Button = Gtk.Template.Child()
    details_view_developer: Gtk.Label = Gtk.Template.Child()
    details_view_publisher: Gtk.Label = Gtk.Template.Child()
    details_view_release_date: Gtk.Label = Gtk.Template.Child()
    details_view_rating: Gtk.Label = Gtk.Template.Child()
    details_view_metacritic: Gtk.Label = Gtk.Template.Child()
    details_view_steam_review: Gtk.Label = Gtk.Template.Child()
    details_view_genre: Gtk.Label = Gtk.Template.Child()
    details_view_controller_support: Gtk.Label = Gtk.Template.Child()
    details_view_gamepad_recommended: Gtk.Label = Gtk.Template.Child()
    details_view_description: Gtk.Label = Gtk.Template.Child()
    details_view_notes_box: Gtk.Box = Gtk.Template.Child()
    details_view_notes: Gtk.Label = Gtk.Template.Child()
    details_view_hltb_box: Gtk.Box = Gtk.Template.Child()
    details_view_hltb_main_cell: Gtk.Box = Gtk.Template.Child()
    details_view_hltb_main_value: Gtk.Label = Gtk.Template.Child()
    details_view_hltb_extra_cell: Gtk.Box = Gtk.Template.Child()
    details_view_hltb_extra_value: Gtk.Label = Gtk.Template.Child()
    details_view_hltb_completionist_cell: Gtk.Box = Gtk.Template.Child()
    details_view_hltb_completionist_value: Gtk.Label = Gtk.Template.Child()
    details_view_hltb_separator_1: Gtk.Separator = Gtk.Template.Child()
    details_view_hltb_separator_2: Gtk.Separator = Gtk.Template.Child()
    details_view_hltb_card: Gtk.Box = Gtk.Template.Child()
    details_view_hltb_chapters: Gtk.Box = Gtk.Template.Child()
    details_view_added: Gtk.Label = Gtk.Template.Child()
    details_view_last_played: Gtk.Label = Gtk.Template.Child()
    details_view_playtime: Gtk.Label = Gtk.Template.Child()
    details_view_size: Gtk.Label = Gtk.Template.Child()
    details_view_status_button: Gtk.MenuButton = Gtk.Template.Child()
    details_view_notes_button: Gtk.MenuButton = Gtk.Template.Child()
    details_view_notes_popover: Gtk.Popover = Gtk.Template.Child()
    details_view_notes_view: Gtk.TextView = Gtk.Template.Child()
    details_view_hide_button: Gtk.Button = Gtk.Template.Child()
    details_view_update_notice: Gtk.Button = Gtk.Template.Child()

    hidden_library_page: Adw.NavigationPage = Gtk.Template.Child()
    hidden_primary_menu_button: Gtk.MenuButton = Gtk.Template.Child()
    hidden_library: AnimatedFlowBox = Gtk.Template.Child()
    hidden_library_view: Adw.ToolbarView = Gtk.Template.Child()
    hidden_scrolledwindow: Gtk.ScrolledWindow = Gtk.Template.Child()
    hidden_library_overlay: Gtk.Overlay = Gtk.Template.Child()
    hidden_notice_empty: Adw.StatusPage = Gtk.Template.Child()
    hidden_notice_no_results: Adw.StatusPage = Gtk.Template.Child()
    hidden_search_bar: Gtk.SearchBar = Gtk.Template.Child()
    hidden_search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    hidden_search_button: Gtk.ToggleButton = Gtk.Template.Child()

    game_covers: dict
    toasts: dict
    # Every toast goes through here rather than straight to `toast_overlay`, so
    # that a burst of them plays one at a time instead of interrupting itself.
    toast_queue: ToastQueue
    active_game: Game
    # O jogo da sessão em andamento, enquanto o bloqueador estiver na tela. É
    # dele que trata a anotação escrita ali, e não do jogo que a tela de
    # detalhes por acaso tenha aberto atrás.
    session_game: Optional[Game] = None
    # O tick de 1s do relógio da sessão, 0 quando não há relógio na tela.
    session_timer_id: int = 0
    details_view_game_cover: Optional[GameCover] = None
    sort_state: str = "last_played"
    # The feed watcher driving the Novidades page and its badge. Injected by the
    # application once it exists (see `attach_news_checker`), so the window can
    # be built and shown without one.
    news_checker: Optional[Any] = None
    # Signal handler ids held on the checker, so they can be disconnected on
    # shutdown (see `detach_news_checker`).
    _news_handler_ids: list = []
    # (object, handler id) pairs held on process-lifetime singletons, released
    # when the window is destroyed (see `detach_global_handlers`).
    _global_handler_ids: list = []
    # The "Atualizando…" toast, kept so the poll that answers it can take it
    # down, and a flag marking that the poll in flight was asked for by hand —
    # a background re-poll must never toast at someone who didn't ask.
    _news_refresh_toast: Optional[Adw.Toast] = None
    _news_refresh_requested: bool = False
    _library_child_update_pending: bool = False
    # Filtros do menu (gênero e ano de lançamento). "" significa "Todos".
    # Estado de sessão, como a busca — só a ordenação persiste entre execuções.
    filter_genre_state: str = ""
    filter_year_state: str = ""
    filter_status_state: str = ""
    # O submenu "Filtrar por", inserido uma vez no modelo do menu principal e
    # reconstruído a cada abertura do popover com o que existe na biblioteca.
    _filter_menu: Optional[Gio.Menu] = None
    # De quem é o desfoque que está no fundo da tela de detalhes agora. É o
    # que separa "trocar de jogo" (limpa o fundo) de "o mesmo jogo recomputando
    # o desfoque" (o fundo atual fica até o novo chegar).
    _blurred_backdrop_id: Optional[str] = None
    # Scroll offsets of the two grids, saved while a dialog is open
    _library_scroll: Optional[tuple] = None
    # Se o "Tempo de jogo" do jogo aberto tem sessões por trás. Guardado porque
    # o clique e o hover chegam depois de a tela ter sido montada, e reler o
    # arquivo a cada movimento do mouse seria pagar disco por um realce.
    _playtime_clickable: bool = False
    # Bumped every time the details page is filled in. Kept as a marker of
    # "the page moved on", but no longer the thing a finished lookup is judged
    # against — see `logo_lookup_done`.
    _logo_generation: int = 0

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        # Per-instance state (avoid mutable class-level dicts shared across
        # instances). game_id -> GameCover and (game, action) -> undo Toast.
        self.game_covers = {}
        self.toasts = {}
        self.toast_queue = ToastQueue(self.toast_overlay)
        self._news_handler_ids = []
        # game_ids whose logo lookup is in flight, so revisiting a page while
        # its logo is still downloading does not start a second request
        self._logo_fetches: set[str] = set()

        self.details_view.set_measure_overlay(self.details_view_toolbar_view, True)
        self.details_view.set_clip_overlay(self.details_view_toolbar_view, False)

        self.library.set_filter_func(self.filter_func)
        self.hidden_library.set_filter_func(self.filter_func)

        self.library.set_sort_func(self.sort_func)
        self.hidden_library.set_sort_func(self.sort_func)

        self.set_library_child()

        # A roda do mouse rola com inércia de mola em vez de pular de degrau
        attach_spring_scroll(
            self.scrolledwindow,
            self.hidden_scrolledwindow,
            self.news_scrolledwindow,
        )

        self.notice_empty.set_icon_name(shared.APP_ID + "-symbolic")

        if shared.PROFILE == "development":
            self.add_css_class("devel")

        # Connect search entries
        self.search_bar.connect_entry(self.search_entry)
        self.hidden_search_bar.connect_entry(self.hidden_search_entry)

        # Fechar a barra pelo botão da lupa (binding bidirecional) ou pelo Esc
        # nativo do GtkSearchBar esconde a barra sem limpar o texto, e nada
        # dispara "search-changed" — o filtro continuava aplicado numa grade
        # sem busca visível, mostrando "Nenhum jogo encontrado" do nada. Só o
        # caminho win.toggle_search limpava. Limpar aqui cobre todos.
        self.search_bar.connect(
            "notify::search-mode-enabled",
            self.on_search_mode_changed,
            self.search_entry,
        )
        self.hidden_search_bar.connect(
            "notify::search-mode-enabled",
            self.on_search_mode_changed,
            self.hidden_search_entry,
        )

        # Connect signals
        self.search_entry.connect("search-changed", self.search_changed, False)
        self.hidden_search_entry.connect("search-changed", self.search_changed, True)

        self.search_entry.connect("activate", self.show_details_page_search)
        self.hidden_search_entry.connect("activate", self.show_details_page_search)

        self.navigation_view.connect("popped", self.set_show_hidden)
        self.navigation_view.connect("pushed", self.set_show_hidden)
        self.navigation_view.connect("popped", self.stop_details_animation)

        # Toda caixa de diálogo do app passa por esta propriedade, inclusive as
        # de alerta criadas na hora, então é daqui que dá para desarmar de uma
        # vez o arrasto da janela pelo fundo escurecido.
        self.connect("notify::visible-dialog", self.block_dialog_backdrop_drag)

        style_manager = Adw.StyleManager.get_default()

        # The style manager and the settings schema both live as long as the
        # process, and each of these handlers is a bound method — the same hold
        # documented for the news checker in `attach_news_checker`, only from the
        # other side. Left connected, they pin this window and its whole widget
        # tree in C for the rest of the session, and a theme switch after the
        # window is gone re-enters the handlers over destroyed widgets. The ids
        # are kept so `detach_global_handlers` can undo them.
        self._global_handler_ids = [
            (
                style_manager,
                style_manager.connect(
                    "notify::dark", self.set_details_view_opacity
                ),
            ),
            (
                style_manager,
                style_manager.connect(
                    "notify::high-contrast", self.set_details_view_opacity
                ),
            ),
            # Refresh every game's play/details icon from one handler when the
            # setting changes, instead of one per-game handler that is never
            # released
            (
                shared.schema,
                shared.schema.connect(
                    "changed::cover-launches-game", self.update_play_icons
                ),
            ),
        ]
        self.connect("destroy", self.detach_global_handlers)

        # The "session in progress" overlay button ends the session, same as the
        # compact window's button
        self.session_blocker_button.connect("clicked", self.on_session_blocker_clicked)

        # O menu do status é o mesmo do começo ao fim da execução: as opções
        # não dependem do jogo aberto, só o rótulo do botão depende.
        self.details_view_status_button.set_menu_model(self.build_status_menu())

        # A anotação é lida e escrita aqui mesmo, sem passar pela tela de
        # edição. Um só handler para os dois lados: ao abrir, o balão carrega o
        # que está gravado; ao fechar, grava o que ficou escrito — inclusive
        # quando se fecha com Esc, porque perder o texto por causa de uma tecla
        # é pior do que salvar uma edição que talvez não se quisesse.
        self.details_view_notes_popover.connect(
            "notify::visible", self.on_notes_popover_toggled
        )
        # O mesmo editor no bloqueador de sessão: com o jogo aberto, a janela
        # está travada e a anotação — que é justamente sobre onde se parou —
        # ficaria inalcançável até a sessão terminar.
        self.session_blocker_notes_popover.connect(
            "notify::visible", self.on_session_notes_popover_toggled
        )

        # O histórico abre pelo próprio "Tempo de jogo", que é o que ele detalha
        # — ver `update_playtime_label`. Um clique sobre um Label comum, e não um
        # botão ou um link: os três rótulos daquela linha têm de continuar
        # idênticos entre si.
        click = Gtk.GestureClick.new()
        click.connect("released", self.on_playtime_activated)
        self.details_view_playtime.add_controller(click)

        # Clicking the patch banner asks for confirmation before dismissing it
        self.details_view_update_notice.connect(
            "clicked", self.on_update_notice_clicked
        )

        # Both refresh affordances on the news page do the same thing: force a
        # poll. The retry button only ever appears on the "nothing to show"
        # state, which is exactly when re-polling is what the user wants.
        self.news_refresh_button.connect("clicked", self.on_news_refresh_clicked)
        self.news_retry_button.connect("clicked", self.on_news_refresh_clicked)

        self._install_filter_menu()

        # Allow for a custom number of rows for the library
        if shared.schema.get_uint("library-rows"):
            shared.schema.bind(
                "library-rows",
                self.library,
                "max-children-per-line",
                Gio.SettingsBindFlags.DEFAULT,
            )
            shared.schema.bind(
                "library-rows",
                self.hidden_library,
                "max-children-per-line",
                Gio.SettingsBindFlags.DEFAULT,
            )
        else:
            # Sem teto na prática: as colunas acompanham a largura da janela,
            # como já acontecia de 1 a 10 — numa tela larga a grade continua
            # abrindo colunas em vez de parar na décima. O limite real é o
            # número de jogos (o GtkFlowBox nunca abre mais colunas que
            # filhos); 999 só existe porque a propriedade exige um número.
            self.library.set_max_children_per_line(999)
            self.hidden_library.set_max_children_per_line(999)

    def detach_global_handlers(self, *_args: Any) -> None:
        """Let go of the process-wide singletons. Called on destroy.

        The mirror of `detach_news_checker`: the style manager and the settings
        schema outlive every window, so until this runs a closed window is still
        on their handler lists — kept alive, and still asked to repaint on the
        next theme change.
        """
        for obj, handler_id in self._global_handler_ids:
            if obj.handler_is_connected(handler_id):
                obj.disconnect(handler_id)
        self._global_handler_ids = []

    def block_dialog_backdrop_drag(self, *_args: Any) -> None:
        if (dialog := self.get_visible_dialog()) is not None:
            block_window_drag(dialog)

    def update_play_icons(self, *_args: Any) -> None:
        for game in shared.store:
            if not game.removed:
                game.set_play_icon()

    def session_toast(self, game: Game, seconds: int) -> None:
        """O aviso de fim de sessão, com um atalho para a anotação.

        Um lugar só para os dois modos de sessão (a janelinha manual e o
        rastreio de processo), que mostravam o mesmo aviso escrito duas vezes.

        O botão só aparece quando há onde anotar — a mesma condição do botão da
        tela de detalhes, que é para onde ele leva. Sem isso, ele abriria uma
        tela sem nada em que clicar. É aqui que a anotação costuma nascer: no
        fim da sessão você acabou de ver onde parou, e o balão já abre aberto.
        """
        toast = Adw.Toast.new(
            # The variables are the game's title and the session length
            _("{}: {} de jogo").format(game.name, format_playtime(seconds))
        )
        # The game's name is interpolated in and Adw.Toast parses its title as
        # Pango markup by default; an "&" or "<" mangles or drops the label.
        toast.set_use_markup(False)
        if can_edit_notes(game):
            toast.set_button_label(_("Anotar"))
            toast.connect("button-clicked", self.on_session_toast_notes, game)
        self.toast_queue.add(toast)

    def on_session_toast_notes(self, _toast: Adw.Toast, game: Game) -> None:
        """Abre o jogo com o balão da anotação já aberto.

        Pelo idle porque a página acabou de ser empilhada: um balão pedido
        antes de o botão dele existir na tela não abre em lugar nenhum.
        """
        self.show_details_page(game)
        GLib.idle_add(self.details_view_notes_popover.popup)

    def move_to_session_monitor(self) -> bool:
        """Manda a janela para o monitor escolhido, maximizada. Diz se foi.

        Falso também com a opção ligada, se o monitor escolhido não estiver
        mais ligado na máquina — e aí quem chamou minimiza a janela, que é o
        que o app fazia antes desta opção existir. Ficar sem saber onde a
        janela foi parar é pior do que ela não sair do lugar.
        """
        if not shared.schema.get_boolean("session-move-window"):
            return False
        return window_geometry.move_to_monitor(
            self, shared.schema.get_string("session-monitor")
        )

    def session_elapsed(self) -> int:
        """Os segundos que a sessão em andamento já contou. Zero sem sessão."""
        # avoid import cycles
        from cartridges.process_session import ProcessSession
        from cartridges.session_window import SessionWindow

        if ProcessSession.active is not None:
            return ProcessSession.active.elapsed
        if (active := SessionWindow.active) is not None:
            # `flush` grava a cada minuto adiantando `session_start`; sem somar
            # o que já foi gravado, o relógio voltava a zero a cada gravação.
            return active.session_seconds + int(monotonic() - active.session_start)
        return 0

    def session_tick(self, *_args: Any) -> bool:
        self.session_blocker_timer.set_label(format_stopwatch(self.session_elapsed()))
        return GLib.SOURCE_CONTINUE

    def show_session_blocker(self, game: Game) -> None:
        # O jogo inteiro, e não só o nome: o botão de anotação daqui grava
        # nele, e é o único jogo que o bloqueador tem para oferecer.
        self.session_game = game
        # The variable is the name of the game currently being played
        self.session_blocker_label.set_label(_("{} em andamento").format(game.name))
        # The opaque overlay covers the whole window content (including the
        # header bar) so "Jogar" can't start a second session; the window can
        # still be moved/closed via the taskbar or system shortcuts
        self.session_blocker.set_visible(True)

        # O relógio só faz sentido onde ele pode ser visto: se a janela foi
        # para o outro monitor, ela fica à vista a sessão inteira; se não foi,
        # ela está minimizada e ninguém veria segundo nenhum. A pergunta é se a
        # mudança aconteceu, e não se a opção está ligada — com o monitor
        # escolhido desligado da máquina, a opção está ligada e a janela
        # minimizou assim mesmo.
        if window_geometry.session_geometry() is not None:
            self.session_tick()
            self.session_blocker_timer.set_visible(True)
            self.session_timer_id = GLib.timeout_add_seconds(1, self.session_tick)

        # Vestir os monitores em pé com a arte do jogo. A preparação roda numa
        # thread porque o caminho completo é rede (busca e download no
        # wallhaven) mais Pillow, e nada disso pode segurar a tela enquanto o
        # jogo abre — quando a arte já está em disco, ela aparece junto com o
        # bloqueador.
        if shared.schema.get_boolean("session-wallpaper"):
            session_wallpaper.comecar(game)

        # Hand the controller entirely to the game for the duration: stop
        # polling and release the XInput DLL until the session ends.
        from cartridges.gamepad import GamepadManager  # avoid import cycle

        if GamepadManager.active is not None:
            GamepadManager.active.suspend()

    def hide_session_blocker(self) -> None:
        # Primeiro esconder, depois esquecer o jogo: esconder fecha um balão de
        # anotação que esteja aberto, e é esse fechamento que a grava.
        self.session_blocker.set_visible(False)
        self.session_game = None

        if self.session_timer_id:
            GLib.source_remove(self.session_timer_id)
            self.session_timer_id = 0
        self.session_blocker_timer.set_visible(False)

        # De volta ao monitor de onde saiu, do tamanho que tinha. No-op quando
        # a janela não saiu do lugar. Antes do `present()` de quem chamou, para
        # a janela reaparecer já no lugar certo em vez de aparecer no monitor
        # do jogo e pular.
        window_geometry.restore_from_monitor(self)

        # De volta ao papel de parede de cada monitor. Síncrono, ao contrário
        # da ida: são alguns milissegundos de COM, e uma thread aqui correria
        # com o `do_shutdown`, que chama a mesma devolução ao fechar o app no
        # meio da sessão.
        session_wallpaper.restaurar()

        # Session over: bring gamepad navigation back.
        from cartridges.gamepad import GamepadManager  # avoid import cycle

        if GamepadManager.active is not None:
            GamepadManager.active.resume()

    def on_session_blocker_clicked(self, *_args: Any) -> None:
        # avoid import cycles
        from cartridges.process_session import ProcessSession
        from cartridges.session_window import SessionWindow

        if SessionWindow.active is not None:
            SessionWindow.active.close()
        if ProcessSession.active is not None:
            ProcessSession.active.stop(record=True)

    # -- Filtrar por ----------------------------------------------------------

    def _install_filter_menu(self) -> None:
        """Põe "Filtrar por" acima de "Ordenar por" e liga a reconstrução.

        O conteúdo é dinâmico — só gêneros e anos que existem na biblioteca —
        então o submenu é um Gio.Menu vivo, refeito a cada abertura do popover.
        Inserido no modelo compartilhado uma única vez: os dois botões de menu
        (biblioteca e ocultos) apontam para o mesmo GMenu, e o popover segue
        mudanças do modelo sozinho.

        As ações moram na janela (não no app) de propósito: filtro é estado da
        janela, como a busca, e assim a janela se basta — inclusive nos testes,
        que a constroem sem aplicação nenhuma.
        """
        for name in ("filter_genre", "filter_year", "filter_status"):
            action = Gio.SimpleAction.new_stateful(
                name, GLib.VariantType.new("s"), GLib.Variant("s", "")
            )
            action.connect("activate", self.on_filter_action)
            self.add_action(action)

        clear = Gio.SimpleAction.new("clear_filters", None)
        clear.connect("activate", self.on_clear_filters_action)
        self.add_action(clear)

        # Trocar o status do jogo aberto. Sem estado: o rótulo do botão já
        # mostra o status atual, e um menu de rádio precisaria ressincronizar
        # a cada jogo aberto para dizer a mesma coisa duas vezes.
        set_status = Gio.SimpleAction.new("set_status", GLib.VariantType.new("s"))
        set_status.connect("activate", self.on_set_status_action)
        self.add_action(set_status)

        self._filter_menu = Gio.Menu()
        model = self.primary_menu_button.get_menu_model()
        section = model.get_item_link(0, "section")
        # Defensivo: se a estrutura do .blp mudar e o primeiro item deixar de
        # ser uma seção, o submenu entra na raiz em vez de sumir em silêncio.
        target = section if isinstance(section, Gio.Menu) else model
        target.insert_submenu(0, _("Filtrar por"), self._filter_menu)

        # Refeito na abertura, não a cada mudança da biblioteca: um import em
        # andamento mexeria no menu dezenas de vezes sem ninguém olhando.
        for button in (self.primary_menu_button, self.hidden_primary_menu_button):
            button.get_popover().connect("show", self.rebuild_filter_menu)

        self.rebuild_filter_menu()

    @staticmethod
    def _alpha_key(text: str) -> str:
        """Chave de ordenação alfabética que não exila os acentos.

        Sem isto "Ação" ordena depois de "Aventura": "ç" e "ã" valem mais que
        qualquer letra ASCII. A decomposição NFKD separa a marca da letra-base,
        então a comparação acontece no "c" e no "a".
        """
        return unicodedata.normalize("NFKD", text.casefold())

    def rebuild_filter_menu(self, *_args: Any) -> None:
        """Reconstrói Gêneros e Anos com o que a biblioteca tem agora."""
        genres: set[str] = set()
        years: set[str] = set()
        for game in shared.store:
            if game.removed or game.blacklisted:
                continue
            if game.genre:
                genres.add(game.genre)
            year, _month = parse_release_date(game.release_date or "")
            if year:
                years.add(str(year))

        # Um valor selecionado que saiu da biblioteca (o último jogo daquele
        # gênero foi removido) reseta o filtro: mantê-lo deixaria a grade
        # vazia apontando para uma opção que o menu nem oferece mais.
        if self.filter_genre_state and self.filter_genre_state not in genres:
            self.set_filter("filter_genre", "")
        if self.filter_year_state and self.filter_year_state not in years:
            self.set_filter("filter_year", "")

        self._filter_menu.remove_all()
        self._filter_menu.append_submenu(
            _("Gêneros"),
            self._build_choice_menu(
                "filter_genre",
                [(g, g) for g in sorted(genres, key=self._alpha_key)],
            ),
        )
        self._filter_menu.append_submenu(
            _("Ano de lançamento"),
            # Anos são sempre 4 dígitos, então ordem de texto = ordem numérica
            self._build_choice_menu(
                "filter_year", [(y, y) for y in sorted(years, reverse=True)]
            ),
        )
        # Lista fixa, ao contrário das duas de cima: os status existem quer
        # algum jogo os use ou não, e "Zerado" sumindo do menu quando nenhum
        # jogo está zerado esconderia justamente a pergunta que se quer fazer.
        self._filter_menu.append_submenu(
            _("Status"),
            self._build_choice_menu(
                "filter_status",
                # (rótulo, valor), e não o par do dicionário, que vem ao
                # contrário: STATUS_LABELS é {valor: rótulo}.
                [(label, value) for value, label in STATUS_LABELS.items()],
            ),
        )

        # "Limpar" só existe enquanto há o que limpar: zera os dois filtros num
        # clique, em vez de entrar em cada lista e marcar "Todos" duas vezes.
        # Escolher um filtro fecha o popover, então a próxima abertura já
        # remonta o menu com (ou sem) ele — nada fica desatualizado na tela.
        if self.filter_genre_state or self.filter_year_state or self.filter_status_state:
            section = Gio.Menu()
            section.append(_("Limpar"), "win.clear_filters")
            self._filter_menu.append_section(None, section)

    @staticmethod
    def _build_choice_menu(
        action_name: str, choices: list[tuple[str, str]]
    ) -> Gio.Menu:
        """Uma lista de rádio: "Todos" e cada opção, marcando a escolhida.

        Recebe pares (rótulo, valor) porque nem toda opção mostra o que grava:
        gêneros e anos são o próprio valor, o status grava "beaten" e mostra
        "Zerado".

        Montada com Gio.MenuItem em vez de nomes detalhados de ação: os valores
        são texto livre da biblioteca ("Tiro em Primeira Pessoa (FPS)"), e a
        forma textual exigiria escapar cada um.
        """
        submenu = Gio.Menu()
        for label, value in ((_("Todos"), ""), *choices):
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value(
                f"win.{action_name}", GLib.Variant("s", value)
            )
            submenu.append_item(item)
        return submenu

    def set_filter(self, action_name: str, value: str) -> None:
        """Aplica um filtro pelo nome da ação — o mesmo caminho do menu."""
        self.on_filter_action(
            self.lookup_action(action_name), GLib.Variant("s", value)
        )

    def on_clear_filters_action(self, *_args: Any) -> None:
        """Volta gênero e ano para "Todos" de uma vez."""
        self.set_filter("filter_genre", "")
        self.set_filter("filter_year", "")
        self.set_filter("filter_status", "")

    def on_filter_action(self, action: Gio.SimpleAction, state: GLib.Variant) -> None:
        action.set_state(state)
        value = state.get_string()
        name = action.get_name()
        if name == "filter_genre":
            self.filter_genre_state = value
        elif name == "filter_status":
            self.filter_status_state = value
        else:
            self.filter_year_state = value

        # As duas grades, como a ordenação: o filtro é da biblioteca, não da
        # página que estava aberta quando ele foi escolhido.
        self.library.invalidate_filter()
        self.hidden_library.invalidate_filter()

    # -- Status e histórico ---------------------------------------------------

    @staticmethod
    def build_status_menu() -> Gio.Menu:
        """O menu do botão de status: os quatro status e "Sem status".

        "Sem status" vem por último, numa seção própria: é tirar a marcação,
        não uma quinta forma de estar com o jogo.
        """
        menu = Gio.Menu()
        section = Gio.Menu()
        for value, label in STATUS_LABELS.items():
            item = Gio.MenuItem.new(label, None)
            item.set_action_and_target_value("win.set_status", GLib.Variant("s", value))
            section.append_item(item)
        menu.append_section(None, section)

        clear = Gio.Menu()
        item = Gio.MenuItem.new(_("Sem status"), None)
        item.set_action_and_target_value("win.set_status", GLib.Variant("s", ""))
        clear.append_item(item)
        menu.append_section(None, clear)
        return menu

    def on_set_status_action(self, _action: Any, target: GLib.Variant) -> None:
        game = getattr(self, "active_game", None)
        if game is None:
            return

        game.status = target.get_string()
        game.save()
        game.update()

        self.update_status_button(game)
        self.update_notes_block(game)
        # Um jogo que acabou de sair do status filtrado tem de sair da grade
        # junto: a alternativa é ele ficar lá contradizendo o próprio filtro
        # até a próxima coisa que invalidar a lista.
        if self.filter_status_state:
            self.library.invalidate_filter()
            self.hidden_library.invalidate_filter()

    def update_status_button(self, game: Game) -> None:
        """O botão diz o status atual, ou convida a definir um."""
        self.details_view_status_button.set_label(
            status_label(game.status) or _("Definir status")
        )

    def update_notes_block(self, game: Game) -> None:
        """A anotação na tela: o texto quando existe, o botão quando cabe.

        O bloco de leitura aparece sempre que há algo escrito — inclusive num
        jogo zerado, onde a anotação vira lembrança do que se achou dele. O
        botão de editar aparece em "Jogando", o único status em que a pergunta
        "onde eu parei?" tem resposta, e também em qualquer jogo que já tenha
        anotação: este é o único lugar onde ela se edita, e um texto à mostra
        sem como apagar seria uma anotação presa na tela para sempre.
        """
        notes = (game.notes or "").strip()
        self.details_view_notes.set_label(notes)
        self.details_view_notes_box.set_visible(bool(notes))
        self.details_view_notes_button.set_visible(can_edit_notes(game))

    def on_notes_popover_toggled(self, popover: Gtk.Popover, _pspec: Any) -> None:
        """O balão da tela de detalhes edita o jogo que ela está mostrando."""
        self.sync_notes_editor(
            popover, self.details_view_notes_view, getattr(self, "active_game", None)
        )

    def on_session_notes_popover_toggled(
        self, popover: Gtk.Popover, _pspec: Any
    ) -> None:
        """O balão do bloqueador edita o jogo da sessão, e só ele.

        Nunca o `active_game`: a tela de detalhes por trás do bloqueador pode
        ter ficado em qualquer jogo, e a anotação escrita durante uma sessão é
        sobre o jogo que está rodando.
        """
        self.sync_notes_editor(
            popover, self.session_blocker_notes_view, self.session_game
        )

    def sync_notes_editor(
        self, popover: Gtk.Popover, view: Gtk.TextView, game: Optional[Game]
    ) -> None:
        """Carrega a anotação ao abrir o balão e grava ao fechar."""
        if game is None:
            return

        buffer = view.get_buffer()
        if popover.get_visible():
            buffer.set_text(game.notes or "")
            return

        # Mesmo tratamento de antes: as quebras do meio ficam (são o que separa
        # um lembrete do outro), as das pontas saem para que uma caixa em que
        # só se apertou Enter conte como vazia.
        notes = buffer.get_text(
            buffer.get_start_iter(), buffer.get_end_iter(), False
        ).strip()
        if notes == (game.notes or ""):
            return

        game.notes = notes
        game.save()
        game.update()
        # A tela de detalhes pode estar mostrando este mesmo jogo por trás do
        # bloqueador; quando não for ele, nada ali muda.
        if game is getattr(self, "active_game", None):
            self.update_notes_block(game)

    def update_playtime_label(self, game: Game) -> None:
        """O tempo de jogo, clicável quando há sessões por trás dele.

        O total é a soma das sessões, então é ele mesmo que abre a lista delas
        — em vez de um ícone ao lado, que ficava solto numa linha que só tem
        texto.

        Continua um rótulo comum, idêntico aos dois ao lado: nem link nem botão.
        Um link se pinta da cor de destaque e se sublinha, um botão ganha
        preenchimento e canto arredondado, e qualquer um dos dois quebra uma
        linha cujos três itens são o mesmo tipo de informação — a versão com
        link foi vista na tela e destoava. Quem diz que dá para clicar é o
        cursor de mão e a dica; o desenho da linha não muda em nada.

        Sem sessão gravada nada disso aparece e o rótulo é só um rótulo: uma
        lista vazia é uma promessa que a tela não cumpre. É o caso de toda a
        biblioteca até a primeira partida jogada por aqui, e também o do tempo
        restaurado de um backup, que é um total sem sessões por natureza.
        """
        self.details_view_playtime.set_visible(bool(game.playtime))
        if not game.playtime:
            return

        # A variável é o tempo total de jogo
        self.details_view_playtime.set_text(
            _("Tempo de jogo: {}").format(format_playtime(game.playtime))
        )

        self._playtime_clickable = bool(session_log.load(game.game_id))
        self.details_view_playtime.set_tooltip_text(
            _("Ver o histórico de sessões") if self._playtime_clickable else None
        )
        self.details_view_playtime.set_cursor(
            Gdk.Cursor.new_from_name("pointer", None)
            if self._playtime_clickable
            else None
        )

    def update_install_size_label(self, game: Game) -> None:
        """O tamanho da instalação, quando ele já foi medido.

        Só um rótulo: medir é trabalho da varredura em segundo plano, e a tela
        de detalhes nunca sai andando no disco para preencher esta linha —
        abrir um jogo tem de ser instantâneo. Um jogo ainda não medido (ou cujo
        comando não diz onde ele mora) fica sem a linha, e não com um zero.
        """
        text = format_size(game.install_size)
        self.details_view_size.set_visible(bool(text))
        if text:
            # A variável é o tamanho da instalação, ex.: "87,4 GB"
            self.details_view_size.set_label(_("Tamanho: {}").format(text))

    def on_playtime_activated(self, *_args: Any) -> None:
        if not self._playtime_clickable:
            return
        game = getattr(self, "active_game", None)
        if game is not None:
            SessionHistoryDialog(game).present(self)

    def search_changed(self, _widget: Any, hidden: bool) -> None:
        # Refresh search filter on keystroke in search box
        (self.hidden_library if hidden else self.library).invalidate_filter()

    def on_search_mode_changed(
        self, search_bar: Gtk.SearchBar, _pspec: Any, entry: Gtk.SearchEntry
    ) -> None:
        # set_text("") numa entry já vazia não emite "search-changed", então o
        # caminho toggle_search (que também limpa) não paga nada em dobro.
        if not search_bar.get_search_mode():
            entry.set_text("")

    def set_library_child(self) -> None:
        child, hidden_child = self.notice_empty, self.hidden_notice_empty

        for game in shared.store:
            if game.removed or game.blacklisted:
                continue
            if game.hidden:
                if game.filtered and hidden_child:
                    hidden_child = self.hidden_notice_no_results
                    continue
                hidden_child = None
            else:
                if game.filtered and child:
                    child = self.notice_no_results
                    continue
                child = None

        def remove_from_overlay(widget: Gtk.Widget) -> None:
            if isinstance(widget.get_parent(), Gtk.Overlay):
                widget.get_parent().remove_overlay(widget)

        # O aviso que NÃO foi escolhido sai sempre, e não só quando nenhum é
        # mostrado: a transição direta "Nenhum jogo" → "Nenhum jogo encontrado"
        # (biblioteca vazia com busca ativa) adicionava o novo sem remover o
        # antigo, e os dois AdwStatusPage ficavam sobrepostos.
        for notice in (self.notice_empty, self.notice_no_results):
            if notice is not child:
                remove_from_overlay(notice)
        if child:
            self.library_overlay.add_overlay(child)

        for notice in (self.hidden_notice_empty, self.hidden_notice_no_results):
            if notice is not hidden_child:
                remove_from_overlay(notice)
        if hidden_child:
            self.hidden_library_overlay.add_overlay(hidden_child)

    def filter_func(self, child: Gtk.Widget) -> bool:
        game = child.get_child()
        # The same filter is installed on both grids, so the search box to match
        # against is the one belonging to the grid this child actually lives in.
        # Deciding by the visible page instead matched a game against the wrong
        # box whenever the two disagreed: GTK re-runs the filter on `append`, so
        # a game imported while the hidden page was open was tested against that
        # page's (empty) entry, came out filtered, and stayed invisible — nothing
        # invalidates the filter again once the import is over.
        # A child being appended may not have its parent yet; `game.hidden` is
        # what routes it to one grid or the other, so it answers the same
        # question before GTK does.
        parent = child.get_parent()
        hidden = parent is self.hidden_library if parent else bool(game.hidden)
        text = (
            (self.hidden_search_entry if hidden else self.search_entry)
            .get_text()
            .lower()
        )

        # A anotação entra na busca junto do título, da desenvolvedora e da
        # publicadora: quem escreveu "senha do cofre: 8815" seis meses atrás
        # lembra da palavra, não de qual jogo era — que é a mesma razão de
        # procurar por "Team Cherry" e achar o jogo.
        filtered = text != "" and not (
            text in game.name.lower()
            or (text in game.developer.lower() if game.developer else False)
            or (text in game.publisher.lower() if game.publisher else False)
            or (text in game.notes.lower() if game.notes else False)
        )

        # Os filtros do menu se somam à busca. Um jogo sem o campo (sem gênero,
        # sem data) só aparece em "Todos": o menu lista o que existe, e "não
        # informado" não é um gênero para se listar.
        if not filtered and self.filter_genre_state:
            filtered = (game.genre or "") != self.filter_genre_state
        if not filtered and self.filter_year_state:
            year, _month = parse_release_date(game.release_date or "")
            filtered = str(year or "") != self.filter_year_state
        if not filtered and self.filter_status_state:
            filtered = (game.status or "") != self.filter_status_state

        game.filtered = filtered
        # filter_func runs once per game on every invalidate_filter; calling
        # set_library_child here too made filtering O(n²). Coalesce it into a
        # single deferred update that runs after the whole filter pass instead.
        self.schedule_library_child()

        return not filtered

    def schedule_library_child(self) -> None:
        """Run set_library_child once after the current burst of callers.

        Público porque o DisplayManager tem o mesmo problema do filtro: no
        import em massa ele rodava a varredura completa uma vez por jogo.

        PRIORITY_HIGH_IDLE (100) fica acima do layout (110) e da pintura (120)
        do GTK, então o aviso de grade vazia/cheia muda no mesmo quadro que o
        lote que agendou. Na prioridade padrão (200) ele rodava depois da
        pintura, e o "Nenhum jogo" aparecia por cima da grade recém-preenchida
        — um piscar por abertura, e segundos na primeira, quando os quadros
        iniciais são lentos (shaders frios) e um idle comum fica para trás.
        """
        if self._library_child_update_pending:
            return
        self._library_child_update_pending = True
        GLib.idle_add(
            self._run_library_child_update, priority=GLib.PRIORITY_HIGH_IDLE
        )

    def _run_library_child_update(self) -> bool:
        self._library_child_update_pending = False
        self.set_library_child()
        return False

    def set_active_game(self, _widget: Any, _pspec: Any, game: Game) -> None:
        self.active_game = game

    def store_library_scroll(self) -> None:
        """Remember where each grid is scrolled to.

        Opening and closing a dialog can leave the window without a focused
        widget. GTK then focuses the first game in the grid and the viewport,
        which has scroll-to-focus enabled by default, jumps back to the top.
        Snapshot the position here and put it back with
        :meth:`restore_library_scroll` once the dialog is gone.
        """
        self._library_scroll = tuple(
            scrolled.get_vadjustment().get_value()
            for scrolled in (self.scrolledwindow, self.hidden_scrolledwindow)
        )

    def restore_library_scroll(self) -> None:
        if not (stored := getattr(self, "_library_scroll", None)):
            return
        self._library_scroll = None

        for scrolled, value in zip(
            (self.scrolledwindow, self.hidden_scrolledwindow), stored
        ):
            # Zero is not "nothing to restore": a grid at the top is exactly
            # where scroll-to-focus can only drag the library downwards, to
            # wherever the edited game sits. Suppress it for zero too.
            adjustment = scrolled.get_vadjustment()
            viewport = scrolled.get_child()
            viewport = viewport if isinstance(viewport, Gtk.Viewport) else None

            # Focus lands after the dialog closes, so suppress scroll-to-focus
            # until the position has been re-applied
            if viewport:
                viewport.set_scroll_to_focus(False)

            # The grid is re-laid out over the next few frames (the sort runs
            # on idle); re-apply the value until it sticks
            frames = [0]

            def put_back(
                adjustment: Gtk.Adjustment = adjustment,
                value: float = value,
                viewport: Optional[Gtk.Viewport] = viewport,
                frames: list = frames,
            ) -> bool:
                adjustment.set_value(value)
                frames[0] += 1
                if frames[0] < 4:
                    return True

                if viewport:
                    viewport.set_scroll_to_focus(True)
                return False

            GLib.timeout_add(16, put_back)

    def show_details_page(self, game: Game) -> None:
        self.active_game = game

        self.details_view_cover.set_opacity(int(not game.loading))
        self.details_view_spinner.set_visible(game.loading)

        self.details_view_developer.set_label(game.developer or "")
        self.details_view_developer.set_visible(bool(game.developer))

        self.details_view_publisher.set_label(game.publisher or "")
        self.details_view_publisher.set_visible(bool(game.publisher))

        self.details_view_release_date.set_label(
            # The variable is the game's release date
            _("Lançamento: {}").format(format_release_date(game.release_date))
            if game.release_date
            else ""
        )
        self.details_view_release_date.set_visible(bool(game.release_date))

        # Cheias até a nota, vazias depois: cinco símbolos sempre, para que duas
        # notas lado a lado se comparem pelo desenho e não pela contagem.
        stars = game.stars
        self.details_view_rating.set_visible(bool(stars))
        if stars:
            # A variável são as cinco estrelas, cheias ou vazias
            self.details_view_rating.set_label(
                _("Minha nota: {}").format("★" * stars + "☆" * (5 - stars))
            )

        self.update_status_button(game)

        # Both scores are shown when available, Metacritic first and the Steam
        # review summary on the line right below it.
        has_metacritic = game.metacritic is not None
        # The variable is the game's Metacritic score
        self.details_view_metacritic.set_label(
            _("Metacritic: {}").format(game.metacritic) if has_metacritic else ""
        )
        self.details_view_metacritic.set_visible(has_metacritic)

        has_steam_review = bool(game.steam_review)
        # The variable is the Steam review summary, e.g. "Muito positivas"
        self.details_view_steam_review.set_label(
            _("Avaliações: {}").format(game.steam_review) if has_steam_review else ""
        )
        self.details_view_steam_review.set_visible(has_steam_review)

        # Shown bare, without a "Gênero:" prefix: the value already reads as a
        # label ("Metroidvania", "Tiro em Primeira Pessoa (FPS)").
        self.details_view_genre.set_label(game.genre or "")
        self.details_view_genre.set_visible(bool(game.genre))

        # Only the two states Steam actually asserts. A game carrying neither
        # category is left without a line rather than declared unsupported.
        controller_label = {
            "full": _("Compatibilidade total com controle"),
            "partial": _("Compatibilidade parcial com controle"),
        }.get(game.controller_support or "")
        self.details_view_controller_support.set_label(controller_label or "")
        self.details_view_controller_support.set_visible(bool(controller_label))

        # The sentence is fixed in the template, so only visibility is driven here.
        self.details_view_gamepad_recommended.set_visible(game.gamepad_recommended)

        self.update_notes_block(game)

        self.details_view_description.set_label(game.description or "")
        self.details_view_description.set_visible(bool(game.description))

        self.update_hltb_block(game)

        self.update_details_notice(game)

        icon, text = "view-conceal-symbolic", _("Ocultar")
        if game.hidden:
            icon, text = "view-reveal-symbolic", _("Reexibir")

        self.details_view_hide_button.set_icon_name(icon)
        self.details_view_hide_button.set_tooltip_text(text)

        if self.details_view_game_cover:
            self.details_view_game_cover.set_details_animation(False)
            # Releases the sharp texture along with the picture, so only the
            # cover currently on screen holds one. `discard`, unlike the
            # `remove` this used to be, which raised KeyError whenever the
            # previous cover had already let the picture go (a game edited
            # while its details page was open).
            self.details_view_game_cover.release_details_picture(
                self.details_view_cover
            )

        self.details_view_game_cover = game.game_cover
        self.details_view_game_cover.add_details_picture(self.details_view_cover)
        # The details page always plays the animation, regardless of hover
        self.details_view_game_cover.set_details_animation(True)

        # O desfoque do fundo é computado fora do thread principal na primeira
        # visita (era o engasgo da abertura). Só limpa ao trocar DE JOGO: o
        # desfoque do anterior não pode ficar atrás dos metadados deste. No
        # mesmo jogo, o fundo atual fica no lugar até o novo chegar — o Aplicar
        # da edição troca o objeto da capa e recomeça o desfoque, e limpar aqui
        # fazia a página piscar preto por um quadro nesse meio-tempo.
        if (
            self.details_view_game_cover.blurred is None
            and self._blurred_backdrop_id != game.game_id
        ):
            self.details_view_blurred_cover.set_paintable(None)
            self._blurred_backdrop_id = None
        self.details_view_game_cover.ensure_blurred(self.on_blurred_cover_ready)

        self.details_view_title.set_label(game.name)
        self.details_page.set_title(game.name)
        self.update_details_logo(game)

        date = relative_date(game.added)
        self.details_view_added.set_label(
            # The variable is the date when the game was added
            _("Adicionado: {}").format(date)
        )
        last_played_date = (
            relative_date(game.last_played) if game.last_played else _("Nunca")
        )
        self.details_view_last_played.set_label(
            # The variable is the date when the game was last played
            _("Jogado por último: {}").format(last_played_date)
        )

        # A cada abertura da tela: uma sessão recém-terminada grava sua linha sem
        # passar por aqui, e o total do jogo que acabou de ser jogado pela
        # primeira vez precisa virar link agora, não na execução seguinte.
        self.update_playtime_label(game)
        self.update_install_size_label(game)

        if self.navigation_view.get_visible_page() != self.details_page:
            self.navigation_view.push(self.details_page)
            self.set_focus(self.details_view_play_button)

        self.set_details_view_opacity()

    def on_blurred_cover_ready(self, cover: GameCover) -> None:
        """Põe o desfoque pronto na tela — se a página ainda é deste jogo."""
        if cover is not self.details_view_game_cover:
            return
        self.details_view_blurred_cover.set_paintable(cover.blurred)
        active = getattr(self, "active_game", None)
        self._blurred_backdrop_id = active.game_id if active else None
        self.set_details_view_opacity()

    def update_details_logo(self, game: Game) -> None:
        """Head the content column with ``game``'s logo, or with its title.

        The title is the fallback and also the starting state, so a game with
        no logo — no API key, no match, nothing usable on SteamGridDB — gets
        exactly the page it got before this existed. A cached logo replaces it
        before the page is ever drawn; an uncached one is looked up in the
        background and swapped in when it lands.
        """
        self._logo_generation += 1

        # Reset to the text header first: it is what stays on screen if the
        # lookup finds nothing, and it keeps the previous game's logo from
        # lingering under a new game's metadata for a frame. The reserved
        # height goes with it — a title heading is as tall as the title, and
        # holding a logo's worth of space open above a game that will never
        # have one is just a gap.
        self.details_view_logo_clamp.set_visible(False)
        self.details_view_logo_clamp.set_vexpand(False)
        self.details_view_logo.set_paintable(None)
        self.details_view_header.set_size_request(-1, -1)
        self.details_view_title.set_visible(True)

        path = cached_logo_path(game)
        if path and self.show_details_logo(path):
            return

        if not logo_lookup_needed(game) or game.game_id in self._logo_fetches:
            return

        self._logo_fetches.add(game.game_id)
        threading.Thread(
            target=self.logo_lookup_thread, args=(game,), daemon=True
        ).start()

    def logo_lookup_thread(self, game: Game) -> None:
        """Fetch a logo off the main thread and hand it back to it."""
        path = None
        try:
            path = fetch_logo(game)
        except Exception:  # pylint: disable=broad-exception-caught
            # `fetch_logo` swallows the failures it anticipates, so reaching
            # here means an unanticipated one. It must still not be the end of
            # the story: the hand-back below is the only thing that clears this
            # game from `_logo_fetches`, and a thread dying before it would
            # leave the id in the set for the rest of the session — the guard
            # in `update_details_logo` would then refuse to ever look this game
            # up again, and the page would be stuck on the title with nothing
            # in the log to say why.
            logging.warning(
                "Unexpected error fetching a logo for %s", game.name, exc_info=True
            )
        finally:
            GLib.idle_add(self.logo_lookup_done, game.game_id, path)

    def logo_lookup_done(self, game_id: str, path: Optional[Path]) -> bool:
        self._logo_fetches.discard(game_id)
        if not path:
            return False

        # Judged against the game actually on screen, not against a generation
        # counter. The counter was bumped by every visit, including a return to
        # *this* game while its own lookup was still out — and because the
        # in-flight guard above suppresses the second lookup, the result then
        # arrived stamped with a generation that no longer matched and was
        # thrown away. The logo was on disk; the page kept showing the title
        # until the user navigated away and back.
        active = getattr(self, "active_game", None)
        if (
            active is not None
            and active.game_id == game_id
            and self.navigation_view.get_visible_page() == self.details_page
        ):
            self.show_details_logo(path)
        return False

    def show_details_logo(self, path: Path) -> bool:
        """Draw ``path`` as the header. False when the file is unusable.

        Only a width is imposed, through the clamp around the picture: the
        height then falls out of the logo's own proportions, so a wide
        wordmark and a chunky emblem both land inside the reserved header
        without either being stretched to fit it.

        The reservation itself is put back here, and only here. It is what
        makes every game with a logo start its metadata at the same height —
        a short, very wide wordmark would otherwise sit closer to the studio
        line than a tall one — and it is claimed only once there is a logo to
        justify it.
        """
        loaded = load_logo(path)
        if not loaded:
            return False

        texture, width = loaded
        self.details_view_logo.set_paintable(texture)
        self.details_view_header.set_size_request(-1, LOGO_MAX_HEIGHT)
        # Both bounds are set to the same value so the clamp stops easing
        # between a "tightened" and a full width and simply reports, and
        # allocates, the width asked for.
        self.details_view_logo_clamp.set_maximum_size(width)
        self.details_view_logo_clamp.set_tightening_threshold(width)
        self.details_view_logo_clamp.set_vexpand(True)
        self.details_view_logo_clamp.set_visible(True)
        # Both headers must never be on screen at once: the logo *is* the title
        # when it exists, not a decoration above it.
        self.details_view_title.set_visible(False)
        return True

    def update_hltb_block(self, game: Game) -> None:
        """Fill the HowLongToBeat block and hide what has no data.

        Three levels of visibility, all driven purely by which estimates exist:
        the whole block disappears when the game was never matched, a cell
        disappears when nobody submitted that particular time, and a separator
        only survives when it still sits between two visible cells (otherwise
        a game with one estimate would show a stray vertical line).

        A chaptered game takes the other branch entirely: it has no single
        estimate to put in the card, so the card gives way to a per-chapter
        table. The two are never on screen together.

        Nothing here reads ``game.playtime``: the block is a reference table,
        never a progress indicator.
        """
        if chapters := (game.hltb_chapters or []):
            self.fill_hltb_chapters(chapters)
            self.details_view_hltb_card.set_visible(False)
            self.details_view_hltb_chapters.set_visible(True)
            self.details_view_hltb_box.set_visible(True)
            return

        self.details_view_hltb_chapters.set_visible(False)
        self.details_view_hltb_card.set_visible(True)

        cells = (
            (self.details_view_hltb_main_cell, self.details_view_hltb_main_value),
            (self.details_view_hltb_extra_cell, self.details_view_hltb_extra_value),
            (
                self.details_view_hltb_completionist_cell,
                self.details_view_hltb_completionist_value,
            ),
        )

        visible_flags = []
        for (cell, value_label), seconds in zip(cells, game.hltb_times):
            visible = bool(seconds)
            value_label.set_label(format_hltb_time(seconds) if visible else "")
            cell.set_visible(visible)
            visible_flags.append(visible)

        # Each separator belongs to the cell on its right and only appears when
        # that cell has something visible to its left. Tying it to the right
        # cell (rather than to both neighbours) is what makes a gap in the
        # middle collapse correctly: with only "main" and "completionist", the
        # second separator slides over to divide them and the first disappears,
        # instead of both drawing for a single gap.
        separators = (
            self.details_view_hltb_separator_1,
            self.details_view_hltb_separator_2,
        )
        for index, separator in enumerate(separators):
            right = index + 1
            separator.set_visible(
                visible_flags[right] and any(visible_flags[:right])
            )

        self.details_view_hltb_box.set_visible(any(visible_flags))

    def fill_hltb_chapters(self, chapters: list[dict]) -> None:
        """Rebuild the chapter table: a header row, then one row per chapter.

        Rebuilt from scratch on every render rather than diffed — the table is
        a handful of labels, and a game's chapter list only changes when the
        lookup runs again.
        """
        container = self.details_view_hltb_chapters
        while child := container.get_first_child():
            container.remove(child)

        grid = Gtk.Grid(row_spacing=4, column_spacing=16)

        for column, title in enumerate(
            (_("História"), _("Extras"), _("Completista")), start=1
        ):
            header = Gtk.Label(label=title, halign=Gtk.Align.CENTER)
            header.add_css_class("caption")
            header.add_css_class("dim-label")
            header.add_css_class("hltb-chapter-value")
            grid.attach(header, column, 0, 1, 1)

        for row, chapter in enumerate(chapters, start=1):
            # The variable is the chapter number
            label = Gtk.Label(
                label=_("Capítulo {}").format(chapter.get("number") or row),
                halign=Gtk.Align.START,
                margin_end=8,
            )
            label.add_css_class("caption-heading")
            grid.attach(label, 0, row, 1, 1)

            for column, key in enumerate(
                ("hltb_main", "hltb_main_extra", "hltb_completionist"), start=1
            ):
                value = Gtk.Label(
                    label=format_hltb_time(chapter.get(key)),
                    halign=Gtk.Align.CENTER,
                )
                value.add_css_class("numeric")
                value.add_css_class("hltb-chapter-value")
                grid.attach(value, column, row, 1, 1)

        container.append(grid)

    def update_details_notice(self, game: Game) -> None:
        """Show or hide the patch banner for ``game`` on the details page.

        A single source of truth (``Game.has_update``) drives visibility, so the
        checker (raising a notice in the background) and the initial page build
        can both call this and agree on what should be on screen.
        """
        self.details_view_update_notice.set_visible(game.has_update)

    def on_update_notice_clicked(self, *_args: Any) -> None:
        """Open the repack page, then confirm before hiding the notice."""
        game = self.active_game
        if game is None or not game.has_update:
            return

        # Open the game's repack page first so it is loading while the user
        # reads the dialog. `open_uri` owns the scheme guard: the URL comes from
        # a third-party feed, so an unexpected scheme is never handed to the OS.
        open_uri(getattr(game, "update_url", ""), self)

        dialog = Adw.AlertDialog.new(
            _("Confirma a instalação do patch?"),
            None,
        )
        dialog.add_response("cancel", _("Não"))
        dialog.add_response("confirm", _("Sim"))
        dialog.set_response_appearance(
            "confirm", Adw.ResponseAppearance.SUGGESTED
        )
        dialog.set_default_response("confirm")
        dialog.set_close_response("cancel")
        dialog.connect("response", self.on_update_notice_response, game)
        dialog.present(self)

    def on_update_notice_response(
        self, _dialog: Adw.AlertDialog, response: str, game: Game
    ) -> None:
        if response != "confirm":
            return
        # Record the dismissal in the game's own state and take the banner down.
        game.dismiss_update()
        if self.active_game is game:
            self.update_details_notice(game)

    # -- Novidades ------------------------------------------------------------

    def attach_news_checker(self, checker: Any) -> None:
        """Adopt the feed watcher and start listening to it.

        Injected rather than constructed here so the window never owns a timer
        or a thread: the application creates the checker, hands it over, and
        stops it on shutdown. Everything the page shows is pulled from the
        checker on demand, so this can arrive after the window is already up.
        """
        self.news_checker = checker

        # Handler ids are kept so the connection can be undone. Each of these
        # is a bound method, so the checker holds a strong reference to this
        # window for as long as it lives — and the checker outlives the window,
        # it belongs to the application. Without `detach_news_checker` the
        # window (and the whole widget tree under it) is pinned for the rest of
        # the process, and GC cannot help: the reference is held in C by
        # GObject, not by Python.
        self._news_handler_ids = [
            checker.connect("posts-changed", self.on_news_posts_changed),
            checker.connect("poll-finished", self.on_news_poll_finished),
            checker.connect("unseen-changed", self.on_news_unseen_changed),
        ]

        # The checker may have polled before it was attached.
        self.news_badge.set_visible(checker.has_unseen)
        self.rebuild_news_list()
        self.update_news_view()

    def detach_news_checker(self) -> None:
        """Drop the feed watcher's hold on this window. Called on shutdown."""
        if (checker := self.news_checker) is not None:
            for handler_id in self._news_handler_ids:
                if checker.handler_is_connected(handler_id):
                    checker.disconnect(handler_id)
        self._news_handler_ids = []
        self.news_checker = None

    def on_news_unseen_changed(self, _checker: Any, unseen: bool) -> None:
        """The only thing that ever moves the badge."""
        self.news_badge.set_visible(unseen)

    def on_news_posts_changed(self, *_args: Any) -> None:
        self.rebuild_news_list()
        self.update_news_view()

        # Posts that land while the page is already open have been seen by
        # definition, so don't raise a badge behind the user's back.
        if (
            self.navigation_view.get_visible_page() == self.news_page
            and self.news_checker is not None
        ):
            self.news_checker.mark_seen()

    def on_news_poll_finished(self, _checker: Any, success: bool) -> None:
        self.update_news_view()

        # Only answer a refresh the user actually pressed. The 6-hourly poll
        # finishes silently — the badge is its whole vocabulary.
        if not self._news_refresh_requested:
            return
        self._news_refresh_requested = False
        self.dismiss_news_refresh_toast()

        self.toast_queue.add(
            Adw.Toast.new(
                _("Novidades atualizadas")
                if success
                else _("Não foi possível atualizar as novidades")
            )
        )

    def on_news_refresh_clicked(self, *_args: Any) -> None:
        """Force a poll and say so, from either the refresh or retry button."""
        if (checker := self.news_checker) is None:
            return

        self._news_refresh_requested = True
        self.dismiss_news_refresh_toast()

        # Timeout 0 means "stay until dismissed": the toast is a progress
        # indicator, so it has to outlive an arbitrarily slow request and be
        # replaced by the result rather than time out on its own.
        toast = Adw.Toast.new(_("Atualizando novidades…"))
        toast.set_timeout(0)
        self._news_refresh_toast = toast
        self.toast_queue.add(toast)

        # A poll already in flight is not restarted; its completion answers
        # this toast just the same.
        checker.check_async()
        self.update_news_view()

    def dismiss_news_refresh_toast(self) -> None:
        if self._news_refresh_toast is not None:
            self.toast_queue.dismiss(self._news_refresh_toast)
            self._news_refresh_toast = None

    def on_show_news_action(self, *_args: Any) -> None:
        """Open the Novidades page (header-bar button / win.show_news)."""
        if self.navigation_view.get_visible_page() == self.news_page:
            return

        if (checker := self.news_checker) is not None:
            # Opening the page acknowledges everything on it.
            checker.mark_seen()
            # Nothing cached (first open, or every earlier poll failed): ask
            # again now rather than showing an empty page the user can't fix.
            if not checker.posts:
                checker.check_async()

        self.update_news_view()
        self.navigation_view.push(self.news_page)

    def update_news_view(self) -> None:
        """Pick which of the three news states is on screen.

        Cached posts always win: a failed refresh must not throw away a list the
        user is reading. Only when there is nothing to show does the spinner (a
        poll in flight) or the status page (nothing at all) take over.
        """
        checker = self.news_checker

        if checker is not None and checker.posts:
            name = "list"
        elif checker is not None and checker.loading:
            name = "loading"
        else:
            name = "empty"

        self.news_stack.set_visible_child_name(name)

    def rebuild_news_list(self) -> None:
        """Replace every row with the checker's current posts."""
        while child := self.news_list.get_first_child():
            self.news_list.remove(child)

        if self.news_checker is None:
            return

        for post in self.news_checker.posts:
            self.news_list.append(self.build_news_row(post))

        # A rebuilt list is a different list; leaving the viewport halfway down
        # it would land the user in the middle of rows that just moved.
        self.news_scrolledwindow.get_vadjustment().set_value(0)

    def build_news_row(self, post: NewsPost) -> Gtk.ListBoxRow:
        """One feed post as a row that expands to its full text.

        The excerpt is never abbreviated. An ellipsis would force the reader to
        open a browser just to finish a paragraph the app already has in hand,
        so the row expands in place instead and the link becomes a choice rather
        than a requirement.

        A post with neither excerpt nor link has nothing behind the disclosure
        triangle, so it degrades to a plain row rather than an expander that
        opens onto nothing.
        """
        children: list[Gtk.Widget] = []

        if post.summary:
            children.append(self.build_news_summary_row(post.summary))

        if post.url:
            open_row = Adw.ActionRow(activatable=True)
            open_row.set_use_markup(False)
            open_row.set_title(_("Abrir publicação"))
            open_row.add_suffix(
                Gtk.Image(
                    icon_name="adw-external-link-symbolic",
                    valign=Gtk.Align.CENTER,
                    css_classes=["dim-label"],
                )
            )
            open_row.connect("activated", self.on_news_row_activated, post.url)
            children.append(open_row)

        row = Adw.ExpanderRow() if children else Adw.ActionRow()

        # Feed text is third party and full of ampersands, angle brackets and
        # quotes. Rendering it as Pango markup would mangle it at best and drop
        # the label at worst, so markup is switched off *before* any text is
        # set — setting it afterwards would still let the first parse warn.
        row.set_use_markup(False)
        row.set_title(post.title)
        row.set_title_lines(0)

        # Date and section move into the subtitle now that the row's body is
        # reserved for the text itself.
        if subtitle := " · ".join(
            part
            for part in (
                relative_date(post.timestamp) if post.timestamp else "",
                post.category,
            )
            if part
        ):
            row.set_subtitle(subtitle)
            row.set_subtitle_lines(0)

        for child in children:
            row.add_row(child)

        return row

    @staticmethod
    def build_news_summary_row(text: str) -> Gtk.ListBoxRow:
        """The expanded body of a news row: the whole excerpt, wrapped.

        A bare ListBoxRow rather than an Adw.ActionRow because the text is the
        content, not a title for something else — an ActionRow would squeeze it
        into a subtitle and re-impose a line limit.
        """
        row = Gtk.ListBoxRow(activatable=False, selectable=False)
        row.set_child(
            Gtk.Label(
                label=text,
                wrap=True,
                xalign=0,
                margin_top=12,
                margin_bottom=12,
                margin_start=12,
                margin_end=12,
                css_classes=["body"],
            )
        )
        return row

    def on_news_row_activated(self, _row: Adw.ActionRow, url: str) -> None:
        """Open a post in the default browser."""
        open_uri(url, self)

    def set_details_view_opacity(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() != self.details_page:
            return

        if (
            style_manager := Adw.StyleManager.get_default()
        ).get_high_contrast() or not style_manager.get_system_supports_color_schemes():
            self.details_view_blurred_cover.set_opacity(0.3)
            return

        # `luminance` only exists once `get_blurred` has computed it, and
        # `new_cover` clears it again. A cover saved while the details page is
        # already up goes through exactly that gap: `save_cover` hands the
        # reload back with `GLib.idle_add`, so it lands after `apply_preferences`
        # has shown the page, and a theme or high-contrast change arriving in
        # between used to index None here and raise. Leave the opacity as it is;
        # the reload ends in a redraw that sets it properly.
        cover = self.details_view_game_cover
        if cover is None or cover.luminance is None:
            return

        self.details_view_blurred_cover.set_opacity(
            1 - cover.luminance[0] if style_manager.get_dark() else cover.luminance[1]
        )

    @staticmethod
    def release_sort_key(game: Game) -> int:
        """Turn a release date string into a chronologically sortable number.

        Release dates are stored for display ("Aug 2012" or just "2012"), which
        do not sort correctly as text. Returns ``year * 100 + month`` (month 0
        when only the year is known) or -1 when there is no usable date.
        """
        year, month = parse_release_date(game.release_date or "")
        if year is None:
            return -1
        return year * 100 + (month or 0)

    @staticmethod
    def compare_names(game1: Game, game2: Game) -> int:
        """A–Z by title, with the game id settling an exact tie.

        The old `(name1 > name2) * 2 - 1` never returned 0, so for two records
        with the same title — the same game imported from two sources — it
        claimed each sorted before the other, and the pair traded places on
        every `invalidate_sort`. The id is unique and never changes, so folding
        it into the key makes the order stable instead of merely consistent.
        """
        key1 = (game1.name.lower(), game1.game_id)
        key2 = (game2.name.lower(), game2.game_id)
        if key1 == key2:
            return 0
        return -1 if key1 < key2 else 1

    def sort_func(self, child1: Gtk.Widget, child2: Gtk.Widget) -> int:
        game1, game2 = child1.get_child(), child2.get_child()

        if self.sort_state in ("released_newest", "released_oldest"):
            key1, key2 = self.release_sort_key(game1), self.release_sort_key(game2)
            if key1 != key2:
                # Games without a known release date always sort to the bottom
                if key1 < 0:
                    return 1
                if key2 < 0:
                    return -1
                if self.sort_state == "released_newest":
                    return -1 if key1 > key2 else 1
                return -1 if key1 < key2 else 1
            # Same release date: fall back to A-Z by title
            return self.compare_names(game1, game2)

        if self.sort_state == "rating":
            # Sem nota vai para o fim, como jogo sem data de lançamento: 0 aqui
            # é ausência de nota, e ordená-lo como nota zero poria os jogos que
            # ninguém avaliou abaixo dos que se achou ruins.
            key1, key2 = game1.stars, game2.stars
            if key1 != key2:
                if not key1:
                    return 1
                if not key2:
                    return -1
                return -1 if key1 > key2 else 1
            return self.compare_names(game1, game2)

        # Integer sorts (timestamps, playtime) — compared numerically, not as
        # strings, so values with different digit counts order correctly. Ties
        # fall back to A–Z by title.
        numeric = {
            "newest": ("added", True),
            "oldest": ("added", False),
            "last_played": ("last_played", True),
            "playtime": ("playtime", True),
            # Tamanho zero é "não medido", e cai no fim da lista sozinho:
            # é o menor valor possível e a ordem é decrescente. O que a
            # ordenação promete é "o maior primeiro", e um jogo sem
            # tamanho conhecido não tem como disputar essa posição.
            "install_size": ("install_size", True),
        }
        if self.sort_state in numeric:
            attr, descending = numeric[self.sort_state]
            val1, val2 = getattr(game1, attr), getattr(game2, attr)
            if val1 != val2:
                if descending:
                    return -1 if val1 > val2 else 1
                return -1 if val1 < val2 else 1
            return self.compare_names(game1, game2)

        # a-z / z-a by title
        result = self.compare_names(game1, game2)
        return -result if self.sort_state == "z-a" else result

    def stop_details_animation(self, *_args: Any) -> None:
        """Pause the details cover animation when leaving the details page"""
        if (
            self.details_view_game_cover
            and self.navigation_view.get_visible_page() != self.details_page
        ):
            self.details_view_game_cover.set_details_animation(False)

    def set_show_hidden(self, navigation_view: Adw.NavigationView, *_args: Any) -> None:
        self.lookup_action("show_hidden").set_enabled(
            navigation_view.get_visible_page() == self.library_page
        )

    def on_go_to_parent_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() in (
            self.details_page,
            self.news_page,
        ):
            self.navigation_view.pop()

    def on_go_home_action(self, *_args: Any) -> None:
        self.navigation_view.pop_to_page(self.library_page)

    def on_show_hidden_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.hidden_library_page:
            return

        self.navigation_view.push(self.hidden_library_page)

    def on_sort_action(self, action: Gio.SimpleAction, state: GLib.Variant) -> None:
        action.set_state(state)
        self.sort_state = str(state).strip("'")
        self.library.invalidate_sort()
        self.hidden_library.invalidate_sort()

        shared.state_schema.set_string("sort-mode", self.sort_state)

    def on_toggle_search_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.library_page:
            search_bar = self.search_bar
            search_entry = self.search_entry
        elif self.navigation_view.get_visible_page() == self.hidden_library_page:
            search_bar = self.hidden_search_bar
            search_entry = self.hidden_search_entry
        else:
            return

        search_bar.set_search_mode(not (search_mode := search_bar.get_search_mode()))

        if not search_mode:
            self.set_focus(search_entry)

        search_entry.set_text("")

    def show_details_page_search(self, widget: Gtk.Widget) -> None:
        library = (
            self.hidden_library if widget == self.hidden_search_entry else self.library
        )
        index = 0

        while True:
            if not (child := library.get_child_at_index(index)):
                break

            if self.filter_func(child):
                self.show_details_page(child.get_child())
                break

            index += 1

    def on_undo_action(
        self, _widget: Any, game: Optional[Game] = None, undo: Optional[str] = None
    ) -> None:
        if not game:  # If the action was activated via Ctrl + Z
            if shared.importer and (
                shared.importer.imported_game_ids or shared.importer.removed_game_ids
            ):
                shared.importer.undo_import()
                return

            try:
                game = tuple(self.toasts.keys())[-1][0]
                undo = tuple(self.toasts.keys())[-1][1]
            except IndexError:
                return

        if game:
            if undo == "hide":
                game.toggle_hidden(False)

            elif undo == "remove":
                game.removed = False
                game.save()
                game.update()

            if toast := self.toasts.pop((game, undo), None):
                self.toast_queue.dismiss(toast)

    def on_open_menu_action(self, *_args: Any) -> None:
        if self.navigation_view.get_visible_page() == self.library_page:
            self.primary_menu_button.popup()
        elif self.navigation_view.get_visible_page() == self.hidden_library_page:
            self.hidden_primary_menu_button.popup()

    def on_close_action(self, *_args: Any) -> None:
        self.close()
