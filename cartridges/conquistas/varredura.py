"""A passada de abertura: lê as conquistas de cada jogo e guarda no histórico.

É o `preSearchAchievements` do Hydra Launcher (hydralauncher/hydra, licença
MIT, `src/main/services/achievements/`) no molde de `utils/hltb_backfill.py`:
uma vez por execução, em segundo plano, aparecendo em "Tarefas em andamento".
Entram os jogos da biblioteca e os de Jogos Zerados — as pastas do AppData
sobrevivem à desinstalação, então um zerado antigo ainda recupera o que tinha.

A leitura (arquivos e catálogo, que pode ir à rede) roda numa thread; a gravação
do histórico volta para a thread principal, onde dá para conferir que o jogo
ainda está na store. Sem essa conferência, um jogo excluído no meio da passada
ganharia de volta o arquivo que o Excluir acabou de apagar.

Ao final, um aviso só com o que entrou desde a abertura anterior: o que foi
jogado por fora do app. A primeira varredura de um jogo não conta — senão quem
acabou de instalar receberia "quinhentas conquistas novas".
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Optional

from gi.repository import Adw, GLib

from cartridges import shared
from cartridges.conquistas import arquivos, catalogo, formatos, historico
from cartridges.utils import tarefas

_ATRASO_INICIAL = 10
_ESPERA_IMPORTACAO = 30


def participa(game: Any) -> bool:
    if not getattr(game, "steam_appid", None) or not getattr(game, "conquistas", True):
        return False
    if game.blacklisted:
        return False
    return not game.removed or game.zerado


@dataclass
class Leitura:
    game: Any
    # O appID que a leitura de fato usou: o jogo pode ter o appID corrigido
    # enquanto a thread lê, e a leitura velha não vale para o appID novo.
    appid: str
    desbloqueios: list[formatos.Desbloqueio] = field(default_factory=list)
    chave_recusada: bool = False
    # Veio um catálogo (novo ou do cache): o cartão do jogo aberto pode ter de
    # aparecer mesmo sem conquista nova.
    catalogo_mudou: bool = False
    # Falso na varredura de um jogo só: nem entra no aviso final nem avisa da chave.
    avisar: bool = True


def ler_jogo(game: Any) -> Leitura:
    """Trabalho de thread: lê os arquivos e renova o catálogo. Não grava."""
    appid = str(game.steam_appid)
    desbloqueios = [
        desbloqueio
        for achado in arquivos.arquivos_do_jogo(appid, game.executable)
        for desbloqueio in formatos.ler(achado.caminho, achado.formato)
    ]
    renovacao = catalogo.obter(appid, game.executable)
    return Leitura(
        game,
        appid,
        desbloqueios,
        renovacao.chave_recusada,
        catalogo_mudou=renovacao.catalogo is not None,
    )


def mensagem(novas_por_jogo: list[tuple[str, int]]) -> Optional[str]:
    com_novas = [(nome, novas) for nome, novas in novas_por_jogo if novas > 0]
    if not com_novas:
        return None
    total = sum(novas for _nome, novas in com_novas)
    if len(com_novas) == 1:
        # A primeira variável é o número de conquistas; a segunda, o nome do jogo
        return ngettext("{} nova conquista em {}", "{} novas conquistas em {}", total).format(
            total, com_novas[0][0]
        )
    # A primeira variável é o número de conquistas; a segunda, o de jogos
    return _("{} novas conquistas em {} jogos").format(total, len(com_novas))


def _aviso(texto: str) -> None:
    toast = Adw.Toast.new(texto)
    toast.set_use_markup(False)
    shared.win.toast_queue.add(toast)


class VarreduraConquistas:
    """Uma passada por execução, no molde de `HLTBBackfill`."""

    def __init__(self) -> None:
        self._timeout_id: Optional[int] = None
        self._lock = threading.Lock()
        self._running = False
        self._stopped = False
        self._generation = 0
        # Um aviso de chave recusada por execução, não um por jogo.
        self._avisou_chave = False
        self._novas: list[tuple[str, int]] = []

    # -- agenda ---------------------------------------------------------------

    def start(self) -> None:
        self._stopped = False
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
        self._timeout_id = GLib.timeout_add_seconds(_ATRASO_INICIAL, self._on_timer)

    def stop(self) -> None:
        self._stopped = True
        self._generation += 1
        if self._timeout_id is not None:
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None

    def _on_timer(self) -> bool:
        self._timeout_id = None
        if self._stopped:
            return False
        app = shared.win.get_application() if shared.win is not None else None
        if app is not None and app.state == shared.AppState.IMPORT:
            self._timeout_id = GLib.timeout_add_seconds(_ESPERA_IMPORTACAO, self._on_timer)
            return False
        self.run_async()
        return False

    def run_async(self) -> None:
        if self._stopped:
            return
        # Retrato tirado na thread principal: a store muda durante importações.
        games = [game for game in shared.store if participa(game)]
        if not games:
            return
        with self._lock:
            if self._running:
                return
            self._running = True
        threading.Thread(
            target=self._worker, args=(games, self._generation), daemon=True
        ).start()

    def varrer_jogo(self, game: Any) -> None:
        """Um jogo só, sem aviso (appID corrigido, interruptor religado)."""
        if not participa(game):
            return
        threading.Thread(
            target=self._worker, args=([game], self._generation, False), daemon=True
        ).start()

    # -- a passada ------------------------------------------------------------

    def _worker(self, games: list[Any], geracao: int, avisar: bool = True) -> None:
        tarefa = None
        try:
            if avisar:
                tarefa = tarefas.comecar(_("Conquistas"), len(games))
            for feitos, game in enumerate(games):
                if tarefa is not None:
                    tarefa.atualizar(feitos)
                if self._stopped or geracao != self._generation:
                    break
                try:
                    leitura = ler_jogo(game)
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.warning("Falha ao ler as conquistas de %s", game.name, exc_info=True)
                    continue
                leitura.avisar = avisar
                GLib.idle_add(self._entregar, leitura)
        finally:
            if tarefa is not None:
                tarefa.terminar()
            if avisar:
                with self._lock:
                    self._running = False
                GLib.idle_add(self._concluir)

    # -- na thread principal --------------------------------------------------

    def _entregar(self, leitura: Leitura) -> bool:
        # Roda como callback ocioso do GLib: nada pode escapar daqui.
        try:
            if not self._stopped:
                novas = self._gravar(leitura)
                if novas and leitura.avisar:
                    self._novas.append((leitura.game.name, novas))
                if leitura.avisar and leitura.chave_recusada and not self._avisou_chave:
                    self._avisou_chave = True
                    _aviso(
                        _("A chave da Steam Web API foi recusada. Verifique-a nas Preferências.")
                    )
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao guardar as conquistas de um jogo", exc_info=True)
        return False

    def _gravar(self, leitura: Leitura) -> int:
        """Grava o histórico. Devolve quantas contam para o aviso."""
        game = leitura.game
        if shared.store.get(game.game_id) is not game or not participa(game):
            return 0
        # O appID foi corrigido durante a leitura (e o Aplicar já apagou o
        # histórico antigo): estas conquistas são do jogo errado e, como o
        # histórico só cresce, gravá-las as deixaria para sempre.
        if str(game.steam_appid or "") != leitura.appid:
            return 0
        entraram, primeira = historico.registrar(game.game_id, leitura.desbloqueios)
        mudou = bool(entraram) or leitura.catalogo_mudou
        if mudou and getattr(shared.win, "active_game", None) is game:
            atualizar = getattr(shared.win, "update_conquistas_block", None)
            if atualizar is not None:
                atualizar(game)
        return 0 if primeira else len(entraram)

    def _concluir(self) -> bool:
        # Também callback ocioso do GLib: não levanta, e a lista sempre zera.
        try:
            if not self._stopped and (texto := mensagem(self._novas)):
                _aviso(texto)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao avisar das conquistas novas", exc_info=True)
        finally:
            self._novas = []
        return False
