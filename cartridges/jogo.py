# jogo.py
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

"""O jogo da biblioteca, separado do widget que o desenhava (o antigo `Game`).

Os sinais trocam o que o widget fazia direto na janela: quem desenha (o modelo
da grade, a janela) se conecta a eles. Um `Jogo` nasce e emite também nas
threads do importador; quem mexe em interface conecta com `na_thread_principal`
ou com conexão enfileirada.
"""

import logging
from pathlib import Path
from time import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal

from cartridges import shared
from cartridges.process_session import ProcessSession
from cartridges.session_window import SessionWindow
from cartridges.utils.process_monitor import install_dir_from_command
from cartridges.utils.run_executable import aumid_from_command, run_executable

# Cover formats that hold an animation and are stored in their original form.
# O APNG usa a extensão .png das imagens paradas; guardado, vira .apng, e é a
# extensão que diz ao resto do app que a capa é animada. A ordem é a
# precedência de ``Jogo.get_cover_path``. Mora aqui, e não em `save_cover`
# (que o reexporta), porque aquele ainda depende do gi.
ANIMATED_SUFFIXES = (".gif", ".webp", ".apng")

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
    "conquistas",
    "ludusavi_nome",
    "saves_local_desconhecido_avisado",
    "backup_dos_saves_desligado",
    "comando_a_conferir",
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
class Jogo(QObject):
    # Substitui o "update-ready": a tela precisa redesenhar o jogo.
    atualizado = Signal()
    # Substitui o "save-ready": o FileManager grava a ficha.
    salvar = Signal()
    # Substitui o `create_toast`: (texto já com o nome, ação de desfazer ou "").
    aviso = Signal(str, str)
    # Substitui o diálogo de `_conferir_comando`: leva a função que, chamada
    # depois do "Iniciar" da pessoa, desmarca o comando e lança o jogo.
    confirmar_comando = Signal(object)
    # Substitui o `shared.win.minimize()` depois de lançar.
    sair_da_frente = Signal()

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
    # A capa já decodificada para a grade (era o `GameCover` do GTK); quem
    # desenha a preenche. Não é gravada.
    game_cover: Optional[Any] = None
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
    # Acompanhar as conquistas deste jogo: varredura, cartão na página e, na
    # fase 2, aviso e iluminação. Ligado por padrão; desligar não apaga o que
    # já foi guardado, e religar traz tudo de volta.
    conquistas: bool = True
    # O nome deste jogo no Ludusavi (o do manifesto, ou o do próprio jogo quando
    # o manifesto não o conhece). "" até o primeiro backup resolvê-lo.
    ludusavi_nome: str = ""
    # O usuário já foi avisado de que o local dos saves deste jogo é desconhecido (sem
    # appID e fora do manifesto, não há backup): as próximas sessões só vão para o log.
    saves_local_desconhecido_avisado: bool = False
    # O usuário escolheu "Nenhum" no Jogo no Ludusavi: sem backup deste jogo, e o appID
    # não o religa sozinho. Só uma escolha explícita nas opções avançadas o desfaz.
    backup_dos_saves_desligado: bool = False
    # Veio de um backup restaurado: o comando pode ter sido escrito por outra
    # pessoa, e roda num shell (ou como administrador). O primeiro lançamento o
    # mostra e só segue com a confirmação do usuário.
    comando_a_conferir: bool = False

    def __init__(self, data: dict[str, Any], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.version = shared.SPEC_VERSION

        self.update_values(data)
        self.base_source = self.source.split("_")[0]

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
            setattr(self, key, value)

    def update(self) -> None:
        self.atualizado.emit()

    def save(self) -> None:
        self.salvar.emit()

    def _avisar(self, title: str, action: str = "") -> None:
        """``title`` is a template where {} is the game's name."""
        self.aviso.emit(title.format(self.name), action)

    @property
    def comando_visivel(self) -> str:
        """O comando como o diálogo de conferência o mostra.

        Invisíveis (quebra de linha, U+202E que inverte o texto) aparecem como
        código: escondidos, deixariam parte do comando fora da vista.
        """
        return "".join(
            c if c.isprintable() else f"<U+{ord(c):04X}>" for c in self.executable
        )

    def _conferir_comando(self, lancar: Callable[[], Any]) -> None:
        def confirmar() -> None:
            self.comando_a_conferir = False
            self.save()
            lancar()

        self.confirmar_comando.emit(confirmar)

    def launch(self, ao_confirmar: Optional[Callable[[], Any]] = None) -> bool:
        """``ao_confirmar`` é como relançar depois da confirmação do comando de um
        jogo restaurado; sem ele, é este mesmo ``launch``."""
        # Dentro da função: o `backup_de_saves` importa o `Jogo`.
        from cartridges.saves import backup_de_saves  # noqa: PLC0415

        # Antes do comando a conferir (a ordem da `main`): o jogo não abre no meio da restauração dos saves dele.
        if backup_de_saves.restaurando(self):
            self._avisar(_("Aguarde o fim da restauração dos saves de {}."))
            return False
        if self.comando_a_conferir:
            self._conferir_comando(ao_confirmar or self.launch)
            return False

        self.last_played = int(time())
        self.save()
        self.update()

        # Como esta sessão vai ser acompanhada, decidido antes de lançar o jogo: o que é
        # acompanhável sai do próprio comando (o nome do processo, o pacote ou a pasta de
        # instalação). Sobra o jogo lançado por URI de loja. "playtime-tracking" desliga tudo.
        tracking = shared.schema.get_boolean("playtime-tracking")
        followable = (
            (self.track_process and bool(self.process_executable.strip()))
            or bool(aumid_from_command(self.executable))
            or bool(install_dir_from_command(self.executable))
        )
        sessao = shared.sessao
        # Sair da frente antes de o jogo existir: a janela muda de monitor aqui, com o jogo ainda
        # por lançar. Só com sessão, que é quem devolve a janela ao lugar de origem.
        moved = tracking and sessao is not None and sessao.move_to_session_monitor()

        run_executable(self.executable, self.run_as_admin)
        if sessao is not None:
            sessao.vibrar_abertura()

        # Encerra (com registro) a sessão em andamento antes de começar outra: dois rastreadores
        # nunca contam ao mesmo tempo.
        if SessionWindow.active is not None:
            SessionWindow.active.close()
        if ProcessSession.active is not None:
            ProcessSession.active.stop(record=True)

        if sessao is not None and tracking and followable:
            ProcessSession(self).start()
            if not moved:
                self.sair_da_frente.emit()
        elif sessao is not None and tracking:
            SessionWindow(self).present()
            if not moved:
                self.sair_da_frente.emit()
        elif shared.schema.get_boolean("minimize-after-launch"):
            self.sair_da_frente.emit()

        # The variable is the title of the game
        self._avisar(_("{} iniciado"))
        return True

    def remove_game(self) -> None:
        # Add "removed=True" to the game properties so it can be deleted on next init
        self.removed = True
        self.save()
        # Quem mostra os detalhes deste jogo sai da página ao receber este sinal.
        self.update()

        # The variable is the title of the game
        if self.zerado:
            # Instalado e marcado como Zerado: remover é mandar para a página dos
            # zerados, e o aviso diz para onde ele foi (decisão de 23/09).
            self._avisar(_("{} movido para Jogos Zerados"), "remove")
        else:
            self._avisar(_("{} removido"), "remove")

    def set_loading(self, state: int) -> None:
        antes = self.loading > 0
        self.loading += state
        if (self.loading > 0) != antes:
            self.update()

    # A capa que não coube em disco (arquivo preso): vale até fechar o app (`edicao.aplicar`).
    capa_da_sessao: Optional[Path] = None

    def get_cover_path(self) -> Optional[Path]:
        if self.capa_da_sessao is not None and self.capa_da_sessao.is_file():
            return self.capa_da_sessao
        # Animated covers (kept in their original format) take precedence,
        # then the still TIFF cover.
        for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
            cover_path = shared.covers_dir / f"{self.game_id}{suffix}"
            if cover_path.is_file():
                return cover_path

        return None
