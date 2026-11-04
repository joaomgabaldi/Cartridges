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

"""O jogo da biblioteca.

Os sinais avisam quem desenha (o modelo da grade, a janela). Um `Jogo` nasce e emite também nas threads do importador;
quem mexe em interface conecta com `na_thread_principal` ou com conexão enfileirada.
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

# Formatos de capa que guardam animação, mantidos na forma original. O APNG usa a extensão .png das paradas; guardado,
# vira .apng, e é a extensão que diz ao app que a capa é animada. A ordem é a precedência de ``Jogo.get_cover_path``.
ANIMATED_SUFFIXES = (".gif", ".webp", ".apng")

# Tudo o que vai ao registro JSON do jogo. É também a lista do que `update_values` aceita: o registro é editável à mão,
# e uma chave arbitrária seria gravada por setattr sobre qualquer coisa da instância (um "launch" no registro esconderia
# o método).
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

# Os status possíveis, na ordem de leitura: antes de jogar, jogando, depois de jogar. Fonte única do menu, do seletor da
# edição e do rótulo dos detalhes.
STATUS_LABELS = {
    "backlog": _("Quero jogar"),
    "playing": _("Jogando"),
    "beaten": _("Zerado"),
    "dropped": _("Abandonado"),
}


def status_label(status: str) -> str:
    """O rótulo de um status guardado, ou "" para sem status (ou desconhecido).

    Tolerante de propósito: o registro é editável à mão, e um valor desconhecido aparece como "sem status" em vez de
    derrubar a tela.
    """
    return STATUS_LABELS.get(status or "", "")


# pylint: disable=too-many-instance-attributes
class Jogo(QObject):
    # Emitido quando a tela precisa redesenhar o jogo.
    atualizado = Signal()
    # Emitido quando o FileManager deve gravar o registro.
    salvar = Signal()
    # (texto já com o nome, ação de desfazer ou "").
    aviso = Signal(str, str)
    # Leva a função que, chamada depois do "Iniciar" da pessoa, desmarca o comando e lança o jogo.
    confirmar_comando = Signal(object)
    # Pedido de minimizar a janela depois de lançar.
    sair_da_frente = Signal()

    loading: int = 0
    filtered: bool = False

    # Com default, ao contrário dos campos de identidade: um registro antigo (ou editado à mão) sem este campo levantava
    # AttributeError no FileManager, que o engolia, e o jogo deixava de ser gravado.
    added: int = 0
    executable: str
    game_id: str
    source: str
    last_played: int = 0
    playtime: int = 0
    # Onde o jogo está na sua vida: escolhido à mão, nunca deduzido do tempo de jogo. "" é "sem status".
    status: str = ""
    # Nota pessoal de 1 a 5; 0 é "sem nota", e por isso a ordenação manda os sem nota para o fim.
    rating: int = 0
    # Onde você parou: texto livre, com as quebras de linha que tiver. Não é a `description` (a da Steam).
    notes: str = ""
    name: str
    developer: Optional[str] = None
    publisher: Optional[str] = None
    release_date: Optional[str] = None
    metacritic: Optional[int] = None
    steam_review: Optional[str] = None
    # Já pronto para exibição: vem das tags de usuário da Steam, sem significado estável para derivar de novo.
    genre: Optional[str] = None
    # "full" ou "partial". None é que a Steam não diz, o que não é o mesmo que "sem suporte a controle" (ver
    # SteamAPIHelper.parse_controller_support).
    controller_support: Optional[str] = None
    # "Gamepad Recommended" da Steam: mais forte que suporte total, "feito para jogar com controle".
    gamepad_recommended: bool = False
    description: Optional[str] = None
    # STEAM_METADATA_VERSION da última busca na Steam, ou 0 se o jogo é anterior à marca. Atualizar "só o que falta" lê
    # isto, pois campos vazios podem ser legítimos.
    steam_checked: int = 0
    # AppID da Steam de onde vêm os metadados. Uma vez conhecido, é reusado nas atualizações: resolver pelo nome de novo
    # repetiria uma busca cujo primeiro resultado costuma ser o jogo errado.
    steam_appid: Optional[str] = None
    # Estimativas do HowLongToBeat em segundos (mesma unidade de `playtime`). None é "ainda não buscado ou ninguém
    # enviou esse tempo", por isso não têm default 0.
    hltb_id: Optional[int] = None
    hltb_main: Optional[int] = None
    hltb_main_extra: Optional[int] = None
    hltb_completionist: Optional[int] = None
    # Jogos vendidos como um produto mas catalogados no HowLongToBeat capítulo a capítulo: os três campos acima ficam
    # vazios e aqui vai uma entrada por capítulo ({"number", "name", "hltb_id", "hltb_main", …}).
    hltb_chapters: Optional[list[dict]] = None
    # Tamanho da instalação em bytes e quando foi medido. Zero é "não sei" (a varredura não chegou, ou o comando não diz
    # onde o jogo mora, como em todo jogo aberto por URL de loja); a ordenação por tamanho manda os zeros para o fim.
    install_size: int = 0
    install_size_ts: int = 0
    removed: bool = False
    blacklisted: bool = False
    # A capa já decodificada para a grade; quem desenha a preenche. Não é gravada.
    game_cover: Optional[Any] = None
    version: int = 0
    # Data de modificação do atalho de origem. Mantida nos jogos removidos para que um atalho ainda presente não
    # readicione um jogo excluído, a menos que o atalho seja mais novo (reinstalação).
    shortcut_mtime: int = 0
    shortcut_path: str = ""  # original .lnk/.url path, used for elevated launch
    run_as_admin: bool = False  # launch this game elevated (UAC) on Windows
    # Acompanha o tempo de jogo pelo processo do próprio jogo, em vez da janela de sessão manual; só para executáveis
    # observáveis (não Steam/Epic/UWP, que passam por um launcher).
    track_process: bool = False
    process_executable: str = ""  # exe name to watch, e.g. "game.exe"
    # Opcional por jogo: acompanha o feed de repacks atrás de um patch mais novo. Desligado por padrão: a checagem custa
    # uma requisição de rede.
    track_updates: bool = False
    # pubDate (epoch, em s) do post mais novo em que o jogo foi achado e que está anunciado. 0 é "sem aviso".
    update_available_ts: int = 0
    # pubDate (epoch, em s) do último patch dispensado. Um resumo futuro só reabre o aviso se for mais novo.
    update_dismissed_ts: int = 0
    # Página de repack do patch anunciado, aberta quando o usuário age sobre o aviso. "" se não há aviso ou o resumo não
    # trouxe link.
    update_url: str = ""
    # Acompanhar as conquistas deste jogo. Ligado por padrão; desligar não apaga o que já foi guardado.
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
        """Há um patch a mostrar na página de detalhes: o jogo aderiu e um resumo mais novo que o dispensado está
        anunciado.
        """
        return self.track_updates and self.update_available_ts > 0

    @property
    def zerado(self) -> bool:
        """Está na página Jogos Zerados: desinstalado e marcado como Zerado. Sem campo próprio: sai de dois já
        gravados.
        """
        return self.removed and not self.blacklisted and self.status == "beaten"

    def definir_status(self, status: str) -> None:
        """Troca o status. É o caminho único (o botão da tela e a edição).

        Tirar a marca de um zerado decide para onde ele vai: com o atalho de volta na pasta (reinstalado), volta à
        biblioteca com a ficha inteira; sem ele (ou sem executável, que a carga descartaria), vira um desinstalado
        comum, fora de qualquer grade. Quem chama salva e atualiza depois.
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
        """Confirma o patch anunciado: lembra-o e esconde o aviso.

        O timestamp anunciado vai para ``update_dismissed_ts`` e o anunciado é zerado. Gravado na hora, para
        sobreviver a um reinício.
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
        """``rating`` limitado a 0–5, tolerando um registro editado à mão: um "rating": 9 ou "ótimo" vira 5 ou 0 num
        lugar só.
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
        """O HowLongToBeat já respondeu para este jogo? Um jogo em capítulos conta como respondido mesmo com os três
        campos vazios, senão seria buscado de novo a cada execução.
        """
        return any(self.hltb_times) or bool(self.hltb_chapters)

    def update_values(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
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
        """O comando como o diálogo de conferência o mostra: invisíveis (quebra de linha, U+202E que inverte o texto)
        aparecem como código.
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

        # Antes do comando a conferir: o jogo não abre no meio da restauração dos saves dele.
        if backup_de_saves.restaurando(self):
            self._avisar(_("Aguarde o fim da restauração dos saves de {}."))
            return False
        if self.comando_a_conferir:
            self._conferir_comando(ao_confirmar or self.launch)
            return False

        self.last_played = int(time())
        self.save()
        self.update()

        # Decidido antes de lançar: o que é acompanhável sai do próprio comando (nome do processo, pacote ou pasta de
        # instalação); sobra o jogo lançado por URI de loja. "playtime-tracking" desliga tudo.
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
        self.removed = True
        self.save()
        # Quem mostra os detalhes deste jogo sai da página ao receber este sinal.
        self.update()

        # The variable is the title of the game
        if self.zerado:
            # Instalado e marcado como Zerado: remover é mandar para a página dos zerados, e o aviso diz para onde ele
            # foi.
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
        # A capa animada (na forma original) tem precedência; depois a TIFF parada.
        for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
            cover_path = shared.covers_dir / f"{self.game_id}{suffix}"
            if cover_path.is_file():
                return cover_path

        return None
