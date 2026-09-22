# game.py
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

import logging
from pathlib import Path
from subprocess import list2cmdline
from time import time
from typing import Any, Optional

from gi.repository import Adw, GObject, Gtk

from cartridges import shared
from cartridges.game_cover import GameCover
from cartridges.utils.process_monitor import install_dir_from_command
from cartridges.utils.run_executable import aumid_from_command, run_executable

# Everything written to a game's JSON record. Lives here, not in FileManager
# (who writes it), because it is also the list of what `update_values` accepts:
# the record is a file the user can hand-edit, and an arbitrary key would be
# setattr'd over anything on the instance — a record carrying "launch" or
# "save" would shadow the method with a string and break far from the cause.
# FileManager re-exports the name, so tests keep importing it from there.
PERSISTED_ATTRS = (
    "added",
    "executable",
    "game_id",
    "source",
    "last_played",
    "playtime",
    "status",
    "rating",
    "notes",
    "name",
    "developer",
    "publisher",
    "release_date",
    "metacritic",
    "steam_review",
    "genre",
    "controller_support",
    "gamepad_recommended",
    "description",
    "steam_checked",
    "steam_appid",
    "hltb_id",
    "hltb_main",
    "hltb_main_extra",
    "hltb_completionist",
    "hltb_chapters",
    "removed",
    "blacklisted",
    "version",
    "install_size",
    "install_size_ts",
    "shortcut_mtime",
    "shortcut_path",
    "run_as_admin",
    "track_process",
    "process_executable",
    "track_updates",
    "update_available_ts",
    "update_dismissed_ts",
    "update_url",
)

_KNOWN_KEYS = frozenset(PERSISTED_ATTRS)

# Os status possíveis, na ordem em que fazem sentido lidos de cima para baixo:
# antes de jogar, jogando, depois de jogar. Um dicionário ordenado é a fonte
# única do menu, do seletor da edição e do rótulo da tela de detalhes — três
# listas separadas teriam como divergir, e a que divergisse gravaria um valor
# que as outras duas não sabem exibir.
STATUS_LABELS = {
    "backlog": _("Quero jogar"),
    "playing": _("Jogando"),
    "beaten": _("Zerado"),
    "dropped": _("Abandonado"),
}


def status_label(status: str) -> str:
    """O rótulo de um status guardado, ou "" para sem status (ou desconhecido).

    Tolerante de propósito: o registro do jogo é um arquivo que dá para editar
    à mão, e um valor que ninguém reconhece deve aparecer como "sem status" em
    vez de derrubar a tela de detalhes.
    """
    return STATUS_LABELS.get(status or "", "")


# pylint: disable=too-many-instance-attributes
@Gtk.Template(resource_path=shared.PREFIX + "/gtk/game.ui")
class Game(Gtk.Box):
    __gtype_name__ = "Game"

    title = Gtk.Template.Child()
    play_button = Gtk.Template.Child()
    cover = Gtk.Template.Child()
    spinner = Gtk.Template.Child()
    cover_button = Gtk.Template.Child()
    menu_button = Gtk.Template.Child()
    play_revealer = Gtk.Template.Child()
    menu_revealer = Gtk.Template.Child()
    game_options = Gtk.Template.Child()

    loading: int = 0
    filtered: bool = False

    # Defaulted, unlike the identity fields below: a record written by an older
    # version (or hand-edited) that is missing this used to raise AttributeError
    # inside FileManager, where the manager swallowed it and the game silently
    # stopped being saved at all.
    added: int = 0
    executable: str
    game_id: str
    source: str
    last_played: int = 0
    playtime: int = 0  # total seconds played, summed across sessions
    # Onde o jogo está na sua vida, não na loja: escolhido à mão e nunca
    # deduzido do tempo de jogo — trinta horas não provam que alguém zerou, e
    # zerar não impede de continuar jogando. "" é "sem status", que é o estado
    # normal da maior parte de uma biblioteca importada de uma vez só.
    status: str = ""
    # Nota pessoal, de 1 a 5. 0 é "sem nota", não nota zero: é por isso que a
    # ordenação manda os sem nota para o fim da lista em vez de tratá-los como
    # os piores jogos da biblioteca.
    rating: int = 0
    # Onde você parou: texto livre, escrito por você e por mais ninguém. Não é
    # a `description` — aquela é a peça de marketing da Steam, esta é o recado
    # que o jogo de seis meses atrás deixou para quem for retomá-lo. Guardado
    # com as quebras de linha que tiver: é um bloco de anotações, não um campo.
    notes: str = ""
    name: str
    developer: Optional[str] = None
    publisher: Optional[str] = None
    release_date: Optional[str] = None
    metacritic: Optional[int] = None
    steam_review: Optional[str] = None
    # Already display-ready: it is picked from Steam's user tags, which have no
    # stable meaning to re-derive later, so the chosen name is what is kept.
    genre: Optional[str] = None
    # "full" or "partial". None means Steam says neither, which is not the same
    # as "no gamepad support" — see SteamAPIHelper.parse_controller_support.
    controller_support: Optional[str] = None
    # Steam's "Gamepad Recommended", which is a stronger claim than full
    # support: not "works with a gamepad" but "meant to be played with one".
    gamepad_recommended: bool = False
    # Steam's one-or-two-sentence pitch (`short_description`), in Portuguese.
    # Marketing copy by nature — that is what it is for.
    description: Optional[str] = None
    # STEAM_METADATA_VERSION at the last successful Steam lookup, or 0 for a
    # game that predates the marker. Refreshing "only what is missing" reads it
    # to find games looked up before a field existed — the fields themselves
    # cannot say, since most are legitimately empty.
    steam_checked: int = 0
    # Steam appid this game's metadata comes from. Once known it is reused for
    # every later refresh: resolving by name again would re-run a search whose
    # top result is often the wrong game (a sequel, a re-release), so a title
    # that was corrected once would silently break again on the next update.
    steam_appid: Optional[str] = None
    # HowLongToBeat completion estimates, in seconds (same unit as `playtime`,
    # though the two are deliberately never compared: these are a reference
    # table, not a target the user is measured against). None means "not
    # looked up yet or nobody has submitted that time", which is why they are
    # nullable rather than defaulting to 0 — a real 0 h game does not exist.
    hltb_id: Optional[int] = None
    hltb_main: Optional[int] = None
    hltb_main_extra: Optional[int] = None
    hltb_completionist: Optional[int] = None
    # A handful of games are sold as one product but catalogued on
    # HowLongToBeat only chapter by chapter, so there is no single estimate to
    # show — the three fields above stay empty and this carries one entry per
    # chapter ({"number", "name", "hltb_id", "hltb_main", …}) instead.
    hltb_chapters: Optional[list[dict]] = None
    # Quanto a instalação do jogo ocupa, em bytes, e quando isso foi medido.
    # Zero é "não sei": ou a varredura ainda não chegou neste jogo, ou o
    # comando que o inicia não diz onde ele mora (`install_size_folder`), que é
    # o caso de todo jogo aberto por URL de loja. Nunca é "ocupa nada" — por
    # isso a ordenação por tamanho manda os zeros para o fim.
    install_size: int = 0
    install_size_ts: int = 0
    removed: bool = False
    blacklisted: bool = False
    game_cover: Optional[GameCover] = None
    version: int = 0
    # Modification time of the shortcut this game came from. Kept on removed
    # games (as a tombstone) so a still-present shortcut doesn't re-add a game
    # the user deleted, unless the shortcut is newer (a reinstall).
    shortcut_mtime: int = 0
    shortcut_path: str = ""  # original .lnk/.url path, used for elevated launch
    run_as_admin: bool = False  # launch this game elevated (UAC) on Windows
    # Track playtime by following the game's own process instead of the manual
    # session window. Only works for plain executables we can watch (not
    # Steam/Epic/UWP, which hand off to a launcher).
    track_process: bool = False
    process_executable: str = ""  # exe name to watch, e.g. "game.exe"
    # Opt-in per game: watch the repack feed for a newer patch of this title.
    # Off by default — most games never need it, and the check costs a network
    # request whose only consumers are the games that asked for it.
    track_updates: bool = False
    # pubDate (epoch seconds) of the newest update-digest post this game was
    # matched in and is currently being advertised for. 0 means "no notice":
    # either no digest in the feed mentions the game, or the last advertised
    # patch was already dismissed.
    update_available_ts: int = 0
    # pubDate (epoch seconds) of the most recent patch the user dismissed for
    # this game. A future digest only re-raises the notice when it is newer than
    # this, so confirming a patch silences it until an even newer one lands.
    update_dismissed_ts: int = 0
    # Repack page of the currently advertised patch, taken from the digest that
    # raised the notice. Opened when the user acts on the notice; "" when there
    # is no notice or the digest carried no link.
    update_url: str = ""

    def __init__(self, data: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)

        self.app = shared.win.get_application()
        self.version = shared.SPEC_VERSION

        self.update_values(data)
        self.base_source = self.source.split("_")[0]

        self.set_play_icon()

        self.event_controller_motion = Gtk.EventControllerMotion.new()
        self.add_controller(self.event_controller_motion)
        self.event_controller_motion.connect("enter", self.toggle_play, False)
        self.event_controller_motion.connect("leave", self.toggle_play, None, None)
        self.cover_button.connect("clicked", self.main_button_clicked, False)
        self.play_button.connect("clicked", self.main_button_clicked, True)

        # Right-clicking a game opens its edit dialog directly
        right_click = Gtk.GestureClick.new()
        right_click.set_button(3)  # secondary (right) mouse button
        right_click.connect("pressed", self.edit_on_right_click)
        self.add_controller(right_click)

    def edit_on_right_click(self, *_args: Any) -> None:
        shared.win.active_game = self
        self.app.activate_action("edit_game", None)

    @property
    def has_update(self) -> bool:
        """True when a patch notice should be shown on the details page.

        Both conditions are required: the game must be opted in, and a digest
        newer than anything dismissed must currently be advertised. Reading it
        as a single property keeps the UI from re-deriving the rule in two
        places (show it, and decide whether the click target is live).
        """
        return self.track_updates and self.update_available_ts > 0

    @property
    def zerado(self) -> bool:
        """Está na página Jogos Zerados: desinstalado e marcado como Zerado.

        Sem campo próprio — a regra sai de dois que já são gravados, para que
        não exista um terceiro capaz de discordar deles.
        """
        return self.removed and not self.blacklisted and self.status == "beaten"

    def definir_status(self, status: str) -> None:
        """Troca o status. É o caminho único — o botão da tela e a edição.

        Tirar a marca de um zerado é também decidir para onde ele vai: com o
        atalho de volta na pasta (foi reinstalado), volta à biblioteca com a
        ficha inteira; sem ele — ou sem executável, que a carga descartaria como
        ficha malformada —, vira um desinstalado comum, fora de qualquer
        grade, que o seletor da página volta a oferecer. Quem chama salva e
        atualiza depois.
        """
        era_zerado = self.zerado
        self.status = status
        if (
            era_zerado
            and not self.zerado
            and self.executable
            and self.shortcut_path
            and Path(self.shortcut_path).is_file()
        ):
            self.removed = False

    def dismiss_update(self) -> None:
        """Acknowledge the advertised patch: remember it and hide the notice.

        The advertised timestamp is folded into ``update_dismissed_ts`` so the
        notice stays down until a strictly newer digest mentions the game, then
        cleared so nothing is advertised right now. Persisted immediately: the
        user's "I handled this" must survive a restart even if no other save
        happens.
        """
        self.update_dismissed_ts = max(
            self.update_dismissed_ts, self.update_available_ts
        )
        self.update_available_ts = 0
        self.update_url = ""
        self.save()
        self.update()

    @property
    def stars(self) -> int:
        """``rating`` limitado a 0–5, tolerando um registro editado à mão.

        Todo mundo que desenha estrelas passa por aqui, então um "rating": 9 ou
        "rating": "ótimo" num arquivo vira 5 ou 0 num lugar só, em vez de virar
        uma lista de nove estrelas na tela de detalhes e um IndexError na
        edição.
        """
        try:
            return max(0, min(5, int(self.rating)))
        except (TypeError, ValueError):
            return 0

    @property
    def hltb_times(self) -> tuple[Optional[int], Optional[int], Optional[int]]:
        """The three estimates in display order: main, main + extras, 100%."""
        return (self.hltb_main, self.hltb_main_extra, self.hltb_completionist)

    @property
    def has_hltb_times(self) -> bool:
        """True when HowLongToBeat has already answered for this game.

        A chaptered game counts as answered even though its three fields are
        empty — otherwise the pipeline and the startup backfill would look it
        up again on every run, having no way to tell "no single estimate
        exists" apart from "never looked".
        """
        return any(self.hltb_times) or bool(self.hltb_chapters)

    def update_values(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            # Only the persisted fields: see the note on PERSISTED_ATTRS.
            if key not in _KNOWN_KEYS:
                logging.debug("Ignoring unknown field %s in a game record", key)
                continue
            # Convert legacy list-form executables to a single command string.
            # list2cmdline uses Windows (MSVCRT) quoting rules — shlex.join's
            # POSIX single quotes are not understood by cmd.exe.
            if key == "executable" and isinstance(value, list):
                value = list2cmdline(value)
            setattr(self, key, value)

    def update(self) -> None:
        self.emit("update-ready", {})

    def save(self) -> None:
        self.emit("save-ready", {})

    def create_toast(self, title: str, action: Optional[str] = None) -> None:
        """Show a toast. ``title`` is a template where {} is the game's name."""
        toast = Adw.Toast.new(title.format(self.name))
        toast.set_use_markup(False)

        if action:
            toast.set_button_label(_("Desfazer"))
            toast.connect("button-clicked", shared.win.on_undo_action, self, action)
            # Forget the toast once it goes away so the dict doesn't grow forever
            toast.connect(
                "dismissed",
                lambda dismissed: (
                    shared.win.toasts.pop((self, action), None)
                    if shared.win.toasts.get((self, action)) is dismissed
                    else None
                ),
            )

            if old_toast := shared.win.toasts.get((self, action)):
                # Dismiss the toast if there already is one
                shared.win.toast_queue.dismiss(old_toast)

            shared.win.toasts[(self, action)] = toast

        shared.win.toast_queue.add(toast)

    def launch(self) -> None:
        self.last_played = int(time())
        self.save()
        self.update()

        # Como esta sessão vai ser acompanhada. Decidido antes de lançar o jogo
        # porque a janela sai da frente antes dele — veja `moved` logo abaixo.
        # O que é acompanhável são três coisas, e só a primeira precisa ser
        # configurada: as outras duas saem do próprio comando de lançamento,
        # que já diz onde o jogo mora ou de que pacote ele é. Sobra o jogo
        # lançado por URI de loja (Steam, Epic, Ubisoft), cujo comando nomeia
        # um id e mais nada. A chave "playtime-tracking" desliga tudo.
        tracking_enabled = shared.schema.get_boolean("playtime-tracking")
        followable = (
            (self.track_process and bool(self.process_executable.strip()))
            or bool(aumid_from_command(self.executable))
            or bool(install_dir_from_command(self.executable))
        )

        # Sair da frente *antes* de o jogo existir, e não depois. A janela muda
        # de monitor e maximiza aqui, com o jogo ainda por lançar, de modo que
        # quando ele criar a janela dele já não há mais nada se mexendo para
        # roubar o foco de um jogo em tela cheia. Não custa espera nenhuma ao
        # clique: `run_executable` não bloqueia (é um Popen, ou uma thread no
        # caso do UAC) e nada chega a ser desenhado entre uma linha e outra.
        #
        # Só quando vai haver sessão: quem devolve a janela ao lugar de origem
        # é o fim do bloqueador, e sem sessão ele nunca aparece — a janela
        # ficaria morando no outro monitor.
        moved = tracking_enabled and shared.win.move_to_session_monitor()

        run_executable(self.executable, self.run_as_admin)

        # avoid import cycles
        from cartridges.gamepad import GamepadManager
        from cartridges.process_session import ProcessSession
        from cartridges.session_window import SessionWindow

        # Confirm the launch in the hand holding the controller. Fires before
        # the window minimises, which is the last moment the pad is still ours
        # to talk to.
        GamepadManager.rumble_launch()

        # End any session already in progress (records it) before starting a new
        # one, so two trackers can't count at once
        if SessionWindow.active is not None:
            SessionWindow.active.close()
        if ProcessSession.active is not None:
            ProcessSession.active.stop(record=True)

        # Get out of the way while playing. How the session ends depends on the
        # game: anything we can follow is tracked automatically, and only what
        # we can't needs the user to end the session manually.
        #
        # Sair da frente é minimizar, a não ser que a janela já tenha saído por
        # cima — mudada para outro monitor logo acima. Minimizar depois disso
        # mandaria para a barra de tarefas justamente a tela que a opção existe
        # para deixar à vista.
        if tracking_enabled and followable:
            ProcessSession(self).start()
            if not moved:
                shared.win.minimize()
        elif tracking_enabled:
            # Clock the session in a small window and minimise the main one
            SessionWindow(self).present()
            if not moved:
                shared.win.minimize()
        elif shared.schema.get_boolean("minimize-after-launch"):
            shared.win.minimize()

        # The variable is the title of the game
        self.create_toast(_("{} iniciado"))

    def remove_game(self) -> None:
        # Add "removed=True" to the game properties so it can be deleted on next init
        self.removed = True
        self.save()
        self.update()

        if shared.win.navigation_view.get_visible_page() == shared.win.details_page:
            shared.win.navigation_view.pop()

        # The variable is the title of the game
        self.create_toast(_("{} removido"), "remove")

    def set_loading(self, state: int) -> None:
        self.loading += state
        loading = self.loading > 0

        self.cover.set_opacity(int(not loading))
        self.spinner.set_visible(loading)

    def get_cover_path(self) -> Optional[Path]:
        # Animated covers (kept in their original format) take precedence,
        # then the still TIFF cover.
        for suffix in (".gif", ".webp", ".tiff"):
            cover_path = shared.covers_dir / f"{self.game_id}{suffix}"
            if cover_path.is_file():
                return cover_path  # type: ignore

        return None

    def toggle_play(
        self, _widget: Any, _prop1: Any, _prop2: Any, state: bool = True
    ) -> None:
        if not self.menu_button.get_active():
            self.play_revealer.set_reveal_child(not state)
            self.menu_revealer.set_reveal_child(not state)

        # Only animate the cover the pointer is hovering over
        if self.game_cover:
            self.game_cover.set_hover_animation(not state)

    def main_button_clicked(self, _widget: Any, button: bool) -> None:
        if shared.schema.get_boolean("cover-launches-game") ^ button:
            self.launch()
        else:
            shared.win.show_details_page(self)

    def set_play_icon(self) -> None:
        self.play_button.set_icon_name(
            "help-about-symbolic"
            if shared.schema.get_boolean("cover-launches-game")
            else "media-playback-start-symbolic"
        )

    @GObject.Signal(name="update-ready", arg_types=[object])
    def update_ready(self, _additional_data):  # type: ignore
        """Signal emitted when the game needs updating"""

    @GObject.Signal(name="save-ready", arg_types=[object])
    def save_ready(self, _additional_data):  # type: ignore
        """Signal emitted when the game needs saving"""
