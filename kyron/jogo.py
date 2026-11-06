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

"""O jogo da biblioteca; emite também nas threads do importador (conectar com `na_thread_principal` ou conexão enfileirada)."""

import logging
import threading
import weakref
from pathlib import Path
from time import time
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, Signal

from kyron import shared
from kyron.process_session import ProcessSession
from kyron.session_window import SessionWindow
from kyron.utils.process_monitor import install_dir_from_command
from kyron.utils.run_executable import aumid_from_command, run_executable
from kyron.utils.thread_principal import na_thread_principal

# Formatos de capa animada, mantidos na forma original. O APNG guardado vira .apng: a extensão diz ao app que a capa é animada.
# A ordem é a precedência de ``Jogo.get_cover_path``.
ANIMATED_SUFFIXES = (".gif", ".webp", ".apng")

# Tudo o que vai ao JSON do jogo, e a lista do que `update_values` aceita: uma chave arbitrária seria gravada por setattr sobre qualquer coisa da instância.
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
    "inis",
    "idioma_proprio",
    "nome_proprio",
    "appid_manual",
    "idiomas_steam",
)

_KNOWN_KEYS = frozenset(PERSISTED_ATTRS)

# Os status possíveis, na ordem de leitura. Fonte única do menu, do seletor da edição e do rótulo dos detalhes.
STATUS_LABELS = {
    "backlog": _("Quero jogar"),
    "playing": _("Jogando"),
    "beaten": _("Zerado"),
    "dropped": _("Abandonado"),
}


def status_label(status: str) -> str:
    """O rótulo de um status guardado, ou "" para sem status. Tolerante de propósito: um valor desconhecido (arquivo editado à mão) vira "sem status" em vez de derrubar a tela."""
    return STATUS_LABELS.get(status or "", "")


# pylint: disable=too-many-instance-attributes
class Jogo(QObject):
    atualizado = Signal()
    salvar = Signal()
    # (texto já com o nome, ação de desfazer ou "").
    aviso = Signal(str, str)
    # Leva a função que, chamada depois do "Iniciar" da pessoa, desmarca o comando e lança o jogo.
    confirmar_comando = Signal(object)
    sair_da_frente = Signal()
    # A conferência dos .ini não achou os arquivos e vai procurá-los: (jogar agora, cancelar). `inis_procurados` diz que acabou.
    procurando_inis = Signal(object, object)
    inis_procurados = Signal()

    loading: int = 0
    # Uma conferência dos .ini em andamento; e o uso único que deixa o relançamento dela passar sem conferir de novo.
    _conferindo: bool = False
    _procurando: bool = False  # a busca começou e o diálogo foi pedido
    _launch_iniciou: bool = False  # o `launch` mais recente foi o que começou a conferência
    _inis_conferidos: bool = False
    _rodada: Any = None  # ({"decidido"}, jogar, cancelar) da decisão mais recente
    filtered: bool = False

    # Com default, ao contrário dos de identidade: um arquivo antigo sem este campo levantava AttributeError no FileManager e o jogo deixava de ser gravado.
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
    # "full" ou "partial". None é que a Steam não diz, não "sem suporte a controle" (ver SteamAPIHelper.parse_controller_support).
    controller_support: Optional[str] = None
    # "Gamepad Recommended" da Steam: mais forte que suporte total, "feito para jogar com controle".
    gamepad_recommended: bool = False
    description: Optional[str] = None
    # STEAM_METADATA_VERSION da última busca, ou 0 se o jogo é anterior à marca; o "só o que falta" lê isto, pois campos vazios podem ser legítimos.
    steam_checked: int = 0
    # AppID da Steam de onde vêm os metadados; reusado nas atualizações (resolver pelo nome repetiria uma busca cujo primeiro resultado costuma ser o jogo errado).
    steam_appid: Optional[str] = None
    # Estimativas do HowLongToBeat em segundos. None é "ainda não buscado ou ninguém enviou", por isso sem default 0.
    hltb_id: Optional[int] = None
    hltb_main: Optional[int] = None
    hltb_main_extra: Optional[int] = None
    hltb_completionist: Optional[int] = None
    # Jogos vendidos como um produto mas catalogados no HowLongToBeat por capítulo: os três campos acima ficam vazios e aqui vai uma entrada por capítulo.
    hltb_chapters: Optional[list[dict]] = None
    # Tamanho da instalação em bytes e quando foi medido. Zero é "não sei" (inclusive em jogo aberto por URL de loja); a ordenação por tamanho manda os zeros para o fim.
    install_size: int = 0
    install_size_ts: int = 0
    removed: bool = False
    blacklisted: bool = False
    # A capa já decodificada para a grade; quem desenha a preenche. Não é gravada.
    game_cover: Optional[Any] = None
    version: int = 0
    # Data de modificação do atalho de origem; mantida nos jogos removidos para um atalho ainda presente não readicionar um jogo excluído (salvo se mais novo).
    shortcut_mtime: int = 0
    shortcut_path: str = ""  # original .lnk/.url path, used for elevated launch
    run_as_admin: bool = False  # launch this game elevated (UAC) on Windows
    # Acompanha o tempo de jogo pelo processo do próprio jogo; só para executáveis observáveis (não Steam/Epic/UWP, que passam por um launcher).
    track_process: bool = False
    process_executable: str = ""  # exe name to watch, e.g. "game.exe"
    # Opcional por jogo: acompanha o feed de repacks atrás de um patch mais novo. Desligado por padrão (custa uma requisição de rede).
    track_updates: bool = False
    # pubDate (epoch, em s) do post mais novo em que o jogo foi achado e que está anunciado. 0 é "sem aviso".
    update_available_ts: int = 0
    # pubDate (epoch, em s) do último patch dispensado. Um resumo futuro só reabre o aviso se for mais novo.
    update_dismissed_ts: int = 0
    # Página de repack do patch anunciado, aberta quando o usuário age sobre o aviso; "" se não há aviso ou o resumo não trouxe link.
    update_url: str = ""
    # Acompanhar as conquistas deste jogo. Ligado por padrão; desligar não apaga o que já foi guardado.
    conquistas: bool = True
    # O nome do jogo no Ludusavi (o do manifesto, ou o do próprio jogo); "" até o primeiro backup resolvê-lo.
    ludusavi_nome: str = ""
    # O usuário já foi avisado de que o local dos saves é desconhecido (sem appID e fora do manifesto): as próximas sessões só vão para o log.
    saves_local_desconhecido_avisado: bool = False
    # O usuário escolheu "Nenhum" no Jogo no Ludusavi: o appID não religa o backup sozinho; só uma escolha explícita nas opções avançadas.
    backup_dos_saves_desligado: bool = False
    # Veio de um backup restaurado: o comando pode ter sido escrito por outra pessoa e roda num shell (ou como administrador); o primeiro lançamento o mostra e só segue com a confirmação.
    comando_a_conferir: bool = False
    # Caminhos dos .ini de emulador de Steam do jogo; None é "nunca procurado", [] é "procurado e não há".
    inis: Optional[list[str]] = None
    # Idioma e nome do jogador só deste jogo; "" segue o padrão do Kyron.
    idioma_proprio: str = ""
    nome_proprio: str = ""
    # O AppID foi escrito à mão: a leitura dos .ini não o troca mais.
    appid_manual: bool = False
    # Idiomas que a Steam lista para o AppID; None é "ainda não consultado".
    idiomas_steam: Optional[list[str]] = None

    def __init__(self, data: dict[str, Any], parent: Optional[QObject] = None) -> None:
        super().__init__(parent)

        self.version = shared.SPEC_VERSION

        self.update_values(data)
        self.base_source = self.source.split("_")[0]

    @property
    def has_update(self) -> bool:
        """Há um patch a mostrar na página de detalhes: o jogo aderiu e um resumo mais novo que o dispensado está anunciado."""
        return self.track_updates and self.update_available_ts > 0

    @property
    def zerado(self) -> bool:
        """Está na página Jogos Zerados: desinstalado e marcado como Zerado. Sem campo próprio: sai de dois já gravados."""
        return self.removed and not self.blacklisted and self.status == "beaten"

    def definir_status(self, status: str) -> None:
        """Troca o status; caminho único (o botão da tela e a edição). Quem chama salva e atualiza depois.

        Tirar a marca de um zerado decide para onde ele vai: com o atalho de volta na pasta (reinstalado), volta à
        biblioteca com os dados inteiros; sem ele (ou sem executável, que a carga descartaria), vira um desinstalado comum.
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
        """Confirma o patch anunciado: lembra-o (``update_dismissed_ts``), zera o anunciado e esconde o aviso. Gravado na hora."""
        self.update_dismissed_ts = max(
            self.update_dismissed_ts, self.update_available_ts
        )
        self.update_available_ts = 0
        self.update_url = ""
        self.save()
        self.update()

    @property
    def stars(self) -> int:
        """``rating`` limitado a 0–5, tolerando arquivo editado à mão ("rating": 9 ou "ótimo" vira 5 ou 0)."""
        try:
            return max(0, min(5, int(self.rating)))
        except (TypeError, ValueError):
            return 0

    @property
    def hltb_times(self) -> tuple[Optional[int], Optional[int], Optional[int]]:
        """As três estimativas na ordem de exibição: principal, com extras, 100%."""
        return (self.hltb_main, self.hltb_main_extra, self.hltb_completionist)

    @property
    def has_hltb_times(self) -> bool:
        """O HowLongToBeat já respondeu para este jogo? Um jogo em capítulos conta como respondido mesmo com os três campos vazios."""
        return any(self.hltb_times) or bool(self.hltb_chapters)

    def update_values(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if key not in _KNOWN_KEYS:
                logging.debug("Ignoring unknown field %s in a game record", key)
                continue
            setattr(self, key, value)
        # Registro editado à mão: valor de tipo errado volta ao padrão em vez de derrubar quem o usa.
        for chave in ("inis", "idiomas_steam"):
            valor = getattr(self, chave)
            if not isinstance(valor, list) or not all(isinstance(i, str) for i in valor):
                setattr(self, chave, None)
        for chave in ("idioma_proprio", "nome_proprio"):
            if not isinstance(getattr(self, chave), str):
                setattr(self, chave, "")

    def update(self) -> None:
        self.atualizado.emit()

    def save(self) -> None:
        self.salvar.emit()

    def _avisar(self, title: str, action: str = "") -> None:
        """``title`` é um modelo em que {} é o nome do jogo."""
        self.aviso.emit(title.format(self.name), action)

    @property
    def comando_visivel(self) -> str:
        """O comando como o diálogo de conferência o mostra: invisíveis (quebra de linha, U+202E que inverte o texto) aparecem como código."""
        return "".join(
            c if c.isprintable() else f"<U+{ord(c):04X}>" for c in self.executable
        )

    def _conferir_comando(self, lancar: Callable[[], Any]) -> None:
        def confirmar() -> None:
            self.comando_a_conferir = False
            self.save()
            lancar()

        self.confirmar_comando.emit(confirmar)

    @property
    def conferindo_inis(self) -> bool:
        """A conferência que o último `launch` começou está no caminho rápido: o jogo abre em instantes, sem o diálogo."""
        return self._launch_iniciou and self._conferindo and not self._procurando

    @property
    def inis_conferidos(self) -> bool:
        """Verdadeiro só durante o relançamento que vem da conferência (quem relança depois de uma animação o repassa ao `launch`)."""
        return self._inis_conferidos

    def _nova_rodada(self, ao_confirmar: Optional[Callable[[], Any]]) -> None:
        """Uma decisão sobre a mesma busca: só a rodada mais recente lança quando ela termina."""
        ref = weakref.ref(self)  # quem guarda as respostas (a ponte) não prende o jogo
        rodada = {"decidido": False, "cancelado": False}

        def jogar() -> None:
            if rodada["decidido"] or (j := ref()) is None:
                return
            rodada["decidido"] = True
            j._inis_conferidos = True
            try:
                (ao_confirmar or j.launch)()
            finally:
                j._inis_conferidos = False

        def cancelar() -> None:
            rodada["decidido"] = rodada["cancelado"] = True

        self._rodada = (rodada, jogar, cancelar)

    def _mostrar_preparo(self) -> None:
        self._procurando = True
        _rodada, jogar, cancelar = self._rodada
        self.procurando_inis.emit(jogar, cancelar)

    def _fim_da_conferencia(self, falhou: bool = False) -> None:
        self._conferindo = self._procurando = False
        self.inis_procurados.emit()
        # Excluído ou removido durante a busca: não abre um jogo que já saiu da biblioteca.
        if self.removed or (shared.store is not None and shared.store.get(self.game_id) is not self):
            return
        self._rodada[1]()
        if falhou and not self._rodada[0]["cancelado"]:  # jogo que não abriu não leva aviso
            self._avisar(_("Não foi possível aplicar o idioma e o nome do jogador em {}."))

    def _conferir_inis(self, ao_confirmar: Optional[Callable[[], Any]]) -> None:
        """Aplica o idioma e o nome numa thread (toca o disco) e relança na principal; nunca impede o jogo de abrir."""
        from kyron.emuladores import aplicacao, busca, varredura  # noqa: PLC0415

        self._conferindo, self._procurando = True, False
        self._launch_iniciou = True
        self._nova_rodada(ao_confirmar)

        def conferir() -> None:
            resultado = None
            try:
                resultado = aplicacao.aplicar_no_jogo(self)
                if resultado == aplicacao.FALTANDO and busca.raiz_do_jogo(self.executable, []) is not None:
                    na_thread_principal(self._mostrar_preparo)
                    # Adota o AppID como a varredura; só grava o jogo se ele ainda está na biblioteca.
                    resultado = varredura.procurar_jogo(self, buscar_idiomas=False)  # o play não espera a Steam
            except Exception:  # noqa: BLE001
                logging.exception("Falha ao conferir os .ini de %s", self.name)
            na_thread_principal(self._fim_da_conferencia, resultado == aplicacao.FALHOU)

        threading.Thread(target=conferir, name="conferencia-dos-inis", daemon=True).start()

    def launch(
        self, ao_confirmar: Optional[Callable[[], Any]] = None, inis_conferidos: bool = False, em_tela_cheia: bool = False
    ) -> bool:
        """``ao_confirmar``: como relançar depois da confirmação do comando ou da conferência dos .ini; sem ele, este mesmo ``launch``.

        ``inis_conferidos``: relançamento de uma conferência que passou por uma animação (Big Picture) e já não vê a marca.

        ``em_tela_cheia``: lançado do Big Picture; a janela não muda de monitor nem sai da frente.
        """
        # Dentro da função: o `backup_de_saves` importa o `Jogo`.
        from kyron.emuladores import aplicacao, busca  # noqa: PLC0415
        from kyron.saves import backup_de_saves  # noqa: PLC0415

        conferidos, self._inis_conferidos = inis_conferidos or self._inis_conferidos, False
        self._launch_iniciou = False  # um launch ignorado não deixa quem o chamou esperando a conferência de outro
        # Antes do comando a conferir: o jogo não abre no meio da restauração dos saves dele.
        if backup_de_saves.restaurando(self):
            self._avisar(_("Aguarde o fim da restauração dos saves de {}."))
            return False
        if self.comando_a_conferir:
            self._conferir_comando(ao_confirmar or self.launch)
            return False
        if not conferidos:
            if self._conferindo:
                # Clique repetido: ignorado enquanto ninguém decidiu; depois de decidido, a mesma busca pede de novo.
                if self._rodada[0]["decidido"]:
                    self._nova_rodada(ao_confirmar)
                    self._mostrar_preparo()
                return False
            # Jogo de loja não tem .ini de emulador: abre direto, sem thread.
            if not busca.eh_de_loja(self.executable) and aplicacao.valores_para(self) != (None, None):
                self._conferir_inis(ao_confirmar)
                return False

        self.last_played = int(time())
        self.save()
        self.update()

        # Decidido antes de lançar: o que é acompanhável sai do próprio comando (processo, pacote ou pasta); sobra o jogo lançado por URI de loja.
        # "playtime-tracking" desliga tudo.
        tracking = shared.schema.get_boolean("playtime-tracking")
        followable = (
            (self.track_process and bool(self.process_executable.strip()))
            or bool(aumid_from_command(self.executable))
            or bool(install_dir_from_command(self.executable))
        )
        sessao = shared.sessao
        # Sair da frente antes de o jogo existir: a janela muda de monitor com o jogo ainda por lançar. Só com sessão, que devolve a janela ao lugar de origem.
        moved = tracking and sessao is not None and not em_tela_cheia and sessao.move_to_session_monitor()

        run_executable(self.executable, self.run_as_admin)
        if sessao is not None:
            sessao.vibrar_abertura()

        # Encerra (com registro) a sessão em andamento antes de começar outra: dois rastreadores nunca contam ao mesmo tempo.
        if SessionWindow.active is not None:
            SessionWindow.active.close()
        if ProcessSession.active is not None:
            ProcessSession.active.stop(record=True)

        if sessao is not None and tracking and followable:
            ProcessSession(self).start()
            if not moved and not em_tela_cheia:
                self.sair_da_frente.emit()
        elif sessao is not None and tracking:
            SessionWindow(self).present()
            if not moved and not em_tela_cheia:
                self.sair_da_frente.emit()
        elif not em_tela_cheia and shared.schema.get_boolean("minimize-after-launch"):
            self.sair_da_frente.emit()

        self._avisar(_("{} iniciado"))
        return True

    def remove_game(self) -> None:
        self.removed = True
        self.save()
        # Quem mostra os detalhes deste jogo sai da página ao receber este sinal.
        self.update()

        if self.zerado:
            # Instalado e marcado como Zerado: remover manda para a página dos zerados, e o aviso diz para onde.
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
        for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
            cover_path = shared.covers_dir / f"{self.game_id}{suffix}"
            if cover_path.is_file():
                return cover_path

        return None
