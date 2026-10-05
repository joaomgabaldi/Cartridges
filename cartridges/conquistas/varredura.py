"""A passada de abertura: lê as conquistas de cada jogo e guarda no histórico.

É o `preSearchAchievements` do Hydra Launcher (hydralauncher/hydra, licença
MIT, `src/main/services/achievements/`) no molde de `utils/hltb_backfill.py`:
uma vez por execução, em segundo plano, aparecendo em "Tarefas em andamento".
Entram os jogos da biblioteca e os de Jogos Zerados — as pastas do AppData
sobrevivem à desinstalação, então um zerado antigo ainda recupera o que tinha.

A leitura roda numa thread, em duas passadas. A primeira decide a fonte das
conquistas de cada jogo (`fontes.do_jogo`: conta Xbox, Steam/emulador ou
nenhuma) e lê só os arquivos dos emuladores (disco); a gravação do histórico,
com a fonte (ou o esquecimento dela, para o jogo sem fonte), volta para a
thread principal, onde dá para conferir que o jogo ainda está na store. Sem
essa conferência, um jogo excluído no meio da passada ganharia de volta o
arquivo que o Excluir acabou de apagar. A segunda vai à rede: renova o
catálogo dos jogos da Steam e lê a conta Xbox dos jogos do Xbox. Quando um
pedido falha por rede, os jogos seguintes (de qualquer fonte) ficam só com o
cache e o arquivo do jogo. Jogo sem fonte não vai à rede.

A fonte do Xbox só é gravada na segunda passada, junto com as conquistas da
conta. A primeira leitura de uma fonte (o jogo ainda não tinha o Xbox como
fonte: conta recém-conectada, por exemplo) não conta no aviso, senão as
conquistas antigas da conta apareceriam como novas.

Terminada a primeira passada, um aviso só com o que entrou desde a abertura
anterior: o que foi jogado por fora do app. Ele não espera a rede; as
conquistas novas do Xbox, que só chegam pela rede, saem num aviso próprio no
fim da segunda passada, com o mesmo texto. A primeira
varredura de um jogo não conta — senão quem acabou de instalar receberia
"quinhentas conquistas novas". Num jogo da Steam, também não conta a conquista
com data anterior à varredura anterior: ela foi ganha em outro aparelho e só
chegou agora porque a Steam deste PC criou o arquivo quando o jogo rodou aqui
pela primeira vez (o mesmo critério do vigia, com a mesma margem).
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from gi.repository import Adw, GLib

from cartridges import shared
from cartridges.conquistas import arquivos, catalogo, fontes, formatos, historico, sessao
from cartridges.conquistas.fontes import Fonte
from cartridges.conquistas.vigia import MARGEM_DA_STEAM
from cartridges.conquistas.xbox import api, conta
from cartridges.utils import tarefas

_ULTIMA_VARREDURA = "conquistas-ultima-varredura"

_ATRASO_INICIAL = 10
_ESPERA_IMPORTACAO = 30


def participa(game: Any) -> bool:
    if not getattr(game, "conquistas", True):
        return False
    if game.blacklisted:
        return False
    return not game.removed or game.zerado


def _filtrar(games: list[Any], filtro: Callable[[Any], bool]) -> list[Any]:
    """Trabalho de thread: quem passa no filtro. O que o filtro não souber decidir fica de fora."""
    passaram = []
    for game in games:
        try:
            if filtro(game):
                passaram.append(game)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao filtrar %s para a varredura de conquistas", game.name, exc_info=True)
    return passaram


@dataclass
class Leitura:
    """O que os arquivos de um jogo trazem (primeira passada)."""

    game: Any
    # O appID que a leitura de fato usou: o jogo pode ter o appID corrigido
    # enquanto a thread lê, e a leitura velha não vale para o appID novo.
    # Vazio quando a fonte não é a Steam.
    appid: str
    desbloqueios: list[formatos.Desbloqueio] = field(default_factory=list)
    # Falso na varredura de um jogo só: não entra no aviso final.
    avisar: bool = True
    # De onde vêm as conquistas do jogo; None = de lugar nenhum.
    fonte: Optional[Fonte] = None
    # O executável que gerou a fonte: se for editado até a entrega, a leitura é descartada.
    executavel: str = ""


@dataclass
class LeituraXbox:
    """O que a conta Xbox trouxe para um jogo (segunda passada)."""

    game: Any
    fonte: Fonte
    desbloqueios: list[formatos.Desbloqueio] = field(default_factory=list)
    # Falso na varredura de um jogo só: não entra no aviso do Xbox.
    avisar: bool = True
    # O executável que gerou a fonte: se for editado até a entrega (o jogo passou a
    # ser outro, ou de outra loja), a leitura é descartada, como a do appID corrigido.
    executavel: str = ""


@dataclass
class Catalogacao:
    """O que a renovação do catálogo de um jogo trouxe (segunda passada)."""

    game: Any
    appid: str
    chave_recusada: bool = False
    # Veio um catálogo (novo ou do cache): o cartão do jogo aberto pode ter de
    # aparecer mesmo sem conquista nova.
    mudou: bool = False
    # A Steam não respondeu: o resto da passada não vai à rede.
    rede_falhou: bool = False
    # Falso na varredura de um jogo só: não avisa da chave.
    avisar: bool = True


def ler_jogo(game: Any) -> Leitura:
    """Trabalho de thread: decide a fonte e lê os arquivos (só Steam/emulador). Só disco."""
    executavel = getattr(game, "executable", "") or ""
    fonte = fontes.do_jogo(game)
    if fonte is None or fonte.tipo != fontes.STEAM:
        return Leitura(game, "", [], fonte=fonte, executavel=executavel)
    desbloqueios = [
        desbloqueio
        for achado in arquivos.arquivos_do_jogo(fonte.id, game.executable)
        for desbloqueio in formatos.ler(achado.caminho, achado.formato)
    ]
    return Leitura(game, fonte.id, desbloqueios, fonte=fonte, executavel=executavel)


def ler_xbox(
    game: Any, fonte: Fonte, executavel: Optional[str] = None
) -> tuple[Optional[LeituraXbox], bool]:
    """Trabalho de thread, com rede: titleId (se faltar) e a leitura da conta.

    ``executavel``: o que a primeira passada leu (sem ele, o de agora).
    Devolve ``(leitura, rede_falhou)``.
    """
    if executavel is None:
        executavel = getattr(game, "executable", "") or ""
    try:
        titulo = fonte.id or api.titulo(fontes.pfn(game), fontes.bases(game))
        if not titulo:
            return None, False
        leitura = api.ler(titulo)
    except api.FalhaDeRede:
        logging.info("Sem rede para as conquistas do Xbox; o resto da passada fica sem rede")
        return None, True
    if leitura is None:
        return None, False
    return LeituraXbox(game, Fonte(fontes.XBOX, titulo), leitura.desbloqueios, executavel=executavel), False


def renovar_catalogo(game: Any, rede: bool = True, usar_chave: bool = True) -> Catalogacao:
    """Trabalho de thread: renova o catálogo, que pode ir à rede. Não grava."""
    appid = str(game.steam_appid)
    renovacao = catalogo.obter(appid, game.executable, rede=rede, usar_chave=usar_chave)
    return Catalogacao(
        game,
        appid,
        renovacao.chave_recusada,
        mudou=renovacao.catalogo is not None,
        rede_falhou=renovacao.rede_falhou,
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
        self._novas_xbox: list[tuple[str, int]] = []
        # Quando começou a varredura anterior que foi até o fim (0 = nenhuma),
        # lido do estado no começo de cada passada com aviso.
        self._desde = 0

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
        """Um jogo só, sem aviso (appID corrigido, interruptor religado, fim de sessão)."""
        self.varrer_jogos([game])

    def varrer_jogos(self, games: Any, filtro: Optional[Callable[[Any], bool]] = None) -> None:
        """Alguns jogos, numa thread só e sem aviso (jogos recém-importados).

        Não grava a data da varredura e não conta como a passada da abertura.
        Quem não participa fica de fora; sem ninguém, nada roda.

        ``filtro``: critério extra que pode ler o disco do jogo; por isso é
        aplicado na thread da varredura, nunca por quem pede.
        """
        jogos = [game for game in games if participa(game)]
        if not jogos:
            return
        threading.Thread(
            target=self._worker, args=(jogos, self._generation, False, filtro), daemon=True
        ).start()

    # -- a passada ------------------------------------------------------------

    def _worker(
        self,
        games: list[Any],
        geracao: int,
        avisar: bool = True,
        filtro: Optional[Callable[[Any], bool]] = None,
    ) -> None:
        """Duas passadas. A dos arquivos vem primeiro e só toca o disco: o
        histórico é gravado e o aviso de conquistas novas sai sem esperar a
        Steam. A da rede (catálogo da Steam, conta Xbox) vem depois."""
        tarefa = None
        concluiu = False
        try:
            if filtro is not None:
                games = _filtrar(games, filtro)
            if avisar:
                inicio = int(time.time())
                # Na fila antes de qualquer `_entregar` desta passada: o
                # GLib serve os callbacks ociosos na ordem em que entraram.
                GLib.idle_add(self._comecar_aviso)
                tarefa = tarefas.comecar(_("Conquistas"), 2 * len(games))
            lidas: dict[str, tuple[Optional[Fonte], str]] = {}
            leu_tudo = self._passada_dos_arquivos(games, geracao, avisar, tarefa, lidas)
            if avisar:
                concluiu = True
                GLib.idle_add(self._concluir, inicio if leu_tudo else None)
            self._passada_da_rede(games, geracao, avisar, tarefa, lidas)
        finally:
            if tarefa is not None:
                tarefa.terminar()
            if avisar:
                with self._lock:
                    self._running = False
                if not concluiu:
                    GLib.idle_add(self._concluir)
                # Depois de todo `_entregar_xbox` desta passada (ordem do GLib).
                GLib.idle_add(self._concluir_xbox)

    def _deve_parar(self, geracao: int) -> bool:
        return self._stopped or geracao != self._generation

    def _passada_dos_arquivos(
        self,
        games: list[Any],
        geracao: int,
        avisar: bool,
        tarefa: Optional[Any],
        lidas: dict[str, tuple[Optional[Fonte], str]],
    ) -> bool:
        """Lê os arquivos de cada jogo e anota em ``lidas`` a fonte (e o executável) de cada um.

        Devolve se foi até o fim sem ser parada.
        """
        for feitos, game in enumerate(games):
            if tarefa is not None:
                tarefa.atualizar(feitos)
            if self._deve_parar(geracao):
                return False
            try:
                leitura = ler_jogo(game)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao ler as conquistas de %s", game.name, exc_info=True)
                continue
            leitura.avisar = avisar
            lidas[game.game_id] = (leitura.fonte, leitura.executavel)
            GLib.idle_add(self._entregar, leitura)
        return True

    def _passada_da_rede(
        self,
        games: list[Any],
        geracao: int,
        avisar: bool,
        tarefa: Optional[Any],
        lidas: dict[str, tuple[Optional[Fonte], str]],
    ) -> None:
        rede = True
        usar_chave = True
        for feitos, game in enumerate(games, start=len(games)):
            if tarefa is not None:
                tarefa.atualizar(feitos)
            if self._deve_parar(geracao):
                break
            fonte, executavel = lidas.get(game.game_id, (None, ""))
            if fonte is None:
                continue
            if fonte.tipo == fontes.XBOX:
                rede = self._ler_xbox(game, fonte, executavel, rede, avisar)
                continue
            try:
                catalogacao = renovar_catalogo(game, rede, usar_chave)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao renovar o catálogo de %s", game.name, exc_info=True)
                continue
            if catalogacao.rede_falhou and rede:
                # Sem rede para um jogo, sem rede para os outros: o resto da
                # passada fica com o cache e o arquivo de cada jogo.
                rede = False
                logging.info("Sem rede para o catálogo de conquistas; seguindo só com o disco")
            if catalogacao.chave_recusada and usar_chave:
                # A mesma chave seria recusada em cada jogo: os seguintes não
                # a mandam à Steam. O aviso ao usuário segue sendo um só.
                usar_chave = False
                logging.info("Chave da Steam recusada; os demais jogos seguem sem ela")
            catalogacao.avisar = avisar
            GLib.idle_add(self._entregar_catalogo, catalogacao)

    def _ler_xbox(self, game: Any, fonte: Fonte, executavel: str, rede: bool, avisar: bool) -> bool:
        """Lê a conta Xbox de um jogo. Devolve se a rede segue valendo."""
        if not rede or not conta.conectada():
            return rede
        try:
            leitura, falhou = ler_xbox(game, fonte, executavel)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao ler as conquistas do Xbox de %s", game.name, exc_info=True)
            return rede
        if falhou:
            return False
        if leitura is not None:
            leitura.avisar = avisar
            GLib.idle_add(self._entregar_xbox, leitura)
        return rede

    # -- na thread principal --------------------------------------------------

    def _comecar_aviso(self) -> bool:
        # Callback ocioso do GLib: nada pode escapar daqui.
        try:
            self._desde = int(shared.state_schema.get_int64(_ULTIMA_VARREDURA))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Data da varredura anterior de conquistas ilegível", exc_info=True)
            self._desde = 0
        return False

    def _contam(self, game: Any, entraram: list[str], lidos: list[formatos.Desbloqueio]) -> int:
        """Quantas das que entraram contam como novas no aviso.

        Num jogo da Steam, a conquista com data anterior à varredura anterior
        (menos a margem do relógio) é de outro aparelho: entrou no histórico,
        mas não é novidade desde a última abertura. Sem data, conta.
        """
        if not self._desde or not arquivos.eh_jogo_da_steam(getattr(game, "executable", "") or ""):
            return len(entraram)
        horas: dict[str, int] = {}
        for lido in lidos:
            nome = lido.nome.strip().upper()
            if lido.quando > 0 and (nome not in horas or lido.quando < horas[nome]):
                horas[nome] = lido.quando
        limite = self._desde - MARGEM_DA_STEAM
        return sum(1 for nome in entraram if not 0 < horas.get(nome, 0) < limite)

    def _entregar(self, leitura: Leitura) -> bool:
        # Roda como callback ocioso do GLib: nada pode escapar daqui.
        try:
            if not self._stopped:
                novas = self._gravar(leitura)
                if novas and leitura.avisar:
                    self._novas.append((leitura.game.name, novas))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao guardar as conquistas de um jogo", exc_info=True)
        return False

    def _entregar_catalogo(self, catalogacao: Catalogacao) -> bool:
        # Também callback ocioso do GLib: nada pode escapar daqui.
        try:
            if self._stopped:
                return False
            game = catalogacao.game
            if catalogacao.mudou and getattr(shared.win, "active_game", None) is game:
                atualizar = getattr(shared.win, "update_conquistas_block", None)
                if atualizar is not None:
                    atualizar(game)
            if catalogacao.avisar and catalogacao.chave_recusada and not self._avisou_chave:
                self._avisou_chave = True
                _aviso(_("A chave da Steam Web API foi recusada. Verifique-a nas Preferências."))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao entregar o catálogo de conquistas", exc_info=True)
        return False

    def _gravar(self, leitura: Leitura) -> int:
        """Grava o histórico e a fonte. Devolve quantas contam para o aviso."""
        game = leitura.game
        if shared.store.get(game.game_id) is not game or not participa(game):
            return 0
        fonte = leitura.fonte
        # O appID foi corrigido durante a leitura (e o Aplicar já apagou o
        # histórico antigo): estas conquistas são do jogo errado e, como o
        # histórico só cresce, gravá-las as deixaria para sempre.
        if (
            fonte is not None
            and fonte.tipo == fontes.STEAM
            and str(game.steam_appid or "") != leitura.appid
        ):
            return 0
        # Sessão aberta com o vigia ativo: o histórico do jogo é dele agora.
        if sessao.acompanhando(game):
            return 0
        antes = historico.fonte(game.game_id)
        if fonte is None:
            historico.esquecer_fonte(game.game_id)
            self._atualizar_pagina(game, antes is not None)
            return 0
        if fonte.tipo != fontes.STEAM:
            # A do Xbox é gravada na segunda passada, junto com as conquistas.
            return 0
        entraram, primeira = historico.registrar(
            game.game_id, leitura.desbloqueios, fonte=fonte.texto
        )
        self._atualizar_pagina(game, bool(entraram) or antes != fonte.texto)
        return 0 if primeira else self._contam(game, entraram, leitura.desbloqueios)

    def _atualizar_pagina(self, game: Any, mudou: bool) -> None:
        if mudou and getattr(shared.win, "active_game", None) is game:
            atualizar = getattr(shared.win, "update_conquistas_block", None)
            if atualizar is not None:
                atualizar(game)

    def _entregar_xbox(self, leitura: LeituraXbox) -> bool:
        # Também callback ocioso do GLib: nada pode escapar daqui.
        try:
            game = leitura.game
            if (
                self._stopped
                or shared.store.get(game.game_id) is not game
                or not participa(game)
                or sessao.acompanhando(game)
                or not conta.conectada()
            ):
                return False
            # O executável foi editado depois da leitura: o jogo pode ser outro (ou
            # de outra loja) e, como o histórico só cresce, gravar deixaria as
            # conquistas do jogo errado para sempre. A próxima varredura refaz.
            if (getattr(game, "executable", "") or "") != leitura.executavel:
                return False
            texto = leitura.fonte.texto
            antes = historico.fonte(game.game_id)
            entraram, primeira = historico.registrar(
                game.game_id, leitura.desbloqueios, fonte=texto
            )
            # A primeira leitura da fonte (conta recém-conectada, por exemplo)
            # traz o que a conta já tinha: não é novidade.
            novas = 0 if (primeira or antes != texto) else len(entraram)
            self._atualizar_pagina(game, bool(entraram) or antes != texto)
            if novas and leitura.avisar:
                self._novas_xbox.append((game.name, novas))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao guardar as conquistas do Xbox de um jogo", exc_info=True)
        return False

    def _concluir_xbox(self) -> bool:
        """Callback ocioso do GLib: não levanta, e a lista sempre zera."""
        try:
            if not self._stopped and (texto := mensagem(self._novas_xbox)):
                _aviso(texto)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao avisar das conquistas novas do Xbox", exc_info=True)
        finally:
            self._novas_xbox = []
        return False

    def _concluir(self, inicio: Optional[int] = None) -> bool:
        """Também callback ocioso do GLib: não levanta, e a lista sempre zera.

        ``inicio``: quando começou esta passada, se ela leu os arquivos de todos
        os jogos; vira a "varredura anterior" da próxima abertura.
        """
        try:
            if not self._stopped and (texto := mensagem(self._novas)):
                _aviso(texto)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao avisar das conquistas novas", exc_info=True)
        finally:
            self._novas = []
        if inicio is not None and not self._stopped:
            try:
                shared.state_schema.set_int64(_ULTIMA_VARREDURA, inicio)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao guardar a data da varredura de conquistas", exc_info=True)
        return False
